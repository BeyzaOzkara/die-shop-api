# backend/routers/production_orders.py
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel, ConfigDict
from datetime import datetime, timezone, date

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
from ..deps import require_admin


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
    die_diameter_mm: float
    total_package_length_mm: float
    die_type_id: int
    description: Optional[str] = None
    expected_completion_date: Optional[date] = None
    
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
# Preview Schemas
# =========================

class ComponentTypeNested(BaseModel):
    id: int
    code: str
    name: str
    
    model_config = ConfigDict(from_attributes=True)


class OperationTypeNested(BaseModel):
    id: int
    code: str
    name: str
    
    model_config = ConfigDict(from_attributes=True)


class BOMOperationPreview(BaseModel):
    """Single BOM operation for preview."""
    bom_id: int
    sequence_number: int
    operation_name: str
    operation_type: OperationTypeNested
    estimated_duration_minutes: Optional[int] = None
    notes: Optional[str] = None


class ComponentPreview(BaseModel):
    """Preview of a component and its BOM operations."""
    component_id: int
    component_type: ComponentTypeNested
    package_length_mm: float
    theoretical_consumption_kg: float
    bom_operations: List[BOMOperationPreview] = []


class WorkOrderPreviewResponse(BaseModel):
    """Full preview of work orders that would be generated."""
    production_order_id: int
    die_number: str
    components: List[ComponentPreview] = []
    total_components: int
    total_operations: int


class GenerateWorkOrdersRequest(BaseModel):
    """Optional request body for selective work order generation."""
    selected_operations: Optional[dict[int, List[int]]] = None
    # Key: die_component_id, Value: list of ComponentBOM.id to include
    # If None, include all operations (current behavior)


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
# @router.post("/", response_model=ProductionOrderRead, status_code=201)
@router.post("/", response_model=ProductionOrderRead, status_code=201, dependencies=[Depends(require_admin)])
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


@router.post("/{id}/preview-work-orders", response_model=WorkOrderPreviewResponse, dependencies=[Depends(require_admin)])
def preview_work_orders(
    id: int,
    db: Session = Depends(get_db),
):
    """
    Preview the work orders and operations that would be generated.
    Returns all BOM operations grouped by component - no database changes.
    """
    po = (
        db.query(ProductionOrder)
        .options(
            joinedload(ProductionOrder.die)
                .joinedload(Die.components)
                .joinedload(DieComponent.component_type),
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

    components_preview = []
    total_operations = 0

    for component in sorted(die.components, key=lambda c: c.id):
        # Get BOM operations for this component type
        boms = (
            db.query(ComponentBOM)
            .options(joinedload(ComponentBOM.operation_type))
            .filter(ComponentBOM.component_type_id == component.component_type_id)
            .order_by(ComponentBOM.sequence_number.asc())
            .all()
        )

        bom_operations = []
        for bom in boms:
            bom_operations.append(BOMOperationPreview(
                bom_id=bom.id,
                sequence_number=bom.sequence_number,
                operation_name=bom.operation_name,
                operation_type=OperationTypeNested(
                    id=bom.operation_type.id,
                    code=bom.operation_type.code,
                    name=bom.operation_type.name,
                ),
                estimated_duration_minutes=bom.estimated_duration_minutes,
                notes=bom.notes,
            ))
            total_operations += 1

        components_preview.append(ComponentPreview(
            component_id=component.id,
            component_type=ComponentTypeNested(
                id=component.component_type.id,
                code=component.component_type.code,
                name=component.component_type.name,
            ),
            package_length_mm=float(component.package_length_mm),
            theoretical_consumption_kg=float(component.theoretical_consumption_kg),
            bom_operations=bom_operations,
        ))

    return WorkOrderPreviewResponse(
        production_order_id=po.id,
        die_number=die.die_number,
        components=components_preview,
        total_components=len(components_preview),
        total_operations=total_operations,
    )


# @router.post("/{id}/generate-work-orders", response_model=ProductionOrderRead, status_code=201)
@router.post("/{id}/generate-work-orders", response_model=ProductionOrderRead, status_code=201, dependencies=[Depends(require_admin)])
def generate_work_orders_for_production_order(
    id: int,
    payload: Optional[GenerateWorkOrdersRequest] = None,
    db: Session = Depends(get_db),
):
    """
    Generate work orders for a production order.
    
    If payload.selected_operations is provided, only creates operations for selected BOMs.
    Format: { component_id: [bom_id, bom_id, ...], ... }
    If None or empty, creates all operations (original behavior).
    """
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

    existing_wo = db.query(WorkOrder).filter(WorkOrder.production_order_id == po.id).first()
    if existing_wo:
        raise HTTPException(status_code=400, detail="Work orders already generated for this production order")

    # Parse selected operations
    selected_ops = None
    if payload and payload.selected_operations:
        selected_ops = payload.selected_operations

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
            .options(joinedload(ComponentBOM.operation_type))
            .filter(ComponentBOM.component_type_id == component.component_type_id)
            .order_by(ComponentBOM.sequence_number.asc())
            .all()
        )

        # Filter BOMs if selected_ops provided
        if selected_ops is not None:
            component_selected = selected_ops.get(component.id, [])
            if component_selected:  # If list is provided, filter
                boms = [b for b in boms if b.id in component_selected]
            # If component not in selected_ops or empty list, include all BOMs for that component

        for bom in boms:
            op = WorkOrderOperation(
                work_order_id=wo.id,
                sequence_number=bom.sequence_number,
                operation_type_id = bom.operation_type_id,
                operation_name=bom.operation_name,
                # operation_name=bom.operation_type.name,  # snapshot (istersen None da yaparsın)
                # work_center_id=bom.preferred_work_center_id,  # NULL olabilir
                work_center_id=None,
                estimated_duration_minutes=bom.estimated_duration_minutes,
                notes=bom.notes,
                status=OperationStatus.Waiting,
            )
            db.add(op)

    # 3) Kalıbı "InProduction", üretim emrini "InProgress" yap
    die.status = DieStatus.InProduction
    po.status = OrderStatus.InProgress
    if not po.started_at:
        po.started_at = datetime.now(timezone.utc)

    db.commit()

    # 4) Tekrar join'li olarak dön
    po = (
        db.query(ProductionOrder)
        .options(joinedload(ProductionOrder.die).joinedload(Die.files),
                 joinedload(ProductionOrder.die))
        .get(po.id)
    )
    return po


# @router.patch("/{id}", response_model=ProductionOrderRead)
@router.patch("/{id}", response_model=ProductionOrderRead, dependencies=[Depends(require_admin)])
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