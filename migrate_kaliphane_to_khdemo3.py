"""
Migration Script: kaliphane → khdemo3
======================================
Standalone script to migrate data from the old kaliphane database
to the new khdemo3 database on the same PostgreSQL server.

Usage:
    cd die-shop-api
    .venv\Scripts\python migrate_kaliphane_to_khdemo3.py

Prerequisites:
    - Both databases must exist on 192.168.150.230:5432
    - The new khdemo3 schema must already be created (via Alembic or schema.sql)
    - The new khdemo3 tables should be EMPTY before running this script
"""

import logging
import sys
from datetime import datetime, timezone
from decimal import Decimal
import json

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

# Register psycopg2 JSON adapter so Python dicts auto-serialize to JSONB
import psycopg2.extensions
import psycopg2.extras
psycopg2.extensions.register_adapter(dict, psycopg2.extras.Json)


# ── Configure Logging ─────────────────────────────────────────────
log = logging.getLogger("migration")
log.setLevel(logging.INFO)
_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

# Force UTF-8 on stdout to handle Turkish characters + emoji on Windows
import io
_stdout_handler = logging.StreamHandler(
    io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
)
_stdout_handler.setFormatter(_formatter)
log.addHandler(_stdout_handler)

_file_handler = logging.FileHandler("migration.log", encoding="utf-8")
_file_handler.setFormatter(_formatter)
log.addHandler(_file_handler)


# ── Database Connection Strings ───────────────────────────────────
OLD_DB_URL = "postgresql+psycopg2://arslan:gqTYe5HdX0VQ@192.168.150.230:5432/kaliphane"
NEW_DB_URL = "postgresql+psycopg2://arslan:gqTYe5HdX0VQ@192.168.150.230:5432/kaliphaneNew"

old_engine = create_engine(OLD_DB_URL, echo=False)
new_engine = create_engine(NEW_DB_URL, echo=False)

OldSession = sessionmaker(bind=old_engine)
NewSession = sessionmaker(bind=new_engine)


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def fetch_all(session, query: str):
    """Fetch all rows from a DB as list of dicts."""
    result = session.execute(text(query))
    columns = result.keys()
    return [dict(zip(columns, row)) for row in result.fetchall()]


def count_rows(session, table_name: str) -> int:
    """Count rows in a table."""
    result = session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
    return result.scalar()


def log_table_start(table_name: str, old_count: int):
    log.info(f"{'='*60}")
    log.info(f"Migrating: {table_name} ({old_count} rows)")


def log_table_done(table_name: str, migrated: int):
    log.info(f"  [OK] {table_name}: {migrated} rows migrated")


def reset_sequence(new_session, table_name: str, column: str = "id"):
    """Reset PostgreSQL sequence to max(id) + 1 to avoid PK conflicts."""
    seq_name = f"{table_name}_{column}_seq"
    try:
        max_id = new_session.execute(
            text(f"SELECT COALESCE(MAX({column}), 0) FROM {table_name}")
        ).scalar()
        if max_id and max_id > 0:
            new_session.execute(
                text(f"SELECT setval('{seq_name}', {max_id}, true)")
            )
            log.info(f"  [SEQ] Sequence {seq_name} reset to {max_id}")
    except Exception as e:
        log.warning(f"  [WARN] Could not reset sequence {seq_name}: {e}")


# ═══════════════════════════════════════════════════════════════════
# PHASE 1: DIRECT COPY TABLES (identical or near-identical schema)
# ═══════════════════════════════════════════════════════════════════

def migrate_users(old_s: Session, new_s: Session):
    table = "users"
    rows = fetch_all(old_s, "SELECT * FROM users ORDER BY id")
    log_table_start(table, len(rows))
    for r in rows:
        new_s.execute(
            text("""
                INSERT INTO users (id, username, name, surname, email, password_hash,
                                   is_active, is_admin, created_at, updated_at)
                VALUES (:id, :username, :name, :surname, :email, :password_hash,
                        :is_active, :is_admin, :created_at, :updated_at)
                ON CONFLICT (id) DO NOTHING
            """), r
        )
    new_s.commit()
    reset_sequence(new_s, table)
    log_table_done(table, len(rows))


def migrate_files(old_s: Session, new_s: Session):
    table = "files"
    rows = fetch_all(old_s, "SELECT * FROM files ORDER BY id")
    log_table_start(table, len(rows))
    for r in rows:
        new_s.execute(
            text("""
                INSERT INTO files (id, entity_type, entity_id, original_name,
                                   storage_path, mime_type, size_bytes, created_at)
                VALUES (:id, :entity_type, :entity_id, :original_name,
                        :storage_path, :mime_type, :size_bytes, :created_at)
                ON CONFLICT (id) DO NOTHING
            """), r
        )
    new_s.commit()
    reset_sequence(new_s, table)
    log_table_done(table, len(rows))


def migrate_die_type(old_s: Session, new_s: Session):
    table = "die_type"
    rows = fetch_all(old_s, "SELECT * FROM die_type ORDER BY id")
    log_table_start(table, len(rows))
    for r in rows:
        new_s.execute(
            text("""
                INSERT INTO die_type (id, code, name, description, is_active, created_at, updated_at)
                VALUES (:id, :code, :name, :description, :is_active, :created_at, :updated_at)
                ON CONFLICT (id) DO NOTHING
            """), r
        )
    new_s.commit()
    reset_sequence(new_s, table)
    log_table_done(table, len(rows))


def migrate_operation_type(old_s: Session, new_s: Session):
    table = "operation_type"
    rows = fetch_all(old_s, "SELECT * FROM operation_type ORDER BY id")
    log_table_start(table, len(rows))
    for r in rows:
        new_s.execute(
            text("""
                INSERT INTO operation_type (id, code, name, description, is_active,
                                            is_cutting, execution_mode, created_at)
                VALUES (:id, :code, :name, :description, :is_active,
                        :is_cutting, :execution_mode, :created_at)
                ON CONFLICT (id) DO NOTHING
            """), {**r, "is_cutting": r.get("is_cutting", False)}
        )
    new_s.commit()
    reset_sequence(new_s, table)
    log_table_done(table, len(rows))


def migrate_work_center(old_s: Session, new_s: Session):
    table = "work_center"
    rows = fetch_all(old_s, "SELECT * FROM work_center ORDER BY id")
    log_table_start(table, len(rows))
    for r in rows:
        new_s.execute(
            text("""
                INSERT INTO work_center (id, name, status,
                                         capacity_per_hour, setup_time_minutes,
                                         cost_per_hour, created_at)
                VALUES (:id, :name, :status,
                        :capacity_per_hour, :setup_time_minutes,
                        :cost_per_hour, :created_at)
                ON CONFLICT (id) DO NOTHING
            """), {
                "id": r["id"],
                "name": r["name"],
                "status": r["status"],
                "capacity_per_hour": r.get("capacity_per_hour"),
                "setup_time_minutes": r.get("setup_time_minutes"),
                "cost_per_hour": r.get("cost_per_hour"),
                "created_at": r.get("created_at"),
            }
        )
    new_s.commit()
    reset_sequence(new_s, table)
    log_table_done(table, len(rows))


def migrate_component_type(old_s: Session, new_s: Session):
    table = "component_type"
    rows = fetch_all(old_s, "SELECT * FROM component_type ORDER BY id")
    log_table_start(table, len(rows))
    for r in rows:
        new_s.execute(
            text("""
                INSERT INTO component_type (id, code, name, description, is_active,
                                            created_at, updated_at)
                VALUES (:id, :code, :name, :description, :is_active,
                        :created_at, :updated_at)
                ON CONFLICT (id) DO NOTHING
            """), r
        )
    new_s.commit()
    reset_sequence(new_s, table)
    log_table_done(table, len(rows))


def migrate_supplier(old_s: Session, new_s: Session):
    table = "supplier"
    rows = fetch_all(old_s, "SELECT * FROM supplier ORDER BY id")
    log_table_start(table, len(rows))
    for r in rows:
        new_s.execute(
            text("""
                INSERT INTO supplier (id, name, tax_no, contact_name, phone, email,
                                      address, notes, contact_info, is_active,
                                      created_at, updated_at)
                VALUES (:id, :name, :tax_no, :contact_name, :phone, :email,
                        :address, :notes, :contact_info, :is_active,
                        :created_at, :updated_at)
                ON CONFLICT (id) DO NOTHING
            """), {**r, "contact_info": r.get("contact_info", None)}
        )
    new_s.commit()
    reset_sequence(new_s, table)
    log_table_done(table, len(rows))


def migrate_operator(old_s: Session, new_s: Session):
    table = "operator"
    rows = fetch_all(old_s, "SELECT * FROM operator ORDER BY id")
    log_table_start(table, len(rows))
    for r in rows:
        new_s.execute(
            text("""
                INSERT INTO operator (id, rfid_code, name, employee_number, is_active,
                                      created_at, updated_at, role)
                VALUES (:id, :rfid_code, :name, :employee_number, :is_active,
                        :created_at, :updated_at, :role)
                ON CONFLICT (id) DO NOTHING
            """), r
        )
    new_s.commit()
    reset_sequence(new_s, table)
    log_table_done(table, len(rows))


def migrate_domain_action_log(old_s: Session, new_s: Session):
    table = "domain_action_log"
    rows = fetch_all(old_s, "SELECT * FROM domain_action_log ORDER BY id")
    log_table_start(table, len(rows))
    for r in rows:
        new_s.execute(
            text("""
                INSERT INTO domain_action_log (id, action_type, actor_type, actor_id,
                                               entity_type, entity_id, reason, notes,
                                               before_snapshot, after_snapshot,
                                               meta_data, created_at)
                VALUES (:id, :action_type, :actor_type, :actor_id,
                        :entity_type, :entity_id, :reason, :notes,
                        :before_snapshot, :after_snapshot,
                        :meta_data, :created_at)
                ON CONFLICT (id) DO NOTHING
            """), r
        )
    new_s.commit()
    reset_sequence(new_s, table)
    log_table_done(table, len(rows))


# ── M2M Association Tables ────────────────────────────────────────

def migrate_operator_work_center(old_s: Session, new_s: Session):
    table = "operator_work_center"
    rows = fetch_all(old_s, "SELECT * FROM operator_work_center")
    log_table_start(table, len(rows))
    for r in rows:
        new_s.execute(
            text("""
                INSERT INTO operator_work_center (operator_id, work_center_id)
                VALUES (:operator_id, :work_center_id)
                ON CONFLICT DO NOTHING
            """), r
        )
    new_s.commit()
    log_table_done(table, len(rows))


def migrate_work_center_operation_type(old_s: Session, new_s: Session):
    table = "work_center_operation_type"
    rows = fetch_all(old_s, "SELECT * FROM work_center_operation_type")
    log_table_start(table, len(rows))
    for r in rows:
        new_s.execute(
            text("""
                INSERT INTO work_center_operation_type (work_center_id, operation_type_id)
                VALUES (:work_center_id, :operation_type_id)
                ON CONFLICT DO NOTHING
            """), r
        )
    new_s.commit()
    log_table_done(table, len(rows))


def migrate_die_type_component(old_s: Session, new_s: Session):
    table = "die_type_component"
    rows = fetch_all(old_s, "SELECT * FROM die_type_component ORDER BY id")
    log_table_start(table, len(rows))
    for r in rows:
        new_s.execute(
            text("""
                INSERT INTO die_type_component (id, die_type_id, component_type_id, created_at)
                VALUES (:id, :die_type_id, :component_type_id, :created_at)
                ON CONFLICT (id) DO NOTHING
            """), r
        )
    new_s.commit()
    reset_sequence(new_s, table)
    log_table_done(table, len(rows))


def migrate_component_bom(old_s: Session, new_s: Session):
    table = "component_bom"
    rows = fetch_all(old_s, "SELECT * FROM component_bom ORDER BY id")
    log_table_start(table, len(rows))
    for r in rows:
        new_s.execute(
            text("""
                INSERT INTO component_bom (id, component_type_id, sequence_number,
                                           operation_name, operation_type_id,
                                           preferred_work_center_id,
                                           estimated_duration_minutes, notes, created_at)
                VALUES (:id, :component_type_id, :sequence_number,
                        :operation_name, :operation_type_id,
                        :preferred_work_center_id,
                        :estimated_duration_minutes, :notes, :created_at)
                ON CONFLICT (id) DO NOTHING
            """), r
        )
    new_s.commit()
    reset_sequence(new_s, table)
    log_table_done(table, len(rows))


def migrate_die(old_s: Session, new_s: Session):
    table = "die"
    rows = fetch_all(old_s, "SELECT * FROM die ORDER BY id")
    log_table_start(table, len(rows))
    for r in rows:
        new_s.execute(
            text("""
                INSERT INTO die (id, die_number, die_diameter_mm, total_package_length_mm,
                                 die_type_id, status, created_at, updated_at,
                                 profile_no, figure_count, customer_name, press_code,
                                 is_revisioned, expected_completion_date, description)
                VALUES (:id, :die_number, :die_diameter_mm, :total_package_length_mm,
                        :die_type_id, :status, :created_at, :updated_at,
                        :profile_no, :figure_count, :customer_name, :press_code,
                        :is_revisioned, :expected_completion_date, :description)
                ON CONFLICT (id) DO NOTHING
            """), r
        )
    new_s.commit()
    reset_sequence(new_s, table)
    log_table_done(table, len(rows))


def migrate_production_order(old_s: Session, new_s: Session):
    table = "production_order"
    rows = fetch_all(old_s, "SELECT * FROM production_order ORDER BY id")
    log_table_start(table, len(rows))
    for r in rows:
        new_s.execute(
            text("""
                INSERT INTO production_order (id, die_id, order_number, status,
                                              started_at, completed_at, created_at)
                VALUES (:id, :die_id, :order_number, :status,
                        :started_at, :completed_at, :created_at)
                ON CONFLICT (id) DO NOTHING
            """), r
        )
    new_s.commit()
    reset_sequence(new_s, table)
    log_table_done(table, len(rows))


# ═══════════════════════════════════════════════════════════════════
# PHASE 2: SEED / DERIVE NEW TABLES
# ═══════════════════════════════════════════════════════════════════

def seed_item_category(new_s: Session) -> int:
    """Seed the 'Sıcak İş Takım Çeliği' category. Returns the category ID."""
    table = "item_category"
    log_table_start(table, 0)
    log.info("  Seeding: 'Sıcak İş Takım Çeliği'")

    attributes_schema = json.dumps([
        {"key": "diameter_mm", "label": "Çap (mm)", "type": "number"},
        {"key": "length_mm", "label": "Boy (mm)", "type": "number"},
        {"key": "alloy", "label": "Alaşım", "type": "text"},
    ], ensure_ascii=False)

    new_s.execute(
        text("""
            INSERT INTO item_category (name, base_uom, is_cuttable, attributes_schema, created_at)
            VALUES (:name, :base_uom, :is_cuttable, CAST(:attributes_schema AS jsonb), :created_at)
            ON CONFLICT (name) DO NOTHING
        """), {
            "name": "Sıcak İş Takım Çeliği",
            "base_uom": "kg",
            "is_cuttable": True,
            "attributes_schema": attributes_schema,
            "created_at": datetime.now(timezone.utc),
        }
    )
    new_s.commit()

    cat_id = new_s.execute(
        text("SELECT id FROM item_category WHERE name = :name"),
        {"name": "Sıcak İş Takım Çeliği"}
    ).scalar()

    reset_sequence(new_s, table)
    log.info(f"  ✅ item_category seeded (id={cat_id})")
    return cat_id


def derive_material_grades(old_s: Session, new_s: Session) -> dict:
    """Create MaterialGrade records from unique steel_stock_item.alloy values.
    Returns: {alloy_name: material_grade_id}
    """
    table = "material_grade"
    alloys = fetch_all(old_s, "SELECT DISTINCT alloy FROM steel_stock_item WHERE alloy IS NOT NULL ORDER BY alloy")
    log_table_start(table, len(alloys))

    for row in alloys:
        alloy = row["alloy"]
        new_s.execute(
            text("""
                INSERT INTO material_grade (name, composition, created_at)
                VALUES (:name, :composition, :created_at)
                ON CONFLICT (name) DO NOTHING
            """), {
                "name": alloy,
                "composition": None,
                "created_at": datetime.now(timezone.utc),
            }
        )
    new_s.commit()

    # Fetch back the IDs
    alloy_map = {}
    grades = fetch_all(new_s, "SELECT id, name FROM material_grade")
    for g in grades:
        alloy_map[g["name"]] = g["id"]

    reset_sequence(new_s, table)
    log_table_done(table, len(alloy_map))
    return alloy_map


def derive_locations(old_s: Session, new_s: Session) -> dict:
    """Create Location records from unique work_center.location strings.
    Returns: {location_name: location_id}
    """
    table = "location"
    wcs = fetch_all(old_s, """
        SELECT id, name, location 
        FROM work_center 
        WHERE location IS NOT NULL AND location != ''
        ORDER BY id
    """)
    log_table_start(table, len(wcs))

    # Track unique location names to avoid duplicates
    seen_locations = set()
    for wc in wcs:
        loc_name = wc["location"].strip()
        if loc_name and loc_name not in seen_locations:
            seen_locations.add(loc_name)
            new_s.execute(
                text("""
                    INSERT INTO location (name, location_type, description, work_center_id,
                                          is_active, created_at)
                    VALUES (:name, :location_type, :description, :work_center_id,
                            :is_active, :created_at)
                    ON CONFLICT (name) DO NOTHING
                """), {
                    "name": loc_name,
                    "location_type": "WORK_CENTER",
                    "description": f"{wc['name']} iş merkezi konumu",
                    "work_center_id": wc["id"],
                    "is_active": True,
                    "created_at": datetime.now(timezone.utc),
                }
            )
    new_s.commit()

    # Fetch back the IDs
    loc_map = {}
    locs = fetch_all(new_s, "SELECT id, name FROM location")
    for loc in locs:
        loc_map[loc["name"]] = loc["id"]

    reset_sequence(new_s, table)
    log_table_done(table, len(loc_map))
    return loc_map


# ═══════════════════════════════════════════════════════════════════
# PHASE 3: TRANSFORMED TABLES
# ═══════════════════════════════════════════════════════════════════

def migrate_lots(old_s: Session, new_s: Session, alloy_map: dict, steel_items: list) -> dict:
    """Migrate lots with lot_number generation and material_grade linking.
    Returns: {old_lot_id: {"steel_stock_item_id": ..., physical data...}}
    """
    table = "lot"
    rows = fetch_all(old_s, "SELECT * FROM lot ORDER BY id")
    log_table_start(table, len(rows))

    # Build a lookup: steel_stock_item_id → alloy
    steel_alloy_map = {}
    for si in steel_items:
        steel_alloy_map[si["id"]] = si["alloy"]

    lot_steel_map = {}  # old_lot_id → old_steel_stock_item_id + physical data

    for r in rows:
        # Resolve material_grade_id from the lot's steel_stock_item → alloy
        material_grade_id = None
        old_steel_id = r.get("stock_item_id")
        if old_steel_id and old_steel_id in steel_alloy_map:
            alloy = steel_alloy_map[old_steel_id]
            material_grade_id = alloy_map.get(alloy)

        lot_number = f"LOT-{r['id']}"

        new_s.execute(
            text("""
                INSERT INTO lot (id, lot_number, certificate_number, receive_date,
                                 supplier_id, material_grade_id, notes, created_at)
                VALUES (:id, :lot_number, :certificate_number, :receive_date,
                        :supplier_id, :material_grade_id, :notes, :created_at)
                ON CONFLICT (id) DO NOTHING
            """), {
                "id": r["id"],
                "lot_number": lot_number,
                "certificate_number": r.get("certificate_number"),
                "receive_date": r["received_date"],
                "supplier_id": r.get("supplier_id"),
                "material_grade_id": material_grade_id,
                "notes": None,
                "created_at": r.get("created_at"),
            }
        )

        lot_steel_map[r["id"]] = {
            "steel_stock_item_id": old_steel_id,
            "length_mm": r.get("length_mm"),
            "gross_weight_kg": r.get("gross_weight_kg"),
            "remaining_kg": r.get("remaining_kg"),
        }

    new_s.commit()
    reset_sequence(new_s, table)
    log_table_done(table, len(rows))
    return lot_steel_map


def migrate_stock_items(
    old_s: Session,
    new_s: Session,
    category_id: int,
    steel_items: list,
    lot_steel_map: dict,
) -> dict:
    """Create StockItem records from steel_stock_item + lot physical data.
    Returns: {old_steel_stock_item_id: new_stock_item_id}
    """
    table = "stock_item"
    log_table_start(table, len(steel_items))

    # Build reverse map: steel_id → list of lot info
    steel_to_lots = {}
    for lot_id, lot_data in lot_steel_map.items():
        sid = lot_data["steel_stock_item_id"]
        if sid:
            if sid not in steel_to_lots:
                steel_to_lots[sid] = []
            steel_to_lots[sid].append({
                "lot_id": lot_id,
                **lot_data,
            })

    steel_to_stock_map = {}  # old_steel_id → new_stock_item_id

    for si in steel_items:
        old_id = si["id"]
        lots_for_steel = steel_to_lots.get(old_id, [])

        if lots_for_steel:
            # Create one StockItem per lot that references this steel
            for lot_info in lots_for_steel:
                remaining = lot_info.get("remaining_kg") or Decimal("0")
                attrs = {
                    "diameter_mm": si["diameter_mm"],
                    "alloy": si["alloy"],
                }
                if si.get("description"):
                    attrs["description"] = si["description"]
                if lot_info.get("length_mm"):
                    attrs["length_mm"] = lot_info["length_mm"]
                if lot_info.get("gross_weight_kg"):
                    attrs["gross_weight_kg"] = float(lot_info["gross_weight_kg"])

                attrs_json = json.dumps(attrs, ensure_ascii=False, default=str)

                new_s.execute(
                    text("""
                        INSERT INTO stock_item (item_type, category_id, lot_id, parent_id,
                                                location_id, quantity, attributes,
                                                is_active, created_at, updated_at)
                        VALUES (:item_type, :category_id, :lot_id, :parent_id,
                                :location_id, :quantity, CAST(:attributes AS jsonb),
                                :is_active, :created_at, :updated_at)
                        RETURNING id
                    """), {
                        "item_type": "RAW_MATERIAL",
                        "category_id": category_id,
                        "lot_id": lot_info["lot_id"],
                        "parent_id": None,
                        "location_id": None,
                        "quantity": remaining,
                        "attributes": attrs_json,
                        "is_active": True if remaining > 0 else False,
                        "created_at": si.get("created_at") or datetime.now(timezone.utc),
                        "updated_at": datetime.now(timezone.utc),
                    }
                )
                result = new_s.execute(text("SELECT lastval()"))
                new_stock_id = result.scalar()

                # Map the first lot's stock item as the primary mapping for this steel
                if old_id not in steel_to_stock_map:
                    steel_to_stock_map[old_id] = new_stock_id
        else:
            # Steel item with no lots — create a standalone StockItem
            attrs = {
                "diameter_mm": si["diameter_mm"],
                "alloy": si["alloy"],
            }
            if si.get("description"):
                attrs["description"] = si["description"]

            attrs_json = json.dumps(attrs, ensure_ascii=False, default=str)

            new_s.execute(
                text("""
                    INSERT INTO stock_item (item_type, category_id, lot_id, parent_id,
                                            location_id, quantity, attributes,
                                            is_active, created_at, updated_at)
                    VALUES (:item_type, :category_id, :lot_id, :parent_id,
                            :location_id, :quantity, CAST(:attributes AS jsonb),
                            :is_active, :created_at, :updated_at)
                    RETURNING id
                """), {
                    "item_type": "RAW_MATERIAL",
                    "category_id": category_id,
                    "lot_id": None,
                    "parent_id": None,
                    "location_id": None,
                    "quantity": Decimal("0"),
                    "attributes": attrs_json,
                    "is_active": True,
                    "created_at": si.get("created_at") or datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            result = new_s.execute(text("SELECT lastval()"))
            new_stock_id = result.scalar()
            steel_to_stock_map[old_id] = new_stock_id

    new_s.commit()
    reset_sequence(new_s, table)
    log_table_done(table, len(steel_to_stock_map))
    log.info(f"  📋 Steel→Stock mapping: {len(steel_to_stock_map)} entries")
    return steel_to_stock_map


def cleanup_phase3_tables(new_s: Session):
    """Delete previously migrated Phase 3 data that needs re-doing.
    Order: reverse FK dependencies.
    """
    log.info("Cleaning up Phase 3 tables for re-migration...")
    tables_to_clean = [
        "stock_transaction",
        "work_order_operation",
        "work_order",
        "die_component",
    ]
    for t in tables_to_clean:
        count = new_s.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
        new_s.execute(text(f"DELETE FROM {t}"))
        log.info(f"  Deleted {count} rows from {t}")

    # Only delete WIP stock items, keep RAW_MATERIAL
    wip_count = new_s.execute(
        text("SELECT COUNT(*) FROM stock_item WHERE item_type = 'WIP'")
    ).scalar()
    new_s.execute(text("DELETE FROM stock_item WHERE item_type = 'WIP'"))
    log.info(f"  Deleted {wip_count} WIP stock_items (RAW_MATERIAL kept)")

    new_s.commit()
    log.info("  [OK] Phase 3 cleanup complete")


def migrate_die_component(
    old_s: Session,
    new_s: Session,
    steel_to_stock_map: dict,
    category_id: int,
) -> dict:
    """Migrate die_component and create WIP StockItems for each.

    For each die_component that references a steel_stock_item:
    1. Create a WIP StockItem (parent_id → RAW_MATERIAL StockItem)
    2. Point die_component.stock_item_id → the WIP StockItem

    Returns: {die_component_id: wip_stock_item_id} mapping for work_order.
    """
    table = "die_component"

    # Fetch die_components WITH die and component_type info via JOINs
    rows = fetch_all(old_s, """
        SELECT dc.id, dc.die_id, dc.component_type_id, dc.stock_item_id,
               dc.package_length_mm, dc.theoretical_consumption_kg, dc.created_at,
               d.die_number,
               ct.name AS component_type_name,
               si.diameter_mm AS steel_diameter_mm,
               si.alloy AS steel_alloy
        FROM die_component dc
        JOIN die d ON d.id = dc.die_id
        JOIN component_type ct ON ct.id = dc.component_type_id
        LEFT JOIN steel_stock_item si ON si.id = dc.stock_item_id
        ORDER BY dc.id
    """)
    log_table_start(table, len(rows))

    # Also fetch work_order lot assignments: die_component_id → lot_id
    wo_lot_rows = fetch_all(old_s, """
        SELECT die_component_id, lot_id
        FROM work_order
        WHERE die_component_id IS NOT NULL AND lot_id IS NOT NULL
    """)
    dc_to_lot = {}
    for wl in wo_lot_rows:
        # Use the first lot_id found for each die_component
        if wl["die_component_id"] not in dc_to_lot:
            dc_to_lot[wl["die_component_id"]] = wl["lot_id"]

    dc_to_wip_map = {}  # die_component_id → wip_stock_item_id
    wip_created = 0

    for r in rows:
        old_steel_id = r.get("stock_item_id")
        raw_material_stock_id = steel_to_stock_map.get(old_steel_id) if old_steel_id else None
        wip_stock_id = None

        if raw_material_stock_id:
            # Build WIP attributes: physical props from steel + production context
            attrs = {}
            if r.get("steel_diameter_mm"):
                attrs["diameter_mm"] = r["steel_diameter_mm"]
            if r.get("steel_alloy"):
                attrs["alloy"] = r["steel_alloy"]
            if r.get("package_length_mm"):
                attrs["length_mm"] = float(r["package_length_mm"])
            if r.get("die_number"):
                attrs["Kalıp"] = r["die_number"]
            if r.get("component_type_name"):
                attrs["Bileşen"] = r["component_type_name"]

            attrs_json = json.dumps(attrs, ensure_ascii=False, default=str)

            # Resolve lot_id from work_order if available
            lot_id = dc_to_lot.get(r["id"])

            # Create WIP StockItem
            new_s.execute(
                text("""
                    INSERT INTO stock_item (item_type, category_id, lot_id, parent_id,
                                            location_id, quantity, attributes,
                                            is_active, created_at, updated_at)
                    VALUES (:item_type, :category_id, :lot_id, :parent_id,
                            :location_id, :quantity, CAST(:attributes AS jsonb),
                            :is_active, :created_at, :updated_at)
                    RETURNING id
                """), {
                    "item_type": "WIP",
                    "category_id": category_id,
                    "lot_id": lot_id,
                    "parent_id": raw_material_stock_id,
                    "location_id": None,
                    "quantity": Decimal("1"),
                    "attributes": attrs_json,
                    "is_active": True,
                    "created_at": r.get("created_at") or datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            result = new_s.execute(text("SELECT lastval()"))
            wip_stock_id = result.scalar()
            dc_to_wip_map[r["id"]] = wip_stock_id
            wip_created += 1

        # Insert die_component with stock_item_id → WIP (not RAW_MATERIAL)
        new_s.execute(
            text("""
                INSERT INTO die_component (id, die_id, component_type_id, stock_item_id,
                                           package_length_mm, theoretical_consumption_kg,
                                           created_at)
                VALUES (:id, :die_id, :component_type_id, :stock_item_id,
                        :package_length_mm, :theoretical_consumption_kg,
                        :created_at)
                ON CONFLICT (id) DO NOTHING
            """), {
                "id": r["id"],
                "die_id": r["die_id"],
                "component_type_id": r["component_type_id"],
                "stock_item_id": wip_stock_id,
                "package_length_mm": r["package_length_mm"],
                "theoretical_consumption_kg": r["theoretical_consumption_kg"],
                "created_at": r.get("created_at"),
            }
        )

    new_s.commit()
    reset_sequence(new_s, "stock_item")
    reset_sequence(new_s, table)
    log_table_done(table, len(rows))
    log.info(f"  [WIP] Created {wip_created} WIP StockItems for die_components")
    log.info(f"  [MAP] die_component→WIP mapping: {len(dc_to_wip_map)} entries")
    return dc_to_wip_map


def migrate_work_order(old_s: Session, new_s: Session, dc_to_wip_map: dict):
    """Migrate work_order with stock_item_id populated from die_component→WIP mapping."""
    table = "work_order"
    rows = fetch_all(old_s, "SELECT * FROM work_order ORDER BY id")
    log_table_start(table, len(rows))

    linked_count = 0
    for r in rows:
        # Resolve stock_item_id: from die_component → WIP mapping
        stock_item_id = r.get("stock_item_id", None)
        dc_id = r.get("die_component_id")
        if dc_id and dc_id in dc_to_wip_map:
            stock_item_id = dc_to_wip_map[dc_id]
            linked_count += 1

        new_s.execute(
            text("""
                INSERT INTO work_order (id, production_order_id, die_component_id,
                                        stock_item_id, order_number,
                                        pre_machining_order_number,
                                        status, theoretical_consumption_kg,
                                        actual_consumption_kg,
                                        planned_cut_length_mm, planned_cut_weight_kg,
                                        actual_cut_length_mm, actual_cut_weight_kg,
                                        lot_id, started_at, completed_at, created_at)
                VALUES (:id, :production_order_id, :die_component_id,
                        :stock_item_id, :order_number,
                        :pre_machining_order_number,
                        :status, :theoretical_consumption_kg,
                        :actual_consumption_kg,
                        :planned_cut_length_mm, :planned_cut_weight_kg,
                        :actual_cut_length_mm, :actual_cut_weight_kg,
                        :lot_id, :started_at, :completed_at, :created_at)
                ON CONFLICT (id) DO NOTHING
            """), {
                "id": r["id"],
                "production_order_id": r.get("production_order_id"),
                "die_component_id": r.get("die_component_id"),
                "stock_item_id": stock_item_id,
                "order_number": r.get("order_number"),
                "pre_machining_order_number": r.get("pre_machining_order_number", None),
                "status": r["status"],
                "theoretical_consumption_kg": r["theoretical_consumption_kg"],
                "actual_consumption_kg": r.get("actual_consumption_kg"),
                "planned_cut_length_mm": r.get("planned_cut_length_mm", None),
                "planned_cut_weight_kg": r.get("planned_cut_weight_kg", None),
                "actual_cut_length_mm": r.get("actual_cut_length_mm", None),
                "actual_cut_weight_kg": r.get("actual_cut_weight_kg", None),
                "lot_id": r.get("lot_id"),
                "started_at": r.get("started_at"),
                "completed_at": r.get("completed_at"),
                "created_at": r.get("created_at"),
            }
        )

    new_s.commit()
    reset_sequence(new_s, table)
    log_table_done(table, len(rows))
    log.info(f"  [LINK] {linked_count} work_orders linked to WIP stock_items")


def migrate_work_order_operation(old_s: Session, new_s: Session):
    table = "work_order_operation"
    rows = fetch_all(old_s, "SELECT * FROM work_order_operation ORDER BY id")
    log_table_start(table, len(rows))

    for r in rows:
        new_s.execute(
            text("""
                INSERT INTO work_order_operation (id, work_order_id, sequence_number,
                                                   operation_type_id, work_center_id,
                                                   operation_name, operator_name,
                                                   status, estimated_duration_minutes,
                                                   started_at, completed_at, notes,
                                                   created_at, meta_data)
                VALUES (:id, :work_order_id, :sequence_number,
                        :operation_type_id, :work_center_id,
                        :operation_name, :operator_name,
                        :status, :estimated_duration_minutes,
                        :started_at, :completed_at, :notes,
                        :created_at, :meta_data)
                ON CONFLICT (id) DO NOTHING
            """), r
        )

    new_s.commit()
    reset_sequence(new_s, table)
    log_table_done(table, len(rows))


def migrate_stock_movements(old_s: Session, new_s: Session, lot_steel_map: dict, steel_to_stock_map: dict):
    """Attempt to convert stock_movement → stock_transaction.
    Falls back to clean ledger on failure.
    """
    table = "stock_transaction"
    rows = fetch_all(old_s, "SELECT * FROM stock_movement ORDER BY id")
    log_table_start(table, len(rows))

    if not rows:
        log.info("  ℹ️  No stock_movement records found — skipping")
        return

    try:
        # Build lot_id → stock_item_id map
        lot_to_stock = {}
        for lot_id, lot_data in lot_steel_map.items():
            steel_id = lot_data.get("steel_stock_item_id")
            if steel_id and steel_id in steel_to_stock_map:
                lot_to_stock[lot_id] = steel_to_stock_map[steel_id]

        migrated = 0
        skipped = 0

        for r in rows:
            stock_item_id = lot_to_stock.get(r["lot_id"])
            if not stock_item_id:
                skipped += 1
                log.warning(
                    f"  ⚠️  stock_movement id={r['id']}: lot_id={r['lot_id']} "
                    f"has no stock_item mapping — skipping"
                )
                continue

            quantity_kg = r.get("quantity_kg", Decimal("0"))

            new_s.execute(
                text("""
                    INSERT INTO stock_transaction (stock_item_id, transaction_type,
                                                    quantity_change, quantity_after,
                                                    work_order_id, process_batch_id,
                                                    reference_item_id, notes,
                                                    meta_data, timestamp)
                    VALUES (:stock_item_id, :transaction_type,
                            :quantity_change, :quantity_after,
                            :work_order_id, :process_batch_id,
                            :reference_item_id, :notes,
                            :meta_data, :timestamp)
                """), {
                    "stock_item_id": stock_item_id,
                    "transaction_type": "PARTIAL_CONSUME",
                    "quantity_change": -abs(quantity_kg),  # deduction (negative)
                    "quantity_after": Decimal("0"),        # best-effort snapshot
                    "work_order_id": r.get("work_order_id"),
                    "process_batch_id": None,
                    "reference_item_id": None,
                    "notes": r.get("notes"),
                    "meta_data": None,
                    "timestamp": r.get("movement_date") or r.get("created_at"),
                }
            )
            migrated += 1

        new_s.commit()
        reset_sequence(new_s, table)
        log.info(f"  ✅ stock_transaction: {migrated} migrated, {skipped} skipped")

    except Exception as e:
        new_s.rollback()
        log.error(f"  ❌ stock_movement → stock_transaction conversion FAILED: {e}")
        log.info("  ↩️  Falling back to clean ledger — no stock_transaction records migrated.")


# ═══════════════════════════════════════════════════════════════════
# VERIFICATION
# ═══════════════════════════════════════════════════════════════════

def verify_migration(old_s: Session, new_s: Session):
    """Run basic verification checks after migration."""
    log.info("=" * 60)
    log.info("VERIFICATION")
    log.info("=" * 60)

    # Direct-copy tables: row count comparison
    direct_tables = [
        "users", "files", "die_type", "operation_type", "work_center",
        "component_type", "supplier", "operator", "domain_action_log",
        "die_type_component", "component_bom", "die", "production_order",
        "work_order", "work_order_operation",
    ]

    all_ok = True
    for t in direct_tables:
        try:
            old_count = count_rows(old_s, t)
            new_count = count_rows(new_s, t)
            status = "✅" if old_count == new_count else "❌"
            if old_count != new_count:
                all_ok = False
            log.info(f"  {status} {t}: old={old_count}, new={new_count}")
        except Exception as e:
            log.warning(f"  ⚠️  {t}: verification error — {e}")

    # New/transformed tables: just report counts
    new_tables = [
        "item_category", "material_grade", "location",
        "lot", "stock_item", "stock_transaction",
        "die_component",
    ]
    for t in new_tables:
        try:
            new_count = count_rows(new_s, t)
            log.info(f"  📊 {t}: {new_count} rows")
        except Exception as e:
            log.warning(f"  ⚠️  {t}: verification error — {e}")

    # FK integrity check: die_component.stock_item_id
    try:
        orphans = new_s.execute(text("""
            SELECT COUNT(*) FROM die_component dc
            WHERE dc.stock_item_id IS NOT NULL
            AND dc.stock_item_id NOT IN (SELECT id FROM stock_item)
        """)).scalar()
        status = "✅" if orphans == 0 else "❌"
        log.info(f"  {status} die_component FK integrity: {orphans} orphaned stock_item_ids")
        if orphans > 0:
            all_ok = False
    except Exception as e:
        log.warning(f"  ⚠️  FK integrity check error: {e}")

    if all_ok:
        log.info("  🎉 All verification checks PASSED!")
    else:
        log.warning("  ⚠️  Some verification checks FAILED — review above")


# ═══════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════

def main():
    log.info("=" * 60)
    log.info("DATA MIGRATION: kaliphane → khdemo3")
    log.info(f"Started at: {datetime.now(timezone.utc).isoformat()}")
    log.info("=" * 60)

    old_s = OldSession()
    new_s = NewSession()

    try:
        # ── Pre-flight: fetch steel_stock_items for later use ──
        steel_items = fetch_all(old_s, "SELECT * FROM steel_stock_item ORDER BY id")
        log.info(f"Pre-flight: {len(steel_items)} steel_stock_item records found")

        # ── PHASE 1: Direct copies ────────────────────────────
        log.info("\n" + "=" * 60)
        log.info("PHASE 1: DIRECT COPY TABLES")
        log.info("=" * 60)

        migrate_users(old_s, new_s)
        migrate_files(old_s, new_s)
        migrate_die_type(old_s, new_s)
        migrate_operation_type(old_s, new_s)
        migrate_work_center(old_s, new_s)
        migrate_component_type(old_s, new_s)
        migrate_supplier(old_s, new_s)
        migrate_operator(old_s, new_s)
        migrate_domain_action_log(old_s, new_s)
        migrate_operator_work_center(old_s, new_s)
        migrate_work_center_operation_type(old_s, new_s)
        migrate_die_type_component(old_s, new_s)
        migrate_component_bom(old_s, new_s)
        migrate_die(old_s, new_s)
        migrate_production_order(old_s, new_s)

        # ── PHASE 2: Seed / Derive new tables ─────────────────
        log.info("\n" + "=" * 60)
        log.info("PHASE 2: SEED / DERIVE NEW TABLES")
        log.info("=" * 60)

        category_id = seed_item_category(new_s)
        alloy_map = derive_material_grades(old_s, new_s)
        location_map = derive_locations(old_s, new_s)

        # ── PHASE 3: Transformed tables ───────────────────────
        log.info("\n" + "=" * 60)
        log.info("PHASE 3: TRANSFORMED TABLES")
        log.info("=" * 60)

        # Clean up previously migrated Phase 3 data before re-doing
        cleanup_phase3_tables(new_s)

        lot_steel_map = migrate_lots(old_s, new_s, alloy_map, steel_items)
        steel_to_stock_map = migrate_stock_items(old_s, new_s, category_id, steel_items, lot_steel_map)
        dc_to_wip_map = migrate_die_component(old_s, new_s, steel_to_stock_map, category_id)
        migrate_work_order(old_s, new_s, dc_to_wip_map)
        migrate_work_order_operation(old_s, new_s)
        migrate_stock_movements(old_s, new_s, lot_steel_map, steel_to_stock_map)

        # ── VERIFICATION ──────────────────────────────────────
        verify_migration(old_s, new_s)

        log.info("\n" + "=" * 60)
        log.info(f"MIGRATION COMPLETED at {datetime.now(timezone.utc).isoformat()}")
        log.info("=" * 60)

    except Exception as e:
        log.error(f"[FAILED] MIGRATION FAILED: {e}", exc_info=True)
        new_s.rollback()
        raise
    finally:
        old_s.close()
        new_s.close()
        old_engine.dispose()
        new_engine.dispose()


if __name__ == "__main__":
    main()
