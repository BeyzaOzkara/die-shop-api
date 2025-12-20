# backend/routers/operation_types.py
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict
from datetime import datetime

from ..database import get_db
from ..models import OperationType

router = APIRouter(prefix="/operation-types", tags=["Operation Types"])


# =========================
# Pydantic Şemalar
# =========================

class OperationTypeBase(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    is_active: bool = True


class OperationTypeCreate(OperationTypeBase):
    pass


class OperationTypeUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class OperationTypeRead(OperationTypeBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# =========================
# Endpoints
# =========================

@router.get("", response_model=List[OperationTypeRead])
def list_operation_types(
    only_active: bool = True,
    db: Session = Depends(get_db),
):
    q = db.query(OperationType)
    if only_active:
        q = q.filter(OperationType.is_active == True)  # noqa
    return q.order_by(OperationType.name.asc()).all()


@router.post("", response_model=OperationTypeRead, status_code=201)
def create_operation_type(payload: OperationTypeCreate, db: Session = Depends(get_db)):
    existing = db.query(OperationType).filter(OperationType.code == payload.code).first()
    if existing:
        raise HTTPException(status_code=400, detail="Operation type code already exists")

    ot = OperationType(**payload.model_dump())
    db.add(ot)
    db.commit()
    db.refresh(ot)
    return ot


@router.patch("/{id}", response_model=OperationTypeRead)
def update_operation_type(id: int, payload: OperationTypeUpdate, db: Session = Depends(get_db)):
    ot = db.query(OperationType).get(id)
    if not ot:
        raise HTTPException(status_code=404, detail="Operation type not found")

    data = payload.model_dump(exclude_unset=True)

    # code normalize + unique check
    if "code" in data and data["code"] is not None:
        new_code = data["code"].strip().upper()
        # sadece değişiyorsa kontrol et
        if new_code != ot.code:
            exists = (
                db.query(OperationType)
                .filter(OperationType.code == new_code, OperationType.id != id)
                .first()
            )
            if exists:
                raise HTTPException(status_code=400, detail="Operation type code already exists")
        data["code"] = new_code

    for field, value in data.items():
        setattr(ot, field, value)
    # for field, value in payload.model_dump(exclude_unset=True).items():
    #     setattr(ot, field, value)

    db.commit()
    db.refresh(ot)
    return ot


@router.delete("/{id}", status_code=204)
def delete_operation_type(id: int, db: Session = Depends(get_db)):
    ot = db.query(OperationType).get(id)
    if not ot:
        raise HTTPException(status_code=404, detail="Operation type not found")

    # db.delete(ot)
    ot.is_active = False
    db.commit()
    return
