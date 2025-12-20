# app/routers/operators.py
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import Operator, WorkCenter, WorkCenterStatus

router = APIRouter(prefix="/operators", tags=["Operators"])


# ---------- Pydantic şemalar ----------

class WorkCenterNested(BaseModel):
    id: int
    name: str
    status: WorkCenterStatus
    location: Optional[str] = None
    capacity_per_hour: Optional[int] = None
    setup_time_minutes: Optional[int] = None
    cost_per_hour: Optional[float] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OperatorBase(BaseModel):
    rfid_code: str
    name: str
    employee_number: Optional[str] = None
    is_active: bool = True


class OperatorCreate(OperatorBase):
    work_center_ids: List[int]


class OperatorUpdate(BaseModel):
    rfid_code: Optional[str] = None
    name: Optional[str] = None
    employee_number: Optional[str] = None
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


# ---------- Endpoint’ler ----------

@router.get("/", response_model=List[OperatorRead])
def list_operators(db: Session = Depends(get_db)):
    rows = (
        db.query(Operator)
        .options(joinedload(Operator.work_centers))
        .order_by(Operator.name.asc())
        .all()
    )
    return rows


@router.get("/{id}", response_model=OperatorRead)
def get_operator(id: int, db: Session = Depends(get_db)):
    op = (
        db.query(Operator)
        .options(joinedload(Operator.work_centers))
        .filter(Operator.id == id)
        .first()
    )
    if not op:
        raise HTTPException(status_code=404, detail="Operator not found")
    return op


@router.post("/", response_model=OperatorRead, status_code=201)
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
    db.refresh(op, attribute_names=["work_centers"])
    return op


@router.patch("/{id}", response_model=OperatorRead)
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
    db.refresh(op, attribute_names=["work_centers"])
    return op


@router.delete("/{id}", status_code=204)
def delete_operator(id: int, db: Session = Depends(get_db)):
    op = db.query(Operator).get(id)
    if not op:
        raise HTTPException(status_code=404, detail="Operator not found")

    db.delete(op)
    db.commit()
    return


@router.post("/login-by-rfid", response_model=OperatorRead)
def login_by_rfid(payload: OperatorLoginRequest, db: Session = Depends(get_db)):
    op = (
        db.query(Operator)
        .options(joinedload(Operator.work_centers))
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
