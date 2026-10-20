from __future__ import annotations

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


def record_usage(
    *,
    owner=None,
    project=None,
    provider: str,
    operation: str,
    status: str = "succeeded",
    request_id: str = "",
    model_name: str = "",
    cost_amount: Decimal | None = None,
    metadata: dict | None = None,
) -> None:
    if owner is None and project is not None:
        owner = getattr(project, "owner", None)
    if owner is None:
        return
    try:
        from ai.models import UsageRecord

        UsageRecord.objects.create(
            owner=owner,
            project=project,
            provider=provider,
            model_name=model_name,
            operation=operation,
            status=status,
            request_id=request_id,
            cost_amount=cost_amount,
            metadata=metadata or {},
        )
    except Exception:
        logger.exception("Could not store usage")
