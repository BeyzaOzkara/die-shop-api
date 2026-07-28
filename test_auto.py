from app.database import SessionLocal
from app.models import WorkOrderOperation, WorkOrder
from app.routers.work_orders import _auto_complete_work_order
db = SessionLocal()
wo_id = 9
all_ops = db.query(WorkOrderOperation).filter(WorkOrderOperation.work_order_id == wo_id).all()
print([op.status for op in all_ops])
