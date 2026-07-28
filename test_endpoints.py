import json
import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from app.main import app
from app.deps import require_admin
from app.models import ItemType

# Override admin requirement for testing
app.dependency_overrides[require_admin] = lambda: True

client = TestClient(app)

def run_tests():
    print("Starting API Endpoint Tests...")
    run_id = uuid.uuid4().hex[:6]

    # 1. Create Location
    loc_payload = {
        "name": f"Main Warehouse {run_id}",
        "location_type": "WAREHOUSE",
        "description": "Primary storage"
    }
    resp = client.post("/inventory/locations", json=loc_payload)
    assert resp.status_code == 201, f"Failed to create Location: {resp.text}"
    loc_id = resp.json()["id"]
    print(f"Created Location (ID: {loc_id})")

    # 2. Create ItemCategory
    cat_payload = {
        "name": f"Raw Steel {run_id}",
        "base_uom": "kg",
        "is_cuttable": True
    }
    resp = client.post("/inventory/categories", json=cat_payload)
    assert resp.status_code == 201, f"Failed to create Category: {resp.text}"
    cat_id = resp.json()["id"]
    print(f"Created Category (ID: {cat_id})")

    # 3. Create MaterialGrade
    grade_payload = {
        "name": f"H13 {run_id}",
        "composition": {"C": 0.40, "Cr": 5.20}
    }
    resp = client.post("/inventory/material-grades", json=grade_payload)
    assert resp.status_code == 201, f"Failed to create MaterialGrade: {resp.text}"
    grade_id = resp.json()["id"]
    print(f"Created MaterialGrade (ID: {grade_id})")

    # 4. Create Lot
    lot_data = {
        "lot_number": f"LOT-{run_id}",
        "receive_date": datetime.utcnow().isoformat(),
        "material_grade_id": grade_id
    }
    resp = client.post(
        "/inventory/lots", 
        data={"payload": json.dumps(lot_data)}
    )
    assert resp.status_code == 201, f"Failed to create Lot: {resp.text}"
    lot_id = resp.json()["id"]
    print(f"Created Lot (ID: {lot_id})")

    # 5. Create StockItem
    stock_payload = {
        "item_type": ItemType.RAW_MATERIAL.value,
        "category_id": cat_id,
        "quantity": 1000.0,
        "location_id": loc_id,
        "lot_id": lot_id,
        "attributes": {
            "diameter_mm": 50,
            "length_mm": 6000
        }
    }
    resp = client.post("/inventory/stock-items", json=stock_payload)
    assert resp.status_code == 201, f"Failed to create StockItem: {resp.text}"
    parent_stock_id = resp.json()["id"]
    print(f"Created StockItem (Parent ID: {parent_stock_id})")

    # 6. Test /inventory/cut-steel
    cut_payload = {
        "parent_stock_item_id": parent_stock_id,
        "cut_quantity": 50.0,
        "child_attributes": {
            "diameter_mm": 50,
            "length_mm": 300,
            "piece_type": "die_component"
        },
        "notes": "First cut for test"
    }
    resp = client.post("/inventory/cut-steel", json=cut_payload)
    assert resp.status_code == 200, f"Failed to cut steel: {resp.text}"
    data = resp.json()
    child_id = data["child"]["id"]
    assert data["parent"]["quantity"] == 950.0, "Parent quantity not reduced correctly"
    print(f"Cut Steel Success! Created Child WIP (ID: {child_id}), Parent remaining: 950.0 kg")

    # 7. Test ProcessBatch Creation & Completion
    batch_payload = {
        "batch_number": f"BATCH-{run_id}",
        "operation_type": "HEAT_TREATMENT",
        "stock_item_ids": [child_id],
        "process_parameters": {"temp": "1000C"}
    }
    resp = client.post("/inventory/process-batches", json=batch_payload)
    assert resp.status_code == 201, f"Failed to create ProcessBatch: {resp.text}"
    batch_id = resp.json()["id"]
    print(f"Created ProcessBatch (ID: {batch_id})")

    # Complete the batch
    complete_batch_payload = {
        "process_batch_id": batch_id,
        "result_attributes": {"hardness": "50 HRC"},
        "notes": "Passed QC"
    }
    resp = client.post("/inventory/complete-batch", json=complete_batch_payload)
    assert resp.status_code == 200, f"Failed to complete batch: {resp.text}"
    print(f"Completed ProcessBatch (ID: {batch_id})")

    print("\nALL TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_tests()
