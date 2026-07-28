from app.database import SessionLocal
from app.models import StockItem, ItemType, WorkOrder
import json

db = SessionLocal()

wips = db.query(StockItem).filter(StockItem.item_type == ItemType.WIP).all()
updated_count = 0

for wip in wips:
    # Find work order
    wo = db.query(WorkOrder).filter(WorkOrder.stock_item_id == wip.id).first()
    if wo:
        attrs = dict(wip.attributes) if wip.attributes else {}
        modified = False
        
        if wo.is_pre_machining and "Sipariş Türü" not in attrs:
            attrs["Sipariş Türü"] = "Ön İşleme"
            modified = True
            
        elif wo.production_order and wo.production_order.die:
            if "Kalıp" not in attrs:
                attrs["Kalıp"] = wo.production_order.die.die_number
                modified = True
            if wo.die_component and wo.die_component.component_type and "Bileşen" not in attrs:
                attrs["Bileşen"] = wo.die_component.component_type.name
                modified = True
                
        if modified:
            wip.attributes = attrs
            updated_count += 1

db.commit()
print(f"Updated {updated_count} WIP items")
