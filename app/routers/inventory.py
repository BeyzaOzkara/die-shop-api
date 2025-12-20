# backend/routers/inventory.py
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel, ConfigDict
from datetime import datetime

from ..database import get_db
from ..models import (
    WorkCenter,
    WorkCenterStatus,
    SteelStockItem,
    Lot,
    StockMovement,
    OperationType,
)

router = APIRouter(prefix="/inventory", tags=["Inventory"])


# =========================
# Pydantic Şemalar
# =========================

class OperationTypeNested(BaseModel):
    id: int
    code: str
    name: str
    model_config = ConfigDict(from_attributes=True)

class WorkCenterBase(BaseModel):
    name: str
    status: WorkCenterStatus = WorkCenterStatus.Available
    location: Optional[str] = None
    capacity_per_hour: Optional[int] = None
    setup_time_minutes: Optional[int] = None
    cost_per_hour: Optional[float] = None


class WorkCenterCreate(WorkCenterBase):
    operation_type_ids: List[int] = []


class WorkCenterUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[WorkCenterStatus] = None
    location: Optional[str] = None
    capacity_per_hour: Optional[int] = None
    setup_time_minutes: Optional[int] = None
    cost_per_hour: Optional[float] = None
    operation_type_ids: Optional[List[int]] = None


class WorkCenterRead(WorkCenterBase):
    id: int
    created_at: datetime
    operation_types: List[OperationTypeNested] = []
    model_config = ConfigDict(from_attributes=True)


class SteelStockItemBase(BaseModel):
    alloy: str
    diameter_mm: int
    description: Optional[str] = None


class SteelStockItemCreate(SteelStockItemBase):
    pass


class SteelStockItemRead(SteelStockItemBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LotBase(BaseModel):
    stock_item_id: int
    certificate_number: str
    supplier: str
    length_mm: int
    gross_weight_kg: float
    remaining_kg: float
    certificate_file_url: Optional[str] = None
    received_date: datetime


class LotCreate(LotBase):
    pass


class StockItemNested(BaseModel):
    id: int
    alloy: str
    diameter_mm: int
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class LotRead(LotBase):
    id: int
    created_at: datetime
    stock_item: Optional[StockItemNested] = None

    model_config = ConfigDict(from_attributes=True)


class LotRemainingRead(BaseModel):
    id: int
    remaining_kg: float

    model_config = ConfigDict(from_attributes=True)


class LotUpdateRemaining(BaseModel):
    remaining_kg: float


class StockMovementBase(BaseModel):
    lot_id: int
    work_order_id: int
    quantity_kg: float
    movement_date: datetime
    notes: Optional[str] = None


class StockMovementCreate(StockMovementBase):
    pass


class StockMovementRead(StockMovementBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# =========================
# Work Centers
# =========================

@router.get("/work-centers", response_model=List[WorkCenterRead])
def list_work_centers(db: Session = Depends(get_db)):
    return (
        db.query(WorkCenter)
        .options(joinedload(WorkCenter.operation_types))
        .order_by(WorkCenter.name)
        .all()
    )


@router.post("/work-centers", response_model=WorkCenterRead, status_code=201)
def create_work_center(payload: WorkCenterCreate, db: Session = Depends(get_db)):
    wc = WorkCenter(
        name=payload.name,
        status=payload.status,
        location=payload.location,
        capacity_per_hour=payload.capacity_per_hour,
        setup_time_minutes=payload.setup_time_minutes,
        cost_per_hour=payload.cost_per_hour,
    )

    if payload.operation_type_ids:
        ots = (
            db.query(OperationType)
            .filter(OperationType.id.in_(payload.operation_type_ids))
            .all()
        )
        wc.operation_types = ots

    db.add(wc)
    db.commit()
    db.refresh(wc)
    db.refresh(wc, attribute_names=["operation_types"])
    return wc

@router.delete("/work-centers/{id}", status_code=204)
def delete_work_center(id: int, db: Session = Depends(get_db)):
    wc = db.query(WorkCenter).get(id)
    if not wc:
        raise HTTPException(status_code=404, detail="Work center not found")
    db.delete(wc)
    db.commit()
    return

@router.patch("/work-centers/{id}", response_model=WorkCenterRead)
def update_work_center(id: int, payload: WorkCenterUpdate, db: Session = Depends(get_db)):
    wc = (
        db.query(WorkCenter)
        .options(joinedload(WorkCenter.operation_types))
        .get(id)
    )
    if not wc:
        raise HTTPException(status_code=404, detail="Work center not found")

    data = payload.model_dump(exclude_unset=True)

    # normal alanlar
    for field in ["name", "status", "location", "capacity_per_hour", "setup_time_minutes", "cost_per_hour"]:
        if field in data:
            setattr(wc, field, data[field])

    # M2M replace
    if "operation_type_ids" in data:
        from ..models import OperationType
        ids = data["operation_type_ids"] or []
        ots = db.query(OperationType).filter(OperationType.id.in_(ids)).all() if ids else []
        wc.operation_types = ots

    db.commit()
    db.refresh(wc)
    db.refresh(wc, attribute_names=["operation_types"])
    return wc

# =========================
# Steel Stock Items
# =========================

@router.get("/steel-stock-items", response_model=List[SteelStockItemRead])
def list_steel_stock_items(db: Session = Depends(get_db)):
    return (
        db.query(SteelStockItem)
        .order_by(SteelStockItem.alloy, SteelStockItem.diameter_mm)
        .all()
    )

@router.post("/steel-stock-items", response_model=SteelStockItemRead, status_code=201)
def create_steel_stock_item(payload: SteelStockItemCreate, db: Session = Depends(get_db)):
    item = SteelStockItem(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

# =========================
# Lots
# =========================

@router.get("/lots", response_model=List[LotRead])
def list_lots(include_stock_item: bool = True, db: Session = Depends(get_db)):
    query = db.query(Lot)
    if include_stock_item:
        query = query.options(joinedload(Lot.stock_item))
    lots = query.order_by(Lot.received_date.desc()).all()
    return lots

@router.get("/lots/by-stock-item/{stock_item_id}", response_model=List[LotRead])
def list_lots_by_stock_item(
    stock_item_id: int,
    only_with_remaining: bool = True,
    db: Session = Depends(get_db),
):
    query = (
        db.query(Lot)
        .options(joinedload(Lot.stock_item))
        .filter(Lot.stock_item_id == stock_item_id)
    )
    if only_with_remaining:
        query = query.filter(Lot.remaining_kg > 0)
    lots = query.order_by(Lot.received_date.asc()).all()
    return lots

@router.post("/lots", response_model=LotRead, status_code=201)
def create_lot(payload: LotCreate, db: Session = Depends(get_db)):
    lot = Lot(**payload.model_dump())
    db.add(lot)
    db.commit()
    db.refresh(lot)
    # eager load stock_item
    db.refresh(lot, attribute_names=["stock_item"])
    return lot

@router.get("/lots/{lot_id}/remaining", response_model=LotRemainingRead)
def get_lot_remaining(lot_id: int, db: Session = Depends(get_db)):
    lot = db.query(Lot).get(lot_id)
    if not lot:
        raise HTTPException(status_code=404, detail="Lot not found")
    return LotRemainingRead(id=lot.id, remaining_kg=float(lot.remaining_kg))

@router.patch("/lots/{lot_id}/remaining", response_model=LotRead)
def update_lot_remaining(lot_id: int, payload: LotUpdateRemaining, db: Session = Depends(get_db)):
    lot = db.query(Lot).options(joinedload(Lot.stock_item)).get(lot_id)
    if not lot:
        raise HTTPException(status_code=404, detail="Lot not found")
    lot.remaining_kg = payload.remaining_kg
    db.commit()
    db.refresh(lot)
    return lot

# =========================
# Stock Movements
# =========================

@router.post("/stock-movements", response_model=StockMovementRead, status_code=201)
def create_stock_movement(payload: StockMovementCreate, db: Session = Depends(get_db)):
    movement = StockMovement(**payload.model_dump())
    db.add(movement)
    db.commit()
    db.refresh(movement)
    return movement

@router.get("/stock-movements", response_model=List[StockMovementRead])
def list_stock_movements(db: Session = Depends(get_db)):
    return (
        db.query(StockMovement)
        .order_by(StockMovement.movement_date.desc())
        .all()
    )
