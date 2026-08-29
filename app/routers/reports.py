# app/routers/reports.py
from datetime import datetime, date, time, timezone
from typing import List, Optional, Dict
from pydantic import BaseModel, ConfigDict
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import DomainActionLog, WorkCenter, WorkOrderOperation

router = APIRouter(prefix="/reports", tags=["Reports"])

class OperationInterval(BaseModel):
    operation_id: int
    operation_name: str
    work_order_number: Optional[str] = None
    status: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_minutes: float = 0.0

    model_config = ConfigDict(from_attributes=True)

class WorkCenterDailyStats(BaseModel):
    work_center_id: int
    work_center_name: str
    operating_time_minutes: float
    downtime_minutes: float
    intervals: List[OperationInterval]

    model_config = ConfigDict(from_attributes=True)

@router.get("/work-centers/daily-stats", response_model=List[WorkCenterDailyStats])
def get_work_center_daily_stats(
    target_date: date = Query(..., description="Target date for the report"),
    db: Session = Depends(get_db)
):
    """
    Returns operating time vs downtime and detailed fragmented intervals 
    for each work center for a specific date.
    """
    start_of_day = datetime.combine(target_date, time.min).replace(tzinfo=timezone.utc)
    end_of_day = datetime.combine(target_date, time.max).replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    
    if target_date == now.date():
        total_day_minutes = (now - start_of_day).total_seconds() / 60.0
        if total_day_minutes < 0:
             total_day_minutes = 0
    elif target_date < now.date():
        total_day_minutes = 24 * 60.0
    else:
        total_day_minutes = 0

    work_centers = db.query(WorkCenter).all()
    wc_dict: Dict[int, WorkCenterDailyStats] = {}
    
    for wc in work_centers:
        wc_dict[wc.id] = WorkCenterDailyStats(
            work_center_id=wc.id,
            work_center_name=wc.name,
            operating_time_minutes=0,
            downtime_minutes=0,
            intervals=[]
        )
    
    active_operations = (
        db.query(WorkOrderOperation)
        .filter(
            WorkOrderOperation.started_at != None,
            WorkOrderOperation.started_at <= end_of_day
        )
        .all()
    )
    
    relevant_operations = [
        op for op in active_operations
        if op.completed_at is None or op.completed_at >= start_of_day
    ]
    
    for op in relevant_operations:
        op_logs = (
            db.query(DomainActionLog)
            .filter(
                DomainActionLog.entity_type == "work_order_operation",
                DomainActionLog.entity_id == op.id,
                DomainActionLog.created_at <= end_of_day
            )
            .order_by(DomainActionLog.created_at)
            .all()
        )
        
        current_interval_start = None
        wc_id = None
        
        for log in op_logs:
            if log.meta_data and isinstance(log.meta_data, dict):
                wc_id_val = log.meta_data.get("work_center_id")
                if wc_id_val:
                    wc_id = int(wc_id_val)
                    
            if not wc_id and op.work_center_id:
                wc_id = op.work_center_id
                
            if log.action_type in ("OPERATION_START", "OPERATION_RESUME", "OPERATION_BATCH_START"):
                if not current_interval_start:
                    current_interval_start = log.created_at
            elif log.action_type in ("OPERATION_PAUSED", "OPERATION_COMPLETED", "OPERATION_CANCELLED"):
                if current_interval_start:
                    interval_start = max(current_interval_start, start_of_day)
                    interval_end = min(log.created_at, end_of_day)
                    
                    if interval_start < interval_end and wc_id and wc_id in wc_dict:
                        duration = (interval_end - interval_start).total_seconds() / 60.0
                        wo_num = op.work_order.order_number if op.work_order else None
                        
                        wc_dict[wc_id].intervals.append(
                            OperationInterval(
                                operation_id=op.id,
                                operation_name=op.operation_name,
                                work_order_number=wo_num,
                                status=log.action_type.replace("OPERATION_", ""),
                                start_time=interval_start,
                                end_time=interval_end,
                                duration_minutes=duration
                            )
                        )
                        wc_dict[wc_id].operating_time_minutes += duration
                    current_interval_start = None
        
        if current_interval_start:
            interval_start = max(current_interval_start, start_of_day)
            actual_end = min(now, end_of_day)
            interval_end = max(interval_start, actual_end)
            
            if interval_start < interval_end and wc_id and wc_id in wc_dict:
                duration = (interval_end - interval_start).total_seconds() / 60.0
                wo_num = op.work_order.order_number if op.work_order else None
                
                wc_dict[wc_id].intervals.append(
                    OperationInterval(
                        operation_id=op.id,
                        operation_name=op.operation_name,
                        work_order_number=wo_num,
                        status="ONGOING",
                        start_time=interval_start,
                        end_time=interval_end,
                        duration_minutes=duration
                    )
                )
                wc_dict[wc_id].operating_time_minutes += duration

    for stats in wc_dict.values():
        stats.downtime_minutes = max(0, total_day_minutes - stats.operating_time_minutes)

    return list(wc_dict.values())
