# app/schemas/inventory.py
"""
Pydantic schemas for the unified inventory system.

Covers:
- Master data (ItemCategory, MaterialGrade, Location)
- Lot (traceability)
- StockItem (unified stock entity)
- StockTransaction (ledger)
- ProcessBatch (heat treatment / batch ops)
- CutSteel / GenerateWIP (deduction & generation pattern)
- CompleteBatch (heat treatment completion)
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# =========================
# MASTER DATA SCHEMAS
# =========================

class ItemCategoryCreate(BaseModel):
    name: str
    base_uom: str
    is_cuttable: bool = False

class ItemCategoryRead(BaseModel):
    id: int
    name: str
    base_uom: str
    is_cuttable: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ItemCategoryUpdate(BaseModel):
    name: Optional[str] = None
    base_uom: Optional[str] = None
    is_cuttable: Optional[bool] = None


class MaterialGradeCreate(BaseModel):
    name: str
    composition: Optional[dict] = None   # {"C": 0.40, "Cr": 5.20, ...}

class MaterialGradeRead(BaseModel):
    id: int
    name: str
    composition: Optional[dict] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class MaterialGradeUpdate(BaseModel):
    name: Optional[str] = None
    composition: Optional[dict] = None


class LocationCreate(BaseModel):
    name: str
    location_type: str                   # "WAREHOUSE" or "WORK_CENTER"
    description: Optional[str] = None
    work_center_id: Optional[int] = None

class LocationRead(BaseModel):
    id: int
    name: str
    location_type: str
    description: Optional[str] = None
    work_center_id: Optional[int] = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class LocationUpdate(BaseModel):
    name: Optional[str] = None
    location_type: Optional[str] = None
    description: Optional[str] = None
    work_center_id: Optional[int] = None
    is_active: Optional[bool] = None


# =========================
# SUPPLIER SCHEMAS
# =========================

class SupplierNested(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


# =========================
# LOT SCHEMAS (REFACTORED)
# =========================

class LotCreate(BaseModel):
    lot_number: str
    certificate_number: Optional[str] = None
    receive_date: datetime
    supplier_id: Optional[int] = None
    material_grade_id: Optional[int] = None
    notes: Optional[str] = None

class LotRead(BaseModel):
    id: int
    lot_number: str
    certificate_number: Optional[str] = None
    receive_date: datetime
    supplier_id: Optional[int] = None
    material_grade_id: Optional[int] = None
    notes: Optional[str] = None
    created_at: datetime

    # Nested relationships
    supplier: Optional[SupplierNested] = None
    material_grade: Optional[MaterialGradeRead] = None

    model_config = ConfigDict(from_attributes=True)


# =========================
# STOCK ITEM SCHEMAS
# =========================

class StockItemCreate(BaseModel):
    item_type: str                         # "RAW_MATERIAL", "WIP", "FINISHED_GOOD", "CONSUMABLE"
    category_id: int
    lot_id: Optional[int] = None
    parent_id: Optional[int] = None
    location_id: Optional[int] = None
    quantity: float
    attributes: Optional[dict] = None      # {"diameter_mm": 120, "length_mm": 500, "alloy": "1.2344"}

class StockItemRead(BaseModel):
    id: int
    item_type: str
    category_id: int
    lot_id: Optional[int] = None
    parent_id: Optional[int] = None
    location_id: Optional[int] = None
    quantity: float
    attributes: Optional[dict] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    # Nested (optional, populated when needed)
    category: Optional[ItemCategoryRead] = None
    lot: Optional[LotRead] = None
    location: Optional[LocationRead] = None

    model_config = ConfigDict(from_attributes=True)


# =========================
# STOCK TRANSACTION (LEDGER) SCHEMAS
# =========================

class StockTransactionRead(BaseModel):
    id: int
    stock_item_id: int
    transaction_type: str
    quantity_change: float
    quantity_after: float
    work_order_id: Optional[int] = None
    process_batch_id: Optional[int] = None
    reference_item_id: Optional[int] = None
    notes: Optional[str] = None
    meta_data: Optional[dict] = None
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)


# =========================
# PROCESS BATCH SCHEMAS
# =========================

class ProcessBatchCreate(BaseModel):
    batch_number: str
    operation_type: str                    # "HEAT_TREATMENT", "COATING", etc.
    process_parameters: Optional[dict] = None
    stock_item_ids: list[int] = []         # Items to link to this batch
    notes: Optional[str] = None

class ProcessBatchRead(BaseModel):
    id: int
    batch_number: str
    operation_type: str
    status: str
    process_parameters: Optional[dict] = None
    result_attributes: Optional[dict] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# =========================
# CUT STEEL / GENERATE WIP — Deduction & Generation Pattern
# =========================

class CutSteelRequest(BaseModel):
    """Request to cut a piece from a raw material stock item (or existing WIP).
    
    The parent stock item's quantity is reduced by cut_quantity,
    and a new WIP child item is generated with the given attributes.
    """
    parent_stock_item_id: int = Field(
        ..., description="ID of the source StockItem to cut from"
    )
    cut_quantity: float = Field(
        ..., gt=0, description="Amount to cut, in the parent's UOM (e.g., mm for length)"
    )
    child_attributes: dict = Field(
        default_factory=dict,
        description="Attributes for the new WIP item, e.g. {'diameter_mm': 120, 'length_mm': 30}",
    )
    work_order_id: Optional[int] = Field(
        None, description="Optional work order this cut is for"
    )
    location_id: Optional[int] = Field(
        None, description="Where the new WIP piece goes (Location.id). Defaults to parent's location."
    )
    notes: Optional[str] = None

class CutSteelResponse(BaseModel):
    """Response from a cut operation: updated parent, new child, and ledger entries."""
    parent: StockItemRead
    child: StockItemRead
    transactions: list[StockTransactionRead]


# =========================
# COMPLETE BATCH — Heat Treatment Completion
# =========================

class CompleteBatchRequest(BaseModel):
    """Complete a process batch and apply result attributes to all linked items.
    
    result_attributes are MERGED (dict update) into each linked StockItem's
    attributes JSONB. Existing attributes are preserved; new ones are added/overwritten.
    """
    process_batch_id: int
    result_attributes: dict = Field(
        ..., description="Attributes to merge into all linked items, e.g. {'hardness_HRC': 52}"
    )
    end_time: Optional[datetime] = Field(
        None, description="Batch end time. Defaults to now if not provided."
    )
    notes: Optional[str] = None

class CompleteBatchResponse(BaseModel):
    """Response from completing a batch: updated batch, affected items, and ledger entries."""
    batch: ProcessBatchRead
    updated_items: list[StockItemRead]
    transactions: list[StockTransactionRead]
