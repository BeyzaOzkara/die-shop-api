# backend/routers/dies.py
from typing import List, Optional
import json
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File as UploadFileField, Form
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from ..services.file_storage import save_uploaded_file
from ..config import settings
from ..database import get_db
from ..models import (
    Die,
    DieStatus,
    DieType,
    DieComponent,
    ComponentType,
    SteelStockItem,
)
from ..deps import require_admin


router = APIRouter(prefix="/dies", tags=["Dies"])


# =========================
# Pydantic Schemas
# =========================

# ---- Nested types ----

class DieTypeRef(BaseModel):
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


class StockItemNested(BaseModel):
    id: int
    alloy: str
    diameter_mm: int
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class FileRead(BaseModel):
    id: int
    # entity_type: str
    # entity_id: int
    original_name: str
    storage_path: str
    mime_type: str
    size_bytes: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# ---- Die ----

class DieBase(BaseModel):
    die_number: str
    die_diameter_mm: float
    total_package_length_mm: float
    die_type_id: int
    
    profile_no: Optional[str] = None
    figure_count: Optional[int] = None
    customer_name: Optional[str] = None
    press_code: Optional[str] = None


class DieComponentBase(BaseModel):
    component_type_id: int
    stock_item_id: int
    package_length_mm: float
    theoretical_consumption_kg: float


class DieComponentCreate(DieComponentBase):
    pass


class DieCreateIn(BaseModel):
    die_number: str
    die_diameter_mm: float
    total_package_length_mm: float
    die_type_id: int

    profile_no: Optional[str] = None
    figure_count: Optional[int] = None
    customer_name: Optional[str] = None
    press_code: Optional[str] = None
    # ... profile_no, figure_count, customer_name, press_code, is_fason

    components: List[DieComponentCreate] = []


class DieCreate(DieBase):
    # Supabase: insert({ ...die, status: 'Draft' })
    # burada status'i hep Draft yapacağız; payload'tan almak zorunda değiliz.
    pass


class DieUpdate(BaseModel): # dosya güncelleme eklenecek
    status: Optional[DieStatus] = None
    die_type_id: Optional[int] = None
    # diğer alanları da ileride istersen ekleyebiliriz.

# ---- DieComponent ----

class DieComponentRead(DieComponentBase):
    id: int
    die_id: int
    created_at: datetime
    component_type: Optional[ComponentTypeNested] = None
    stock_item: Optional[StockItemNested] = None

    model_config = ConfigDict(from_attributes=True)


class DieRead(DieBase):
    id: int

    die_number: str # NEW
    die_diameter_mm: float
    total_package_length_mm: float
    die_type_id: int

    status: DieStatus
    created_at: datetime
    updated_at: datetime
    die_type_ref: Optional[DieTypeRef] = None

    files: List["FileRead"] = []
    components: List["DieComponentRead"] = []

    model_config = ConfigDict(from_attributes=True)
DieRead.model_rebuild()


# =========================
# Die endpoints
# =========================

@router.get("/", response_model=List[DieRead])
def list_dies(db: Session = Depends(get_db)):
    dies = (
        db.query(Die)
        # .options(joinedload(Die.die_type), joinedload(Die.files))
        .options(
            joinedload(Die.die_type),
            joinedload(Die.files),
            joinedload(Die.components).joinedload(DieComponent.component_type),
            joinedload(Die.components).joinedload(DieComponent.stock_item),
        )
        .order_by(Die.created_at.desc())
        .all()
    )
    result: List[DieRead] = []
    for die in dies:
        die_dict = DieRead.model_validate(die).model_dump()
        if die.die_type:
            die_dict["die_type_ref"] = DieTypeRef.model_validate(die.die_type)
        else:
            die_dict["die_type_ref"] = None
        result.append(DieRead.model_validate(die_dict))
    return result


@router.get("/{die_id}", response_model=DieRead)
def get_die(die_id: int, db: Session = Depends(get_db)):
    die = (
        db.query(Die)
        # .options(joinedload(Die.die_type), joinedload(Die.files))
        .options(
            joinedload(Die.die_type),
            joinedload(Die.files),
            joinedload(Die.components).joinedload(DieComponent.component_type),
            joinedload(Die.components).joinedload(DieComponent.stock_item),
        )
        .filter(Die.id == die_id)
        .first()
    )
    if not die:
        raise HTTPException(status_code=404, detail="Die not found")
    # return die
    die_dict = DieRead.model_validate(die).model_dump()
    if die.die_type:
        die_dict["die_type_ref"] = DieTypeRef.model_validate(die.die_type)
    else:
        die_dict["die_type_ref"] = None
    return DieRead.model_validate(die_dict)


# @router.post("/", response_model=DieRead, status_code=201)
# @router.post("/", response_model=DieRead, status_code=201, dependencies=[Depends(require_admin)])
# def create_die(
#     payload: str = Form(...),
#     design_files: List[UploadFile] = UploadFileField([]),
#     db: Session = Depends(get_db),
# ):
#     # 1) payload json parse + validate
#     try:
#         data = json.loads(payload)
#         p = DieCreateIn.model_validate(data)
#     except Exception as e:
#         raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")

#     # 2) uniq kontrol
#     existing = db.query(Die).filter(Die.die_number == p.die_number).first()
#     if existing:
#         raise HTTPException(status_code=400, detail="Die number already exists")

#     # 3) die oluştur
#     die = Die(
#         die_number=p.die_number,
#         die_diameter_mm=p.die_diameter_mm,
#         total_package_length_mm=p.total_package_length_mm,
#         die_type_id=p.die_type_id,
#         status=DieStatus.Draft,

#         profile_no=p.profile_no,
#         figure_count=p.figure_count,
#         customer_name=p.customer_name,
#         press_code=p.press_code,
#     )
#     db.add(die)
#     db.flush()  # die.id lazım

#     # 4) dosyalar varsa kaydet + File kayıtları bas
#     first_url: Optional[str] = None
#     for f in design_files or []:
#         save_uploaded_file(
#             db=db,
#             upload=f,
#             entity_type="die",
#             entity_id=die.id,
#         )

#     db.commit()

#     die = (
#         db.query(Die)
#         .options(joinedload(Die.die_type), joinedload(Die.files))
#         .get(die.id)
#     )
#     return die

@router.post("/", response_model=DieRead, status_code=201, dependencies=[Depends(require_admin)])
def create_die(
    payload: str = Form(...),
    design_files: List[UploadFile] = UploadFileField([]),
    db: Session = Depends(get_db),
):
    # 1) payload json parse + validate
    try:
        data = json.loads(payload)
        p = DieCreateIn.model_validate(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")

    # 1.1) components zorunlu olsun (senin akışına göre)
    if not p.components or len(p.components) == 0:
        raise HTTPException(status_code=400, detail="Components are required")

    # 2) uniq kontrol
    existing = db.query(Die).filter(Die.die_number == p.die_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="Die number already exists")

    # 3) referans kontrolleri (daha erken patlasın)
    die_type = db.query(DieType).get(p.die_type_id)
    if not die_type:
        raise HTTPException(status_code=400, detail="Invalid die_type_id")

    # component validations (id var mı, stock var mı, duplicate var mı)
    seen_component_type_ids = set()

    component_type_ids = [c.component_type_id for c in p.components]
    stock_item_ids = [c.stock_item_id for c in p.components]

    # duplicate component_type_id kontrolü
    for cid in component_type_ids:
        if cid in seen_component_type_ids:
            raise HTTPException(status_code=400, detail=f"Duplicate component_type_id in payload: {cid}")
        seen_component_type_ids.add(cid)

    # toplu fetch (performans + doğruluk)
    # existing_component_types = {
    #     ct.id for ct in db.query(ComponentType.id).filter(ComponentType.id.in_(component_type_ids)).all()
    # }
    existing_component_types = set(
        r[0] for r in db.query(ComponentType.id)
        .filter(ComponentType.id.in_(component_type_ids))
        .all()
    )

    missing_ct = [cid for cid in component_type_ids if cid not in existing_component_types]
    if missing_ct:
        raise HTTPException(status_code=400, detail=f"Invalid component_type_id(s): {missing_ct}")

    # existing_stock_items = {
    #     si.id for si in db.query(SteelStockItem.id).filter(SteelStockItem.id.in_(stock_item_ids)).all()
    # }
    existing_stock_items = set(
        r[0] for r in db.query(SteelStockItem.id)
        .filter(SteelStockItem.id.in_(stock_item_ids))
        .all()
    )
    missing_si = [sid for sid in stock_item_ids if sid not in existing_stock_items]
    if missing_si:
        raise HTTPException(status_code=400, detail=f"Invalid stock_item_id(s): {missing_si}")

    # numeric sanity checks (NaN burada gelmez çünkü pydantic parse ediyor ama 0 kontrolü önemli)
    for c in p.components:
        if c.package_length_mm <= 0:
            raise HTTPException(status_code=400, detail="package_length_mm must be > 0")
        if c.theoretical_consumption_kg <= 0:
            raise HTTPException(status_code=400, detail="theoretical_consumption_kg must be > 0")

    # 4) atomik transaction
    try:
        die = Die(
            die_number=p.die_number,
            die_diameter_mm=p.die_diameter_mm,
            total_package_length_mm=p.total_package_length_mm,
            die_type_id=p.die_type_id,
            status=DieStatus.Draft,
            profile_no=p.profile_no,
            figure_count=p.figure_count,
            customer_name=p.customer_name,
            press_code=p.press_code,
        )
        db.add(die)
        db.flush()  # die.id lazım

        # 4.1) dosyalar
        for f in design_files or []:
            save_uploaded_file(
                db=db,
                upload=f,
                entity_type="die",
                entity_id=die.id,
            )

        # 4.2) bileşenler (bulk create)
        for c in p.components:
            comp = DieComponent(
                die_id=die.id,
                component_type_id=c.component_type_id,
                stock_item_id=c.stock_item_id,
                package_length_mm=c.package_length_mm,
                theoretical_consumption_kg=c.theoretical_consumption_kg,
            )
            db.add(comp)

        db.commit()

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Create die failed: {e}")

    # 5) response (die_type_ref + files)
    die = (
        db.query(Die)
        .options(joinedload(Die.die_type), joinedload(Die.files))
        .get(die.id)
    )

    die_dict = DieRead.model_validate(die).model_dump()
    die_dict["die_type_ref"] = DieTypeRef.model_validate(die.die_type) if die.die_type else None
    return DieRead.model_validate(die_dict)


# @router.patch("/{die_id}", response_model=DieRead)
@router.patch("/{die_id}", response_model=DieRead, dependencies=[Depends(require_admin)])
def update_die(
    die_id: int,
    payload: DieUpdate,
    db: Session = Depends(get_db),
):
    die = db.query(Die).get(die_id)
    if not die:
        raise HTTPException(status_code=404, detail="Die not found")

    data = payload.model_dump(exclude_unset=True)

    # status enum/string normalize
    if "status" in data and data["status"] is not None:
        new_status = data["status"]
        if isinstance(new_status, str):
            new_status = DieStatus(new_status)
        die.status = new_status

    if "die_type_id" in data and data["die_type_id"] is not None:
        die.die_type_id = data["die_type_id"]

    db.commit()

    die = (
        db.query(Die)
        .options(joinedload(Die.die_type), joinedload(Die.files))
        .get(die_id)
    )

    die_dict = DieRead.model_validate(die).model_dump()
    die_dict["die_type_ref"] = DieTypeRef.model_validate(die.die_type) if die.die_type else None
    return DieRead.model_validate(die_dict)


# =========================
# DieComponent endpoints
# =========================

@router.get("/{die_id}/components", response_model=List[DieComponentRead])
def list_die_components(die_id: int, db: Session = Depends(get_db)):
    components = (
        db.query(DieComponent)
        .options(
            joinedload(DieComponent.component_type),
            joinedload(DieComponent.stock_item),
        )
        .filter(DieComponent.die_id == die_id)
        .order_by(DieComponent.created_at.asc())
        .all()
    )
    return components


# @router.post("/{die_id}/components", response_model=DieComponentRead, status_code=201)
@router.post("/{die_id}/components", response_model=DieComponentRead, status_code=201, dependencies=[Depends(require_admin)])
def create_die_component(
    die_id: int,
    payload: DieComponentCreate,
    db: Session = Depends(get_db),
):
    # die var mı kontrolü
    die = db.query(Die).get(die_id)
    if not die:
        raise HTTPException(status_code=404, detail="Die not found")

    # die_component (die_id + component_type_id) unique constraint var,
    # aynı bileşen zaten eklenmişse hata verelim
    existing = (
        db.query(DieComponent)
        .filter(
            DieComponent.die_id == die_id,
            DieComponent.component_type_id == payload.component_type_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="This component is already added to the die")

    comp = DieComponent(
        die_id=die_id,
        component_type_id=payload.component_type_id,
        stock_item_id=payload.stock_item_id,
        package_length_mm=payload.package_length_mm,
        theoretical_consumption_kg=payload.theoretical_consumption_kg,
    )
    db.add(comp)
    db.commit()
    db.refresh(comp)
    # ilişkileri yüklü getir
    comp = (
        db.query(DieComponent)
        .options(
            joinedload(DieComponent.component_type),
            joinedload(DieComponent.stock_item),
        )
        .get(comp.id)
    )
    return comp
