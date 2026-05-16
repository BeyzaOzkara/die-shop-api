# backend/routers/work_orders.py
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import exists, and_
from pydantic import BaseModel, ConfigDict
from datetime import datetime, timezone, date
from sqlalchemy import asc

from ..database import get_db
from ..models import (
    WorkOrder,
    WorkOrderOperation,
    OrderStatus,
    OperationStatus,
    WorkCenter,
    WorkCenterStatus,
    DieComponent,
    Lot,
    ProductionOrder,
    Die,
    Operator,
    StockMovement,
    SteelStockItem,
)
from ..deps import require_admin

router = APIRouter(prefix="/work-orders", tags=["Work Orders"])


# =====================================
# Pydantic NESTED MODELLER
# =====================================

class FileRead(BaseModel):
    id: int
    original_name: str
    storage_path: str
    mime_type: str
    size_bytes: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ComponentTypeNested(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class SteelStockItemNested(BaseModel):
    id: int
    alloy: str
    diameter_mm: int
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class DieComponentNested(BaseModel):
    id: int
    die_id: int
    component_type_id: int
    stock_item_id: int
    package_length_mm: float
    theoretical_consumption_kg: float
    created_at: datetime
    component_type: Optional[ComponentTypeNested] = None
    stock_item: Optional[SteelStockItemNested] = None

    model_config = ConfigDict(from_attributes=True)


class LotNested(BaseModel):
    id: int
    stock_item_id: int
    certificate_number: str
    supplier: str
    length_mm: int
    gross_weight_kg: float
    remaining_kg: float
    certificate_file_url: Optional[str] = None
    received_date: datetime
    created_at: datetime
    stock_item: Optional[SteelStockItemNested] = None

    model_config = ConfigDict(from_attributes=True)


class DieTypeNested(BaseModel):  #NEW
    id: int
    code: str
    name: str
    description: Optional[str] = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class DieNested(BaseModel):
    id: int
    die_number: str
    die_diameter_mm: float
    total_package_length_mm: float
    die_type_id: int
    die_type: Optional[DieTypeNested] = None  # NEW
    description: Optional[str] = None
    expected_completion_date: Optional[date] = None

    files: List[FileRead] = []

    model_config = ConfigDict(from_attributes=True)


class ProductionOrderNested(BaseModel):
    id: int
    die_id: int
    order_number: str
    status: OrderStatus
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    die: Optional[DieNested] = None

    model_config = ConfigDict(from_attributes=True)


# =====================================
# WORK ORDER MODELLERİ
# =====================================

class WorkOrderBase(BaseModel):
    production_order_id: int
    die_component_id: int
    order_number: str
    status: OrderStatus = OrderStatus.Waiting
    theoretical_consumption_kg: float
    actual_consumption_kg: Optional[float] = None
    lot_id: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class WorkOrderCreate(BaseModel):
    production_order_id: int
    die_component_id: int
    order_number: str
    theoretical_consumption_kg: float
    status: OrderStatus = OrderStatus.Waiting


class WorkOrderUpdate(BaseModel):
    production_order_id: Optional[int] = None
    die_component_id: Optional[int] = None
    order_number: Optional[str] = None
    status: Optional[OrderStatus] = None
    theoretical_consumption_kg: Optional[float] = None
    actual_consumption_kg: Optional[float] = None
    lot_id: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class WorkOrderRead(WorkOrderBase):
    id: int
    created_at: datetime
    die_component: Optional[DieComponentNested] = None
    lot: Optional[LotNested] = None
    production_order: Optional[ProductionOrderNested] = None

    model_config = ConfigDict(from_attributes=True)


# =====================================
# WORK CENTER / OPERATION NESTED MODELLER
# =====================================

class WorkCenterNested(BaseModel):
    id: int
    name: str
    status: WorkCenterStatus
    location: Optional[str] = None
    capacity_per_hour: Optional[int] = None
    setup_time_minutes: Optional[int] = None
    cost_per_hour: Optional[float] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OperationTypeNested(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    is_active: bool = True

    model_config = ConfigDict(from_attributes=True)


class WorkOrderNestedForOperation(BaseModel):
    id: int
    production_order_id: int
    die_component_id: int
    order_number: str
    status: OrderStatus
    theoretical_consumption_kg: float
    actual_consumption_kg: Optional[float] = None
    lot_id: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    die_component: Optional[DieComponentNested] = None
    production_order: Optional[ProductionOrderNested] = None

    model_config = ConfigDict(from_attributes=True)


class WorkOrderOperationBase(BaseModel):
    work_order_id: int
    sequence_number: int
    operation_name: str
    work_center_id: Optional[int]
    operator_name: Optional[str] = None
    status: OperationStatus = OperationStatus.Waiting
    estimated_duration_minutes: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    notes: Optional[str] = None


class WorkOrderOperationCreate(BaseModel):
    work_order_id: int
    sequence_number: int
    operation_type_id: int
    operation_name: Optional[str] = None
    work_center_id: Optional[int] = None
    estimated_duration_minutes: Optional[int] = None
    notes: Optional[str] = None
    status: OperationStatus = OperationStatus.Waiting

class WorkOrderOperationUpdate(BaseModel):
    sequence_number: Optional[int] = None
    operation_type_id: Optional[int] = None
    operation_name: Optional[str] = None
    work_center_id: Optional[int] = None
    operator_name: Optional[str] = None
    status: Optional[OperationStatus] = None
    estimated_duration_minutes: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    notes: Optional[str] = None

class WorkOrderOperationRead(BaseModel):
    id: int
    work_order_id: int
    sequence_number: int
    operation_type_id: int
    operation_name: Optional[str] = None
    work_center_id: Optional[int] = None   # nullable
    operator_name: Optional[str] = None
    status: OperationStatus
    estimated_duration_minutes: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime

    work_center: Optional[WorkCenterNested] = None
    operation_type: Optional[OperationTypeNested] = None
    work_order: Optional[WorkOrderNestedForOperation] = None

    model_config = ConfigDict(from_attributes=True)


class WorkOrderOperationWithWorkOrderRead(WorkOrderOperationRead):
    work_order: Optional[WorkOrderNestedForOperation] = None

class AssignOperationRequest(BaseModel):
    work_center_id: int
    operator_name: Optional[str] = None

class LotForSawRead(BaseModel):
    id: int
    certificate_number: str
    supplier: str
    length_mm: int
    gross_weight_kg: float
    remaining_kg: float
    received_date: datetime
    
    # ✅ yeni (opsiyonel ama öneririm)
    stock_item_id: int
    alloy: Optional[str] = None
    diameter_mm: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

# =====================================
# WORK ORDER ENDPOINT'LERİ
# =====================================

# @router.get("/", response_model=List[WorkOrderRead])
@router.get("/", response_model=List[WorkOrderRead], dependencies=[Depends(require_admin)])
def list_work_orders(db: Session = Depends(get_db)):
    rows = (
        db.query(WorkOrder)
        .options(
            joinedload(WorkOrder.die_component).joinedload(DieComponent.component_type),
            joinedload(WorkOrder.die_component).joinedload(DieComponent.stock_item),
            joinedload(WorkOrder.lot).joinedload(Lot.stock_item),
            joinedload(WorkOrder.production_order).joinedload(ProductionOrder.die).options(                         # ✅ EKLE
                joinedload(Die.die_type),
                joinedload(Die.files),
            ),
        )
        .order_by(WorkOrder.created_at.desc())
        .all()
    )
    return rows


# @router.get("/{id}", response_model=WorkOrderRead)
@router.get("/{id}", response_model=WorkOrderRead, dependencies=[Depends(require_admin)])
def get_work_order(id: int, db: Session = Depends(get_db)):
    wo = (
        db.query(WorkOrder)
        .options(
            joinedload(WorkOrder.die_component).joinedload(DieComponent.component_type),
            joinedload(WorkOrder.die_component).joinedload(DieComponent.stock_item),
            joinedload(WorkOrder.lot).joinedload(Lot.stock_item),
            joinedload(WorkOrder.production_order).joinedload(ProductionOrder.die).options(                         # ✅ EKLE
                joinedload(Die.die_type),
                joinedload(Die.files),
            ),
        )
        .filter(WorkOrder.id == id)
        .first()
    )
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")
    return wo


# @router.post("/", response_model=WorkOrderRead, status_code=201)
@router.post("/", response_model=WorkOrderRead, status_code=201, dependencies=[Depends(require_admin)])
def create_work_order(payload: WorkOrderCreate, db: Session = Depends(get_db)):
    existing = (
        db.query(WorkOrder)
        .filter(WorkOrder.order_number == payload.order_number)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Work order number already exists")

    wo = WorkOrder(
        production_order_id=payload.production_order_id,
        die_component_id=payload.die_component_id,
        order_number=payload.order_number,
        theoretical_consumption_kg=payload.theoretical_consumption_kg,
        status=payload.status,
    )
    db.add(wo)
    db.commit()
    db.refresh(wo)

    # nestedleri load edelim
    wo = (
        db.query(WorkOrder)
        .options(
            joinedload(WorkOrder.die_component).joinedload(DieComponent.component_type),
            joinedload(WorkOrder.die_component).joinedload(DieComponent.stock_item),
            joinedload(WorkOrder.lot).joinedload(Lot.stock_item),
            joinedload(WorkOrder.production_order).joinedload(ProductionOrder.die),
        )
        .get(wo.id)
    )
    return wo


# @router.patch("/{id}", response_model=WorkOrderRead)
@router.patch("/{id}", response_model=WorkOrderRead, dependencies=[Depends(require_admin)])
def update_work_order(id: int, payload: WorkOrderUpdate, db: Session = Depends(get_db)):
    wo = db.query(WorkOrder).get(id)
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(wo, field, value)

    db.commit()
    db.refresh(wo)
    wo = (
        db.query(WorkOrder)
        .options(
            joinedload(WorkOrder.die_component)
            .joinedload(DieComponent.component_type),
            joinedload(WorkOrder.die_component)
            .joinedload(DieComponent.stock_item),
            joinedload(WorkOrder.lot)
            .joinedload(Lot.stock_item),
            joinedload(WorkOrder.production_order)
            .joinedload(ProductionOrder.die),
        )
        .get(wo.id)
    )
    return wo


# =====================================
# WORK ORDER OPERATIONS ENDPOINT'LERİ
# =====================================

# Aynı app içinde ama farklı prefix kullanmak için ikinci router'ı da buradan expose edeceğiz.
ops_router = APIRouter(prefix="/work-order-operations", tags=["Work Order Operations"])


class StartOperationRequest(BaseModel):
    work_center_id: int
    operator_name: Optional[str] = None # name değil sicil no yapalım
    notes: Optional[str] = None


@ops_router.get("/by-work-order/{work_order_id}", response_model=List[WorkOrderOperationRead])
def list_operations_for_work_order(
    work_order_id: int,
    db: Session = Depends(get_db),
):
    rows = (
        db.query(WorkOrderOperation)
        .options(joinedload(WorkOrderOperation.work_center),
            joinedload(WorkOrderOperation.operation_type),)
        .filter(WorkOrderOperation.work_order_id == work_order_id)
        .order_by(WorkOrderOperation.sequence_number.asc())
        .all()
    )
    return rows


# ---------------------------
# ASSIGNED QUEUE (work_center_id = X)
# ---------------------------
@ops_router.get("/assigned/by-work-center/{work_center_id}", response_model=List[WorkOrderOperationWithWorkOrderRead])
def list_assigned_operations_by_work_center(work_center_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(WorkOrderOperation)
        .options(
            joinedload(WorkOrderOperation.work_center),
            joinedload(WorkOrderOperation.operation_type),
            joinedload(WorkOrderOperation.work_order)
                .joinedload(WorkOrder.die_component)
                .joinedload(DieComponent.component_type),
            joinedload(WorkOrderOperation.work_order)
                .joinedload(WorkOrder.production_order)
                .joinedload(ProductionOrder.die)
                .joinedload(Die.die_type),
            joinedload(WorkOrderOperation.work_order)
                .joinedload(WorkOrder.production_order)
                .joinedload(ProductionOrder.die)
                .joinedload(Die.files),
        )
        .filter(WorkOrderOperation.work_center_id == work_center_id,
        WorkOrderOperation.status.in_([OperationStatus.Waiting, OperationStatus.InProgress, OperationStatus.Paused]),)
        .order_by(WorkOrderOperation.created_at.asc())
        .all()
    )
    return rows


# ---------------------------
# ELIGIBLE QUEUE (work_center_id IS NULL + wc.operation_types includes op.operation_type_id)
# ---------------------------
@ops_router.get("/eligible/by-work-center/{work_center_id}", response_model=List[WorkOrderOperationWithWorkOrderRead])
def list_eligible_operations_for_work_center(work_center_id: int, db: Session = Depends(get_db)):
    wc = (
        db.query(WorkCenter)
        .options(joinedload(WorkCenter.operation_types))
        .get(work_center_id)
    )
    if not wc:
        raise HTTPException(status_code=404, detail="Work center not found")

    op_type_ids = [ot.id for ot in wc.operation_types]
    if not op_type_ids:
        return []

    rows = (
        db.query(WorkOrderOperation)
        .options(
            joinedload(WorkOrderOperation.work_center),
            joinedload(WorkOrderOperation.operation_type),
            joinedload(WorkOrderOperation.work_order)
                .joinedload(WorkOrder.die_component)
                .joinedload(DieComponent.component_type),
            joinedload(WorkOrderOperation.work_order)
                .joinedload(WorkOrder.production_order)
                .joinedload(ProductionOrder.die)
                .joinedload(Die.die_type),
            joinedload(WorkOrderOperation.work_order)
                .joinedload(WorkOrder.production_order)
                .joinedload(ProductionOrder.die)
                .joinedload(Die.files),
        )
        .filter(
            WorkOrderOperation.work_center_id.is_(None),
            WorkOrderOperation.operation_type_id.in_(op_type_ids),
            WorkOrderOperation.status == OperationStatus.Waiting,
        )
        .order_by(WorkOrderOperation.created_at.asc())
        .all()
    )
    return rows


# ---------------------------
# ASSIGN (eligible -> assigned)
# ---------------------------
# Operatör panelinde “uygun iş listesinden seçip merkezi seçip başlat” akışı var — bu endpoint operatör panelinde kullanılacak.
@ops_router.post("/{id}/assign", response_model=WorkOrderOperationRead)
def assign_operation(id: int, payload: AssignOperationRequest, db: Session = Depends(get_db)):
    op_row = db.query(WorkOrderOperation).get(id)
    if not op_row:
        raise HTTPException(status_code=404, detail="Work order operation not found")

    if op_row.work_center_id is not None:
        raise HTTPException(status_code=400, detail="Operation is already assigned to a work center")

    if op_row.status != OperationStatus.Waiting:
        raise HTTPException(status_code=400, detail="Only Waiting operations can be assigned")

    wc = (
        db.query(WorkCenter)
        .options(joinedload(WorkCenter.operation_types))
        .get(payload.work_center_id)
    )
    if not wc:
        raise HTTPException(status_code=404, detail="Work center not found")

    allowed_ids = {ot.id for ot in wc.operation_types}
    if op_row.operation_type_id not in allowed_ids:
        raise HTTPException(status_code=400, detail="This work center cannot perform this operation type")

    op_row.work_center_id = wc.id
    if payload.operator_name:
        op_row.operator_name = payload.operator_name

    db.commit()
    db.refresh(op_row)

    op_row = (
        db.query(WorkOrderOperation)
        .options(
            joinedload(WorkOrderOperation.work_center),
            joinedload(WorkOrderOperation.operation_type),
        )
        .get(op_row.id)
    )
    return op_row


@ops_router.get("/by-work-center/{work_center_id}", response_model=List[WorkOrderOperationWithWorkOrderRead])
def list_operations_by_work_center(
    work_center_id: int,
    db: Session = Depends(get_db),
):
    rows = (
        db.query(WorkOrderOperation)
        .options(
            joinedload(WorkOrderOperation.work_center),
            joinedload(WorkOrderOperation.operation_type),
            joinedload(WorkOrderOperation.work_order).joinedload(WorkOrder.die_component).joinedload(DieComponent.component_type),
            joinedload(WorkOrderOperation.work_order).joinedload(WorkOrder.production_order).joinedload(ProductionOrder.die),
            joinedload(WorkOrderOperation.work_order).joinedload(WorkOrder.production_order).joinedload(ProductionOrder.die).joinedload(Die.die_type),
            joinedload(WorkOrderOperation.work_order).joinedload(WorkOrder.production_order).joinedload(ProductionOrder.die).joinedload(Die.files),
        )
        .filter(WorkOrderOperation.work_center_id == work_center_id,
        WorkOrderOperation.status.in_([OperationStatus.Waiting, OperationStatus.InProgress, OperationStatus.Paused]),)
        .order_by(WorkOrderOperation.created_at.asc())
        .all()
    )
    return rows


# @ops_router.post("/", response_model=WorkOrderOperationRead, status_code=201)
@ops_router.post("/", response_model=WorkOrderOperationRead, status_code=201, dependencies=[Depends(require_admin)])
def create_work_order_operation(
    payload: WorkOrderOperationCreate,
    db: Session = Depends(get_db),
):
    op_row = WorkOrderOperation(**payload.model_dump())
    db.add(op_row)
    db.commit()
    db.refresh(op_row)

    op_row = (
        db.query(WorkOrderOperation)
        .options(
            joinedload(WorkOrderOperation.work_center),
            joinedload(WorkOrderOperation.operation_type),
        )
        .get(op_row.id)
    )
    return op_row


@ops_router.patch("/{id}", response_model=WorkOrderOperationRead)
def update_work_order_operation(
    id: int,
    payload: WorkOrderOperationUpdate,
    db: Session = Depends(get_db),
):
    op = db.query(WorkOrderOperation).get(id)
    if not op:
        raise HTTPException(status_code=404, detail="Work order operation not found")

    data = payload.model_dump(exclude_unset=True)

    # Eğer status güncellenecekse özel mantığı burada çalıştır
    if "status" in data:
        new_status = data["status"]

        # new_status hem Enum hem string gelebilir, normalize edelim
        if isinstance(new_status, str):
            new_status = OperationStatus(new_status)

        def require_work_center(): # operatör starı start_ope ile yapacak buradaki admin yapmak isterse diye
            if op.work_center_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="Bu işlem için önce work center atanmış olmalı.",
                )

        # ---- InProgress'e geçerken: önceki operasyonlar tamam mı? ----
        if new_status == OperationStatus.InProgress:
            require_work_center()
            previous_ops = (
                db.query(WorkOrderOperation)
                .filter(
                    WorkOrderOperation.work_order_id == op.work_order_id,
                    WorkOrderOperation.sequence_number < op.sequence_number,
                )
                .all()
            )
            if any(p.status != OperationStatus.Completed for p in previous_ops):
                raise HTTPException(
                    status_code=400,
                    detail="Önceki operasyon(lar) tamamlanmadan bu operasyon başlatılamaz.",
                )

            op.status = OperationStatus.InProgress
            op.started_at = datetime.now(timezone.utc)

            # Work center'ı meşgul yap
            wc = db.query(WorkCenter).get(op.work_center_id)
            # if wc:
            #     wc.status = WorkCenterStatus.Busy
            if wc:
                is_isil_islem = False
                if op.operation_type and op.operation_type.name in ['ISIL İŞLEM TARTIM', 'ISIL İŞLEM']:
                    is_isil_islem = True
                elif wc.name in ['ISIL İŞLEM TARTIM', 'ISIL İŞLEM']:
                    is_isil_islem = True
                
                if not is_isil_islem:
                    wc.status = WorkCenterStatus.Busy

        elif new_status == OperationStatus.Paused:
            require_work_center()
            op.status = OperationStatus.Paused
            wc = db.query(WorkCenter).get(op.work_center_id)
            if wc:
                wc.status = WorkCenterStatus.Available
            # log eklenecek

        elif new_status == OperationStatus.Cancelled:
            require_work_center()
            op.status = OperationStatus.Cancelled
            op.completed_at = datetime.now(timezone.utc)

            wc = db.query(WorkCenter).get(op.work_center_id)
            if wc:
                wc.status = WorkCenterStatus.Available

            # log eklenecek

        # ---- Completed'a geçerken: bitiş tarihi ve work center durumu ----
        elif new_status == OperationStatus.Completed:
            require_work_center()
            op.status = OperationStatus.Completed
            op.completed_at = datetime.now(timezone.utc)

            wc = db.query(WorkCenter).get(op.work_center_id)
            if wc:
                wc.status = WorkCenterStatus.Available

        else:
            # Diğer statüler için sadece doğrudan ata
            op.status = new_status

        # Generic loop'ta bir daha status set etmeyelim
        data.pop("status", None)
        

    # status dışındaki alanları generic olarak güncelle
    for field, value in data.items():
        setattr(op, field, value)

    db.commit()
    db.refresh(op)
    op = (
        db.query(WorkOrderOperation)
        .options(joinedload(WorkOrderOperation.work_center))
        .get(op.id)
    )
    return op


@ops_router.post("/{id}/start", response_model=WorkOrderOperationRead)
def start_operation(
    id: int,
    payload: StartOperationRequest,
    db: Session = Depends(get_db),
):
    """
    Eğer operasyon zaten assigned değilse → seçilen work_center’a assign eder
    Zaten başka merkeze assigned ise → 400
    Status Waiting veya Paused ise başlatır
    Önceki operasyonlar tamam mı kontrol eder
    started_at set eder
    WorkCenter → Busy yapar
    """
    op_row = (
        db.query(WorkOrderOperation)
        .options(joinedload(WorkOrderOperation.work_center),
                 joinedload(WorkOrderOperation.operation_type))
        .get(id)
    )
    if not op_row:
        raise HTTPException(status_code=404, detail="Work order operation not found")

    # sadece Waiting / Paused başlatılabilir
    if op_row.status not in (OperationStatus.Waiting, OperationStatus.Paused):
        raise HTTPException(status_code=400, detail="Only Waiting/Paused operations can be started")

    # work center ataması: yoksa ata, varsa aynı mı kontrol et
    if op_row.work_center_id is None:
        wc = (
            db.query(WorkCenter)
            .options(joinedload(WorkCenter.operation_types))
            .get(payload.work_center_id)
        )
        if not wc:
            raise HTTPException(status_code=404, detail="Work center not found")

        allowed_ids = {ot.id for ot in wc.operation_types}
        if op_row.operation_type_id not in allowed_ids:
            raise HTTPException(status_code=400, detail="This work center cannot perform this operation type")

        op_row.work_center_id = wc.id

    else:
        # zaten assigned ise farklı bir wc ile start edilemesin
        if op_row.work_center_id != payload.work_center_id:
            raise HTTPException(status_code=400, detail="Operation is already assigned to another work center")

        wc = db.query(WorkCenter).get(op_row.work_center_id)
        if not wc:
            raise HTTPException(status_code=404, detail="Assigned work center not found")

    # önceki operasyonlar tamam mı?
    previous_ops = (
        db.query(WorkOrderOperation)
        .filter(
            WorkOrderOperation.work_order_id == op_row.work_order_id,
            WorkOrderOperation.sequence_number < op_row.sequence_number,
        )
        .all()
    )
    not_completed = [p for p in previous_ops if p.status != OperationStatus.Completed]
    if not_completed:
        raise HTTPException(
            status_code=400,
            detail="Önceki operasyon(lar) tamamlanmadan bu operasyon başlatılamaz.",
        )

    # başlat
    op_row.status = OperationStatus.InProgress
    op_row.started_at = datetime.now(timezone.utc)

    if payload.operator_name:
        op_row.operator_name = payload.operator_name

    # work center busy
    # wc.status = WorkCenterStatus.Busy
    is_isil_islem = False
    if op_row.operation_type and op_row.operation_type.name in ['ISIL İŞLEM TARTIM', 'ISIL İŞLEM']:
        is_isil_islem = True
    elif wc.name in ['ISIL İŞLEM TARTIM', 'ISIL İŞLEM']:
        is_isil_islem = True
        
    if not is_isil_islem:
        wc.status = WorkCenterStatus.Busy

    db.commit()
    db.refresh(op_row)

    op_row = (
        db.query(WorkOrderOperation)
        .options(
            joinedload(WorkOrderOperation.work_center),
            joinedload(WorkOrderOperation.operation_type),
        )
        .get(op_row.id)
    )
    return op_row


class AvailableForOperatorRequest(BaseModel):
    operator_id: int
    operation_type_id: int


# Seçilen operation type + önceki işlemler tamam
# Operator’un izinli work center’ları içinden, seçilen operation_type_id için, başlatılabilir operasyonlar listesi
@ops_router.post("/available-for-operator", response_model=List[WorkOrderOperationWithWorkOrderRead])
def available_for_operator(payload: AvailableForOperatorRequest, db: Session = Depends(get_db)):
    # operator + work centers + their op types
    op = (
        db.query(Operator)
        .options(joinedload(Operator.work_centers).joinedload(WorkCenter.operation_types))
        .get(payload.operator_id)
    )
    if not op:
        raise HTTPException(status_code=404, detail="Operator not found")

    allowed_wc_ids = [wc.id for wc in op.work_centers]
    if not allowed_wc_ids:
        return []

    # operatorın izinli WC’leri içinde bu operation type’ı yapabilen WC var mı?
    eligible_wc_ids = []
    for wc in op.work_centers:
        if any(ot.id == payload.operation_type_id for ot in wc.operation_types):
            eligible_wc_ids.append(wc.id)

    if not eligible_wc_ids:
        return []

    # previous ops completed check: NOT EXISTS (previous not completed)
    prev_not_completed = exists().where(and_(
        WorkOrderOperation.work_order_id == WorkOrderOperation.work_order_id,  # placeholder; aşağıda correlate edeceğiz
    ))

    # SQLAlchemy correlate için doğru kullanım:
    prev_not_completed = (
        db.query(WorkOrderOperation.id)
        .filter(
            WorkOrderOperation.work_order_id == WorkOrderOperation.work_order_id,  # correlate
        )
    )

    # Daha net yazalım: alias ile
    from sqlalchemy.orm import aliased
    Prev = aliased(WorkOrderOperation)

    rows = (
        db.query(WorkOrderOperation)  
        .options(
            joinedload(WorkOrderOperation.operation_type),
            joinedload(WorkOrderOperation.work_order)
                .joinedload(WorkOrder.die_component)
                .joinedload(DieComponent.component_type),
            joinedload(WorkOrderOperation.work_order)
                .joinedload(WorkOrder.production_order)
                .joinedload(ProductionOrder.die)
                .joinedload(Die.die_type),
            joinedload(WorkOrderOperation.work_order)
                .joinedload(WorkOrder.production_order)
                .joinedload(ProductionOrder.die)
                .joinedload(Die.files),
        )
        .filter(
            WorkOrderOperation.status == OperationStatus.Waiting,
            WorkOrderOperation.work_center_id.is_(None),
            WorkOrderOperation.operation_type_id == payload.operation_type_id,
            ~exists().where(and_(
                Prev.work_order_id == WorkOrderOperation.work_order_id,
                Prev.sequence_number < WorkOrderOperation.sequence_number,
                Prev.status != OperationStatus.Completed,
            ))
        )
        .order_by(WorkOrderOperation.created_at.asc())
        .all()
    )
    return rows


@ops_router.get("/{operation_id}/available-lots", response_model=List[LotForSawRead])
def list_available_lots_for_operation(operation_id: int, db: Session = Depends(get_db)):
    op = (
        db.query(WorkOrderOperation)
        .options(
            joinedload(WorkOrderOperation.work_order)
                .joinedload(WorkOrder.die_component)
                .joinedload(DieComponent.stock_item)   # ✅ stock_item'ı da yükle
        )
        .get(operation_id)
    )
    if not op:
        raise HTTPException(status_code=404, detail="Work order operation not found")

    if not op.work_order or not op.work_order.die_component or not op.work_order.die_component.stock_item:
        raise HTTPException(status_code=400, detail="Operation has no die component / stock item")

    component_stock = op.work_order.die_component.stock_item
    min_diameter = component_stock.diameter_mm
    alloy = component_stock.alloy

    # ✅ aynı alloy + çap >= seçilen çap olan tüm stock_item’ları bul
    eligible_stock_item_ids = [
        x.id
        for x in (
            db.query(SteelStockItem.id)
            .filter(
                SteelStockItem.alloy == alloy,
                SteelStockItem.diameter_mm >= min_diameter,
            )
            .all()
        )
    ]

    if not eligible_stock_item_ids:
        return []

    lots = (
        db.query(Lot)
        .options(joinedload(Lot.stock_item))  # ✅ alloy/diameter döndürmek için
        .filter(
            Lot.stock_item_id.in_(eligible_stock_item_ids),
            Lot.remaining_kg > 0
        )
        # ✅ önce daha küçük çaplar önce gelsin (seçilen çapa yakın), sonra eski lotlar
        .order_by(
            asc(Lot.stock_item_id),          # istersen bunu kaldır
            asc(Lot.received_date)
        )
        .all()
    )

    # ✅ response’a alloy/diameter basmak için map’leyelim
    out: List[LotForSawRead] = []
    for lot in lots:
        out.append(LotForSawRead(
            id=lot.id,
            certificate_number=lot.certificate_number,
            supplier=lot.supplier,
            length_mm=lot.length_mm,
            gross_weight_kg=lot.gross_weight_kg,
            remaining_kg=lot.remaining_kg,
            received_date=lot.received_date,
            stock_item_id=lot.stock_item_id,
            alloy=getattr(lot.stock_item, "alloy", None),
            diameter_mm=getattr(lot.stock_item, "diameter_mm", None),
        ))
    return out

class CompleteSawRequest(BaseModel):
    lot_id: int
    quantity_kg: float
    note: Optional[str] = None

@ops_router.post("/{operation_id}/complete-saw", response_model=WorkOrderOperationRead)
def complete_saw_operation(operation_id: int, payload: CompleteSawRequest, db: Session = Depends(get_db)):
    """
    TESTERE operasyonu tamamlanırken:
    - Lot seçilir
    - quantity_kg kadar lot.remaining_kg düşülür
    - StockMovement yazılır
    - WorkOrder.lot_id set edilir (+ actual_consumption_kg opsiyonel güncellenir)
    - Operation Completed + wc Available
    """
    op = (
        db.query(WorkOrderOperation)
        .options(
            joinedload(WorkOrderOperation.work_center),
            joinedload(WorkOrderOperation.work_order)
                .joinedload(WorkOrder.die_component)
                .joinedload(DieComponent.stock_item),   # ✅ EKLE
            joinedload(WorkOrderOperation.operation_type),
        )
        .get(operation_id)
    )

    if not op:
        raise HTTPException(status_code=404, detail="Work order operation not found")

    # sadece atanmış operasyon tamamlanabilir
    if op.work_center_id is None:
        raise HTTPException(status_code=400, detail="Work center must be assigned before completing")

    # zaten Completed/Cancelled ise engelle
    if op.status in (OperationStatus.Completed, OperationStatus.Cancelled):
        raise HTTPException(status_code=400, detail="Operation is already completed/cancelled")

    # TESTERE check (senin datanda opTypeId=33 gibi duruyor)
    # İstersen daha sağlam: op.operation_type.code == "SAW" gibi yaparsın.
    # SAW_OPERATION_TYPE_ID = 33
    # if op.operation_type_id != SAW_OPERATION_TYPE_ID:
    #     raise HTTPException(status_code=400, detail="This endpoint is only for SAW/TESTERE operations")
    if op.operation_type.code not in ["T", "SAW", "TESTERE"]:
        raise HTTPException(status_code=400, detail=f"This endpoint is only for SAW/TESTERE operations (got {op.operation_type.code})")

    if payload.quantity_kg <= 0:
        raise HTTPException(status_code=400, detail="quantity_kg must be > 0")

    wo = op.work_order
    if not wo or not wo.die_component:
        raise HTTPException(status_code=400, detail="Work order / die component not found")

    # Lot doğrula: aynı stock_item mı?
    # lot = db.query(Lot).get(payload.lot_id)
    lot = (
        db.query(Lot)
        .options(joinedload(Lot.stock_item))   # ✅ EKLE
        .get(payload.lot_id)
    )

    if not lot:
        raise HTTPException(status_code=404, detail="Lot not found")

    # stock_item_id = wo.die_component.stock_item_id
    # if lot.stock_item_id != stock_item_id:
    #     raise HTTPException(status_code=400, detail="Selected lot does not match required steel stock item")

    component_stock = wo.die_component.stock_item
    if not component_stock:
        raise HTTPException(status_code=400, detail="Die component stock item not found")

    # ✅ alloy + diameter kuralı
    lot_stock = lot.stock_item
    if not lot_stock:
        raise HTTPException(status_code=400, detail="Lot stock item not found")

    if lot_stock.alloy != component_stock.alloy:
        raise HTTPException(
            status_code=400,
            detail=f"Selected lot alloy mismatch (need {component_stock.alloy}, got {lot_stock.alloy})",
        )

    if int(lot_stock.diameter_mm) < int(component_stock.diameter_mm):
        raise HTTPException(
            status_code=400,
            detail=f"Selected lot diameter too small (need >= {component_stock.diameter_mm}, got {lot_stock.diameter_mm})",
        )

    if float(lot.remaining_kg) < float(payload.quantity_kg):
        raise HTTPException(status_code=400, detail="Lot remaining_kg is not enough")

    # Lot düş
    lot.remaining_kg = float(lot.remaining_kg) - float(payload.quantity_kg)

    # WorkOrder lot + actual
    wo.lot_id = lot.id
    if wo.actual_consumption_kg is None:
        wo.actual_consumption_kg = float(payload.quantity_kg)
    else:
        wo.actual_consumption_kg = float(wo.actual_consumption_kg) + float(payload.quantity_kg)

    # StockMovement yaz
    mv = StockMovement(
        lot_id=lot.id,
        work_order_id=wo.id,
        quantity_kg=float(payload.quantity_kg),
        movement_date=datetime.now(timezone.utc),
        notes=payload.note,
    )
    db.add(mv)

    # Operation completed + timestamps
    op.status = OperationStatus.Completed
    op.completed_at = datetime.now(timezone.utc)

    # WorkCenter available
    wc = db.query(WorkCenter).get(op.work_center_id)
    if wc:
        wc.status = WorkCenterStatus.Available

    db.commit()
    db.refresh(op)

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
                .joinedload(ProductionOrder.die)
                .joinedload(Die.die_type),
            joinedload(WorkOrderOperation.work_order)
                .joinedload(WorkOrder.production_order)
                .joinedload(ProductionOrder.die)
                .joinedload(Die.files),
        )
        .get(op.id)
    )
    return op