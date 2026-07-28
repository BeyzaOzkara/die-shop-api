from app.database import SessionLocal
from app.models import WorkOrderOperation, WorkOrder, OrderStatus, OperationStatus
from app.routers.work_orders import _auto_complete_work_order

db = SessionLocal()

wo = db.query(WorkOrder).filter(WorkOrder.status != OrderStatus.Completed).first()
if wo:
    # 1. Load op like complete_saw_operation does
    op = db.query(WorkOrderOperation).filter(WorkOrderOperation.work_order_id == wo.id).first()
    
    print(f"Loaded op: {op.id}, status: {op.status.value}")
    
    # 2. Simulate cut_steel_generate_wip committing
    db.commit()
    
    # 3. Change op status
    op.status = OperationStatus.Completed
    print(f"Set op {op.id} status to {op.status.value}")
    
    # 4. Check what all_ops returns inside _auto_complete_work_order
    all_ops = db.query(WorkOrderOperation).filter(WorkOrderOperation.work_order_id == wo.id).all()
    for o in all_ops:
        print(f"all_ops item {o.id}: {o.status.value}")
        
    _auto_complete_work_order(db, wo.id)
    print(f"WO Status: {wo.status.value}")
    db.rollback()
