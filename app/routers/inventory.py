# backend/routers/inventory.py
from typing import List, Optional
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File as UploadFileField, Form, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func, cast, String
from pydantic import BaseModel, ConfigDict

from ..config import settings
from ..services.file_storage import save_uploaded_file
from ..database import get_db
from ..models import (
    WorkCenter,
    WorkCenterStatus,
    OperationType,
    Location,
    ItemCategory,
    MaterialGrade,
    Supplier,
    Lot,
    StockItem,
    StockTransaction,
    ProcessBatch,
    ItemType,
    TransactionType,
    BatchStatus
)
from ..schemas.inventory import (
    ItemCategoryCreate, ItemCategoryRead, ItemCategoryUpdate,
    MaterialGradeCreate, MaterialGradeRead, MaterialGradeUpdate,
    LocationCreate, LocationRead, LocationUpdate,
    LotCreate, LotRead,
    StockItemCreate, StockItemRead, StockItemPaginatedRead,
    StockTransactionRead,
    ProcessBatchCreate, ProcessBatchRead,
    CutSteelRequest, CutSteelResponse,
    CompleteBatchRequest, CompleteBatchResponse
)
from ..services.inventory_service import cut_steel_generate_wip, complete_process_batch

router = APIRouter(prefix="/inventory", tags=["Inventory"])

# =========================
# WorkCenter & Base Schemas
# =========================

class OperationTypeNested(BaseModel):
    id: int
    code: str
    name: str
    model_config = ConfigDict(from_attributes=True)

class WorkCenterBase(BaseModel):
    name: str
    status: WorkCenterStatus = WorkCenterStatus.Available
    capacity_per_hour: Optional[int] = None
    setup_time_minutes: Optional[int] = None
    cost_per_hour: Optional[float] = None

class WorkCenterCreate(WorkCenterBase):
    operation_type_ids: List[int] = []

class WorkCenterUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[WorkCenterStatus] = None
    capacity_per_hour: Optional[int] = None
    setup_time_minutes: Optional[int] = None
    cost_per_hour: Optional[float] = None
    operation_type_ids: Optional[List[int]] = None

class WorkCenterRead(WorkCenterBase):
    id: int
    created_at: datetime
    operation_types: List[OperationTypeNested] = []
    model_config = ConfigDict(from_attributes=True)

class FileRead(BaseModel):
    id: int
    original_name: str
    storage_path: str
    mime_type: str
    size_bytes: int
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
        capacity_per_hour=payload.capacity_per_hour,
        setup_time_minutes=payload.setup_time_minutes,
        cost_per_hour=payload.cost_per_hour,
    )
    if payload.operation_type_ids:
        ots = db.query(OperationType).filter(OperationType.id.in_(payload.operation_type_ids)).all()
        wc.operation_types = ots
    db.add(wc)
    db.flush()
    
    from ..models import LocationType
    # Automatically generate paired inventory location
    loc = Location(
        name=f"{wc.name} Location",
        location_type=LocationType.WORK_CENTER,
        work_center_id=wc.id,
        is_active=True
    )
    db.add(loc)
    
    db.commit()
    db.refresh(wc)
    db.refresh(wc, attribute_names=["operation_types"])
    return wc

@router.delete("/work-centers/{id}", status_code=204)
def delete_work_center(id: int, db: Session = Depends(get_db)):
    wc = db.query(WorkCenter).get(id)
    if not wc:
        raise HTTPException(status_code=404, detail="Work center not found")
        
    loc = db.query(Location).filter(Location.work_center_id == id).first()
    if loc:
        # Check for active WIP stock
        if db.query(StockItem).filter(StockItem.location_id == loc.id).first():
            raise HTTPException(
                status_code=400, 
                detail="Cannot delete work center: active stock exists in its location. Move the stock first."
            )
        db.delete(loc)
        
    db.delete(wc)
    db.commit()
    return

@router.patch("/work-centers/{id}", response_model=WorkCenterRead)
def update_work_center(id: int, payload: WorkCenterUpdate, db: Session = Depends(get_db)):
    wc = db.query(WorkCenter).options(joinedload(WorkCenter.operation_types)).get(id)
    if not wc:
        raise HTTPException(status_code=404, detail="Work center not found")

    data = payload.model_dump(exclude_unset=True)
    
    # Synchronize Location name if WorkCenter name changes
    if "name" in data and data["name"] != wc.name:
        loc = db.query(Location).filter(Location.work_center_id == id).first()
        if loc:
            loc.name = f"{data['name']} Location"

    for field in ["name", "status", "capacity_per_hour", "setup_time_minutes", "cost_per_hour"]:
        if field in data:
            setattr(wc, field, data[field])

    if "operation_type_ids" in data:
        ids = data["operation_type_ids"] or []
        ots = db.query(OperationType).filter(OperationType.id.in_(ids)).all() if ids else []
        wc.operation_types = ots

    db.commit()
    db.refresh(wc)
    db.refresh(wc, attribute_names=["operation_types"])
    return wc

# =========================
# Location
# =========================

@router.get("/locations", response_model=List[LocationRead])
def list_locations(db: Session = Depends(get_db)):
    return db.query(Location).all()

@router.post("/locations", response_model=LocationRead, status_code=201)
def create_location(payload: LocationCreate, db: Session = Depends(get_db)):
    loc = Location(**payload.model_dump())
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc

@router.patch("/locations/{id}", response_model=LocationRead)
def update_location(id: int, payload: LocationUpdate, db: Session = Depends(get_db)):
    loc = db.query(Location).get(id)
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(loc, field, value)
        
    db.commit()
    db.refresh(loc)
    return loc

@router.delete("/locations/{id}", status_code=204)
def delete_location(id: int, db: Session = Depends(get_db)):
    loc = db.query(Location).get(id)
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    
    # Check if used in StockItems
    if db.query(StockItem).filter(StockItem.location_id == id).first():
        raise HTTPException(status_code=400, detail="Cannot delete location: it is assigned to one or more stock items.")
        
    db.delete(loc)
    db.commit()
    return

# =========================
# ItemCategory
# =========================

@router.get("/categories", response_model=List[ItemCategoryRead])
def list_categories(db: Session = Depends(get_db)):
    return db.query(ItemCategory).all()

@router.post("/categories", response_model=ItemCategoryRead, status_code=201)
def create_category(payload: ItemCategoryCreate, db: Session = Depends(get_db)):
    cat = ItemCategory(**payload.model_dump())
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat

@router.patch("/categories/{id}", response_model=ItemCategoryRead)
def update_category(id: int, payload: ItemCategoryUpdate, db: Session = Depends(get_db)):
    cat = db.query(ItemCategory).get(id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
        
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(cat, field, value)
        
    db.commit()
    db.refresh(cat)
    return cat

@router.delete("/categories/{id}", status_code=204)
def delete_category(id: int, db: Session = Depends(get_db)):
    cat = db.query(ItemCategory).get(id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
        
    if db.query(StockItem).filter(StockItem.category_id == id).first():
        raise HTTPException(status_code=400, detail="Cannot delete category: it is assigned to one or more stock items.")
        
    db.delete(cat)
    db.commit()
    return

# =========================
# MaterialGrade
# =========================

@router.get("/material-grades", response_model=List[MaterialGradeRead])
def list_material_grades(db: Session = Depends(get_db)):
    return db.query(MaterialGrade).all()

@router.post("/material-grades", response_model=MaterialGradeRead, status_code=201)
def create_material_grade(payload: MaterialGradeCreate, db: Session = Depends(get_db)):
    mg = MaterialGrade(**payload.model_dump())
    db.add(mg)
    db.commit()
    db.refresh(mg)
    return mg

@router.patch("/material-grades/{id}", response_model=MaterialGradeRead)
def update_material_grade(id: int, payload: MaterialGradeUpdate, db: Session = Depends(get_db)):
    mg = db.query(MaterialGrade).get(id)
    if not mg:
        raise HTTPException(status_code=404, detail="Material grade not found")
        
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(mg, field, value)
        
    db.commit()
    db.refresh(mg)
    return mg

@router.delete("/material-grades/{id}", status_code=204)
def delete_material_grade(id: int, db: Session = Depends(get_db)):
    mg = db.query(MaterialGrade).get(id)
    if not mg:
        raise HTTPException(status_code=404, detail="Material grade not found")
        
    if db.query(Lot).filter(Lot.material_grade_id == id).first():
        raise HTTPException(status_code=400, detail="Cannot delete material grade: it is assigned to one or more lots.")
        
    db.delete(mg)
    db.commit()
    return

# =========================
# Lots
# =========================

@router.get("/lots", response_model=List[LotRead])
def list_lots(
    lot_number: Optional[str] = None,
    certificate_number: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Lot).options(
        joinedload(Lot.supplier),
        joinedload(Lot.material_grade),
        joinedload(Lot.files)
    )
    if lot_number:
        query = query.filter(Lot.lot_number.ilike(f"%{lot_number}%"))
    if certificate_number:
        query = query.filter(Lot.certificate_number.ilike(f"%{certificate_number}%"))
    return query.order_by(Lot.receive_date.desc()).all()

@router.post("/lots", response_model=LotRead, status_code=201)
def create_lot(
    payload: str = Form(...),
    certificate_files: List[UploadFile] = UploadFileField([]),
    db: Session = Depends(get_db),
):
    try:
        data = json.loads(payload)
        p = LotCreate.model_validate(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")

    try:
        lot = Lot(**p.model_dump())
        db.add(lot)
        db.flush()

        for f in certificate_files or []:
            save_uploaded_file(db=db, upload=f, entity_type="lot", entity_id=lot.id)

        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Create lot failed: {e}")

    return db.query(Lot).options(joinedload(Lot.supplier), joinedload(Lot.material_grade), joinedload(Lot.files)).get(lot.id)

# =========================
# StockItems
# =========================

@router.get("/stock-items", response_model=List[StockItemRead])
def list_stock_items(
    item_type: Optional[str] = None,
    category_id: Optional[int] = None,
    lot_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    query = db.query(StockItem).options(
        joinedload(StockItem.category),
        joinedload(StockItem.lot),
        joinedload(StockItem.location)
    )
    if item_type:
        query = query.filter(StockItem.item_type == ItemType(item_type))
    if category_id:
        query = query.filter(StockItem.category_id == category_id)
    if lot_id:
        query = query.filter(StockItem.lot_id == lot_id)
        
    return query.all()

@router.get("/stock-items-paginated", response_model=StockItemPaginatedRead)
def list_stock_items_paginated(
    skip: int = 0,
    limit: int = 20,
    search: Optional[str] = None,
    item_type: Optional[str] = None,
    category_id: Optional[int] = None,
    location_id: Optional[int] = None,
    min_quantity: Optional[float] = None,
    max_quantity: Optional[float] = None,
    attributes_search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(StockItem).options(
        joinedload(StockItem.category),
        joinedload(StockItem.lot),
        joinedload(StockItem.location)
    )
    
    if search:
        search_filter = []
        if search.isdigit():
            search_filter.append(StockItem.id == int(search))
        search_filter.append(StockItem.lot.has(Lot.lot_number.ilike(f"%{search}%")))
        query = query.filter(or_(*search_filter))
        
    if item_type:
        query = query.filter(StockItem.item_type == ItemType(item_type))
    if category_id:
        query = query.filter(StockItem.category_id == category_id)
    if location_id:
        query = query.filter(StockItem.location_id == location_id)
    if min_quantity is not None:
        query = query.filter(StockItem.quantity >= min_quantity)
    if max_quantity is not None:
        query = query.filter(StockItem.quantity <= max_quantity)
    if attributes_search:
        query = query.filter(cast(StockItem.attributes, String).ilike(f"%{attributes_search}%"))
        
    total = query.count()
    items = query.order_by(StockItem.id.desc()).offset(skip).limit(limit).all()
    
    return {"items": items, "total": total}

@router.post("/stock-items", response_model=StockItemRead, status_code=201)
def create_stock_item(payload: StockItemCreate, db: Session = Depends(get_db)):
    item = StockItem(**payload.model_dump())
    
    db.add(item)
    db.flush()
    
    # Create an initial transaction
    tx = StockTransaction(
        stock_item_id=item.id,
        transaction_type=TransactionType.RECEIVE,
        quantity_change=item.quantity,
        quantity_after=item.quantity,
        notes="Initial manual receipt"
    )
    db.add(tx)
    
    db.commit()
    return db.query(StockItem).options(joinedload(StockItem.category), joinedload(StockItem.lot), joinedload(StockItem.location)).get(item.id)

# =========================
# ProcessBatch
# =========================

@router.get("/process-batches", response_model=List[ProcessBatchRead])
def list_process_batches(db: Session = Depends(get_db)):
    return db.query(ProcessBatch).all()

@router.post("/process-batches", response_model=ProcessBatchRead, status_code=201)
def create_process_batch(payload: ProcessBatchCreate, db: Session = Depends(get_db)):
    batch = ProcessBatch(
        batch_number=payload.batch_number,
        operation_type=payload.operation_type,
        process_parameters=payload.process_parameters,
        notes=payload.notes,
        status=BatchStatus.PENDING
    )
    
    if payload.stock_item_ids:
        items = db.query(StockItem).filter(StockItem.id.in_(payload.stock_item_ids)).all()
        batch.stock_items = items
        
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch

# =========================
# StockTransactions
# =========================

@router.get("/stock-transactions", response_model=List[StockTransactionRead])
def list_stock_transactions(
    stock_item_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    query = db.query(StockTransaction)
    if stock_item_id:
        query = query.filter(StockTransaction.stock_item_id == stock_item_id)
    return query.order_by(StockTransaction.timestamp.desc()).all()

# =========================
# Services (Cut Steel / Complete Batch)
# =========================

@router.post("/cut-steel", response_model=CutSteelResponse)
def api_cut_steel(payload: CutSteelRequest, db: Session = Depends(get_db)):
    return cut_steel_generate_wip(db, payload)

@router.post("/complete-batch", response_model=CompleteBatchResponse)
def api_complete_batch(payload: CompleteBatchRequest, db: Session = Depends(get_db)):
    return complete_process_batch(db, payload)
