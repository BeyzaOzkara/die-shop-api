from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_
from pydantic import BaseModel

from app.database import get_db
from app.models import (
    StockItem, ItemType, WorkOrder, WorkOrderOperation,
    OperationType, LocationType, Location, TransactionType, StockTransaction, OrderStatus, OperationStatus
)

router = APIRouter(prefix="/pre-machining", tags=["pre-machining"])

# --- Schemas ---

class PlannedOperation(BaseModel):
    operation_type_id: int
    work_center_id: Optional[int] = None

class PreMachiningOrderCreate(BaseModel):
    source_type: str  # "RAW_MATERIAL" or "WIP"
    source_stock_item_id: int
    planned_cut_length_mm: Optional[float] = None
    planned_cut_weight_kg: Optional[float] = None
    planned_operations: List[PlannedOperation]

class PreMachiningShelveRequest(BaseModel):
    target_location_id: int

# --- Helper ---

def generate_pm_order_number(db: Session) -> str:
    current_year = datetime.now().year
    prefix = f"PM-{current_year}-"
    last = (
        db.query(WorkOrder.pre_machining_order_number)
        .filter(WorkOrder.pre_machining_order_number.like(f"{prefix}%"))
        .order_by(WorkOrder.pre_machining_order_number.desc())
        .first()
    )
    if last and last[0]:
        try:
            seq = int(last[0].split("-")[-1]) + 1
        except ValueError:
            seq = 1
    else:
        seq = 1
    return f"{prefix}{seq:03d}"

# --- Endpoints ---

@router.get("/raw-materials")
def list_raw_materials(db: Session = Depends(get_db)):
    """List active RAW_MATERIAL stock items."""
    return db.query(StockItem).filter(
        StockItem.item_type == ItemType.RAW_MATERIAL,
        StockItem.is_active == True,
        StockItem.quantity > 0
    ).all()

@router.get("/available-wip")
def list_available_wip(db: Session = Depends(get_db)):
    """List WIP items not assigned to any DieComponent and not in an active standalone PM order."""
    # Find active WIP
    wip_items = db.query(StockItem).filter(
        StockItem.item_type == ItemType.WIP,
        StockItem.is_active == True,
        StockItem.quantity > 0
    ).all()
    
    available = []
    for item in wip_items:
        # Check if assigned to DieComponent
        is_assigned_to_die = any(dc for dc in item.die_components)
        if is_assigned_to_die:
            continue
            
        # Check if currently in an active standalone PM order
        active_pm = db.query(WorkOrder).filter(
            WorkOrder.stock_item_id == item.id,
            WorkOrder.production_order_id == None,
            WorkOrder.die_component_id == None,
            WorkOrder.status.in_([OrderStatus.Waiting, OrderStatus.InProgress])
        ).first()
        
        if active_pm:
            continue
            
        available.append(item)
        
    return available

@router.post("/orders")
def create_pre_machining_order(req: PreMachiningOrderCreate, db: Session = Depends(get_db)):
    source_item = db.query(StockItem).filter(StockItem.id == req.source_stock_item_id).first()
    if not source_item:
        raise HTTPException(status_code=404, detail="Source stock item not found.")
        
    # Validate source type matches reality
    if req.source_type == "RAW_MATERIAL" and source_item.item_type != ItemType.RAW_MATERIAL:
        raise HTTPException(status_code=400, detail="Stock item is not a RAW_MATERIAL.")
    if req.source_type == "WIP" and source_item.item_type != ItemType.WIP:
        raise HTTPException(status_code=400, detail="Stock item is not a WIP.")
        
    from app.models import ProductionOrder
    pm_number = generate_pm_order_number(db)
    
    # Create ProductionOrder
    prod_order = ProductionOrder(
        die_id=None,
        order_number=pm_number,
        status=OrderStatus.InProgress,
        started_at=datetime.utcnow()
    )
    db.add(prod_order)
    db.flush()
    
    pm_order = WorkOrder(
        production_order_id=prod_order.id,
        die_component_id=None,
        stock_item_id=source_item.id,
        order_number=None,
        pre_machining_order_number=pm_number,
        status=OrderStatus.InProgress,
        started_at=datetime.utcnow(),
        theoretical_consumption_kg=req.planned_cut_weight_kg if req.source_type == "RAW_MATERIAL" and req.planned_cut_weight_kg is not None else 0,
        planned_cut_length_mm=req.planned_cut_length_mm if req.source_type == "RAW_MATERIAL" else None,
        planned_cut_weight_kg=req.planned_cut_weight_kg if req.source_type == "RAW_MATERIAL" else None,
    )
    db.add(pm_order)
    db.flush()
    
    for idx, pop in enumerate(req.planned_operations, start=1):
        op_type = db.query(OperationType).filter(OperationType.id == pop.operation_type_id).first()
        if not op_type:
            raise HTTPException(status_code=400, detail=f"Operation type {pop.operation_type_id} not found.")
            
        op = WorkOrderOperation(
            work_order_id=pm_order.id,
            sequence_number=idx,
            operation_type_id=op_type.id,
            work_center_id=pop.work_center_id,
            operation_name=op_type.name,
            status=OperationStatus.Waiting
        )
        db.add(op)
        
    db.commit()
    db.refresh(pm_order)
    return {"message": "Pre-machining order created", "order": pm_order}

@router.get("/orders")
def list_pre_machining_orders(db: Session = Depends(get_db)):
    return db.query(WorkOrder).outerjoin(
        StockItem, WorkOrder.stock_item_id == StockItem.id
    ).outerjoin(
        Location, StockItem.location_id == Location.id
    ).filter(
        WorkOrder.die_component_id == None,
        WorkOrder.pre_machining_order_number != None,
        ~and_(
            WorkOrder.status == OrderStatus.Completed,
            Location.location_type == LocationType.WAREHOUSE
        )
    ).order_by(WorkOrder.created_at.desc()).all()

@router.get("/wip-shelf")
def list_wip_shelf(db: Session = Depends(get_db)):
    wips = db.query(StockItem).filter(
        StockItem.item_type == ItemType.WIP,
        StockItem.is_active == True,
        StockItem.quantity > 0,
        StockItem.location_id != None
    ).all()
    
    shelved = []
    for wip in wips:
        if wip.location and wip.location.location_type == LocationType.WAREHOUSE:
            if not any(dc for dc in wip.die_components):
                shelved.append(wip)
    return shelved

@router.post("/orders/{order_id}/shelve")
def shelve_completed_pm_order(order_id: int, req: PreMachiningShelveRequest, db: Session = Depends(get_db)):
    pm_order = db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
    if not pm_order or not pm_order.is_pre_machining:
        raise HTTPException(status_code=404, detail="Standalone PM order not found.")
        
    if pm_order.status != OrderStatus.Completed:
        raise HTTPException(status_code=400, detail="Order must be completed before shelving.")
        
    wip_item = db.query(StockItem).filter(StockItem.id == pm_order.stock_item_id).first()
    if not wip_item or wip_item.item_type != ItemType.WIP:
        raise HTTPException(status_code=400, detail="Target stock item is not a WIP.")
        
    from app.models import Location
    target_loc = db.query(Location).filter(Location.id == req.target_location_id, Location.location_type == LocationType.WAREHOUSE).first()
    if not target_loc:
        raise HTTPException(status_code=400, detail="Invalid WAREHOUSE location.")
        
    wip_item.location_id = target_loc.id
    
    txn = StockTransaction(
        stock_item_id=wip_item.id,
        transaction_type=TransactionType.LOCATION_MOVE,
        quantity_change=0,
        quantity_after=wip_item.quantity,
        notes=f"Shelved after PM order {pm_order.pre_machining_order_number}",
        work_order_id=pm_order.id
    )
    db.add(txn)

    # Complete the associated ProductionOrder
    if pm_order.production_order:
        pm_order.production_order.status = OrderStatus.Completed
        pm_order.production_order.completed_at = datetime.utcnow()
        db.add(pm_order.production_order)

    db.commit()
    
    return {"message": "WIP shelved and production order completed successfully.", "wip": wip_item}
