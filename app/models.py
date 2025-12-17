# backend/models.py
from datetime import datetime, timezone
import enum

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    Text,
    DateTime,
    Enum as SAEnum,
    Numeric,
    ForeignKey,
    Table,
    BigInteger,
    func
)
from sqlalchemy.orm import relationship

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


# =========================
# OPERATOR - WORK CENTER M2M
# =========================

operator_work_center = Table(
    "operator_work_center",
    Base.metadata,
    Column("operator_id", Integer, ForeignKey("operator.id"), primary_key=True),
    Column("work_center_id", Integer, ForeignKey("work_center.id"), primary_key=True),
)


# =========================
# MASTER DATA
# =========================

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

class DieType(Base):
    __tablename__ = "die_type"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now)

    die_type_components = relationship("DieTypeComponent", back_populates="die_type")
    dies = relationship("Die", back_populates="die_type")


class WorkCenter(Base):
    __tablename__ = "work_center"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    status = Column(SAEnum(WorkCenterStatus), nullable=False, default=WorkCenterStatus.Available)
    location = Column(String)
    capacity_per_hour = Column(Integer)
    setup_time_minutes = Column(Integer)
    cost_per_hour = Column(Numeric(12, 2))
    created_at = Column(DateTime(timezone=True), default=utc_now)

    component_boms = relationship("ComponentBOM", back_populates="work_center")
    work_order_operations = relationship("WorkOrderOperation", back_populates="work_center")
    operators = relationship(
        "Operator",
        secondary=operator_work_center,
        back_populates="work_centers",
    )
    # operators = relationship("Operator", back_populates="work_center")  # NEW


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
    operation_name = Column(String, nullable=False)
    work_center_id = Column(Integer, ForeignKey("work_center.id"), nullable=False)
    estimated_duration_minutes = Column(Integer)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    component_type = relationship("ComponentType", back_populates="component_boms")
    work_center = relationship("WorkCenter", back_populates="component_boms")


# =========================
# STEEL STOCK & LOTS
# =========================

class SteelStockItem(Base):
    __tablename__ = "steel_stock_item"

    id = Column(Integer, primary_key=True, index=True)
    alloy = Column(String, nullable=False)
    diameter_mm = Column(Integer, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    lots = relationship("Lot", back_populates="stock_item")


class Lot(Base):
    __tablename__ = "lot"

    id = Column(Integer, primary_key=True, index=True)
    stock_item_id = Column(Integer, ForeignKey("steel_stock_item.id"), nullable=False)
    certificate_number = Column(String, nullable=False)
    supplier = Column(String, nullable=False)
    length_mm = Column(Integer, nullable=False)
    gross_weight_kg = Column(Numeric(12, 3), nullable=False)
    remaining_kg = Column(Numeric(12, 3), nullable=False)
    certificate_file_url = Column(Text)
    received_date = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    stock_item = relationship("SteelStockItem", back_populates="lots")
    work_orders = relationship("WorkOrder", back_populates="lot")
    stock_movements = relationship("StockMovement", back_populates="lot")


# =========================
# DIE & COMPONENTS
# =========================

class Die(Base):
    __tablename__ = "die"

    id = Column(Integer, primary_key=True, index=True)
    die_number = Column(String, nullable=False, unique=True)
    die_diameter_mm = Column(Integer, nullable=False)
    total_package_length_mm = Column(Integer, nullable=False)
    die_type_id = Column(Integer, ForeignKey("die_type.id"), nullable=False)
    status = Column(SAEnum(DieStatus), nullable=False, default=DieStatus.Draft)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now)

    die_type = relationship("DieType", lazy="selectin") #, back_populates="dies")
    components = relationship("DieComponent", back_populates="die")
    production_orders = relationship("ProductionOrder", back_populates="die")
    files = relationship("File",
        primaryjoin="and_(File.entity_type=='die', foreign(File.entity_id)==Die.id)",
        viewonly=True, lazy="selectin", order_by="File.created_at.asc()"
    )

@property
def die_type_ref(self):
    return self.die_type


class DieComponent(Base):
    __tablename__ = "die_component"

    id = Column(Integer, primary_key=True, index=True)
    die_id = Column(Integer, ForeignKey("die.id"), nullable=False)
    component_type_id = Column(Integer, ForeignKey("component_type.id"), nullable=False)
    stock_item_id = Column(Integer, ForeignKey("steel_stock_item.id"), nullable=False)
    package_length_mm = Column(Integer, nullable=False)
    theoretical_consumption_kg = Column(Numeric(12, 3), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    die = relationship("Die", back_populates="components")
    component_type = relationship("ComponentType", back_populates="die_components")
    stock_item = relationship("SteelStockItem")
    work_orders = relationship("WorkOrder", back_populates="die_component")


# =========================
# ORDERS & OPERATIONS
# =========================

class ProductionOrder(Base):
    __tablename__ = "production_order"

    id = Column(Integer, primary_key=True, index=True)
    die_id = Column(Integer, ForeignKey("die.id"), nullable=False)
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
    production_order_id = Column(Integer, ForeignKey("production_order.id"), nullable=False)
    die_component_id = Column(Integer, ForeignKey("die_component.id"), nullable=False)
    order_number = Column(String, nullable=False, unique=True)
    status = Column(SAEnum(OrderStatus), nullable=False, default=OrderStatus.Waiting)
    theoretical_consumption_kg = Column(Numeric(12, 3), nullable=False)
    actual_consumption_kg = Column(Numeric(12, 3))
    lot_id = Column(Integer, ForeignKey("lot.id"))
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utc_now)

    production_order = relationship("ProductionOrder", back_populates="work_orders")
    die_component = relationship("DieComponent", back_populates="work_orders")
    lot = relationship("Lot", back_populates="work_orders")
    operations = relationship("WorkOrderOperation", back_populates="work_order")
    stock_movements = relationship("StockMovement", back_populates="work_order")


class WorkOrderOperation(Base):
    __tablename__ = "work_order_operation"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_order.id"), nullable=False)
    sequence_number = Column(Integer, nullable=False)
    operation_name = Column(String, nullable=False)
    work_center_id = Column(Integer, ForeignKey("work_center.id"), nullable=False)
    operator_name = Column(String)
    status = Column(
        SAEnum(OperationStatus, name="operation_status"),
        nullable=False,
        default=OperationStatus.Waiting,
    )
    # status = Column(SAEnum(OperationStatus), nullable=False, default=OperationStatus.Waiting)
    estimated_duration_minutes = Column(Integer)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    work_order = relationship("WorkOrder", back_populates="operations")
    work_center = relationship("WorkCenter", back_populates="work_order_operations")


# =========================
# STOCK MOVEMENTS
# =========================

class StockMovement(Base):
    __tablename__ = "stock_movement"

    id = Column(Integer, primary_key=True, index=True)
    lot_id = Column(Integer, ForeignKey("lot.id"), nullable=False)
    work_order_id = Column(Integer, ForeignKey("work_order.id"), nullable=False)
    quantity_kg = Column(Numeric(12, 3), nullable=False)
    movement_date = Column(DateTime(timezone=True), nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    lot = relationship("Lot", back_populates="stock_movements")
    work_order = relationship("WorkOrder", back_populates="stock_movements")


# =========================
# OPERATORS
# =========================
class Operator(Base):
    __tablename__ = "operator"

    id = Column(Integer, primary_key=True, index=True)
    rfid_code = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    employee_number = Column(String)
    # sonradan silinebilir
    work_center_id = Column(Integer, ForeignKey("work_center.id"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now)

    # work_center = relationship("WorkCenter", back_populates="operators")
    work_centers = relationship(
        "WorkCenter",
        secondary=operator_work_center,
        back_populates="operators",
    )


# class FileAttachment(Base):
#     __tablename__ = "file_attachments"

#     id = Column(Integer, primary_key=True, index=True)
#     file_id = Column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
#     # Generic bağlama
#     entity_type = Column(String, nullable=False)  # örn: "die", "work_order", "operation"
#     entity_id = Column(Integer, nullable=False)   # ilgili tablodaki PK
#     # İsteğe bağlı label/tag
#     label = Column(String, nullable=True)   # "DXF", "Teknik Çizim", "Resim" gibi
#     created_at = Column(DateTime(timezone=True), server_default=func.now())