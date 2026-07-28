import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import SessionLocal
from app.models import WorkOrder, WorkOrderOperation

db = SessionLocal()
wos = db.query(WorkOrder).all()
for wo in wos:
    print(f"WO {wo.id} - Status: {wo.status.value}")
    ops = db.query(WorkOrderOperation).filter(WorkOrderOperation.work_order_id == wo.id).all()
    for op in ops:
        print(f"  Op {op.id}: {op.status.value}")
