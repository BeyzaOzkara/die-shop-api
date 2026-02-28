# backend/routers/inventory.py
from typing import List, Optional
import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File as UploadFileField, Form
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from pydantic import BaseModel, ConfigDict
from datetime import datetime

from ..config import settings
from ..services.file_storage import save_uploaded_file
from ..database import get_db
from ..models import (
    WorkCenter,
    WorkCenterStatus,
    SteelStockItem,
    Lot,
    StockMovement,
    OperationType,
    Supplier,
    WorkOrder,
    ProductionOrder,
    Die,
    DieComponent,
    ComponentType,
)
from ..deps import require_admin


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

class FileRead(BaseModel):
    id: int
    original_name: str
    storage_path: str
    mime_type: str
    size_bytes: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class SupplierNested(BaseModel):
    id: int
    name: str
    model_config = ConfigDict(from_attributes=True)

class LotBase(BaseModel):
    stock_item_id: int
    certificate_number: str
    supplier: Optional[str] = None        # legacy string (backward compat)
    supplier_id: Optional[int] = None     # new FK
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
    supplier_ref: Optional[SupplierNested] = None   # opsiyonel supplier bilgisi
    files: List[FileRead] = []   # YENİ

    model_config = ConfigDict(from_attributes=True)

LotRead.model_rebuild()

class LotRemainingRead(BaseModel):
    id: int
    remaining_kg: float

    model_config = ConfigDict(from_attributes=True)


class LotUpdateRemaining(BaseModel):
    remaining_kg: float

class LotUpdate(BaseModel):
    stock_item_id: Optional[int] = None
    certificate_number: Optional[str] = None
    supplier: Optional[str] = None          # legacy string
    supplier_id: Optional[int] = None       # NEW FK
    length_mm: Optional[int] = None
    gross_weight_kg: Optional[float] = None
    remaining_kg: Optional[float] = None
    certificate_file_url: Optional[str] = None
    received_date: Optional[datetime] = None

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

    # --- nested schemas for movements list ---

    class _DieNested(BaseModel):
        id: int
        die_number: str
        model_config = ConfigDict(from_attributes=True)

    class _ProductionOrderNested(BaseModel):
        id: int
        die: Optional['StockMovementRead._DieNested'] = None
        model_config = ConfigDict(from_attributes=True)

    class _ComponentTypeNested(BaseModel):
        id: int
        name: str
        model_config = ConfigDict(from_attributes=True)

    class _DieComponentNested(BaseModel):
        id: int
        component_type: Optional['StockMovementRead._ComponentTypeNested'] = None
        model_config = ConfigDict(from_attributes=True)

    class _WorkOrderNested(BaseModel):
        id: int
        order_number: str
        production_order: Optional['StockMovementRead._ProductionOrderNested'] = None
        die_component: Optional['StockMovementRead._DieComponentNested'] = None
        model_config = ConfigDict(from_attributes=True)

    class _LotNested(BaseModel):
        id: int
        stock_item: Optional[StockItemNested] = None
        supplier_ref: Optional[SupplierNested] = None
        supplier: str = ''
        model_config = ConfigDict(from_attributes=True)

    work_order: Optional[_WorkOrderNested] = None
    lot: Optional[_LotNested] = None

    model_config = ConfigDict(from_attributes=True)

StockMovementRead.model_rebuild()

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


# @router.post("/work-centers", response_model=WorkCenterRead, status_code=201)
@router.post("/work-centers", response_model=WorkCenterRead, status_code=201, dependencies=[Depends(require_admin)])
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

# @router.delete("/work-centers/{id}", status_code=204)
@router.delete("/work-centers/{id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_work_center(id: int, db: Session = Depends(get_db)):
    wc = db.query(WorkCenter).get(id)
    if not wc:
        raise HTTPException(status_code=404, detail="Work center not found")
    db.delete(wc)
    db.commit()
    return

# @router.patch("/work-centers/{id}", response_model=WorkCenterRead)
@router.patch("/work-centers/{id}", response_model=WorkCenterRead, dependencies=[Depends(require_admin)])
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

# @router.post("/steel-stock-items", response_model=SteelStockItemRead, status_code=201)
@router.post("/steel-stock-items", response_model=SteelStockItemRead, status_code=201, dependencies=[Depends(require_admin)])
def create_steel_stock_item(payload: SteelStockItemCreate, db: Session = Depends(get_db)):
    item = SteelStockItem(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

# =========================
# Lots
# =========================

# @router.get("/lots", response_model=List[LotRead])
# def list_lots(include_stock_item: bool = True, db: Session = Depends(get_db)):
#     query = db.query(Lot).options(joinedload(Lot.files))
#     if include_stock_item:
#         query = query.options(joinedload(Lot.stock_item))
#     lots = query.order_by(Lot.received_date.desc()).all()
#     return lots

@router.get("/lots", response_model=List[LotRead])
def list_lots(
    include_stock_item: bool = True,

    # 🔎 filters
    alloy: Optional[str] = None,
    diameter_mm: Optional[int] = None,
    supplier: Optional[str] = None,
    certificate_number: Optional[str] = None,
    only_with_remaining: bool = False,

    # opsiyonel tarih aralığı
    received_from: Optional[datetime] = None,
    received_to: Optional[datetime] = None,

    db: Session = Depends(get_db),
):
    # query = db.query(Lot).options(joinedload(Lot.files))
    query = db.query(Lot).options(
        joinedload(Lot.files),
        joinedload(Lot.supplier_ref),
    )
    if include_stock_item:
        query = query.options(joinedload(Lot.stock_item))

    # 🔸 alloy/diameter için SteelStockItem join gerekir
    if alloy or diameter_mm:
        query = query.join(Lot.stock_item)

        if alloy and alloy.strip():
            query = query.filter(SteelStockItem.alloy.ilike(f"%{alloy.strip()}%"))

        if diameter_mm is not None:
            query = query.filter(SteelStockItem.diameter_mm == diameter_mm)

    # if supplier and supplier.strip():
    #     query = query.filter(Lot.supplier.ilike(f"%{supplier.strip()}%"))
    if supplier and supplier.strip():
        s = supplier.strip()
        query = query.outerjoin(Lot.supplier_ref).filter(
            or_(
                Lot.supplier.ilike(f"%{s}%"),          # legacy
                Supplier.name.ilike(f"%{s}%"),         # FK
            )
        )

    if certificate_number and certificate_number.strip():
        query = query.filter(Lot.certificate_number.ilike(f"%{certificate_number.strip()}%"))

    if only_with_remaining:
        query = query.filter(Lot.remaining_kg > 0)

    if received_from:
        query = query.filter(Lot.received_date >= received_from)

    if received_to:
        query = query.filter(Lot.received_date <= received_to)

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
        .options(joinedload(Lot.stock_item), joinedload(Lot.files))
        .filter(Lot.stock_item_id == stock_item_id)
    )
    if only_with_remaining:
        query = query.filter(Lot.remaining_kg > 0)
    lots = query.order_by(Lot.received_date.asc()).all()
    return lots

# @router.post("/lots", response_model=LotRead, status_code=201)
@router.post("/lots", response_model=LotRead, status_code=201, dependencies=[Depends(require_admin)])
def create_lot(
    payload: str = Form(...),
    certificate_files: List[UploadFile] = UploadFileField([]),
    db: Session = Depends(get_db),
):
    # 1) payload json parse + validate
    try:
        data = json.loads(payload)
        p = LotCreate.model_validate(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")

    # 2) referans kontrol
    stock_item = db.query(SteelStockItem).get(p.stock_item_id)
    if not stock_item:
        raise HTTPException(status_code=400, detail="Invalid stock_item_id")
    
    if p.supplier_id is not None:
        supplier = db.query(Supplier).filter(Supplier.id == p.supplier_id, Supplier.is_active == True).first()
        if not supplier:
            raise HTTPException(status_code=400, detail="Geçersiz veya inaktif tedarikçi.")

    # 3) atomik transaction
    try:
        lot = Lot(**p.model_dump())
        db.add(lot)
        db.flush()  # lot.id lazım

        # 3.1) dosyalar
        first_saved_path: Optional[str] = None
        for f in certificate_files or []:
            saved = save_uploaded_file(
                db=db,
                upload=f,
                entity_type="lot",
                entity_id=lot.id,
            )
            # save_uploaded_file dönüş tipi projene göre değişebilir.
            # Eğer dönüşte objede storage_path varsa ilkini url alanına yazalım (opsiyonel).
            if first_saved_path is None:
                # saved None olabilir -> guard
                sp = getattr(saved, "storage_path", None)
                if sp:
                    first_saved_path = sp

        # 3.2) geri uyumluluk: certificate_file_url alanını doldurmak istersen (opsiyonel)
        if first_saved_path and not lot.certificate_file_url:
            base = getattr(settings, "MEDIA_URL", "/api/media")
            lot.certificate_file_url = f"{base}/{first_saved_path}".replace("//", "/")

        db.commit()

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Create lot failed: {e}")

    # 4) response: eager load stock_item + files
    lot = (
        db.query(Lot)
        .options(joinedload(Lot.stock_item), joinedload(Lot.files))
        .get(lot.id)
    )
    return lot


@router.get("/lots/{lot_id}/remaining", response_model=LotRemainingRead)
def get_lot_remaining(lot_id: int, db: Session = Depends(get_db)):
    lot = db.query(Lot).get(lot_id)
    if not lot:
        raise HTTPException(status_code=404, detail="Lot not found")
    return LotRemainingRead(id=lot.id, remaining_kg=float(lot.remaining_kg))

# @router.patch("/lots/{lot_id}/remaining", response_model=LotRead)
@router.patch("/lots/{lot_id}/remaining", response_model=LotRead, dependencies=[Depends(require_admin)])
def update_lot_remaining(lot_id: int, payload: LotUpdateRemaining, db: Session = Depends(get_db)):
    lot = db.query(Lot).options(joinedload(Lot.stock_item), joinedload(Lot.files)).get(lot_id)
    if not lot:
        raise HTTPException(status_code=404, detail="Lot not found")
    lot.remaining_kg = payload.remaining_kg
    db.commit()
    db.refresh(lot)
    return lot

@router.patch("/lots/{lot_id}", response_model=LotRead, dependencies=[Depends(require_admin)])
def update_lot(lot_id: int, payload: LotUpdate, db: Session = Depends(get_db)):
    lot = (
        db.query(Lot)
        .options(joinedload(Lot.stock_item), joinedload(Lot.files), joinedload(Lot.supplier_ref))
        .get(lot_id)
    )
    if not lot:
        raise HTTPException(status_code=404, detail="Lot not found")

    data = payload.model_dump(exclude_unset=True)

    # Lot kullanıldı mı? (stok hareketi var mı?)
    used_count = db.query(StockMovement).filter(StockMovement.lot_id == lot_id).count()

    # Eğer kullanıldıysa kalan kg / brüt kg gibi kritik alanları kilitle (isteğe bağlı ama öneririm)
    protected_fields_if_used = {"gross_weight_kg", "remaining_kg", "stock_item_id"}
    if used_count > 0:
        for f in protected_fields_if_used:
            if f in data:
                raise HTTPException(
                    status_code=409,
                    detail="Bu lot stok hareketlerinde kullanıldığı için brüt/kalan/ürün alanları güncellenemez."
                )
    # supplier_id geldiyse validate + set + legacy supplier string sync
    if "supplier_id" in data:
        new_supplier_id = data["supplier_id"]

        if new_supplier_id is None:
            # supplier ilişkisini kaldırmak istiyorsan
            lot.supplier_id = None
            # legacy string'i de istersen temizle (opsiyonel)
            lot.supplier = data.get("supplier", lot.supplier)  # supplier ayrıca geldiyse onu bırak
        else:
            supplier = (
                db.query(Supplier)
                .filter(Supplier.id == new_supplier_id, Supplier.is_active == True)
                .first()
            )
            if not supplier:
                raise HTTPException(status_code=400, detail="Geçersiz veya inaktif tedarikçi.")

            lot.supplier_id = supplier.id
            # legacy alanı da otomatik eşitle
            lot.supplier = supplier.name

    # normal alanlar (supplier burada opsiyonel; supplier_id set ettiyse zaten üstte override ediliyor)
    for field in [
        "stock_item_id",
        "certificate_number",
        "supplier",              # legacy manual edit (supplier_id yoksa anlamlı)
        "length_mm",
        "gross_weight_kg",
        "remaining_kg",
        "certificate_file_url",
        "received_date",
    ]:
        if field in data:
            # supplier_id set edildiyse supplier'ı override etmiştik;
            # burada tekrar set edilmesini istemiyorsan bir guard koy:
            if field == "supplier" and lot.supplier_id is not None and "supplier_id" in data:
                continue
            setattr(lot, field, data[field])

    db.commit()
    db.refresh(lot)

    # response için supplier_ref ilişkisinin dolu gelmesi adına tekrar load edelim
    lot = (
        db.query(Lot)
        .options(
            joinedload(Lot.stock_item),
            joinedload(Lot.files),
            joinedload(Lot.supplier_ref),
        )
        .get(lot_id)
    )
    return lot

@router.delete("/lots/{lot_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_lot(lot_id: int, db: Session = Depends(get_db)):
    lot = db.query(Lot).get(lot_id)
    if not lot:
        raise HTTPException(status_code=404, detail="Lot not found")

    # Lot kullanıldı mı? (stok hareketi var mı?)
    used_count = db.query(StockMovement).filter(StockMovement.lot_id == lot_id).count()
    # remaining_kg != gross_weight_kg
    if used_count > 0:
        raise HTTPException(
            status_code=409,
            detail="Bu lot stok hareketlerinde kullanıldığı için silinemez."
        )

    db.delete(lot)
    db.commit()
    return


# =========================
# Stock Movements
# =========================

# @router.post("/stock-movements", response_model=StockMovementRead, status_code=201)
@router.post("/stock-movements", response_model=StockMovementRead, status_code=201, dependencies=[Depends(require_admin)])
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
        .options(
            joinedload(StockMovement.lot).joinedload(Lot.stock_item),
            joinedload(StockMovement.lot).joinedload(Lot.supplier_ref),
            joinedload(StockMovement.work_order)
                .joinedload(WorkOrder.production_order)
                .joinedload(ProductionOrder.die),
            joinedload(StockMovement.work_order)
                .joinedload(WorkOrder.die_component)
                .joinedload(DieComponent.component_type),
        )
        .all()
    )
