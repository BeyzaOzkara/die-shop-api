# app/routers/reports.py
from datetime import datetime, date, time, timezone
from typing import List, Optional, Dict
from pydantic import BaseModel, ConfigDict
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import DomainActionLog, WorkCenter, WorkOrderOperation, Operator

router = APIRouter(prefix="/reports", tags=["Reports"])

class OperationInterval(BaseModel):
    operation_id: int
    operation_name: str
    work_order_number: Optional[str] = None
    status: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_minutes: float = 0.0
    operator_name: Optional[str] = None
    total_operation_duration_minutes: float = 0.0
    daily_breakdown: Optional[Dict[str, float]] = None

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
    start_time: datetime = Query(..., description="Start time for the report"),
    end_time: datetime = Query(..., description="End time for the report"),
    db: Session = Depends(get_db)
):
    """
    Returns operating time vs downtime and detailed fragmented intervals 
    for each work center for a specific period.
    """
    from datetime import timezone, timedelta
    local_tz = timezone(timedelta(hours=3))
    
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=local_tz)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=local_tz)
        
    start_of_day = start_time
    end_of_day = end_time
    now = datetime.now(local_tz)
    
    total_period_minutes = max(0, (end_of_day - start_of_day).total_seconds() / 60.0)
    if end_of_day > now:
        if start_of_day > now:
            total_day_minutes = 0
        else:
            total_day_minutes = max(0, (now - start_of_day).total_seconds() / 60.0)
    else:
        total_day_minutes = total_period_minutes

    work_centers = db.query(WorkCenter).all()
    operators = db.query(Operator).all()
    operator_dict = {op.id: op.name for op in operators}
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
        # Fetch all logs up to end_of_day to compute total & daily breakdown
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
        current_interval_operator = None
        wc_id = None
        total_op_duration = 0.0
        daily_breakdown: Dict[str, float] = {}
        today_intervals_data = []
        
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
                    if log.actor_type == "operator" and log.actor_id:
                        current_interval_operator = operator_dict.get(log.actor_id)
                    else:
                        current_interval_operator = op.operator_name
            elif log.action_type in ("OPERATION_PAUSED", "OPERATION_COMPLETED", "OPERATION_COMPLETE", "OPERATION_CANCELLED"):
                if current_interval_start:
                    full_interval_duration = (log.created_at - current_interval_start).total_seconds() / 60.0
                    total_op_duration += max(0, full_interval_duration)
                    
                    day_str = current_interval_start.date().isoformat()
                    daily_breakdown[day_str] = daily_breakdown.get(day_str, 0.0) + max(0, full_interval_duration)
                    
                    interval_start = max(current_interval_start, start_of_day)
                    interval_end = min(log.created_at, end_of_day)
                    
                    if interval_start < interval_end and wc_id:
                        today_duration = (interval_end - interval_start).total_seconds() / 60.0
                        wo_num = op.work_order.order_number if op.work_order else None
                        
                        today_intervals_data.append({
                            "wc_id": wc_id,
                            "operation_id": op.id,
                            "operation_name": op.operation_name,
                            "work_order_number": wo_num,
                            "status": log.action_type.replace("OPERATION_", ""),
                            "start_time": interval_start,
                            "end_time": interval_end,
                            "duration_minutes": today_duration,
                            "operator_name": current_interval_operator
                        })
                        
                    current_interval_start = None
                    current_interval_operator = None
        
        if current_interval_start:
            interval_start = max(current_interval_start, start_of_day)
            
            if op.completed_at:
                comp_at = op.completed_at.replace(tzinfo=timezone.utc) if op.completed_at.tzinfo is None else op.completed_at
                actual_end = min(comp_at, end_of_day)
                status_to_report = "COMPLETED"
                duration = max(0, (comp_at - current_interval_start).total_seconds() / 60.0)
            else:
                actual_end = min(now, end_of_day)
                status_to_report = "ONGOING"
                duration = max(0, (now - current_interval_start).total_seconds() / 60.0)
                
            total_op_duration += duration
            day_str = current_interval_start.date().isoformat()
            daily_breakdown[day_str] = daily_breakdown.get(day_str, 0.0) + duration
                
            interval_end = max(interval_start, actual_end)
            
            if interval_start < interval_end and wc_id:
                today_duration = (interval_end - interval_start).total_seconds() / 60.0
                wo_num = op.work_order.order_number if op.work_order else None
                
                today_intervals_data.append({
                    "wc_id": wc_id,
                    "operation_id": op.id,
                    "operation_name": op.operation_name,
                    "work_order_number": wo_num,
                    "status": status_to_report,
                    "start_time": interval_start,
                    "end_time": interval_end if status_to_report == "COMPLETED" else None,
                    "duration_minutes": today_duration,
                    "operator_name": current_interval_operator
                })
        
        for data in today_intervals_data:
            w_id = data["wc_id"]
            if w_id in wc_dict:
                wc_dict[w_id].intervals.append(
                    OperationInterval(
                        operation_id=data["operation_id"],
                        operation_name=data["operation_name"],
                        work_order_number=data["work_order_number"],
                        status=data["status"],
                        start_time=data["start_time"],
                        end_time=data["end_time"],
                        duration_minutes=data["duration_minutes"],
                        operator_name=data["operator_name"],
                        total_operation_duration_minutes=total_op_duration,
                        daily_breakdown=daily_breakdown
                    )
                )
                wc_dict[w_id].operating_time_minutes += data["duration_minutes"]

    for stats in wc_dict.values():
        stats.downtime_minutes = max(0, total_day_minutes - stats.operating_time_minutes)
        stats.intervals.sort(key=lambda x: x.start_time)

    return list(wc_dict.values())
