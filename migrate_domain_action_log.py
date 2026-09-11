import psycopg2
from psycopg2.extras import execute_values
import json

def serialize_jsonb(rows, json_indices):
    serialized_rows = []
    for row in rows:
        new_row = list(row)
        for idx in json_indices:
            if isinstance(new_row[idx], dict) or isinstance(new_row[idx], list):
                new_row[idx] = json.dumps(new_row[idx])
        serialized_rows.append(tuple(new_row))
    return serialized_rows

try:
    print("Connecting to databases...")
    conn_old = psycopg2.connect('postgresql://arslan:gqTYe5HdX0VQ@192.168.150.230:5432/kaliphane')
    conn_new = psycopg2.connect('postgresql://arslan:gqTYe5HdX0VQ@192.168.150.230:5432/kaliphane1')
    
    cur_old = conn_old.cursor()
    cur_new = conn_new.cursor()
    
    all_columns = [
        "id", "entity_id", "before_snapshot", "after_snapshot", "meta_data", 
        "created_at", "actor_id", "action_type", "actor_type", "reason", 
        "entity_type", "notes"
    ]
    
    columns_no_id = [col for col in all_columns if col != "id"]
    
    print("Fetching existing new data from kaliphane1...")
    cur_new.execute(f"SELECT {', '.join(columns_no_id)} FROM domain_action_log ORDER BY id ASC")
    existing_new_rows = cur_new.fetchall()
    print(f"Found {len(existing_new_rows)} existing rows in kaliphane1.")
    
    print("Fetching old data from kaliphane...")
    cur_old.execute(f"SELECT {', '.join(all_columns)} FROM domain_action_log ORDER BY id ASC")
    old_rows = cur_old.fetchall()
    print(f"Found {len(old_rows)} old rows in kaliphane.")
    
    print("Truncating kaliphane1.domain_action_log...")
    cur_new.execute("TRUNCATE TABLE domain_action_log RESTART IDENTITY;")
    
    if old_rows:
        print("Inserting old data into kaliphane1 (preserving explicit IDs)...")
        insert_old_query = f"""
            INSERT INTO domain_action_log ({', '.join(all_columns)}) 
            VALUES %s
        """
        # id is index 0. before_snapshot is 2, after_snapshot is 3, meta_data is 4
        old_rows_serialized = serialize_jsonb(old_rows, [2, 3, 4])
        execute_values(cur_new, insert_old_query, old_rows_serialized)
        
        cur_new.execute("SELECT setval(pg_get_serial_sequence('domain_action_log', 'id'), coalesce(max(id), 0) + 1, false) FROM domain_action_log;")
    
    if existing_new_rows:
        print("Re-inserting the newer entries (generating new sequential IDs underneath the old data)...")
        insert_new_query = f"""
            INSERT INTO domain_action_log ({', '.join(columns_no_id)}) 
            VALUES %s
        """
        # Without 'id' column, before_snapshot is 1, after_snapshot is 2, meta_data is 3
        existing_new_rows_serialized = serialize_jsonb(existing_new_rows, [1, 2, 3])
        execute_values(cur_new, insert_new_query, existing_new_rows_serialized)
        
    conn_new.commit()
    print("Migration and ID shifting completed successfully!")

except Exception as e:
    print(f"An error occurred: {e}")
    if 'conn_new' in locals() and conn_new:
        conn_new.rollback()
        print("Rolled back changes.")
finally:
    if 'cur_old' in locals() and cur_old: cur_old.close()
    if 'conn_old' in locals() and conn_old: conn_old.close()
    if 'cur_new' in locals() and cur_new: cur_new.close()
    if 'conn_new' in locals() and conn_new: conn_new.close()
