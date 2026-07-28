from app.database import SessionLocal
from app.models import WorkOrderOperation, WorkOrder, OrderStatus, OperationStatus
from app.routers.work_orders import _auto_complete_work_order

db = SessionLocal()

wos = db.query(WorkOrder).filter(WorkOrder.status != OrderStatus.Completed).all()
for wo in wos:
    ops = db.query(WorkOrderOperation).filter(WorkOrderOperation.work_order_id == wo.id).all()
    if len(ops) > 0:
        print(f"Testing WO {wo.id} - Current status: {wo.status.value}")
        print(f"Current operations: {[op.status.value for op in ops]}")
        
        # Change all operations to Completed in memory
        for op in ops:
            op.status = OperationStatus.Completed
            
        print(f"Changed ops to Completed in memory")
        
        # Run auto complete
        _auto_complete_work_order(db, wo.id)
        
        print(f"WO Status after auto_complete: {wo.status.value}")
        break
