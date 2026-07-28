# app/services/inventory_service.py
"""
Core business logic for the unified inventory system.

Contains:
1. cut_steel_generate_wip() — Deduction & Generation pattern for cutting stock
2. complete_process_batch() — Heat treatment / batch operation completion

DESIGN RULES:
- Stock quantities NEVER change without a StockTransaction ledger entry.
- All mutations happen within a single DB transaction (commit at the end).
- JSONB attribute mutations require flag_modified() for SQLAlchemy change detection.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session, joinedload
from sqlalchemy.orm.attributes import flag_modified
from fastapi import HTTPException

from ..models import (
    StockItem,
    StockTransaction,
    ProcessBatch,
    ItemCategory,
    ItemType,
    TransactionType,
    BatchStatus,
)
from ..schemas.inventory import (
    CutSteelRequest,
    CutSteelResponse,
    CompleteBatchRequest,
    CompleteBatchResponse,
    StockItemRead,
    StockTransactionRead,
    ProcessBatchRead,
)


def _to_decimal(value: float | int | Decimal) -> Decimal:
    """Safely convert to Decimal for numeric precision."""
    return Decimal(str(value))


# ============================================================
# 1. CUT STEEL / GENERATE WIP — Deduction & Generation Pattern
# ============================================================

def cut_steel_generate_wip(
    db: Session,
    request: CutSteelRequest,
) -> CutSteelResponse:
    """
    Cut a piece from a parent stock item, generating a new WIP child.

    Flow:
    1. Validate parent exists, is active, has sufficient quantity.
    2. Validate parent's category is_cuttable.
    3. Deduct cut_quantity from parent.quantity.
    4. If parent.quantity reaches 0, mark parent.is_active = False.
    5. Create new WIP StockItem as child (inherits lot_id for traceability).
    6. Create two StockTransaction ledger entries:
       a. PARTIAL_CONSUME on parent (negative qty change)
       b. WIP_CREATED on child (positive qty change)
    7. Commit atomically.
    8. Return updated parent, new child, and both transactions.

    Args:
        db: SQLAlchemy session (caller manages session lifecycle).
        request: CutSteelRequest with parent_stock_item_id, cut_quantity, etc.

    Returns:
        CutSteelResponse with parent, child, and transactions.

    Raises:
        HTTPException 404: Parent stock item not found.
        HTTPException 400: Validation failures (not active, not cuttable, insufficient qty).
    """
    cut_qty = _to_decimal(request.cut_quantity)

    # --- 1. Load and validate parent ---
    parent = (
        db.query(StockItem)
        .options(joinedload(StockItem.category))
        .filter(StockItem.id == request.parent_stock_item_id)
        .first()
    )
    if not parent:
        raise HTTPException(
            status_code=404,
            detail=f"Parent stock item {request.parent_stock_item_id} not found.",
        )
    if not parent.is_active:
        raise HTTPException(
            status_code=400,
            detail=f"Parent stock item {parent.id} is not active (fully consumed or scrapped).",
        )

    # --- 2. Validate cuttable ---
    category: ItemCategory = parent.category
    if not category:
        raise HTTPException(
            status_code=400,
            detail=f"Parent stock item {parent.id} has no category assigned.",
        )
    if not category.is_cuttable:
        raise HTTPException(
            status_code=400,
            detail=f"Category '{category.name}' (UOM: {category.base_uom}) is not cuttable.",
        )

    # --- 3. Validate sufficient quantity ---
    parent_qty = _to_decimal(parent.quantity)
    if cut_qty > parent_qty:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Insufficient quantity: requested {cut_qty}, "
                f"but parent has {parent_qty} {category.base_uom}."
            ),
        )
    if cut_qty <= 0:
        raise HTTPException(
            status_code=400,
            detail="Cut quantity must be greater than zero.",
        )

    # --- 4. Deduct from parent ---
    parent.quantity = parent_qty - cut_qty
    if parent.quantity <= 0:
        parent.is_active = False

    # --- 5. Create child WIP item ---
    child = StockItem(
        item_type=ItemType.WIP,
        category_id=parent.category_id,
        lot_id=parent.lot_id,               # Inherit traceability chain
        parent_id=parent.id,
        location_id=request.location_id or parent.location_id,  # Default to parent's location
        quantity=cut_qty,
        attributes=request.child_attributes or {},
        is_active=True,
    )
    db.add(child)
    db.flush()  # Get child.id for transaction references

    # --- 6. Create ledger entries ---

    # 6a. Parent deduction
    txn_parent = StockTransaction(
        stock_item_id=parent.id,
        transaction_type=TransactionType.PARTIAL_CONSUME,
        quantity_change=-cut_qty,
        quantity_after=parent.quantity,
        work_order_id=request.work_order_id,
        reference_item_id=child.id,
        notes=request.notes or f"Cut {cut_qty} {category.base_uom} for WIP #{child.id}",
    )
    db.add(txn_parent)

    # 6b. Child creation
    txn_child = StockTransaction(
        stock_item_id=child.id,
        transaction_type=TransactionType.WIP_CREATED,
        quantity_change=cut_qty,
        quantity_after=child.quantity,
        work_order_id=request.work_order_id,
        reference_item_id=parent.id,
        notes=request.notes or f"Generated from parent #{parent.id}",
    )
    db.add(txn_child)

    # --- 7. Commit atomically ---
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    # --- 8. Refresh and return ---
    db.refresh(parent)
    db.refresh(child)

    return CutSteelResponse(
        parent=StockItemRead.model_validate(parent),
        child=StockItemRead.model_validate(child),
        transactions=[
            StockTransactionRead.model_validate(txn_parent),
            StockTransactionRead.model_validate(txn_child),
        ],
    )


# ============================================================
# 2. COMPLETE PROCESS BATCH — Heat Treatment / Batch Ops
# ============================================================

def complete_process_batch(
    db: Session,
    request: CompleteBatchRequest,
) -> CompleteBatchResponse:
    """
    Complete a process batch (e.g., heat treatment) and apply result attributes
    to all linked WIP items.

    Flow:
    1. Load ProcessBatch, validate it's not already completed.
    2. Load all linked StockItems via M2M.
    3. For each linked StockItem:
       a. Merge result_attributes into item.attributes (dict update — preserves existing keys).
       b. flag_modified(item, "attributes") — critical for SQLAlchemy JSONB mutation detection.
       c. Create a StockTransaction (BATCH_PROCESS, qty_change=0, attribute mutation only).
    4. Update batch: status=COMPLETED, end_time, result_attributes.
    5. Commit atomically.
    6. Return updated batch, items, and transactions.

    Args:
        db: SQLAlchemy session.
        request: CompleteBatchRequest with process_batch_id, result_attributes, etc.

    Returns:
        CompleteBatchResponse with batch, updated_items, and transactions.

    Raises:
        HTTPException 404: Batch not found.
        HTTPException 400: Batch already completed or no items linked.
    """
    # --- 1. Load and validate batch ---
    batch = (
        db.query(ProcessBatch)
        .options(joinedload(ProcessBatch.stock_items))
        .filter(ProcessBatch.id == request.process_batch_id)
        .first()
    )
    if not batch:
        raise HTTPException(
            status_code=404,
            detail=f"Process batch {request.process_batch_id} not found.",
        )
    if batch.status == BatchStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Batch '{batch.batch_number}' is already completed.",
        )
    if batch.status == BatchStatus.CANCELLED:
        raise HTTPException(
            status_code=400,
            detail=f"Batch '{batch.batch_number}' is cancelled and cannot be completed.",
        )

    # --- 2. Load linked items ---
    linked_items: list[StockItem] = batch.stock_items
    if not linked_items:
        raise HTTPException(
            status_code=400,
            detail=f"Batch '{batch.batch_number}' has no linked stock items.",
        )

    # --- 3. Apply result_attributes to each item ---
    transactions: list[StockTransaction] = []
    for item in linked_items:
        # 3a. Merge attributes (preserves existing, adds/overwrites new)
        current_attrs = dict(item.attributes or {})
        current_attrs.update(request.result_attributes)
        item.attributes = current_attrs

        # 3b. CRITICAL: Tell SQLAlchemy the JSONB column was mutated in-place
        flag_modified(item, "attributes")

        # 3c. Create ledger entry (attribute mutation, no quantity change)
        txn = StockTransaction(
            stock_item_id=item.id,
            transaction_type=TransactionType.BATCH_PROCESS,
            quantity_change=Decimal("0"),
            quantity_after=_to_decimal(item.quantity),
            process_batch_id=batch.id,
            notes=request.notes or f"Batch '{batch.batch_number}' completed — attributes updated",
            meta_data={
                "applied_attributes": request.result_attributes,
                "batch_number": batch.batch_number,
                "operation_type": batch.operation_type,
            },
        )
        db.add(txn)
        transactions.append(txn)

    # --- 4. Update batch status ---
    batch.status = BatchStatus.COMPLETED
    batch.end_time = request.end_time or datetime.now(timezone.utc)
    batch.result_attributes = request.result_attributes

    # --- 5. Commit atomically ---
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    # --- 6. Refresh and return ---
    db.refresh(batch)
    for item in linked_items:
        db.refresh(item)

    return CompleteBatchResponse(
        batch=ProcessBatchRead.model_validate(batch),
        updated_items=[StockItemRead.model_validate(item) for item in linked_items],
        transactions=[StockTransactionRead.model_validate(txn) for txn in transactions],
    )
