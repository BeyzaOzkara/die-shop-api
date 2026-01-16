# app/routers/operator_panel.py
"""
Operator panel endpoints for RFID-authenticated operators.
Enhanced operation lifecycle with pre-checks, structured reason codes, and logging.
"""
from typing import List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload, aliased
from sqlalchemy import exists, and_
from pydantic import BaseModel, ConfigDict

from ..database import get_db
import json
from ..models import (
    WorkOrderOperation,
    WorkOrder,
    WorkCenter,
    Operator,
    ProductionOrder,
    Die,
    DieComponent,
    OperationStatus,
    WorkCenterStatus,
    ExecutionMode,
    DomainActionLog,
)
from ..services.action_logger import log_action, snapshot_operation

router = APIRouter(prefix="/operator-panel", tags=["Operator Panel"])


# =========================
# Pydantic Schemas
# =========================

class PreStartCheckResponse(BaseModel):
    """Response for operation pre-start check."""
    can_start: bool
    blockers: List[str] = []
    warnings: List[str] = []
    
    # Operation info
    operation_id: int
    operation_name: Optional[str] = None
    operation_type_name: Optional[str] = None
    sequence_number: int
    
    # Previous operations status
    previous_operations_completed: bool
    pending_previous_count: int = 0
    
    # Work center info (if already assigned)
    assigned_work_center_id: Optional[int] = None
    assigned_work_center_name: Optional[str] = None
    
    # Work order context
    work_order_number: Optional[str] = None
    die_number: Optional[str] = None
    component_type_name: Optional[str] = None


class StartOperationRequest(BaseModel):
    operator_id: int
    work_center_id: int


class StartOperationResponse(BaseModel):
    id: int
    status: OperationStatus
    operation_name: Optional[str] = None
    work_center_id: int
    started_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


class StopOperationRequest(BaseModel):
    operator_id: int
    reason_code: str  # "COMPLETED", "LUNCH_BREAK", "MACHINE_FAILURE", "QUALITY_ISSUE", "MATERIAL_SHORTAGE", etc.
    next_status: OperationStatus  # Completed, Paused, Cancelled
    notes: Optional[str] = None


class StopOperationResponse(BaseModel):
    id: int
    status: OperationStatus
    completed_at: Optional[datetime] = None
    reason_logged: str
    
    model_config = ConfigDict(from_attributes=True)


class BatchStartRequest(BaseModel):
    operator_id: int
    work_center_id: int
    operation_ids: List[int]


class BatchStartResponse(BaseModel):
    started_count: int
    started_operation_ids: List[int]
    failed_operation_ids: List[int]
    errors: List[str]


# =========================
# Helper Functions
# =========================

def get_operation_with_context(db: Session, operation_id: int) -> WorkOrderOperation:
    """Load operation with all related context."""
    op = (
        db.query(WorkOrderOperation)
        .options(
            joinedload(WorkOrderOperation.work_center),
            joinedload(WorkOrderOperation.operation_type),
            joinedload(WorkOrderOperation.work_order)
                .joinedload(WorkOrder.die_component)
                .joinedload(DieComponent.component_type),
            joinedload(WorkOrderOperation.work_order)
                .joinedload(WorkOrder.production_order)
                .joinedload(ProductionOrder.die),
        )
        .get(operation_id)
    )
    return op


def check_previous_operations_completed(db: Session, operation: WorkOrderOperation) -> tuple[bool, int]:
    """Check if all previous operations in sequence are completed."""
    previous_ops = (
        db.query(WorkOrderOperation)
        .filter(
            WorkOrderOperation.work_order_id == operation.work_order_id,
            WorkOrderOperation.sequence_number < operation.sequence_number,
        )
        .all()
    )
    
    not_completed = [p for p in previous_ops if p.status != OperationStatus.Completed]
    return len(not_completed) == 0, len(not_completed)


# =========================
# Endpoints
# =========================

@router.post("/operations/{operation_id}/pre-start-check", response_model=PreStartCheckResponse)
def pre_start_check(
    operation_id: int,
    db: Session = Depends(get_db),
):
    """
    Check if an operation can be started.
    Returns blockers (must be resolved) and warnings (can proceed with caution).
    """
    op = get_operation_with_context(db, operation_id)
    if not op:
        raise HTTPException(status_code=404, detail="Operation not found")
    
    blockers = []
    warnings = []
    
    # Check status
    if op.status not in (OperationStatus.Waiting, OperationStatus.Paused):
        blockers.append(f"Operation status is {op.status.value}, must be Waiting or Paused to start")
    
    # Check previous operations
    prev_completed, pending_count = check_previous_operations_completed(db, op)
    if not prev_completed:
        blockers.append(f"{pending_count} previous operation(s) not completed")
    
    # Check work center if already assigned
    if op.work_center_id:
        wc = db.get(WorkCenter, op.work_center_id)
        if wc and wc.status == WorkCenterStatus.Busy:
            warnings.append(f"Assigned work center '{wc.name}' is currently busy")
        elif wc and wc.status == WorkCenterStatus.UnderMaintenance:
            blockers.append(f"Assigned work center '{wc.name}' is under maintenance")
    
    # Build response
    can_start = len(blockers) == 0
    
    # Extract context info
    wo = op.work_order
    die_number = None
    component_type_name = None
    
    if wo:
        if wo.production_order and wo.production_order.die:
            die_number = wo.production_order.die.die_number
        if wo.die_component and wo.die_component.component_type:
            component_type_name = wo.die_component.component_type.name
    
    return PreStartCheckResponse(
        can_start=can_start,
        blockers=blockers,
        warnings=warnings,
        operation_id=op.id,
        operation_name=op.operation_name,
        operation_type_name=op.operation_type.name if op.operation_type else None,
        sequence_number=op.sequence_number,
        previous_operations_completed=prev_completed,
        pending_previous_count=pending_count,
        assigned_work_center_id=op.work_center_id,
        assigned_work_center_name=op.work_center.name if op.work_center else None,
        work_order_number=wo.order_number if wo else None,
        die_number=die_number,
        component_type_name=component_type_name,
    )


@router.post("/operations/{operation_id}/start", response_model=StartOperationResponse)
def start_operation(
    operation_id: int,
    payload: StartOperationRequest,
    db: Session = Depends(get_db),
):
    """
    Start an operation with operator RFID authentication and logging.
    """
    # Validate operator
    operator = db.get(Operator, payload.operator_id)
    if not operator or not operator.is_active:
        raise HTTPException(status_code=404, detail="Operator not found or inactive")
    
    # Get operation
    op = get_operation_with_context(db, operation_id)
    if not op:
        raise HTTPException(status_code=404, detail="Operation not found")
    
    # Check status
    if op.status not in (OperationStatus.Waiting, OperationStatus.Paused):
        raise HTTPException(status_code=400, detail=f"Cannot start operation in {op.status.value} status")
    
    # Check previous operations
    prev_completed, pending_count = check_previous_operations_completed(db, op)
    if not prev_completed:
        raise HTTPException(status_code=400, detail=f"{pending_count} previous operation(s) not completed")
    
    # Validate work center
    wc = (
        db.query(WorkCenter)
        .options(joinedload(WorkCenter.operation_types))
        .get(payload.work_center_id)
    )
    if not wc:
        raise HTTPException(status_code=404, detail="Work center not found")
    
    # Check work center can do this operation type
    allowed_ids = {ot.id for ot in wc.operation_types}
    if op.operation_type_id not in allowed_ids:
        raise HTTPException(status_code=400, detail="Work center cannot perform this operation type")
    
    # Check assignment
    if op.work_center_id is not None and op.work_center_id != payload.work_center_id:
        raise HTTPException(status_code=400, detail="Operation already assigned to different work center")
    
    # Capture before state
    before = snapshot_operation(op)
    
    # Update operation
    op.work_center_id = wc.id
    op.operator_name = operator.name  # Store operator name for display
    op.status = OperationStatus.InProgress
    op.started_at = datetime.now(timezone.utc)
    
    # Mark work center busy
    wc.status = WorkCenterStatus.Busy
    
    # Log the action
    log_action(
        db=db,
        action_type="OPERATION_START",
        actor_type="operator",
        actor_id=operator.id,
        entity_type="work_order_operation",
        entity_id=op.id,
        before_snapshot=before,
        after_snapshot=snapshot_operation(op),
        meta_data={
            "work_center_id": wc.id,
            "work_center_name": wc.name,
            "operator_rfid": operator.rfid_code,
        },
    )
    
    db.commit()
    db.refresh(op)
    
    return StartOperationResponse(
        id=op.id,
        status=op.status,
        operation_name=op.operation_name,
        work_center_id=op.work_center_id,
        started_at=op.started_at,
    )


@router.post("/operations/{operation_id}/stop", response_model=StopOperationResponse)
def stop_operation(
    operation_id: int,
    payload: StopOperationRequest,
    db: Session = Depends(get_db),
):
    """
    Stop an operation with structured reason code and logging.
    """
    # Validate operator
    operator = db.get(Operator, payload.operator_id)
    if not operator or not operator.is_active:
        raise HTTPException(status_code=404, detail="Operator not found or inactive")
    
    # Validate next status
    if payload.next_status not in (OperationStatus.Completed, OperationStatus.Paused, OperationStatus.Cancelled):
        raise HTTPException(status_code=400, detail="next_status must be Completed, Paused, or Cancelled")
    
    # Get operation
    op = get_operation_with_context(db, operation_id)
    if not op:
        raise HTTPException(status_code=404, detail="Operation not found")
    
    # Check status
    if op.status != OperationStatus.InProgress:
        raise HTTPException(status_code=400, detail=f"Cannot stop operation in {op.status.value} status")
    
    if not op.work_center_id:
        raise HTTPException(status_code=400, detail="Operation has no work center assigned")
    
    # Capture before state
    before = snapshot_operation(op)
    
    # Update operation
    op.status = payload.next_status
    if payload.next_status in (OperationStatus.Completed, OperationStatus.Cancelled):
        op.completed_at = datetime.now(timezone.utc)
    
    # Free up work center
    wc = db.get(WorkCenter, op.work_center_id)
    if wc:
        wc.status = WorkCenterStatus.Available
    
    # Log the action
    action_type = f"OPERATION_{payload.next_status.value.upper()}"  # OPERATION_COMPLETED, OPERATION_PAUSED, etc.
    log_action(
        db=db,
        action_type=action_type,
        actor_type="operator",
        actor_id=operator.id,
        entity_type="work_order_operation",
        entity_id=op.id,
        reason=payload.reason_code,
        notes=payload.notes,
        before_snapshot=before,
        after_snapshot=snapshot_operation(op),
        meta_data={
            "work_center_id": op.work_center_id,
            "operator_rfid": operator.rfid_code,
        },
    )
    
    db.commit()
    db.refresh(op)
    
    return StopOperationResponse(
        id=op.id,
        status=op.status,
        completed_at=op.completed_at,
        reason_logged=payload.reason_code,
    )


@router.post("/batch-start", response_model=BatchStartResponse)
def batch_start_operations(
    payload: BatchStartRequest,
    db: Session = Depends(get_db),
):
    """
    Start multiple operations of the same batch-capable operation type.
    All operations must have execution_mode=Batch and same operation_type.
    """
    # Validate operator
    operator = db.get(Operator, payload.operator_id)
    if not operator or not operator.is_active:
        raise HTTPException(status_code=404, detail="Operator not found or inactive")
    
    # Validate work center
    wc = (
        db.query(WorkCenter)
        .options(joinedload(WorkCenter.operation_types))
        .get(payload.work_center_id)
    )
    if not wc:
        raise HTTPException(status_code=404, detail="Work center not found")
    
    if not payload.operation_ids:
        raise HTTPException(status_code=400, detail="No operation IDs provided")
    
    # Load all operations
    operations = (
        db.query(WorkOrderOperation)
        .options(joinedload(WorkOrderOperation.operation_type))
        .filter(WorkOrderOperation.id.in_(payload.operation_ids))
        .all()
    )
    
    if len(operations) != len(payload.operation_ids):
        raise HTTPException(status_code=400, detail="Some operations not found")
    
    # Validate all are same operation type and batch-capable
    operation_types = {op.operation_type_id for op in operations}
    if len(operation_types) > 1:
        raise HTTPException(status_code=400, detail="All operations must be same operation type for batch start")
    
    first_op = operations[0]
    if not first_op.operation_type or first_op.operation_type.execution_mode != ExecutionMode.Batch:
        raise HTTPException(status_code=400, detail="Operation type is not batch-capable")
    
    # Check work center can do this operation type
    allowed_ids = {ot.id for ot in wc.operation_types}
    if first_op.operation_type_id not in allowed_ids:
        raise HTTPException(status_code=400, detail="Work center cannot perform this operation type")
    
    # --- Log-based Batch Numbering ---
    
    # Format: {work_center_id}-{YY}-{XXXX}
    # Example: 5-26-0001
    
    # 1. Find last BATCH_START action for this work center
    last_batch_log = (
        db.query(DomainActionLog)
        .filter(
            DomainActionLog.action_type == "OPERATION_BATCH_START",
            DomainActionLog.meta_data.like(f'%"work_center_id": {wc.id}%')
        )
        .order_by(DomainActionLog.created_at.desc())
        .first()
    )
    
    current_year_suffix = datetime.now().strftime("%y") # "26"
    sequence_num = 1
    
    if last_batch_log and last_batch_log.meta_data:
        try:
            meta = json.loads(last_batch_log.meta_data)
            last_batch_number = meta.get("batch_number")
            if last_batch_number:
                # Parse: "5-26-0042"
                parts = last_batch_number.split("-")
                if len(parts) == 3:
                    last_wc_id, last_year, last_seq = parts
                    if last_wc_id == str(wc.id) and last_year == current_year_suffix:
                        sequence_num = int(last_seq) + 1
        except Exception:
            pass # fallback to 1 if parse fails
            
    batch_number = f"{wc.id}-{current_year_suffix}-{sequence_num:04d}"
    
    started_ids = []
    failed_ids = []
    errors = []
    # batch_number generation gerekli, log içine yazılacak
    # Log BATCH action (we log per operation, but share the batch number)
    for op in operations:
        try:
            # Check status
            if op.status not in (OperationStatus.Waiting, OperationStatus.Paused):
                failed_ids.append(op.id)
                errors.append(f"Operation {op.id}: status is {op.status.value}")
                continue
            
            # Check previous operations
            prev_completed, pending_count = check_previous_operations_completed(db, op)
            if not prev_completed:
                failed_ids.append(op.id)
                errors.append(f"Operation {op.id}: {pending_count} previous op(s) not completed")
                continue
            
            # Check assignment
            if op.work_center_id is not None and op.work_center_id != payload.work_center_id:
                failed_ids.append(op.id)
                errors.append(f"Operation {op.id}: assigned to different work center")
                continue
            
            # Start operation
            before = snapshot_operation(op)
            op.work_center_id = wc.id
            op.operator_name = operator.name
            op.status = OperationStatus.InProgress
            op.started_at = datetime.now(timezone.utc)
            
            log_action(
                db=db,
                action_type="OPERATION_BATCH_START",
                actor_type="operator",
                actor_id=operator.id,
                entity_type="work_order_operation",
                entity_id=op.id,
                before_snapshot=before,
                after_snapshot=snapshot_operation(op),
                meta_data={
                    "batch_number": batch_number,
                    "batch_operation_ids": payload.operation_ids,
                    "work_center_id": wc.id,
                },
            )
            
            started_ids.append(op.id)
            
        except Exception as e:
            failed_ids.append(op.id)
            errors.append(f"Operation {op.id}: {str(e)}")
    
    # Mark work center busy if any started
    if started_ids:
        wc.status = WorkCenterStatus.Busy
    
    db.commit()
    
    return BatchStartResponse(
        started_count=len(started_ids),
        started_operation_ids=started_ids,
        failed_operation_ids=failed_ids,
        errors=errors,
    )
