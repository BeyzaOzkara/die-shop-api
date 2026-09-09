import psycopg2
from psycopg2.extras import execute_values

try:
    print("Connecting to databases...")
    conn_old = psycopg2.connect('postgresql://arslan:gqTYe5HdX0VQ@192.168.150.230:5432/kaliphane')
    conn_new = psycopg2.connect('postgresql://arslan:gqTYe5HdX0VQ@192.168.150.230:5432/kaliphane1')
    
    cur_old = conn_old.cursor()
    cur_new = conn_new.cursor()
    
    print("Fetching data from kaliphane.work_order_operation...")
    # Make sure we fetch columns in a specific order so we can insert them easily
    columns = [
        "id", "work_order_id", "sequence_number", "operation_name", "work_center_id", 
        "operator_name", "status", "estimated_duration_minutes", "started_at", 
        "completed_at", "notes", "created_at", "operation_type_id", "meta_data"
    ]
    
    cur_old.execute(f"SELECT {', '.join(columns)} FROM work_order_operation")
    rows = cur_old.fetchall()
    print(f"Found {len(rows)} rows to copy.")
    
    if rows:
        print("Inserting data into kaliphane1.work_order_operation...")
        
        insert_query = f"""
            INSERT INTO work_order_operation ({', '.join(columns)}) 
            VALUES %s 
            ON CONFLICT (id) DO UPDATE SET 
                work_order_id = EXCLUDED.work_order_id,
                sequence_number = EXCLUDED.sequence_number,
                operation_name = EXCLUDED.operation_name,
                work_center_id = EXCLUDED.work_center_id,
                operator_name = EXCLUDED.operator_name,
                status = EXCLUDED.status,
                estimated_duration_minutes = EXCLUDED.estimated_duration_minutes,
                started_at = EXCLUDED.started_at,
                completed_at = EXCLUDED.completed_at,
                notes = EXCLUDED.notes,
                created_at = EXCLUDED.created_at,
                operation_type_id = EXCLUDED.operation_type_id,
                meta_data = EXCLUDED.meta_data;
        """
        
        execute_values(cur_new, insert_query, rows)
        
        # Also need to update the sequence in the new db so new inserts don't fail
        cur_new.execute("SELECT setval(pg_get_serial_sequence('work_order_operation', 'id'), coalesce(max(id), 0) + 1, false) FROM work_order_operation;")
        
        conn_new.commit()
        print("Data copied successfully!")
    else:
        print("No data found to copy.")
        
except Exception as e:
    print(f"An error occurred: {e}")
    if 'conn_new' in locals() and conn_new:
        conn_new.rollback()
finally:
    if 'cur_old' in locals() and cur_old: cur_old.close()
    if 'conn_old' in locals() and conn_old: conn_old.close()
    if 'cur_new' in locals() and cur_new: cur_new.close()
    if 'conn_new' in locals() and conn_new: conn_new.close()
