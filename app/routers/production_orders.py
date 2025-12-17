# backend/routers/production_orders.py
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel, ConfigDict
from datetime import datetime

from ..database import get_db
from ..models import (
    ProductionOrder,
    Die,
    DieComponent,
    WorkOrder,
    WorkOrderOperation,
    ComponentBOM,
    OrderStatus,
    OperationStatus,
    DieStatus,
)
from ..order_number_helper import generate_production_order_number, generate_work_order_number

router = APIRouter(prefix="/production-orders", tags=["Production Orders"])


# =========================
# Pydantic Şemalar
# =========================

class FileRead(BaseModel):
    id: int
    original_name: str
    storage_path: str
    mime_type: str
    size_bytes: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DieNested(BaseModel):
    id: int
    die_number: str
    die_diameter_mm: int
    total_package_length_mm: int
    die_type_id: int
    
    files: List[FileRead] = []

    model_config = ConfigDict(from_attributes=True)


class ProductionOrderBase(BaseModel):
    die_id: int
    # order_number: str
    status: OrderStatus = OrderStatus.Waiting


class ProductionOrderCreate(ProductionOrderBase):
    """
    Supabase:
      .insert({
        die_id: dieId,
        status: 'Waiting',
      })
      .select()
      .single();
    """
    pass


class ProductionOrderUpdate(BaseModel):
    die_id: Optional[int] = None
    order_number: Optional[str] = None
    status: Optional[OrderStatus] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class ProductionOrderRead(ProductionOrderBase):
    id: int
    order_number: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    die: Optional[DieNested] = None  # Supabase: die:dies(*)

    model_config = ConfigDict(from_attributes=True)


# =========================
# Endpoint'ler
# =========================

@router.get("/", response_model=List[ProductionOrderRead])
def list_production_orders(db: Session = Depends(get_db)):
    rows = (
        db.query(ProductionOrder)
        .options(joinedload(ProductionOrder.die).joinedload(Die.files))
        .order_by(ProductionOrder.created_at.desc())
        .all()
    )
    return rows

@router.get("/{id}", response_model=ProductionOrderRead)
def get_production_order(id: int, db: Session = Depends(get_db)):
    po = (
        db.query(ProductionOrder)
        .options(joinedload(ProductionOrder.die).joinedload(Die.files))
        .filter(ProductionOrder.id == id)
        .first()
    )
    if not po:
        raise HTTPException(status_code=404, detail="Production order not found")
    return po

# Sadece production_order tablosuna kayıt aç
# status = 'Waiting'
# iş emri/operasyon üretme
@router.post("/", response_model=ProductionOrderRead, status_code=201)
def create_production_order(
    payload: ProductionOrderCreate,
    db: Session = Depends(get_db),
):

    # die var mı kontrolü
    die = db.query(Die).get(payload.die_id)
    if not die:
        raise HTTPException(status_code=400, detail="Related die not found")

    # order number üret
    order_number = generate_production_order_number(db, die)
    po = ProductionOrder(
        die_id=payload.die_id,
        order_number=order_number, 
        status=payload.status,
    )
    db.add(po)
    db.commit()

    # ✅ return edeceğin şeyi join'li reload et
    po = (
        db.query(ProductionOrder)
        .options(
            joinedload(ProductionOrder.die).joinedload(Die.files),
            joinedload(ProductionOrder.die),  # istersen die_type da eklersin
        )
        .get(po.id)
    )
    return po

# Örn: POST /{id}/generate-work-orders
# @router.post("/{id}/generate-work-orders", response_model=ProductionOrderRead, status_code=201)
# def generate_work_orders_for_production_order(production_order_id: int):
#     # production_order → die
#     # die → die_components
#     # component_type → component_bom
#     # BURADA iş emirleri (work_orders) ve operasyonlarını (work_order_operations) oluştur
#     # Sonunda production_order.status = "In Progress" yapabilirsin,
#     # ya da status update için ayrı endpoint bırakabilirsin (frontend tarafında zaten var).
#     pass

@router.post("/{id}/generate-work-orders", response_model=ProductionOrderRead, status_code=201)
def generate_work_orders_for_production_order(
    id: int,
    db: Session = Depends(get_db),
):
    # 1) Üretim emrini ve ilişkili kalıbı + bileşenleri çek
    po = (
        db.query(ProductionOrder)
        .options(
            joinedload(ProductionOrder.die).joinedload(Die.components),
            joinedload(ProductionOrder.die).joinedload(Die.files), 
        )
        .get(id)
    )
    if not po:
        raise HTTPException(status_code=404, detail="Production order not found")

    die = po.die
    if not die:
        raise HTTPException(status_code=400, detail="Related die not found")

    if not die.components:
        raise HTTPException(status_code=400, detail="Die has no components")

    # 2) Her bileşen için iş emri + operasyonları oluştur
    index = 1
    for component in sorted(die.components, key=lambda c: c.id):
        wo_number = generate_work_order_number(die, po, index)
        index += 1

        wo = WorkOrder(
            production_order_id=po.id,
            die_component_id=component.id,
            order_number=wo_number,
            theoretical_consumption_kg=component.theoretical_consumption_kg,
            status=OrderStatus.Waiting,
        )
        db.add(wo)
        db.flush()  # wo.id almak için

        # component_type için BOM satırlarını al
        boms = (
            db.query(ComponentBOM)
            .filter(ComponentBOM.component_type_id == component.component_type_id)
            .order_by(ComponentBOM.sequence_number.asc())
            .all()
        )

        for bom in boms:
            op = WorkOrderOperation(
                work_order_id=wo.id,
                sequence_number=bom.sequence_number,
                operation_name=bom.operation_name,
                work_center_id=bom.work_center_id,
                estimated_duration_minutes=bom.estimated_duration_minutes,
                notes=bom.notes,
                status=OperationStatus.Waiting,
            )
            db.add(op)

    # 3) Kalıbı "InProduction", üretim emrini "InProgress" yap
    die.status = DieStatus.InProduction
    po.status = OrderStatus.InProgress
    if not po.started_at:
        po.started_at = datetime.utcnow()

    db.commit()

    # 4) Tekrar join'li olarak dön
    po = (
        db.query(ProductionOrder)
        .options(joinedload(ProductionOrder.die).joinedload(Die.files),
                 joinedload(ProductionOrder.die))
        .get(po.id)
    )
    return po

@router.patch("/{id}", response_model=ProductionOrderRead)
def update_production_order(
    id: int,
    payload: ProductionOrderUpdate,
    db: Session = Depends(get_db),
):
    po = db.query(ProductionOrder).get(id)
    if not po:
        raise HTTPException(status_code=404, detail="Production order not found")

    data = payload.model_dump(exclude_unset=True)

    if "status" in data and data["status"] is not None:
        print(f'payload.status: {data["status"]}')
        # payload.status frontend’den "In Progress", "Waiting" gibi geliyor olabilir
        # veya Pydantic Enum olarak gelebilir.
        if isinstance(data["status"], OrderStatus):
            po.status = data["status"]          # Enum’ü direkt ata
        else:
            # payload.status -> "In Progress" gibi string ise burada Enum’a çevir
            po.status = OrderStatus(data["status"])

        # started_at / finished_at mantığı:
        from datetime import datetime, timezone

        if po.status == OrderStatus.InProgress:
            po.started_at = datetime.now(timezone.utc)
        elif po.status in (OrderStatus.Completed, OrderStatus.Cancelled):
            po.completed_at = datetime.now(timezone.utc)

        data.pop("status", None)

    # Diğer alanlar (istersen aç)
    for field, value in data.items():
        setattr(po, field, value)

    db.commit()

    # ✅ response için po'yu die + die.files ile tekrar çek
    po = (
        db.query(ProductionOrder)
        .options(
            joinedload(ProductionOrder.die).joinedload(Die.files),
            # istersen:
            # joinedload(ProductionOrder.die).joinedload(Die.die_type),
        )
        .filter(ProductionOrder.id == id)
        .first()
    )
    return po