# app/services/action_logger.py
"""
Centralized domain action logging service.
Captures business event audit trail (not error logging).

NOTES
- DomainActionLog.before_snapshot / after_snapshot / meta_data are JSONB columns.
- Therefore we store Python dict/list directly (NOT json.dumps strings).
- Values inside snapshots must be JSON-serializable. This module provides _to_jsonable()
  to safely convert common types (datetime, Decimal, Enum, UUID, etc.).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional, Union
from uuid import UUID

from sqlalchemy.orm import Session

from ..models import DomainActionLog


# ---------------------------
# JSONB-friendly type helpers
# ---------------------------
JsonPrimitive = Union[str, int, float, bool, None]
JsonValue = Union[JsonPrimitive, Dict[str, Any], list[Any]]


def _to_jsonable(value: Any) -> JsonValue:
    """
    Convert common Python/SQLAlchemy types into JSON-serializable values.
    Keeps domain logging from crashing due to non-JSON types.

    - datetime/date -> ISO8601 string (timezone-aware for datetime)
    - Decimal -> float
    - Enum -> .value (fallback to str)
    - UUID -> str
    - dict/list/tuple/set -> recursively converted
    - fallback -> str(value)
    """
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Decimal):
        # If you need exactness, use str(value) instead.
        return float(value)

    if isinstance(value, (datetime, date)):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()

    if isinstance(value, Enum):
        try:
            return _to_jsonable(value.value)
        except Exception:
            return str(value)

    if isinstance(value, UUID):
        return str(value)

    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v) for v in value]

    return str(value)


# ---------------------------
# Public API
# ---------------------------
def log_action(
    db: Session,
    action_type: str,
    actor_type: str,
    entity_type: str,
    entity_id: int,
    actor_id: Optional[int] = None,
    reason: Optional[str] = None,
    notes: Optional[str] = None,
    before_snapshot: Optional[dict] = None,
    after_snapshot: Optional[dict] = None,
    meta_data: Optional[dict] = None,
) -> DomainActionLog:
    """
    Log a domain action for audit trail.

    IMPORTANT:
    - This function does NOT commit. Caller manages commit/rollback so the log is part
      of the same transaction as the business action.

    Args:
        action_type: e.g. "OPERATION_START", "OPERATION_COMPLETE"
        actor_type: "user", "operator", "system"
        entity_type: e.g. "work_order_operation"
        entity_id: PK of affected entity
        actor_id: optional (system actions may be None)
        reason: optional reason code (pause/cancel)
        notes: optional free text
        before_snapshot/after_snapshot/meta_data: dicts stored as JSONB

    Returns:
        The created DomainActionLog row (pending flush/commit).
    """
    log_entry = DomainActionLog(
        action_type=action_type,
        actor_type=actor_type,
        actor_id=actor_id,
        entity_type=entity_type,
        entity_id=entity_id,
        reason=reason,
        notes=notes,
        before_snapshot=_to_jsonable(before_snapshot) if before_snapshot is not None else None,
        after_snapshot=_to_jsonable(after_snapshot) if after_snapshot is not None else None,
        meta_data=_to_jsonable(meta_data) if meta_data is not None else None,
    )

    db.add(log_entry)
    return log_entry


# ---------------------------
# Snapshots (Level 1 - Minimal)
# ---------------------------
def snapshot_operation(operation: Any) -> dict:
    """
    Minimal snapshot of a WorkOrderOperation.
    Keep only fields that matter for audit/debug.
    """
    return {
        "id": operation.id,
        "status": operation.status.value if getattr(operation, "status", None) else None,
        "work_center_id": getattr(operation, "work_center_id", None),
        "operator_name": getattr(operation, "operator_name", None),
        "started_at": getattr(operation, "started_at", None),
        "completed_at": getattr(operation, "completed_at", None),
    }


def snapshot_work_order(work_order: Any) -> dict:
    """
    Minimal snapshot of a WorkOrder.
    """
    actual = getattr(work_order, "actual_consumption_kg", None)

    return {
        "id": work_order.id,
        "status": work_order.status.value if getattr(work_order, "status", None) else None,
        "lot_id": getattr(work_order, "lot_id", None),
        "actual_consumption_kg": float(actual) if actual is not None else None,
        "started_at": getattr(work_order, "started_at", None),
        "completed_at": getattr(work_order, "completed_at", None),
    }
