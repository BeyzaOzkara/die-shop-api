# backend/routers/suppliers.py
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict, field_validator
from datetime import datetime

from ..database import get_db
from ..models import Supplier, Lot
from ..deps import require_admin

router = APIRouter(prefix="/suppliers", tags=["Suppliers"])


# =========================
# Pydantic Schemas
# =========================

class SupplierCreate(BaseModel):
    name: str
    tax_no: Optional[str] = None
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, v: str) -> str:
        return v.strip()


class SupplierUpdate(BaseModel):
    name: Optional[str] = None
    tax_no: Optional[str] = None
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return v.strip()
        return v


class SupplierRead(BaseModel):
    id: int
    name: str
    tax_no: Optional[str] = None
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# =========================
# Endpoints
# =========================

@router.get("", response_model=List[SupplierRead])
def list_suppliers(
    search: Optional[str] = None,
    active: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Supplier)
    if active is not None:
        query = query.filter(Supplier.is_active == active)
    if search:
        query = query.filter(Supplier.name.ilike(f"%{search}%"))
    return query.order_by(Supplier.name).all()


@router.post("", response_model=SupplierRead, status_code=201, dependencies=[Depends(require_admin)])
def create_supplier(payload: SupplierCreate, db: Session = Depends(get_db)):
    existing = db.query(Supplier).filter(Supplier.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Bu isimde bir tedarikçi zaten mevcut.")

    supplier = Supplier(**payload.model_dump())
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return supplier


@router.put("/{id}", response_model=SupplierRead, dependencies=[Depends(require_admin)])
def update_supplier(id: int, payload: SupplierUpdate, db: Session = Depends(get_db)):
    supplier = db.query(Supplier).get(id)
    if not supplier:
        raise HTTPException(status_code=404, detail="Tedarikçi bulunamadı.")

    data = payload.model_dump(exclude_unset=True)

    # Duplicate name check (excluding self)
    if "name" in data and data["name"] != supplier.name:
        conflict = db.query(Supplier).filter(Supplier.name == data["name"]).first()
        if conflict:
            raise HTTPException(status_code=409, detail="Bu isimde bir tedarikçi zaten mevcut.")

    for field, value in data.items():
        setattr(supplier, field, value)

    db.commit()
    db.refresh(supplier)
    return supplier


@router.delete("/{id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_supplier(id: int, db: Session = Depends(get_db)):
    supplier = db.query(Supplier).get(id)
    if not supplier:
        raise HTTPException(status_code=404, detail="Tedarikçi bulunamadı.")

    # Soft delete — set is_active=False
    supplier.is_active = False
    db.commit()
    return
