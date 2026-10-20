from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from commerce.models import (
    CommissionEntry,
    LedgerEntry,
    PayoutAccount,
    TrackingEvent,
    Wallet,
    WithdrawalRequest,
)
from commerce.services.audit import record_audit
from commerce.services.commissions import commission_hold_days, money, require_currency
from commerce.services.tracking import record_event

WITHDRAWAL_TRANSITIONS = {
    WithdrawalRequest.Status.REQUESTED: {
        WithdrawalRequest.Status.APPROVED,
        WithdrawalRequest.Status.REJECTED,
        WithdrawalRequest.Status.CANCELLED,
        WithdrawalRequest.Status.PROCESSING,
    },
    WithdrawalRequest.Status.APPROVED: {
        WithdrawalRequest.Status.PROCESSING,
        WithdrawalRequest.Status.PAID,
        WithdrawalRequest.Status.REJECTED,
    },
    WithdrawalRequest.Status.PROCESSING: {
        WithdrawalRequest.Status.PAID,
        WithdrawalRequest.Status.FAILED,
    },
    WithdrawalRequest.Status.FAILED: {
        WithdrawalRequest.Status.PROCESSING,
        WithdrawalRequest.Status.REJECTED,
    },
    WithdrawalRequest.Status.PAID: set(),
    WithdrawalRequest.Status.REJECTED: set(),
    WithdrawalRequest.Status.CANCELLED: set(),
}


def get_or_create_wallet(agent, currency: str = "") -> Wallet:
    currency = require_currency(currency)
    try:
        wallet, _ = Wallet.objects.get_or_create(agent=agent, defaults={"currency": currency})
    except IntegrityError:
        wallet = Wallet.objects.get(agent=agent)
    if wallet.currency != currency:
        raise ValidationError(
            f"Wallet currency is {wallet.currency}; {currency} cannot be mixed."
        )
    return wallet


def _bucket_sum(wallet: Wallet, buckets: list[str]):
    total = wallet.entries.filter(bucket__in=buckets).aggregate(total=Sum("amount"))["total"]
    return money(total or 0)


def refresh_wallet(wallet: Wallet) -> Wallet:
    wallet.pending_balance = _bucket_sum(wallet, [LedgerEntry.Bucket.PENDING])
    wallet.available_balance = _bucket_sum(wallet, [LedgerEntry.Bucket.AVAILABLE])
    withdrawn = _bucket_sum(wallet, [LedgerEntry.Bucket.WITHDRAWN, LedgerEntry.Bucket.PAID])
    wallet.withdrawn_balance = withdrawn
    wallet.paid_balance = withdrawn
    wallet.save(
        update_fields=[
            "pending_balance",
            "available_balance",
            "withdrawn_balance",
            "paid_balance",
            "updated_at",
        ]
    )
    return wallet


def locked_wallet(agent, currency: str = "") -> Wallet:
    wallet = get_or_create_wallet(agent, currency=currency)
    # Postgres: row lock. SQLite: select_for_update is a no-op, so the
    # refresh write below takes a reserved lock for this transaction.
    wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
    return refresh_wallet(wallet)


def post_ledger(
    *,
    wallet: Wallet,
    entry_type: str,
    bucket: str,
    amount,
    commission=None,
    withdrawal=None,
    note: str = "",
    metadata: dict | None = None,
    idempotency_key: str = "",
    source_type: str = "",
    source_id: str = "",
    currency: str = "",
) -> LedgerEntry:
    amount = money(amount)
    currency = require_currency(currency or wallet.currency)
    if currency != wallet.currency:
        raise ValidationError(
            f"Ledger currency {currency} does not match wallet {wallet.currency}."
        )
    key = (idempotency_key or "").strip()
    if key:
        existing = LedgerEntry.objects.filter(idempotency_key=key).first()
        if existing:
            return existing
    if commission is not None and not source_type:
        source_type = "CommissionEntry"
        source_id = str(commission.pk)
    if withdrawal is not None and not source_type:
        source_type = "WithdrawalRequest"
        source_id = str(withdrawal.pk)
    try:
        entry = LedgerEntry.objects.create(
            wallet=wallet,
            agent=wallet.agent,
            currency=currency,
            entry_type=entry_type,
            bucket=bucket,
            amount=amount,
            commission=commission,
            withdrawal=withdrawal,
            note=note,
            metadata=metadata or {},
            idempotency_key=key,
            source_type=source_type,
            source_id=source_id,
        )
    except IntegrityError:
        existing = LedgerEntry.objects.filter(idempotency_key=key).first()
        if existing:
            return existing
        raise
    refresh_wallet(wallet)
    return entry


def post_commission_ledger(entry: CommissionEntry, wallet: Wallet) -> None:
    meta = {
        "gross": str(entry.gross_amount),
        "platform_fee_percent": str(entry.platform_fee_percent),
        "platform_fee": str(entry.platform_fee_amount),
        "net": str(entry.agent_net_amount),
        "rate_type": entry.rate_type,
        "rate_value": str(entry.rate_value),
    }
    post_ledger(
        wallet=wallet,
        entry_type=LedgerEntry.EntryType.COMMISSION_EARNED,
        bucket=LedgerEntry.Bucket.PENDING,
        amount=entry.gross_amount,
        commission=entry,
        currency=entry.currency,
        metadata=meta,
        idempotency_key=f"commission:{entry.pk}:earned",
        note="Gross commission earned (snapshot).",
    )
    post_ledger(
        wallet=wallet,
        entry_type=LedgerEntry.EntryType.PLATFORM_FEE,
        bucket=LedgerEntry.Bucket.PENDING,
        amount=-entry.platform_fee_amount,
        commission=entry,
        currency=entry.currency,
        metadata=meta,
        idempotency_key=f"commission:{entry.pk}:fee",
        note="MISA platform fee (snapshot).",
    )


@transaction.atomic
def record_conversion(
    *,
    tracking_link,
    settle: bool | None = True,
    actor=None,
    request=None,
    source: str = "test",
    source_name: str = "",
    external_id: str = "",
    idempotency_key: str = "",
    gross_value=None,
    currency: str = "",
) -> CommissionEntry:
    from commerce.services.conversions import ingest_conversion

    conversion = ingest_conversion(
        tracking_link=tracking_link,
        settle=settle,
        actor=actor,
        request=request,
        source=source,
        source_name=source_name,
        external_id=external_id,
        idempotency_key=idempotency_key,
        gross_value=gross_value,
        currency=currency,
    )
    if conversion.commission_entry_id:
        return CommissionEntry.objects.get(pk=conversion.commission_entry_id)
    raise ValidationError(conversion.rejection_reason or "Conversion was not commissionable.")


def commission_should_auto_release(hold_days: int | None = None) -> bool:
    days = commission_hold_days() if hold_days is None else int(hold_days)
    return days == 0


@transaction.atomic
def settle_commission(entry: CommissionEntry, *, force: bool = False) -> CommissionEntry:
    entry = CommissionEntry.objects.select_for_update().get(pk=entry.pk)
    if entry.status != CommissionEntry.Status.PENDING:
        raise ValidationError("Only pending commissions can be settled.")
    if not force and entry.available_at and entry.available_at > timezone.now():
        raise ValidationError("This commission is still inside its holding period.")
    wallet = locked_wallet(entry.agent, currency=entry.currency)
    post_ledger(
        wallet=wallet,
        entry_type=LedgerEntry.EntryType.COMMISSION_AVAILABLE,
        bucket=LedgerEntry.Bucket.PENDING,
        amount=-entry.agent_net_amount,
        commission=entry,
        currency=entry.currency,
        idempotency_key=f"commission:{entry.pk}:pending_release",
        note="Move net commission out of pending.",
    )
    post_ledger(
        wallet=wallet,
        entry_type=LedgerEntry.EntryType.COMMISSION_AVAILABLE,
        bucket=LedgerEntry.Bucket.AVAILABLE,
        amount=entry.agent_net_amount,
        commission=entry,
        currency=entry.currency,
        idempotency_key=f"commission:{entry.pk}:available",
        note="Commission is now withdrawable.",
    )
    entry.status = CommissionEntry.Status.SETTLED
    entry.save(update_fields=["status"])
    return entry


@transaction.atomic
def release_matured_commissions() -> int:
    due = CommissionEntry.objects.select_for_update().filter(
        status=CommissionEntry.Status.PENDING,
        available_at__lte=timezone.now(),
    )
    released = 0
    for entry in due:
        settle_commission(entry)
        released += 1
    return released


@transaction.atomic
def reverse_commission(entry: CommissionEntry, *, actor=None, reason: str = "") -> CommissionEntry:
    entry = CommissionEntry.objects.select_for_update().get(pk=entry.pk)
    if entry.status == CommissionEntry.Status.REVERSED:
        raise ValidationError("Commission is already reversed.")
    wallet = locked_wallet(entry.agent, currency=entry.currency)
    if entry.status == CommissionEntry.Status.PENDING:
        post_ledger(
            wallet=wallet,
            entry_type=LedgerEntry.EntryType.COMMISSION_REVERSED,
            bucket=LedgerEntry.Bucket.PENDING,
            amount=-entry.agent_net_amount,
            commission=entry,
            currency=entry.currency,
            idempotency_key=f"commission:{entry.pk}:reversed",
            metadata={"reason": reason},
            note="Reverse pending commission net.",
        )
    elif entry.status == CommissionEntry.Status.SETTLED:
        if wallet.available_balance < entry.agent_net_amount:
            raise ValidationError("Available balance is insufficient to reverse this commission.")
        post_ledger(
            wallet=wallet,
            entry_type=LedgerEntry.EntryType.COMMISSION_REVERSED,
            bucket=LedgerEntry.Bucket.AVAILABLE,
            amount=-entry.agent_net_amount,
            commission=entry,
            currency=entry.currency,
            idempotency_key=f"commission:{entry.pk}:reversed",
            metadata={"reason": reason},
            note="Reverse available commission net.",
        )
    if entry.tracking_link_id:
        record_event(
            tracking_link=entry.tracking_link,
            event_type=TrackingEvent.EventType.CONVERSION_REVERSED,
            code=entry.tracking_link.code,
            metadata={"commission_id": entry.pk},
        )
    old_status = entry.status
    entry.status = CommissionEntry.Status.REVERSED
    entry.save(update_fields=["status"])
    record_audit(
        action="commission.reversed",
        actor=actor,
        object_type="CommissionEntry",
        object_id=str(entry.pk),
        payload={
            "old_value": old_status,
            "new_value": entry.status,
            "reason": reason,
            "net": str(entry.agent_net_amount),
            "currency": entry.currency,
        },
    )
    return entry


@transaction.atomic
def post_adjustment(
    *,
    agent,
    amount,
    bucket: str = LedgerEntry.Bucket.AVAILABLE,
    reason: str,
    actor,
    currency: str = "",
    note: str = "",
) -> LedgerEntry:
    if not (reason or "").strip():
        raise ValidationError("An adjustment reason is required.")
    amount = money(amount)
    if amount == 0:
        raise ValidationError("Adjustment amount cannot be zero.")
    currency = require_currency(currency)
    wallet = locked_wallet(agent, currency=currency)
    if bucket == LedgerEntry.Bucket.AVAILABLE and amount < 0 and wallet.available_balance < abs(amount):
        raise ValidationError("Available balance is insufficient for this adjustment.")
    old = {
        "pending": str(wallet.pending_balance),
        "available": str(wallet.available_balance),
        "withdrawn": str(wallet.withdrawn_balance),
    }
    entry = post_ledger(
        wallet=wallet,
        entry_type=LedgerEntry.EntryType.ADJUSTMENT,
        bucket=bucket,
        amount=amount,
        currency=currency,
        metadata={"reason": reason.strip()},
        note=note or reason.strip(),
    )
    wallet.refresh_from_db()
    record_audit(
        action="ledger.adjustment",
        actor=actor,
        object_type="LedgerEntry",
        object_id=str(entry.pk),
        payload={
            "old_value": old,
            "new_value": {
                "pending": str(wallet.pending_balance),
                "available": str(wallet.available_balance),
                "withdrawn": str(wallet.withdrawn_balance),
            },
            "reason": reason.strip(),
            "amount": str(amount),
            "currency": currency,
            "bucket": bucket,
        },
    )
    return entry


def _require_status(withdrawal: WithdrawalRequest, target: str):
    allowed = WITHDRAWAL_TRANSITIONS.get(withdrawal.status, set())
    if target not in allowed:
        raise ValidationError(f"Cannot transition from {withdrawal.status} to {target}.")


@transaction.atomic
def request_withdrawal(
    *,
    agent,
    amount,
    payout_account: PayoutAccount | None = None,
    reviewer=None,
    currency: str = "",
    idempotency_key: str = "",
) -> WithdrawalRequest:
    amount = money(amount)
    if amount <= 0:
        raise ValidationError("Withdrawal amount must be greater than zero.")
    currency = require_currency(currency)
    wallet = locked_wallet(agent, currency=currency)
    if wallet.available_balance < amount:
        raise ValidationError("Insufficient available balance.")
    destination = ""
    if payout_account:
        if payout_account.agent_id != agent.pk:
            raise ValidationError("Payout account does not belong to this agent.")
        destination = payout_account.destination_ref
    withdrawal = WithdrawalRequest.objects.create(
        agent=agent,
        wallet=wallet,
        payout_account=payout_account,
        amount=amount,
        currency=wallet.currency,
        destination_ref=destination,
        status=WithdrawalRequest.Status.REQUESTED,
    )
    post_ledger(
        wallet=wallet,
        entry_type=LedgerEntry.EntryType.WITHDRAWAL_REQUESTED,
        bucket=LedgerEntry.Bucket.AVAILABLE,
        amount=-amount,
        withdrawal=withdrawal,
        currency=wallet.currency,
        idempotency_key=idempotency_key or f"withdrawal:{withdrawal.pk}:requested",
        metadata={"status": withdrawal.status},
        note="Hold available funds for withdrawal request.",
    )
    record_audit(
        action="withdrawal.requested",
        actor=agent,
        object_type="WithdrawalRequest",
        object_id=str(withdrawal.pk),
        payload={"amount": str(amount), "currency": wallet.currency, "old_value": None, "new_value": withdrawal.status},
    )
    return withdrawal


@transaction.atomic
def approve_withdrawal(withdrawal: WithdrawalRequest, *, reviewer) -> WithdrawalRequest:
    withdrawal = WithdrawalRequest.objects.select_for_update().get(pk=withdrawal.pk)
    _require_status(withdrawal, WithdrawalRequest.Status.APPROVED)
    old = withdrawal.status
    withdrawal.status = WithdrawalRequest.Status.APPROVED
    withdrawal.reviewer = reviewer
    withdrawal.reviewed_at = timezone.now()
    withdrawal.save(update_fields=["status", "reviewer", "reviewed_at"])
    record_audit(
        action="withdrawal.approved",
        actor=reviewer,
        object_type="WithdrawalRequest",
        object_id=str(withdrawal.pk),
        payload={"old_value": old, "new_value": withdrawal.status},
    )
    return withdrawal


@transaction.atomic
def start_withdrawal_processing(withdrawal: WithdrawalRequest, *, reviewer) -> WithdrawalRequest:
    withdrawal = WithdrawalRequest.objects.select_for_update().get(pk=withdrawal.pk)
    _require_status(withdrawal, WithdrawalRequest.Status.PROCESSING)
    old = withdrawal.status
    withdrawal.status = WithdrawalRequest.Status.PROCESSING
    withdrawal.reviewer = reviewer
    if not withdrawal.reviewed_at:
        withdrawal.reviewed_at = timezone.now()
    withdrawal.save(update_fields=["status", "reviewer", "reviewed_at"])
    record_audit(
        action="withdrawal.processing",
        actor=reviewer,
        object_type="WithdrawalRequest",
        object_id=str(withdrawal.pk),
        payload={
            "old_value": old,
            "new_value": withdrawal.status,
            "reason": "Accounting state only; no payment provider confirmation.",
        },
    )
    return withdrawal


def _release_withdrawal_hold(wallet: Wallet, withdrawal: WithdrawalRequest, *, reason: str):
    post_ledger(
        wallet=wallet,
        entry_type=LedgerEntry.EntryType.WITHDRAWAL_REVERSED,
        bucket=LedgerEntry.Bucket.AVAILABLE,
        amount=withdrawal.amount,
        withdrawal=withdrawal,
        currency=withdrawal.currency,
        idempotency_key=f"withdrawal:{withdrawal.pk}:reversed",
        metadata={"reason": reason},
        note="Return held funds to available.",
    )


@transaction.atomic
def reject_withdrawal(withdrawal: WithdrawalRequest, *, reviewer, reason: str = "") -> WithdrawalRequest:
    withdrawal = WithdrawalRequest.objects.select_for_update().get(pk=withdrawal.pk)
    _require_status(withdrawal, WithdrawalRequest.Status.REJECTED)
    wallet = locked_wallet(withdrawal.agent, currency=withdrawal.currency)
    _release_withdrawal_hold(wallet, withdrawal, reason=reason or "rejected")
    old = withdrawal.status
    withdrawal.status = WithdrawalRequest.Status.REJECTED
    withdrawal.reviewer = reviewer
    withdrawal.reviewed_at = timezone.now()
    withdrawal.rejection_reason = reason
    withdrawal.save(update_fields=["status", "reviewer", "reviewed_at", "rejection_reason"])
    record_audit(
        action="withdrawal.rejected",
        actor=reviewer,
        object_type="WithdrawalRequest",
        object_id=str(withdrawal.pk),
        payload={"old_value": old, "new_value": withdrawal.status, "reason": reason},
    )
    return withdrawal


@transaction.atomic
def cancel_withdrawal(withdrawal: WithdrawalRequest, *, actor=None) -> WithdrawalRequest:
    withdrawal = WithdrawalRequest.objects.select_for_update().get(pk=withdrawal.pk)
    _require_status(withdrawal, WithdrawalRequest.Status.CANCELLED)
    wallet = locked_wallet(withdrawal.agent, currency=withdrawal.currency)
    _release_withdrawal_hold(wallet, withdrawal, reason="cancelled")
    old = withdrawal.status
    withdrawal.status = WithdrawalRequest.Status.CANCELLED
    withdrawal.reviewed_at = timezone.now()
    withdrawal.save(update_fields=["status", "reviewed_at"])
    record_audit(
        action="withdrawal.cancelled",
        actor=actor,
        object_type="WithdrawalRequest",
        object_id=str(withdrawal.pk),
        payload={"old_value": old, "new_value": withdrawal.status, "reason": "cancelled"},
    )
    return withdrawal


@transaction.atomic
def fail_withdrawal(withdrawal: WithdrawalRequest, *, reviewer, reason: str = "") -> WithdrawalRequest:
    """Mark processing failed. Held funds stay reserved so the payout can be retried.

    Use reject_withdrawal to release funds back to available.
    """
    withdrawal = WithdrawalRequest.objects.select_for_update().get(pk=withdrawal.pk)
    _require_status(withdrawal, WithdrawalRequest.Status.FAILED)
    old = withdrawal.status
    withdrawal.status = WithdrawalRequest.Status.FAILED
    withdrawal.reviewer = reviewer
    withdrawal.rejection_reason = reason
    withdrawal.save(update_fields=["status", "reviewer", "rejection_reason"])
    record_audit(
        action="withdrawal.failed",
        actor=reviewer,
        object_type="WithdrawalRequest",
        object_id=str(withdrawal.pk),
        payload={
            "old_value": old,
            "new_value": withdrawal.status,
            "reason": reason or "Marked failed in MISA accounting; no payment provider confirmation.",
        },
    )
    return withdrawal


@transaction.atomic
def mark_withdrawal_paid(withdrawal: WithdrawalRequest, *, reviewer) -> WithdrawalRequest:
    """Mark a withdrawal paid in the ledger. This is not a payment-provider confirmation."""
    withdrawal = WithdrawalRequest.objects.select_for_update().get(pk=withdrawal.pk)
    _require_status(withdrawal, WithdrawalRequest.Status.PAID)
    wallet = locked_wallet(withdrawal.agent, currency=withdrawal.currency)
    post_ledger(
        wallet=wallet,
        entry_type=LedgerEntry.EntryType.WITHDRAWAL_PAID,
        bucket=LedgerEntry.Bucket.WITHDRAWN,
        amount=withdrawal.amount,
        withdrawal=withdrawal,
        currency=withdrawal.currency,
        idempotency_key=f"withdrawal:{withdrawal.pk}:paid",
        metadata={"psp_confirmed": False},
        note="Marked paid in MISA accounting; no payment provider confirmation.",
    )
    old = withdrawal.status
    withdrawal.status = WithdrawalRequest.Status.PAID
    withdrawal.reviewer = reviewer
    withdrawal.processed_at = timezone.now()
    if not withdrawal.reviewed_at:
        withdrawal.reviewed_at = timezone.now()
    withdrawal.save(update_fields=["status", "reviewer", "processed_at", "reviewed_at"])
    record_audit(
        action="withdrawal.paid",
        actor=reviewer,
        object_type="WithdrawalRequest",
        object_id=str(withdrawal.pk),
        payload={
            "old_value": old,
            "new_value": withdrawal.status,
            "reason": "Accounting mark only; funds are not confirmed by an external provider.",
        },
    )
    return withdrawal
