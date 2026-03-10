# backend/routers/component_bom.py
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel, ConfigDict
from datetime import datetime

from ..database import get_db
from ..models import ComponentBOM
from ..deps import require_admin


# router = APIRouter(prefix="/component-bom", tags=["Component BOM"])
router = APIRouter(
    prefix="/component-bom",
    tags=["Component BOM"],
    dependencies=[Depends(require_admin)],
)


# =========================
# Nested modeller
# =========================

class WorkCenterNested(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class ComponentTypeNested(BaseModel):
    id: int
    code: str
    name: str

    model_config = ConfigDict(from_attributes=True)

class OperationTypeNested(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

# =========================
# BOM modelleri
# =========================

class ComponentBOMBase(BaseModel):
    component_type_id: int
    sequence_number: int
    operation_type_id: int
    operation_name: str 
    preferred_work_center_id: Optional[int] = None
    estimated_duration_minutes: Optional[int] = None
    notes: Optional[str] = None


class ComponentBOMCreate(ComponentBOMBase):
    pass


class ComponentBOMUpdate(BaseModel):
    sequence_number: Optional[int] = None
    operation_type_id: Optional[int] = None
    operation_name: Optional[str] = None
    preferred_work_center_id: Optional[int] = None
    estimated_duration_minutes: Optional[int] = None
    notes: Optional[str] = None


class ComponentBOMRead(ComponentBOMBase):
    id: int
    created_at: datetime
    component_type: Optional[ComponentTypeNested] = None
    operation_type: Optional[OperationTypeNested] = None
    preferred_work_center: Optional[WorkCenterNested] = None

    model_config = ConfigDict(from_attributes=True)


# =========================
# Endpointler
# =========================

@router.get("", response_model=List[ComponentBOMRead])
def list_bom_operations(
    component_type_id: int,   # /component-bom?component_type_id=1
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ComponentBOM)
        .options(
            joinedload(ComponentBOM.component_type),
            joinedload(ComponentBOM.operation_type),
            joinedload(ComponentBOM.preferred_work_center),
        )
        .filter(ComponentBOM.component_type_id == component_type_id)
        .order_by(ComponentBOM.sequence_number.asc())
        .all()
    )
    return rows


@router.post("", response_model=ComponentBOMRead, status_code=201)
def create_bom_operation(
    payload: ComponentBOMCreate,
    db: Session = Depends(get_db),
):
    bom = ComponentBOM(**payload.model_dump())

    db.add(bom)
    db.commit()
    db.refresh(bom)

    bom = (
        db.query(ComponentBOM)
        .options(
            joinedload(ComponentBOM.component_type),
            joinedload(ComponentBOM.operation_type),
            joinedload(ComponentBOM.preferred_work_center),
        )
        .get(bom.id)
    )
    return bom


@router.patch("/{id}", response_model=ComponentBOMRead)
def update_bom_operation(
    id: int,
    payload: ComponentBOMUpdate,
    db: Session = Depends(get_db),
):
    # bom = db.query(ComponentBOM).get(id)
    bom = db.get(ComponentBOM, id)
    if not bom:
        raise HTTPException(status_code=404, detail="Component BOM not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(bom, field, value)

    db.commit()
    db.refresh(bom)

    bom = (
        db.query(ComponentBOM)
        .options(
            joinedload(ComponentBOM.component_type),
            joinedload(ComponentBOM.operation_type),
            joinedload(ComponentBOM.preferred_work_center),
        )
        .get(bom.id)
    )
    return bom


@router.delete("/{id}", status_code=204)
def delete_bom_operation(
    id: int,
    db: Session = Depends(get_db),
):
    # bom = db.query(ComponentBOM).get(id)
    bom = db.get(ComponentBOM, id)
    if not bom:
        raise HTTPException(status_code=404, detail="Component BOM not found")

    db.delete(bom)
    db.commit()


@router.patch("/{id}", response_model=ComponentBOMRead)
def update_bom_operation(
    id: int,
    payload: ComponentBOMUpdate,
    db: Session = Depends(get_db),
):
    # bom = db.query(ComponentBOM).get(id)
    bom = db.get(ComponentBOM, id)
    if not bom:
        raise HTTPException(status_code=404, detail="Component BOM not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(bom, field, value)

    db.commit()
    db.refresh(bom)

    bom = (
        db.query(ComponentBOM)
        .options(
            joinedload(ComponentBOM.component_type),
            joinedload(ComponentBOM.operation_type),
            joinedload(ComponentBOM.preferred_work_center),
        )
        .get(bom.id)
    )
    return bom


# =========================
# Reorder Endpoint
# =========================

class ComponentBOMReorder(BaseModel):
    bom_ids: List[int]

@router.post("/reorder", status_code=204)
def reorder_bom_operations(
    payload: ComponentBOMReorder,
    db: Session = Depends(get_db),
):
    """
    Reorder BOM operations based on the provided list of IDs.
    The order of IDs in the list determines the new sequence_number (1-based).
    """
    if not payload.bom_ids:
        return

    # Verify all BOMs exist (optional optimization: fetch all in one query)
    # We'll just fetch all BOMs involved to minimize queries
    boms = db.query(ComponentBOM).filter(ComponentBOM.id.in_(payload.bom_ids)).all()
    bom_map = {b.id: b for b in boms}

    missing_ids = [bid for bid in payload.bom_ids if bid not in bom_map]
    if missing_ids:
        raise HTTPException(status_code=400, detail=f"Invalid BOM IDs: {missing_ids}")

    # Ensure they all belong to the same component_type_id (very important!)
    component_type_ids = {bom_map[bid].component_type_id for bid in payload.bom_ids}
    if len(component_type_ids) != 1:
        raise HTTPException(
            status_code=400,
            detail="All bom_ids must belong to the same component_type_id",
        )

    # Two-phase update to avoid UNIQUE(component_type_id, sequence_number) conflicts
    try:
        # Phase 1: move to temporary sequence numbers (negative, unique)
        # Example: -1, -2, -3 ... (won't conflict with existing positive sequence)
        for idx, bom_id in enumerate(payload.bom_ids, start=1):
            bom_map[bom_id].sequence_number = -idx

        db.flush()  # push temp values so second phase won't collide

        # Phase 2: apply final sequence numbers (1..N)
        for idx, bom_id in enumerate(payload.bom_ids, start=1):
            bom_map[bom_id].sequence_number = idx

        db.commit()
    except Exception:
        db.rollback()
        raise
