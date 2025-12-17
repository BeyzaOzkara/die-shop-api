# backend/routers/work_orders.py
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel, ConfigDict
from datetime import datetime, timezone

from ..database import get_db
from ..models import (
    WorkOrder,
    WorkOrderOperation,
    OrderStatus,
    OperationStatus,
    WorkCenter,
    WorkCenterStatus,
    DieComponent,
    ComponentType,
    SteelStockItem,
    Lot,
    ProductionOrder,
    Die,
)

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
    package_length_mm: int
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
    die_diameter_mm: int
    total_package_length_mm: int
    die_type_id: int
    die_type: Optional[DieTypeNested] = None  # NEW

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
    type: str
    status: WorkCenterStatus
    location: Optional[str] = None
    capacity_per_hour: Optional[int] = None
    setup_time_minutes: Optional[int] = None
    cost_per_hour: Optional[float] = None
    created_at: datetime

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
    work_center_id: int
    operator_name: Optional[str] = None
    status: OperationStatus = OperationStatus.Waiting
    estimated_duration_minutes: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    notes: Optional[str] = None


class WorkOrderOperationCreate(BaseModel):
    work_order_id: int
    sequence_number: int
    operation_name: str
    work_center_id: int
    estimated_duration_minutes: Optional[int] = None
    notes: Optional[str] = None
    status: OperationStatus = OperationStatus.Waiting


class WorkOrderOperationUpdate(BaseModel):
    work_order_id: Optional[int] = None
    sequence_number: Optional[int] = None
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
    operation_name: str
    work_center_id: int
    operator_name: Optional[str] = None
    status: OperationStatus
    estimated_duration_minutes: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime
    work_center: Optional[WorkCenterNested] = None

    model_config = ConfigDict(from_attributes=True)


class WorkOrderOperationWithWorkOrderRead(WorkOrderOperationRead):
    work_order: Optional[WorkOrderNestedForOperation] = None





# =====================================
# WORK ORDER ENDPOINT'LERİ
# =====================================

@router.get("/", response_model=List[WorkOrderRead])
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


@router.get("/{id}", response_model=WorkOrderRead)
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


@router.post("/", response_model=WorkOrderRead, status_code=201)
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


@router.patch("/{id}", response_model=WorkOrderRead) 
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


@ops_router.get("/by-work-order/{work_order_id}", response_model=List[WorkOrderOperationRead])
def list_operations_for_work_order(
    work_order_id: int,
    db: Session = Depends(get_db),
):
    rows = (
        db.query(WorkOrderOperation)
        .options(joinedload(WorkOrderOperation.work_center))
        .filter(WorkOrderOperation.work_order_id == work_order_id)
        .order_by(WorkOrderOperation.sequence_number.asc())
        .all()
    )
    return rows


@ops_router.get("/by-work-center/{work_center_id}", response_model=List[WorkOrderOperationWithWorkOrderRead])
def list_operations_by_work_center(
    work_center_id: int,
    db: Session = Depends(get_db),
):
    rows = (
        db.query(WorkOrderOperation)
        .options(
            joinedload(WorkOrderOperation.work_center),
            joinedload(WorkOrderOperation.work_order).joinedload(WorkOrder.die_component).joinedload(DieComponent.component_type),
            joinedload(WorkOrderOperation.work_order).joinedload(WorkOrder.production_order).joinedload(ProductionOrder.die)
            .options(
                joinedload(Die.die_type),
                joinedload(Die.files),
            ),
        )
        .filter(WorkOrderOperation.work_center_id == work_center_id)
        .order_by(WorkOrderOperation.created_at.asc())
        .all()
    )
    return rows


@ops_router.post("/", response_model=WorkOrderOperationRead, status_code=201)
def create_work_order_operation(
    payload: WorkOrderOperationCreate,
    db: Session = Depends(get_db),
):
    op = WorkOrderOperation(
        work_order_id=payload.work_order_id,
        sequence_number=payload.sequence_number,
        operation_name=payload.operation_name,
        work_center_id=payload.work_center_id,
        estimated_duration_minutes=payload.estimated_duration_minutes,
        notes=payload.notes,
        status=payload.status,
    )
    db.add(op)
    db.commit()
    db.refresh(op)

    # work_center join'li dönelim
    op = (
        db.query(WorkOrderOperation)
        .options(joinedload(WorkOrderOperation.work_center))
        .get(op.id)
    )
    return op


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

        # ---- InProgress'e geçerken: önceki operasyonlar tamam mı? ----
        if new_status == OperationStatus.InProgress:
            previous_ops = (
                db.query(WorkOrderOperation)
                .filter(
                    WorkOrderOperation.work_order_id == op.work_order_id,
                    WorkOrderOperation.sequence_number < op.sequence_number,
                )
                .all()
            )
            not_completed = [
                p for p in previous_ops
                if p.status != OperationStatus.Completed
            ]
            if not_completed:
                raise HTTPException(
                    status_code=400,
                    detail="Önceki operasyon(lar) tamamlanmadan bu operasyon başlatılamaz.",
                )

            op.status = OperationStatus.InProgress
            op.started_at = datetime.now(timezone.utc)

            # İstersek operatör adını da burada güncelleriz
            if "operator_name" in data and data["operator_name"]:
                op.operator_name = data["operator_name"]

            # Work center'ı meşgul yap
            wc = db.query(WorkCenter).get(op.work_center_id)
            if wc:
                wc.status = WorkCenterStatus.Busy

            # Bu alanları ayrıca aşağıdaki generic loop'ta set etmeyelim
            data.pop("operator_name", None)

        elif new_status == OperationStatus.Paused:
            op.status = OperationStatus.Paused

            # log eklenecek

            data.pop("operator_name", None)

        elif new_status == OperationStatus.Cancelled:
            op.status = OperationStatus.Cancelled
            op.completed_at = datetime.now(timezone.utc)

            wc = db.query(WorkCenter).get(op.work_center_id)
            if wc:
                wc.status = WorkCenterStatus.Available

            data.pop("operator_name", None)

            # log eklenecek

        # ---- Completed'a geçerken: bitiş tarihi ve work center durumu ----
        elif new_status == OperationStatus.Completed:
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
