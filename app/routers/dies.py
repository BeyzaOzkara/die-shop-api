# backend/routers/dies.py
from typing import List, Optional
import json
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File as UploadFileField, Form
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, distinct, or_
from pydantic import BaseModel, ConfigDict
from datetime import datetime, date
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
    ProductionOrder,
    OrderStatus,
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
    
    is_revisioned: bool = False
    expected_completion_date: Optional[date] = None
    description: Optional[str] = None


class DieComponentBase(BaseModel):
    component_type_id: int
    stock_item_id: int
    package_length_mm: float
    theoretical_consumption_kg: float


class DieComponentCreate(DieComponentBase):
    pass


class DieComponentUpdate(BaseModel):
    """Schema for updating a die component. Includes optional id for existing components."""
    id: Optional[int] = None  # if provided, this is an existing component to update
    component_type_id: int
    stock_item_id: int
    package_length_mm: float
    theoretical_consumption_kg: float


class DieComponentsReplace(BaseModel):
    """Schema for batch replacing all components of a die."""
    components: List[DieComponentUpdate]


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

    is_revisioned: bool = False
    expected_completion_date: Optional[date] = None
    description: Optional[str] = None

    components: List[DieComponentCreate] = []

# =======================================
# STATS SCHEMAS
# =======================================

class DieStatsComponentItem(BaseModel):
    component_type_id: int
    component_type_name: str
    component_rows_count: int
    die_count: int

    class Config:
        from_attributes = True


class DieStatsResponse(BaseModel):
    total_dies: int
    total_profiles: int
    components: List[DieStatsComponentItem]

class DieCreate(DieBase):
    # Supabase: insert({ ...die, status: 'Draft' })
    # burada status'i hep Draft yapacağız; payload'tan almak zorunda değiliz.
    pass


class DieUpdate(BaseModel):
    """Schema for updating die fields. die_number is immutable and cannot be updated."""
    status: Optional[DieStatus] = None
    die_type_id: Optional[int] = None
    die_diameter_mm: Optional[float] = None
    total_package_length_mm: Optional[float] = None
    profile_no: Optional[str] = None
    figure_count: Optional[int] = None
    customer_name: Optional[str] = None
    press_code: Optional[str] = None
    is_revisioned: Optional[bool] = None
    expected_completion_date: Optional[date] = None
    description: Optional[str] = None

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
    expected_completion_date: Optional[date] = None

    files: List["FileRead"] = []
    components: List["DieComponentRead"] = []

    model_config = ConfigDict(from_attributes=True)
DieRead.model_rebuild()


class DiePageResponse(BaseModel):
    items: List[DieRead]
    total: int


# =========================
# Die endpoints
# =========================

@router.get("/", response_model=DiePageResponse)
def list_dies(
    skip: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=200),
    search: Optional[str] = Query(None, description="Search die_number, profile_no, customer_name"),
    status: Optional[str] = Query(None, description="DieStatus value"),
    die_type_id: Optional[int] = Query(None),
    is_revisioned: Optional[bool] = Query(None),
    # Numeric range filters
    die_diameter_mm_min: Optional[float] = Query(None, description="die_diameter_mm >= value"),
    die_diameter_mm_max: Optional[float] = Query(None, description="die_diameter_mm <= value"),
    total_package_length_mm_min: Optional[float] = Query(None, description="total_package_length_mm >= value"),
    total_package_length_mm_max: Optional[float] = Query(None, description="total_package_length_mm <= value"),
    figure_count: Optional[int] = Query(None, description="Exact match on figure_count"),
    press_code: Optional[str] = Query(None, description="press_code ilike"),
    date_from: Optional[date] = Query(None, description="Filter created_at >= date_from"),
    date_to: Optional[date] = Query(None, description="Filter created_at <= date_to"),
    db: Session = Depends(get_db),
):
    """Return paginated, filtered dies."""
    q = db.query(Die)

    # --- Search across die_number, profile_no, customer_name ---
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.filter(
            or_(
                Die.die_number.ilike(term),
                Die.profile_no.ilike(term),
                Die.customer_name.ilike(term),
            )
        )

    # --- Exact / enum filters ---
    if status:
        try:
            q = q.filter(Die.status == DieStatus(status))
        except ValueError:
            pass  # ignore unknown status values

    if die_type_id is not None:
        q = q.filter(Die.die_type_id == die_type_id)

    if is_revisioned is not None:
        q = q.filter(Die.is_revisioned == is_revisioned)

    # --- Date range (inclusive) ---
    if date_from:
        q = q.filter(func.date(Die.created_at) >= date_from)
    if date_to:
        q = q.filter(func.date(Die.created_at) <= date_to)

    # --- Numeric range filters ---
    if die_diameter_mm_min is not None:
        q = q.filter(Die.die_diameter_mm >= die_diameter_mm_min)
    if die_diameter_mm_max is not None:
        q = q.filter(Die.die_diameter_mm <= die_diameter_mm_max)
    if total_package_length_mm_min is not None:
        q = q.filter(Die.total_package_length_mm >= total_package_length_mm_min)
    if total_package_length_mm_max is not None:
        q = q.filter(Die.total_package_length_mm <= total_package_length_mm_max)

    # --- Exact integer filter ---
    if figure_count is not None:
        q = q.filter(Die.figure_count == figure_count)

    # --- Text filter ---
    if press_code and press_code.strip():
        q = q.filter(Die.press_code.ilike(f"%{press_code.strip()}%"))

    # --- Count before pagination ---
    total: int = q.with_entities(func.count(Die.id)).scalar() or 0

    # --- Fetch page ---
    dies = (
        q.options(
            joinedload(Die.die_type),
            joinedload(Die.files),
            joinedload(Die.components).joinedload(DieComponent.component_type),
            joinedload(Die.components).joinedload(DieComponent.stock_item),
        )
        .order_by(Die.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    items: List[DieRead] = []
    for die in dies:
        die_dict = DieRead.model_validate(die).model_dump()
        die_dict["die_type_ref"] = DieTypeRef.model_validate(die.die_type) if die.die_type else None
        items.append(DieRead.model_validate(die_dict))
 
    return DiePageResponse(items=items, total=total)

# @router.get("/", response_model=List[DieRead])
# def list_dies(db: Session = Depends(get_db)):
#     dies = (
#         db.query(Die)
#         # .options(joinedload(Die.die_type), joinedload(Die.files))
#         .options(
#             joinedload(Die.die_type),
#             joinedload(Die.files),
#             joinedload(Die.components).joinedload(DieComponent.component_type),
#             joinedload(Die.components).joinedload(DieComponent.stock_item),
#         )
#         .order_by(Die.created_at.desc())
#         .all()
#     )
#     result: List[DieRead] = []
#     for die in dies:
#         die_dict = DieRead.model_validate(die).model_dump()
#         if die.die_type:
#             die_dict["die_type_ref"] = DieTypeRef.model_validate(die.die_type)
#         else:
#             die_dict["die_type_ref"] = None
#         result.append(DieRead.model_validate(die_dict))
#     return result

@router.get("/stats", response_model=DieStatsResponse)
def get_die_stats(db: Session = Depends(get_db)):
    """Global aggregated stats — independent of pagination."""
    # 1) total dies
    total_dies: int = db.query(func.count(Die.id)).scalar() or 0

    # 2) distinct profile_no (ignore blank/null)
    total_profiles: int = (
        db.query(func.count(distinct(Die.profile_no)))
        .filter(Die.profile_no.isnot(None), Die.profile_no != '')
        .scalar()
    ) or 0

    # 3) component breakdown
    rows = (
        db.query(
            ComponentType.id.label('component_type_id'),
            ComponentType.name.label('component_type_name'),
            func.count(DieComponent.id).label('component_rows_count'),
            func.count(distinct(DieComponent.die_id)).label('die_count'),
        )
        .join(DieComponent, DieComponent.component_type_id == ComponentType.id)
        .group_by(ComponentType.id, ComponentType.name)
        .order_by(func.count(DieComponent.id).desc())
        .all()
    )

    components = [
        DieStatsComponentItem(
            component_type_id=r.component_type_id,
            component_type_name=r.component_type_name,
            component_rows_count=r.component_rows_count,
            die_count=r.die_count,
        )
        for r in rows
    ]

    return DieStatsResponse(
        total_dies=total_dies,
        total_profiles=total_profiles,
        components=components,
    )


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
        # if c.theoretical_consumption_kg <= 0:
        #     raise HTTPException(status_code=400, detail="theoretical_consumption_kg must be > 0")

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
            is_revisioned=p.is_revisioned,
            expected_completion_date=p.expected_completion_date,
            description=p.description,
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

    # Update all provided fields
    for field, value in data.items():
        if field == "status" and value is not None:
            # status enum/string normalize
            if isinstance(value, str):
                value = DieStatus(value)
        if hasattr(die, field):
            setattr(die, field, value)

    db.commit()

    # Refresh and return with relations
    die = (
        db.query(Die)
        .options(
            joinedload(Die.die_type),
            joinedload(Die.files),
            joinedload(Die.components).joinedload(DieComponent.component_type),
            joinedload(Die.components).joinedload(DieComponent.stock_item),
        )
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


@router.put("/{die_id}/components", response_model=List[DieComponentRead], dependencies=[Depends(require_admin)])
def replace_die_components(
    die_id: int,
    payload: DieComponentsReplace,
    db: Session = Depends(get_db),
):
    """
    Batch replace all components for a die.
    - Deletes components not in the new list
    - Updates existing components (matched by component_type_id)
    - Creates new components
    """
    # Verify die exists
    die = db.query(Die).get(die_id)
    if not die:
        raise HTTPException(status_code=404, detail="Die not found")

    # Validate no duplicate component_type_ids in payload
    component_type_ids = [c.component_type_id for c in payload.components]
    if len(component_type_ids) != len(set(component_type_ids)):
        raise HTTPException(status_code=400, detail="Duplicate component_type_id in payload")

    # Validate all component_type_ids and stock_item_ids exist
    if component_type_ids:
        existing_component_types = set(
            r[0] for r in db.query(ComponentType.id)
            .filter(ComponentType.id.in_(component_type_ids))
            .all()
        )
        missing_ct = [cid for cid in component_type_ids if cid not in existing_component_types]
        if missing_ct:
            raise HTTPException(status_code=400, detail=f"Invalid component_type_id(s): {missing_ct}")

    stock_item_ids = [c.stock_item_id for c in payload.components]
    if stock_item_ids:
        existing_stock_items = set(
            r[0] for r in db.query(SteelStockItem.id)
            .filter(SteelStockItem.id.in_(stock_item_ids))
            .all()
        )
        missing_si = [sid for sid in stock_item_ids if sid not in existing_stock_items]
        if missing_si:
            raise HTTPException(status_code=400, detail=f"Invalid stock_item_id(s): {missing_si}")

    # Validate numeric values
    for c in payload.components:
        if c.package_length_mm <= 0:
            raise HTTPException(status_code=400, detail="package_length_mm must be > 0")
        # if c.theoretical_consumption_kg <= 0:
        #     raise HTTPException(status_code=400, detail="theoretical_consumption_kg must be > 0")

    try:
        # Get existing components
        existing_components = db.query(DieComponent).filter(DieComponent.die_id == die_id).all()
        existing_by_type = {c.component_type_id: c for c in existing_components}
        
        # Track which component_type_ids are in the new payload
        new_component_type_ids = set(component_type_ids)
        
        # Delete components not in new list
        for comp in existing_components:
            if comp.component_type_id not in new_component_type_ids:
                db.delete(comp)
        
        # Update or create components
        for comp_data in payload.components:
            if comp_data.component_type_id in existing_by_type:
                # Update existing
                existing_comp = existing_by_type[comp_data.component_type_id]
                existing_comp.stock_item_id = comp_data.stock_item_id
                existing_comp.package_length_mm = comp_data.package_length_mm
                existing_comp.theoretical_consumption_kg = comp_data.theoretical_consumption_kg
            else:
                # Create new
                new_comp = DieComponent(
                    die_id=die_id,
                    component_type_id=comp_data.component_type_id,
                    stock_item_id=comp_data.stock_item_id,
                    package_length_mm=comp_data.package_length_mm,
                    theoretical_consumption_kg=comp_data.theoretical_consumption_kg,
                )
                db.add(new_comp)
        
        db.commit()

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Component replacement failed: {e}")

    # Return updated components with relations
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


@router.post("/{die_id}/files", response_model=DieRead, status_code=201, dependencies=[Depends(require_admin)])
def add_die_files(
    die_id: int,
    files: List[UploadFile] = UploadFileField(...),  # form field name: "files"
    db: Session = Depends(get_db),
):
    die = db.query(Die).get(die_id)
    if not die:
        raise HTTPException(status_code=404, detail="Die not found")

    if not files or len(files) == 0:
        raise HTTPException(status_code=400, detail="No files provided")

    try:
        # Dosyaları kaydet
        for f in files:
            save_uploaded_file(
                db=db,
                upload=f,
                entity_type="die",
                entity_id=die.id,
            )

        db.commit()

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

    # Taze haliyle dön (die_type_ref + files + components)
    die = (
        db.query(Die)
        .options(
            joinedload(Die.die_type),
            joinedload(Die.files),
            joinedload(Die.components).joinedload(DieComponent.component_type),
            joinedload(Die.components).joinedload(DieComponent.stock_item),
        )
        .get(die_id)
    )

    die_dict = DieRead.model_validate(die).model_dump()
    die_dict["die_type_ref"] = DieTypeRef.model_validate(die.die_type) if die.die_type else None
    return DieRead.model_validate(die_dict)

@router.delete("/{die_id}/files/{file_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_die_file(
    die_id: int,
    file_id: int,
    db: Session = Depends(get_db),
):
    die = db.query(Die).get(die_id)
    if not die:
        raise HTTPException(status_code=404, detail="Die not found")

    # Burada Die.files ilişkisi üzerinden bulmaya çalışıyoruz.
    # Model isimleri sende "File" veya "StoredFile" olabilir.
    # Die.files relationship'inin target modelini import etmene gerek kalmadan query yazabiliriz:
    file_obj = None
    for f in die.files or []:
        if f.id == file_id:
            file_obj = f
            break

    if not file_obj:
        raise HTTPException(status_code=404, detail="File not found for this die")

    try:
        # Eğer file_storage servisinde delete helper varsa onu kullan (tercih)
        # yoksa db.delete(file_obj) yeterli (diskten silme işi servis içinde olabilir)
        db.delete(file_obj)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Delete failed: {e}")

    return


@router.delete("/{die_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_die(
    die_id: int,
    db: Session = Depends(get_db),
):
    """
    Hard delete a die and all its dependencies.
    
    Business Rule: Can only delete if ALL production orders are in 'Waiting' status.
    Delete order: production_orders → die_files → die_components → die
    """
    try:
        # Lock the die row (FOR UPDATE to prevent race conditions)
        die = db.query(Die).filter(Die.id == die_id).with_for_update().first()
        
        if not die:
            raise HTTPException(status_code=404, detail="Die not found")
        
        # Lock and check production orders
        production_orders = (
            db.query(ProductionOrder)
            .filter(ProductionOrder.die_id == die_id)
            .with_for_update()
            .all()
        )
        
        # Check if any production order is NOT in 'Waiting' status
        for po in production_orders:
            if po.status != OrderStatus.Waiting:
                db.rollback()
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": {
                            "code": "APPROVED_PO_EXISTS",
                            "message": "Cannot delete die: approved production orders exist"
                        }
                    }
                )
        
        # Delete in order: production orders → files → components → die
        
        # 1. Delete production orders (and cascade to work orders if configured)
        for po in production_orders:
            db.delete(po)
        
        # 2. Delete die files
        from ..models import File
        files = db.query(File).filter(
            File.entity_type == "die",
            File.entity_id == die_id
        ).all()
        for file_obj in files:
            db.delete(file_obj)
        
        # 3. Delete die components
        components = db.query(DieComponent).filter(DieComponent.die_id == die_id).all()
        for comp in components:
            db.delete(comp)
        
        # 4. Delete die itself
        db.delete(die)
        
        # Commit transaction
        db.commit()
        
        return
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Delete failed: {e}")
