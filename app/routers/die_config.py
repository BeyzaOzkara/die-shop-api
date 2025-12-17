# backend/routers/die_config.py
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel, ConfigDict
from datetime import datetime

from ..database import get_db
from ..models import DieType, ComponentType, DieTypeComponent

router = APIRouter(prefix="/die-config", tags=["Die Configuration"])


# =====================================
# Pydantic Schemas
# =====================================

# ---- DieType ----

class DieTypeBase(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    is_active: bool = True


class DieTypeCreate(DieTypeBase):
    pass


class DieTypeUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class DieTypeRead(DieTypeBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---- ComponentType ----

class ComponentTypeBase(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    is_active: bool = True


class ComponentTypeCreate(ComponentTypeBase):
    pass


class ComponentTypeUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ComponentTypeRead(ComponentTypeBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---- DieTypeComponent (mapping) ----

class DieTypeNested(BaseModel):
    id: int
    code: str
    name: str

    model_config = ConfigDict(from_attributes=True)


class ComponentTypeNested(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class DieTypeComponentRead(BaseModel):
    id: int
    die_type_id: int
    component_type_id: int
    created_at: datetime
    die_type: Optional[DieTypeNested] = None
    component_type: Optional[ComponentTypeNested] = None

    model_config = ConfigDict(from_attributes=True)


class DieTypeComponentCreate(BaseModel):
    die_type_id: int
    component_type_id: int


class ComponentTypeOnlyRead(ComponentTypeNested):
    pass


# =====================================
# DieTypes
# =====================================

@router.get("/die-types", response_model=List[DieTypeRead])
def list_die_types(db: Session = Depends(get_db)):
    return db.query(DieType).order_by(DieType.name).all()

@router.get("/die-types/active", response_model=List[DieTypeRead])
def list_active_die_types(db: Session = Depends(get_db)):
    return (
        db.query(DieType)
        .filter(DieType.is_active.is_(True))
        .order_by(DieType.name)
        .all()
    )

@router.post("/die-types", response_model=DieTypeRead, status_code=201)
def create_die_type(payload: DieTypeCreate, db: Session = Depends(get_db)):
    existing = db.query(DieType).filter(DieType.code == payload.code).first()
    if existing:
        raise HTTPException(status_code=400, detail="Die type code already exists")

    dt = DieType(**payload.model_dump())
    db.add(dt)
    db.commit()
    db.refresh(dt)
    return dt


@router.patch("/die-types/{id}", response_model=DieTypeRead)
def update_die_type(id: int, payload: DieTypeUpdate, db: Session = Depends(get_db)):
    dt = db.query(DieType).get(id)
    if not dt:
        raise HTTPException(status_code=404, detail="Die type not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(dt, field, value)

    dt.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(dt)
    return dt


@router.delete("/die-types/{id}", status_code=204)
def delete_die_type(id: int, db: Session = Depends(get_db)):
    dt = db.query(DieType).get(id)
    if not dt:
        raise HTTPException(status_code=404, detail="Die type not found")

    db.delete(dt)
    db.commit()
    return


# =====================================
# ComponentTypes
# =====================================

@router.get("/component-types", response_model=List[ComponentTypeRead])
def list_component_types(db: Session = Depends(get_db)):
    return db.query(ComponentType).order_by(ComponentType.name).all()


@router.get("/component-types/active", response_model=List[ComponentTypeRead])
def list_active_component_types(db: Session = Depends(get_db)):
    return (
        db.query(ComponentType)
        .filter(ComponentType.is_active.is_(True))
        .order_by(ComponentType.name)
        .all()
    )


@router.post("/component-types", response_model=ComponentTypeRead, status_code=201)
def create_component_type(payload: ComponentTypeCreate, db: Session = Depends(get_db)):
    existing = db.query(ComponentType).filter(ComponentType.code == payload.code).first()
    if existing:
        raise HTTPException(status_code=400, detail="Component type code already exists")

    ct = ComponentType(**payload.model_dump())
    db.add(ct)
    db.commit()
    db.refresh(ct)
    return ct


@router.patch("/component-types/{id}", response_model=ComponentTypeRead)
def update_component_type(id: int, payload: ComponentTypeUpdate, db: Session = Depends(get_db)):
    ct = db.query(ComponentType).get(id)
    if not ct:
        raise HTTPException(status_code=404, detail="Component type not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(ct, field, value)

    ct.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(ct)
    return ct


@router.delete("/component-types/{id}", status_code=204)
def delete_component_type(id: int, db: Session = Depends(get_db)):
    ct = db.query(ComponentType).get(id)
    if not ct:
        raise HTTPException(status_code=404, detail="Component type not found")

    db.delete(ct)
    db.commit()
    return


# =====================================
# DieTypeComponent (mapping)
# =====================================

@router.get("/die-type-components", response_model=List[DieTypeComponentRead])
def list_die_type_components(db: Session = Depends(get_db)):
    rows = (
        db.query(DieTypeComponent)
        .options(
            joinedload(DieTypeComponent.die_type),
            joinedload(DieTypeComponent.component_type),
        )
        .order_by(DieTypeComponent.created_at)
        .all()
    )
    return rows


@router.get(
    "/die-types/{die_type_id}/components",
    response_model=List[ComponentTypeOnlyRead],
)
def list_components_for_die_type(die_type_id: int, db: Session = Depends(get_db)):
    mappings = (
        db.query(DieTypeComponent)
        .options(joinedload(DieTypeComponent.component_type))
        .filter(DieTypeComponent.die_type_id == die_type_id)
        .all()
    )
    result: List[ComponentTypeOnlyRead] = []
    for m in mappings:
        if m.component_type:
            result.append(ComponentTypeOnlyRead.model_validate(m.component_type))
    return result


@router.post("/die-type-components", response_model=DieTypeComponentRead, status_code=201)
def create_die_type_component(
    payload: DieTypeComponentCreate,
    db: Session = Depends(get_db),
):
    # Aynı eşleşme zaten varsa hata verelim
    exists = (
        db.query(DieTypeComponent)
        .filter(
            DieTypeComponent.die_type_id == payload.die_type_id,
            DieTypeComponent.component_type_id == payload.component_type_id,
        )
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="Mapping already exists")

    mapping = DieTypeComponent(
        die_type_id=payload.die_type_id,
        component_type_id=payload.component_type_id,
    )
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    # ilişkileri yüklü halde dönmek için tekrar joinedload ile fetch edelim
    mapping = (
        db.query(DieTypeComponent)
        .options(
            joinedload(DieTypeComponent.die_type),
            joinedload(DieTypeComponent.component_type),
        )
        .get(mapping.id)
    )
    return mapping


@router.delete("/die-type-components", status_code=204)
def delete_die_type_component(
    die_type_id: int = Query(...),
    component_type_id: int = Query(...),
    db: Session = Depends(get_db),
):
    mapping = (
        db.query(DieTypeComponent)
        .filter(
            DieTypeComponent.die_type_id == die_type_id,
            DieTypeComponent.component_type_id == component_type_id,
        )
        .first()
    )
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")

    db.delete(mapping)
    db.commit()
    return
