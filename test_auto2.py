from app.database import SessionLocal
from app.models import WorkOrderOperation, WorkOrder, OrderStatus, OperationStatus
from app.routers.work_orders import _auto_complete_work_order

db = SessionLocal()

# Find a work order that is Waiting or InProgress and has 1 operation
wo = db.query(WorkOrder).filter(WorkOrder.status != OrderStatus.Completed).first()
if wo:
    print(f"Testing WO {wo.id} - Current status: {wo.status.value}")
    ops = db.query(WorkOrderOperation).filter(WorkOrderOperation.work_order_id == wo.id).all()
    print(f"Current operations: {[op.status.value for op in ops]}")
    
    # Change all operations to Completed in memory
    for op in ops:
        op.status = OperationStatus.Completed
        
    print(f"Changed ops to Completed in memory")
    
    # Run auto complete
    _auto_complete_work_order(db, wo.id)
    
    print(f"WO Status after auto_complete: {wo.status.value}")
else:
    print("No pending WorkOrders found")
