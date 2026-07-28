import sys
import re

with open('app/routers/work_orders.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update LotForSawRead definition
lot_schema_old = """class LotForSawRead(BaseModel):
    id: int
    certificate_number: str
    supplier: Optional[str] = None
    length_mm: int
    gross_weight_kg: float
    remaining_kg: float
    received_date: datetime
    
    # ✅ yeni (opsiyonel ama öneririm)
    stock_item_id: int
    alloy: Optional[str] = None
    diameter_mm: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)"""

lot_schema_new = """class LotForSawRead(BaseModel):
    id: int
    certificate_number: Optional[str] = None
    supplier: Optional[str] = None
    length_mm: Optional[int] = None
    gross_weight_kg: Optional[float] = None
    remaining_kg: float
    received_date: Optional[datetime] = None
    stock_item_id: int
    alloy: Optional[str] = None
    diameter_mm: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)"""

content = content.replace(lot_schema_old, lot_schema_new)

# 2. Update list_available_lots_for_operation
avail_old_pattern = re.compile(r'@ops_router\.get\("/\{operation_id\}/available-lots".*?return out', re.DOTALL)

avail_new = """@ops_router.get("/{operation_id}/available-lots", response_model=List[LotForSawRead])
def list_available_lots_for_operation(operation_id: int, db: Session = Depends(get_db)):
    op = (
        db.query(WorkOrderOperation)
        .options(
            joinedload(WorkOrderOperation.work_order)
                .joinedload(WorkOrder.die_component)
                .joinedload(DieComponent.stock_item)
        )
        .get(operation_id)
    )
    if not op or not op.work_order or not op.work_order.die_component or not op.work_order.die_component.stock_item:
        return []

    component_stock = op.work_order.die_component.stock_item
    req_diameter = component_stock.attributes.get("diameter_mm") if component_stock.attributes else None
    req_alloy = component_stock.attributes.get("alloy") if component_stock.attributes else None

    from ..models import ItemType
    items = db.query(StockItem).options(
        joinedload(StockItem.lot).joinedload(Lot.supplier),
        joinedload(StockItem.lot).joinedload(Lot.material_grade)
    ).filter(
        StockItem.item_type == ItemType.RAW_MATERIAL,
        StockItem.is_active == True,
        StockItem.quantity > 0
    ).all()

    out = []
    for item in items:
        dia = item.attributes.get("diameter_mm") if item.attributes else None
        if req_diameter and dia and int(dia) < int(req_diameter):
            continue
            
        alloy = item.attributes.get("alloy") if item.attributes else None
        if not alloy and item.lot and item.lot.material_grade:
            alloy = item.lot.material_grade.name
            
        if req_alloy and alloy != req_alloy:
            continue
            
        lot = item.lot
        out.append(LotForSawRead(
            id=item.id,
            stock_item_id=item.id,
            certificate_number=lot.certificate_number if lot else None,
            supplier=lot.supplier.name if lot and lot.supplier else None,
            length_mm=item.attributes.get("length_mm") if item.attributes else None,
            gross_weight_kg=float(item.quantity),
            remaining_kg=float(item.quantity),
            received_date=lot.receive_date if lot else item.created_at,
            alloy=alloy,
            diameter_mm=dia,
        ))
    return out"""

content = avail_old_pattern.sub(avail_new, content)

# 3. Update complete_saw_operation
saw_old_pattern = re.compile(r'@ops_router\.post\("/\{operation_id\}/complete-saw".*?return op', re.DOTALL)

saw_new = """@ops_router.post("/{operation_id}/complete-saw", response_model=WorkOrderOperationRead)
def complete_saw_operation(operation_id: int, payload: CompleteSawRequest, db: Session = Depends(get_db)):
    op = (
        db.query(WorkOrderOperation)
        .options(
            joinedload(WorkOrderOperation.work_center),
            joinedload(WorkOrderOperation.work_order)
                .joinedload(WorkOrder.die_component)
                .joinedload(DieComponent.stock_item),
            joinedload(WorkOrderOperation.operation_type),
        )
        .get(operation_id)
    )

    if not op:
        raise HTTPException(status_code=404, detail="Work order operation not found")

    if op.work_center_id is None:
        raise HTTPException(status_code=400, detail="Work center must be assigned before completing")

    if op.status in (OperationStatus.Completed, OperationStatus.Cancelled):
        raise HTTPException(status_code=400, detail="Operation is already completed/cancelled")

    if op.operation_type.code not in ["T", "SAW", "TESTERE"]:
        raise HTTPException(status_code=400, detail=f"This endpoint is only for SAW/TESTERE operations (got {op.operation_type.code})")

    if payload.quantity_kg <= 0:
        raise HTTPException(status_code=400, detail="quantity_kg must be > 0")

    wo = op.work_order
    if not wo or not wo.die_component:
        raise HTTPException(status_code=400, detail="Work order / die component not found")

    # Use the inventory service to cut steel and generate WIP
    from ..services.inventory_service import cut_steel_generate_wip
    from ..schemas.inventory import CutSteelRequest

    cut_req = CutSteelRequest(
        parent_stock_item_id=payload.lot_id,  # payload.lot_id holds the selected StockItem.id from available-lots
        cut_quantity=payload.quantity_kg,
        child_attributes=wo.die_component.stock_item.attributes if wo.die_component.stock_item else {},
        work_order_id=wo.id,
        notes=payload.note
    )
    
    try:
        res = cut_steel_generate_wip(db, cut_req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Set WorkOrder properties
    wo.actual_consumption_kg = (float(wo.actual_consumption_kg) if wo.actual_consumption_kg else 0) + payload.quantity_kg
    if res.parent.lot_id:
        wo.lot_id = res.parent.lot_id

    # Complete operation
    op.status = OperationStatus.Completed
    op.completed_at = datetime.now(timezone.utc)

    wc = db.query(WorkCenter).get(op.work_center_id)
    if wc:
        wc.status = WorkCenterStatus.Available

    _auto_complete_work_order(db, op.work_order_id)

    db.commit()
    db.refresh(op)

    op = (
        db.query(WorkOrderOperation)
        .options(
            joinedload(WorkOrderOperation.work_center),
            joinedload(WorkOrderOperation.operation_type),
            joinedload(WorkOrderOperation.work_order)
                .joinedload(WorkOrder.die_component)
                .joinedload(DieComponent.component_type),
            joinedload(WorkOrderOperation.work_order)
                .joinedload(WorkOrder.production_order)
                .joinedload(ProductionOrder.die),
            joinedload(WorkOrderOperation.work_order)
                .joinedload(WorkOrder.production_order)
                .joinedload(ProductionOrder.die)
                .joinedload(Die.files),
        )
        .get(op.id)
    )
    return op"""

content = saw_old_pattern.sub(saw_new, content)

with open('app/routers/work_orders.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated work_orders.py with CutSteel logic")
