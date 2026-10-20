from commerce.models import AuditLog


def record_audit(
    *,
    action: str,
    actor=None,
    impersonator=None,
    object_type: str = "",
    object_id: str = "",
    payload: dict | None = None,
) -> AuditLog:
    return AuditLog.objects.create(
        actor=actor,
        impersonator=impersonator,
        action=action,
        object_type=object_type,
        object_id=object_id,
        payload=payload or {},
    )
