# app/routers/operators.py
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import Operator, WorkCenter, WorkCenterStatus, OperatorRole
from ..deps import require_admin


router = APIRouter(prefix="/operators", tags=["Operators"])


# ---------- Pydantic şemalar ----------

class OperationTypeNested(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    is_active: bool = True
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class WorkCenterNested(BaseModel):
    id: int
    name: str
    status: WorkCenterStatus
    location: Optional[str] = None
    capacity_per_hour: Optional[int] = None
    setup_time_minutes: Optional[int] = None
    cost_per_hour: Optional[float] = None
    created_at: datetime

    operation_types: List[OperationTypeNested] = [] 

    model_config = ConfigDict(from_attributes=True)


class OperatorBase(BaseModel):
    rfid_code: str
    name: str
    employee_number: Optional[str] = None
    role: OperatorRole = OperatorRole.Operator
    is_active: bool = True


class OperatorCreate(OperatorBase):
    work_center_ids: List[int]


class OperatorUpdate(BaseModel):
    rfid_code: Optional[str] = None
    name: Optional[str] = None
    employee_number: Optional[str] = None
    role: Optional[OperatorRole] = None
    is_active: Optional[bool] = None
    work_center_ids: Optional[List[int]] = None


class OperatorRead(OperatorBase):
    id: int
    created_at: datetime
    updated_at: datetime
    work_centers: List[WorkCenterNested] = []

    model_config = ConfigDict(from_attributes=True)


class OperatorLoginRequest(BaseModel):
    rfid_code: str


# ---------- Helpers ----------

def get_operator_with_centers(db: Session, operator_id: int) -> Operator:
    op = (
        db.query(Operator)
        .options(joinedload(Operator.work_centers).joinedload(WorkCenter.operation_types))
        .filter(Operator.id == operator_id)
        .first()
    )
    if not op:
        raise HTTPException(status_code=404, detail="Operator not found")
    return op


# ---------- Endpoint’ler ----------

# @router.get("/", response_model=List[OperatorRead])
@router.get("/", response_model=List[OperatorRead], dependencies=[Depends(require_admin)])
def list_operators(db: Session = Depends(get_db)):
    rows = (
        db.query(Operator)
        .options(joinedload(Operator.work_centers).joinedload(WorkCenter.operation_types))
        .order_by(Operator.name.asc())
        .all()
    )
    return rows


# @router.get("/{id}", response_model=OperatorRead)
@router.get("/{id}", response_model=OperatorRead, dependencies=[Depends(require_admin)])
def get_operator(id: int, db: Session = Depends(get_db)):
    return get_operator_with_centers(db, id)


# @router.post("/", response_model=OperatorRead, status_code=201)
@router.post("/", response_model=OperatorRead, status_code=201, dependencies=[Depends(require_admin)])
def create_operator(payload: OperatorCreate, db: Session = Depends(get_db)):
    existing = (
        db.query(Operator)
        .filter(Operator.rfid_code == payload.rfid_code)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="RFID code already exists")

    op = Operator(
        rfid_code=payload.rfid_code,
        name=payload.name,
        employee_number=payload.employee_number,
        role=payload.role,
        is_active=payload.is_active,
    )

    if payload.work_center_ids:
        centers = (
            db.query(WorkCenter)
            .filter(WorkCenter.id.in_(payload.work_center_ids))
            .all()
        )
        op.work_centers = centers

    db.add(op)
    db.commit()
    db.refresh(op)

    # Commit'ten sonra joinedload ile tekrar çekiyoruz ki work_centers kesin dolu gelsin.
    return get_operator_with_centers(db, op.id)


# @router.patch("/{id}", response_model=OperatorRead)
@router.patch("/{id}", response_model=OperatorRead, dependencies=[Depends(require_admin)])
def update_operator(id: int, payload: OperatorUpdate, db: Session = Depends(get_db)):
    op = db.query(Operator).get(id)
    if not op:
        raise HTTPException(status_code=404, detail="Operator not found")

    data = payload.model_dump(exclude_unset=True)
    work_center_ids = data.pop("work_center_ids", None)

    for field, value in data.items():
        setattr(op, field, value)

    if work_center_ids is not None:
        centers = (
            db.query(WorkCenter)
            .filter(WorkCenter.id.in_(work_center_ids))
            .all()
        )
        op.work_centers = centers

    db.commit()
    db.refresh(op)
    # same: joinedload ile tekrar çek
    return get_operator_with_centers(db, op.id)


# @router.delete("/{id}", status_code=204)
@router.delete("/{id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_operator(id: int, db: Session = Depends(get_db)):
    op = db.query(Operator).get(id)
    if not op:
        raise HTTPException(status_code=404, detail="Operator not found")

    op.is_active = False
    db.commit()
    return


@router.post("/login-by-rfid", response_model=OperatorRead)
def login_by_rfid(payload: OperatorLoginRequest, db: Session = Depends(get_db)):
    op = (
        db.query(Operator)
        .options(joinedload(Operator.work_centers).joinedload(WorkCenter.operation_types))
        .filter(
            Operator.rfid_code == payload.rfid_code,
            Operator.is_active == True,  # noqa
        )
        .first()
    )
    if not op:
        raise HTTPException(
            status_code=404,
            detail="RFID card not found or operator is not active",
        )
    return op


class EligibleWorkCenterRead(BaseModel):
    id: int
    name: str
    status: WorkCenterStatus
    location: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

# Operatörün yetkili olduğu work center’lar içinden, Seçilen operation_type_id’yi yapabilenlerin hepsini döndür
# Frontend status != Available olanları disabled göster
@router.get("/{operator_id}/eligible-work-centers", response_model=List[EligibleWorkCenterRead])
def eligible_work_centers_for_operator(
    operator_id: int,
    operation_type_id: int = Query(...),
    db: Session = Depends(get_db),
):
    op = (
        db.query(Operator)
        .options(
            joinedload(Operator.work_centers).joinedload(WorkCenter.operation_types)
        )
        .get(operator_id)
    )
    if not op:
        raise HTTPException(status_code=404, detail="Operator not found")

    eligible: List[WorkCenter] = []
    for wc in op.work_centers:
        can_do = any(ot.id == operation_type_id for ot in wc.operation_types)
        if can_do:
            eligible.append(wc)

    # İstersen UI daha stabil olsun diye sırala
    eligible.sort(key=lambda x: x.name.lower() if x.name else "")

    return eligible

# admin korumalı olmayan, public operatör detayı endpoint’i
@router.get("/public/{id}", response_model=OperatorRead)
def get_operator_public(id: int, db: Session = Depends(get_db)):
    op = (
        db.query(Operator)
        .options(joinedload(Operator.work_centers).joinedload(WorkCenter.operation_types))
        .filter(Operator.id == id, Operator.is_active == True)
        .first()
    )
    if not op:
        raise HTTPException(status_code=404, detail="Operator not found or inactive")
    return op
