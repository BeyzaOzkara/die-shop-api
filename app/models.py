# backend/models.py
from datetime import datetime, timezone
import enum

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    Text,
    Date,
    DateTime,
    Enum as SAEnum,
    Numeric,
    Float,
    ForeignKey,
    Table,
    BigInteger,
    Index,
    func,
    and_,
)
from sqlalchemy.orm import relationship, foreign
from sqlalchemy.dialects.postgresql import JSONB

from .database import Base

def utc_now():
    return datetime.now(timezone.utc)


# =========================
# ENUM'lar (TypeScript ile uyumlu)
# =========================

class OrderStatus(str, enum.Enum):
    Waiting = "Waiting"
    InProgress = "InProgress"
    Completed = "Completed"
    Cancelled = "Cancelled"

class WorkCenterStatus(str, enum.Enum):
    Available = "Available"
    Busy = "Busy"
    UnderMaintenance = "UnderMaintenance"

class OperationStatus(str, enum.Enum):
    Waiting = "Waiting"
    InProgress = "InProgress"
    Completed = "Completed"
    Paused = "Paused"
    Cancelled = "Cancelled"

class DieStatus(str, enum.Enum):
    Draft = "Draft"
    Waiting = "Waiting"
    Ready = "Ready"
    InProduction = "InProduction"
    Completed = "Completed"

class OperatorRole(str, enum.Enum):
    Operator = "Operator"
    QualityControl = "QualityControl" # operasyon sonunda ret veirse work order opersayon sırasını bozup başka yere gönderebilir
    Supervisor = "Supervisor"
    Manager = "Manager"
    
class ExecutionMode(str, enum.Enum):
    """Whether operation type runs on single component or batch of components."""
    Single = "Single"     # One component at a time
    Batch = "Batch"       # Multiple components together


# ----- NEW ENUMS (Inventory Refactoring) -----

class ItemType(str, enum.Enum):
    """Type classification for unified StockItem."""
    RAW_MATERIAL = "RAW_MATERIAL"
    WIP = "WIP"
    FINISHED_GOOD = "FINISHED_GOOD"
    CONSUMABLE = "CONSUMABLE"

class TransactionType(str, enum.Enum):
    """All possible inventory ledger transaction types."""
    RECEIVE = "RECEIVE"                   # Initial stock receipt
    PARTIAL_CONSUME = "PARTIAL_CONSUME"   # Deduction from parent (cutting)
    WIP_CREATED = "WIP_CREATED"           # New WIP child generated
    LOCATION_MOVE = "LOCATION_MOVE"       # Physical relocation
    SCRAP = "SCRAP"                       # Write-off / waste
    ADJUSTMENT = "ADJUSTMENT"             # Manual correction
    BATCH_PROCESS = "BATCH_PROCESS"       # Heat treatment / batch op
    FINISHED = "FINISHED"                 # WIP → Finished Good

class LocationType(str, enum.Enum):
    """Type of physical location."""
    WAREHOUSE = "WAREHOUSE"
    WORK_CENTER = "WORK_CENTER"

class BatchStatus(str, enum.Enum):
    """Status of a process batch (heat treatment, coating, etc.)."""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# =========================
# ASSOCIATION TABLES (M2M)
# =========================

operator_work_center = Table(
    "operator_work_center",
    Base.metadata,
    Column("operator_id", Integer, ForeignKey("operator.id"), primary_key=True),
    Column("work_center_id", Integer, ForeignKey("work_center.id"), primary_key=True),
)

work_center_operation_type = Table(
    "work_center_operation_type",
    Base.metadata,
    Column("work_center_id", Integer, ForeignKey("work_center.id"), primary_key=True),
    Column("operation_type_id", Integer, ForeignKey("operation_type.id"), primary_key=True),
)

# ProcessBatch ↔ StockItem M2M
batch_stock_item_link = Table(
    "batch_stock_item_link",
    Base.metadata,
    Column("process_batch_id", Integer, ForeignKey("process_batch.id"), primary_key=True),
    Column("stock_item_id", Integer, ForeignKey("stock_item.id"), primary_key=True),
)


# =========================
# MASTER DATA
# =========================

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    username = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    surname = Column(String(100), nullable=False)

    email = Column(String(255), index=True, nullable=True)
    password_hash = Column(String(255), nullable=False)

    is_active = Column(Boolean, nullable=False, default=True)
    is_admin = Column(Boolean, nullable=False, default=False) # böyle mi olmalı yoksa role mu?

    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

class File(Base):
    __tablename__ = "files"

    id = Column(Integer, primary_key=True, index=True)
    # Hangi entity'ye bağlı?
    entity_type = Column(String, nullable=False)  # "die", "production_order", "operation" vs.
    entity_id = Column(Integer, nullable=False)

    original_name = Column(String, nullable=False)
    storage_path = Column(String, nullable=False, unique=True)  # "die/12/xxx.dxf"
    mime_type = Column(String, nullable=True)
    size_bytes = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# =========================
# LOCATION (NEW)
# =========================

class Location(Base):
    """Physical location: warehouse, work center area, storage zone."""
    __tablename__ = "location"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    location_type = Column(
        SAEnum(LocationType, name="location_type", native_enum=True),
        nullable=False,
    )
    description = Column(Text, nullable=True)
    # Optional FK to link a WORK_CENTER location back to the actual WorkCenter record
    work_center_id = Column(Integer, ForeignKey("work_center.id"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    work_center = relationship("WorkCenter", backref="location_record")
    stock_items = relationship("StockItem", back_populates="location")


# =========================
# ITEM CATEGORY & MATERIAL GRADE (NEW)
# =========================

class ItemCategory(Base):
    """Defines a class of items and their base unit of measure."""
    __tablename__ = "item_category"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)   # "Round Bar", "Flat Plate", "Bolt", "Coolant"
    base_uom = Column(String(20), nullable=False)        # "mm", "pcs", "liters", "kg"
    is_cuttable = Column(Boolean, nullable=False, default=False)
    attributes_schema = Column(JSONB, nullable=True, default=list)
    tracking_schema = Column(JSONB, nullable=True, default=list)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    stock_items = relationship("StockItem", back_populates="category")

class MaterialProfile(Base):
    """Generic material specification — category-scoped catalog entry.

    Stores invariant material properties (e.g. diameter + alloy for steel,
    thread_size for bolts) as JSONB attributes whose shape is defined by
    the related ItemCategory.attributes_schema.

    Examples:
        Round Bar: {"diameter_mm": 120, "alloy": "2344"} → display "Ø120 - 2344"
        Bolt:      {"thread_size": "M12", "length_mm": 50} → display "M12 x 50"
    """
    __tablename__ = "material_profile"

    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("item_category.id"), nullable=False)
    attributes = Column(JSONB, nullable=False, default=dict)  # invariant properties
    display_name = Column(String, nullable=False)              # human-readable label
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    # Relationships
    category = relationship("ItemCategory")
    lots = relationship("Lot", back_populates="material_profile")
    die_components = relationship("DieComponent", back_populates="material_profile")


# =========================
# WORK CENTERS & OPERATION TYPES
# =========================

class DieType(Base):
    __tablename__ = "die_type"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    die_type_components = relationship("DieTypeComponent", back_populates="die_type")
    dies = relationship("Die", back_populates="die_type")

class OperationType(Base):
    __tablename__ = "operation_type"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, nullable=False)   # "GRINDING"
    name = Column(String, nullable=False)               # "Taşlama"
    description = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)
    is_cutting = Column(Boolean, nullable=False, default=False)
    execution_mode = Column(
        SAEnum(ExecutionMode, name="execution_mode", native_enum=True),
        nullable=False,
        default=ExecutionMode.Single,
    )
    created_at = Column(DateTime(timezone=True), default=utc_now)

    work_centers = relationship(
        "WorkCenter",
        secondary=work_center_operation_type,
        back_populates="operation_types",
    )

class WorkCenter(Base):
    __tablename__ = "work_center"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    
    status = Column(SAEnum(WorkCenterStatus), nullable=False, default=WorkCenterStatus.Available)
    capacity_per_hour = Column(Integer)
    setup_time_minutes = Column(Integer)
    cost_per_hour = Column(Numeric(12, 2))
    created_at = Column(DateTime(timezone=True), default=utc_now)

    # BOM'da sadece "önerilen" WC tutuluyor
    preferred_component_boms = relationship("ComponentBOM", back_populates="preferred_work_center")
    work_order_operations = relationship("WorkOrderOperation", back_populates="work_center")

    operators = relationship(
        "Operator",
        secondary=operator_work_center,
        back_populates="work_centers",
    )

    operation_types = relationship(
        "OperationType",
        secondary=work_center_operation_type,
        back_populates="work_centers",
    )

class ComponentType(Base):
    __tablename__ = "component_type"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now)

    die_type_components = relationship("DieTypeComponent", back_populates="component_type")
    component_boms = relationship("ComponentBOM", back_populates="component_type")
    die_components = relationship("DieComponent", back_populates="component_type")

class DieTypeComponent(Base):
    __tablename__ = "die_type_component"

    id = Column(Integer, primary_key=True, index=True)
    die_type_id = Column(Integer, ForeignKey("die_type.id"), nullable=False)
    component_type_id = Column(Integer, ForeignKey("component_type.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    die_type = relationship("DieType", back_populates="die_type_components")
    component_type = relationship("ComponentType", back_populates="die_type_components")

class ComponentBOM(Base):
    __tablename__ = "component_bom"

    id = Column(Integer, primary_key=True, index=True)
    component_type_id = Column(Integer, ForeignKey("component_type.id"), nullable=False)
    sequence_number = Column(Integer, nullable=False)

    operation_name = Column(String, nullable=False) # operastonun spesifik adı (Bakır Markalama)
    # artık operasyon tipi var, kategori gibi (El İşçiliği)
    operation_type_id = Column(Integer, ForeignKey("operation_type.id"), nullable=False)
    # opsiyonel: önerilen / default makine
    preferred_work_center_id = Column(Integer, ForeignKey("work_center.id"), nullable=True)

    estimated_duration_minutes = Column(Integer)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    component_type = relationship("ComponentType", back_populates="component_boms")
    operation_type = relationship("OperationType")
    preferred_work_center = relationship("WorkCenter", back_populates="preferred_component_boms")


# =========================
# SUPPLIER
# =========================

class Supplier(Base):
    __tablename__ = "supplier"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    tax_no = Column(String, nullable=True)
    contact_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    address = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    contact_info = Column(JSONB, nullable=True)    # NEW: extensible contact data
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    lots = relationship("Lot", back_populates="supplier")


# =========================
# LOT (TRACEABILITY - REFACTORED)
# =========================

class Lot(Base):
    """A specific delivery / heat number. Origin metadata container.
    
    Decoupled from physical stock — physical dimensions now live in StockItem.
    References a MaterialProfile for the invariant material specification.
    """
    __tablename__ = "lot"

    id = Column(Integer, primary_key=True, index=True)
    lot_number = Column(String, unique=True, nullable=False, index=True)  # Internal tracking number
    certificate_number = Column(String, nullable=True)                     # Supplier certificate
    receive_date = Column(DateTime(timezone=True), nullable=False)

    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=True)
    material_profile_id = Column(Integer, ForeignKey("material_profile.id"), nullable=True)

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    # Relationships
    supplier = relationship("Supplier", back_populates="lots")
    material_profile = relationship("MaterialProfile", back_populates="lots")
    stock_items = relationship("StockItem", back_populates="lot")

    # File attachments (certificates) — polymorphic File pattern
    files = relationship(
        "File",
        primaryjoin=and_(
            File.entity_type == "lot",
            foreign(File.entity_id) == id,
        ),
        viewonly=True,
        lazy="selectin",
        order_by="File.created_at.asc()",
    )


# =========================
# THE UNIFIED STOCK ENTITY (NEW)
# =========================

class StockItem(Base):
    """Unified physical stock entity: raw materials, WIP, finished goods, consumables.
    
    - quantity: generic float, interpreted via category.base_uom
    - attributes: JSONB for dynamic traits (diameter_mm, length_mm, hardness_HRC, thread_size, etc.)
    - parent_id: self-referential FK for WIP lineage (cut piece → parent block)
    """
    __tablename__ = "stock_item"

    id = Column(Integer, primary_key=True, index=True)

    item_type = Column(
        SAEnum(ItemType, name="item_type", native_enum=True),
        nullable=False,
        index=True,
    )
    category_id = Column(Integer, ForeignKey("item_category.id"), nullable=False)
    lot_id = Column(Integer, ForeignKey("lot.id"), nullable=True)

    # Self-referential: for WIP lineage (cut piece → parent block)
    parent_id = Column(Integer, ForeignKey("stock_item.id"), nullable=True, index=True)

    # Location: FK to the new Location table
    location_id = Column(Integer, ForeignKey("location.id"), nullable=True)

    # Generic quantity — interpreted via category.base_uom
    quantity = Column(Numeric(14, 4), nullable=False, default=0)

    # Dynamic attributes: diameter_mm, length_mm, hardness_HRC, thread_size, color, etc.
    attributes = Column(JSONB, nullable=True, default=dict)

    is_active = Column(Boolean, nullable=False, default=True)  # soft-delete / fully consumed flag
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Relationships
    category = relationship("ItemCategory", back_populates="stock_items")
    lot = relationship("Lot", back_populates="stock_items")
    parent = relationship("StockItem", remote_side="StockItem.id", backref="children")
    location = relationship("Location", back_populates="stock_items")
    transactions = relationship("StockTransaction", back_populates="stock_item", foreign_keys="StockTransaction.stock_item_id")
    die_components = relationship("DieComponent", back_populates="stock_item")

    process_batches = relationship(
        "ProcessBatch",
        secondary=batch_stock_item_link,
        back_populates="stock_items",
    )

    __table_args__ = (
        Index("ix_stock_item_lot_id", "lot_id"),
        Index("ix_stock_item_category_id", "category_id"),
        Index("ix_stock_item_type_active", "item_type", "is_active"),
    )


# =========================
# DIE & COMPONENTS
# =========================

class Die(Base):
    __tablename__ = "die"

    id = Column(Integer, primary_key=True, index=True)
    die_number = Column(String, nullable=False, unique=True)
    die_diameter_mm = Column(Numeric(10, 2), nullable=False)
    total_package_length_mm = Column(Numeric(10, 2), nullable=False)
    die_type_id = Column(Integer, ForeignKey("die_type.id"), nullable=False)
    status = Column(SAEnum(DieStatus), nullable=False, default=DieStatus.Draft)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now)

    profile_no = Column(String, nullable=False)
    figure_count = Column(Integer, nullable=False)
    customer_name = Column(String, nullable=False)
    press_code = Column(String, nullable=False)

    is_revisioned = Column(Boolean, nullable=False, default=False)
    expected_completion_date = Column(Date, nullable=True)  # Ön Görülen Termin
    description = Column(Text, nullable=True)  # Açıklama

    die_type = relationship("DieType", back_populates="dies", lazy="selectin")
    components = relationship("DieComponent", back_populates="die")
    production_orders = relationship("ProductionOrder", back_populates="die")
    files = relationship(
        "File",
        primaryjoin=and_(
            File.entity_type == "die",
            foreign(File.entity_id) == id,
        ),
        viewonly=True,
        lazy="selectin",
        order_by="File.created_at.asc()",
    )

    @property
    def die_type_ref(self):
        return self.die_type

class DieComponent(Base):
    __tablename__ = "die_component"

    id = Column(Integer, primary_key=True, index=True)
    die_id = Column(Integer, ForeignKey("die.id"), nullable=False)
    component_type_id = Column(Integer, ForeignKey("component_type.id"), nullable=False)
    # Design-time material specification (what the engineer needs)
    material_profile_id = Column(Integer, ForeignKey("material_profile.id"), nullable=True)
    # Runtime physical assignment (which actual stock piece is used)
    stock_item_id = Column(Integer, ForeignKey("stock_item.id"), nullable=True)
    package_length_mm = Column(Numeric(10, 2), nullable=False)
    theoretical_consumption_kg = Column(Numeric(12, 3), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    die = relationship("Die", back_populates="components")
    component_type = relationship("ComponentType", back_populates="die_components")
    material_profile = relationship("MaterialProfile", back_populates="die_components")
    stock_item = relationship("StockItem", back_populates="die_components")
    work_orders = relationship("WorkOrder", back_populates="die_component")


# =========================
# ORDERS & OPERATIONS
# =========================

class ProductionOrder(Base):
    __tablename__ = "production_order"

    id = Column(Integer, primary_key=True, index=True)
    die_id = Column(Integer, ForeignKey("die.id"), nullable=True)
    order_number = Column(String, nullable=False, unique=True)
    status = Column(SAEnum(OrderStatus), nullable=False, default=OrderStatus.Waiting)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utc_now)

    die = relationship("Die", back_populates="production_orders")
    work_orders = relationship("WorkOrder", back_populates="production_order")

class WorkOrder(Base):
    __tablename__ = "work_order"

    id = Column(Integer, primary_key=True, index=True)
    production_order_id = Column(Integer, ForeignKey("production_order.id"), nullable=True)
    die_component_id = Column(Integer, ForeignKey("die_component.id"), nullable=True)
    stock_item_id = Column(Integer, ForeignKey("stock_item.id"), nullable=True)
    
    order_number = Column(String, nullable=True, unique=True)
    pre_machining_order_number = Column(String, nullable=True, unique=True)
    
    status = Column(SAEnum(OrderStatus), nullable=False, default=OrderStatus.Waiting)
    theoretical_consumption_kg = Column(Numeric(12, 3), nullable=False)
    actual_consumption_kg = Column(Numeric(12, 3))
    
    planned_cut_length_mm = Column(Numeric(10, 2), nullable=True)
    planned_cut_weight_kg = Column(Numeric(12, 3), nullable=True)
    actual_cut_length_mm = Column(Numeric(10, 2), nullable=True)
    actual_cut_weight_kg = Column(Numeric(12, 3), nullable=True)
    
    lot_id = Column(Integer, ForeignKey("lot.id"))
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utc_now)

    @property
    def is_pre_machining(self):
        return self.pre_machining_order_number is not None

    production_order = relationship("ProductionOrder", back_populates="work_orders")
    die_component = relationship("DieComponent", back_populates="work_orders")
    stock_item = relationship("StockItem")
    lot = relationship("Lot")
    operations = relationship(
        "WorkOrderOperation",
        back_populates="work_order",
        order_by="WorkOrderOperation.sequence_number",
    )

class WorkOrderOperation(Base):
    __tablename__ = "work_order_operation"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_order.id"), nullable=False)
    sequence_number = Column(Integer, nullable=False)

    # artık string değil, normalize  (kategori gibi)
    operation_type_id = Column(Integer, ForeignKey("operation_type.id"), nullable=False)
    # atanana kadar NULL olabilir (atama nasıl olacak bilmiyorum)
    work_center_id = Column(Integer, ForeignKey("work_center.id"), nullable=True)
    # UI / snapshot için tutulabilir (operasyonun spesifik ismi)
    operation_name = Column(String, nullable=False) # nullabale true omamalı çünkü BOM'dan gelecek

    operator_name = Column(String, nullable=True)
    status = Column(
        SAEnum(OperationStatus, name="operation_status"),
        nullable=False,
        default=OperationStatus.Waiting,
    )
    estimated_duration_minutes = Column(Integer)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    meta_data = Column(JSONB, nullable=True)

    work_order = relationship("WorkOrder", back_populates="operations")
    work_center = relationship("WorkCenter", back_populates="work_order_operations")
    operation_type = relationship("OperationType")


# =========================
# STOCK TRANSACTION LEDGER (NEW - replaces StockMovement)
# =========================

class StockTransaction(Base):
    """Immutable ledger entry for every stock quantity change.
    
    Stock quantities must NEVER change without a corresponding StockTransaction.
    quantity_change is signed: positive for additions, negative for deductions.
    quantity_after is a snapshot for point-in-time audit.
    """
    __tablename__ = "stock_transaction"

    id = Column(Integer, primary_key=True, index=True)
    stock_item_id = Column(Integer, ForeignKey("stock_item.id"), nullable=False, index=True)

    transaction_type = Column(
        SAEnum(TransactionType, name="transaction_type", native_enum=True),
        nullable=False,
        index=True,
    )
    quantity_change = Column(Numeric(14, 4), nullable=False)   # negative = deduction
    quantity_after = Column(Numeric(14, 4), nullable=False)    # snapshot of qty after txn

    work_order_id = Column(Integer, ForeignKey("work_order.id"), nullable=True)
    process_batch_id = Column(Integer, ForeignKey("process_batch.id"), nullable=True)
    # Reference to a related stock item (e.g., the child WIP created from cutting)
    reference_item_id = Column(Integer, ForeignKey("stock_item.id"), nullable=True)

    notes = Column(Text, nullable=True)
    meta_data = Column(JSONB, nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    # Relationships
    stock_item = relationship("StockItem", foreign_keys=[stock_item_id], back_populates="transactions")
    work_order = relationship("WorkOrder")
    reference_item = relationship("StockItem", foreign_keys=[reference_item_id])


# =========================
# PROCESS BATCH (NEW - Heat Treatment / Batch Operations)
# =========================

class ProcessBatch(Base):
    """A batch operation (e.g., heat treatment) that processes multiple items together.
    
    Multiple StockItems are linked via the batch_stock_item_link M2M table.
    On completion, result_attributes are merged into each linked StockItem's attributes JSONB.
    """
    __tablename__ = "process_batch"

    id = Column(Integer, primary_key=True, index=True)
    batch_number = Column(String, unique=True, nullable=False, index=True)

    operation_type = Column(String, nullable=False)   # "HEAT_TREATMENT", "COATING", etc.
    status = Column(
        SAEnum(BatchStatus, name="batch_status", native_enum=True),
        nullable=False,
        default=BatchStatus.PENDING,
    )

    process_parameters = Column(JSONB, nullable=True)   # {"temperature_C": 1020, "hold_hours": 2, ...}
    result_attributes = Column(JSONB, nullable=True)    # {"hardness_HRC": 52} — applied on completion

    start_time = Column(DateTime(timezone=True), nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    # M2M to StockItem
    stock_items = relationship(
        "StockItem",
        secondary=batch_stock_item_link,
        back_populates="process_batches",
    )
    transactions = relationship("StockTransaction", backref="process_batch_ref")


# =========================
# OPERATORS
# =========================
class Operator(Base):
    __tablename__ = "operator"

    id = Column(Integer, primary_key=True, index=True)
    rfid_code = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    employee_number = Column(String)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now)

    role = Column(
        SAEnum(
            OperatorRole,
            name="operator_role",          # DB enum type adı
            native_enum=True               # Postgres için önemli
        ),
        nullable=False,
        default=OperatorRole.Operator,
    )

    work_centers = relationship(
        "WorkCenter",
        secondary=operator_work_center,
        back_populates="operators",
    )


# =========================
# DOMAIN ACTION LOGGING
# =========================

class DomainActionLog(Base):
    """Audit trail for business events (not error logging)."""
    __tablename__ = "domain_action_log"

    id = Column(Integer, primary_key=True, index=True)
    action_type = Column(String, nullable=False, index=True)  # e.g. "OPERATION_START", "OPERATION_PAUSE", "OPERATION_COMPLETE", "OPERATION_CANCEL", "OPERATION_RESUME"..
    actor_type = Column(String, nullable=False)               # "user", "operator", "system"
    actor_id = Column(Integer, nullable=True)                 # FK optional for system actions, if user fk user.id, if operator fk operator.id
    entity_type = Column(String, nullable=False, index=True)  # entity table name
    entity_id = Column(Integer, nullable=False)
    reason = Column(String, nullable=True)                    # reason code for stops
    notes = Column(Text, nullable=True)
    before_snapshot = Column(JSONB, nullable=True)             # JSONB
    after_snapshot = Column(JSONB, nullable=True)              # JSONB 
    meta_data = Column(JSONB, nullable=True)                   # JSONB for extra data
    created_at = Column(DateTime(timezone=True), default=utc_now)
