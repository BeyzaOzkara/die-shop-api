# backend/routers/component_bom.py
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel, ConfigDict
from datetime import datetime

from ..database import get_db
from ..models import ComponentBOM, WorkCenter, ComponentType

router = APIRouter(prefix="/component-bom", tags=["Component BOM"])


# =========================
# Nested modeller
# =========================

class WorkCenterNested(BaseModel):
    id: int
    name: str
    type: str

    model_config = ConfigDict(from_attributes=True)


class ComponentTypeNested(BaseModel):
    id: int
    code: str
    name: str

    model_config = ConfigDict(from_attributes=True)


# =========================
# BOM modelleri
# =========================

class ComponentBOMBase(BaseModel):
    component_type_id: int
    sequence_number: int
    operation_name: str
    work_center_id: int
    estimated_duration_minutes: Optional[int] = None
    notes: Optional[str] = None


class ComponentBOMCreate(ComponentBOMBase):
    pass


class ComponentBOMUpdate(BaseModel):
    sequence_number: Optional[int] = None
    operation_name: Optional[str] = None
    work_center_id: Optional[int] = None
    estimated_duration_minutes: Optional[int] = None
    notes: Optional[str] = None


class ComponentBOMRead(ComponentBOMBase):
    id: int
    created_at: datetime
    component_type: Optional[ComponentTypeNested] = None
    work_center: Optional[WorkCenterNested] = None

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
            joinedload(ComponentBOM.work_center),
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
    bom = ComponentBOM(
        component_type_id=payload.component_type_id,
        work_center_id=payload.work_center_id,
        sequence_number=payload.sequence_number,
        operation_name=payload.operation_name,
        estimated_duration_minutes=payload.estimated_duration_minutes,
        notes=payload.notes,
    )

    db.add(bom)
    db.commit()
    db.refresh(bom)

    bom = (
        db.query(ComponentBOM)
        .options(
            joinedload(ComponentBOM.component_type),
            joinedload(ComponentBOM.work_center),
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
    bom = db.query(ComponentBOM).get(id)
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
            joinedload(ComponentBOM.work_center),
        )
        .get(bom.id)
    )
    return bom


@router.delete("/{id}", status_code=204)
def delete_bom_operation(
    id: int,
    db: Session = Depends(get_db),
):
    bom = db.query(ComponentBOM).get(id)
    if not bom:
        raise HTTPException(status_code=404, detail="Component BOM not found")

    db.delete(bom)
    db.commit()
