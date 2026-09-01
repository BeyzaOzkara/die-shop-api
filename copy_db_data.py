import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json
import sys
import codecs

# Fix print encoding
sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

source_db = 'kaliphaneNew'
target_db = 'kaliphaneDemo1'
db_user = 'arslan'
db_password = 'gqTYe5HdX0VQ'
db_host = '192.168.150.230'
db_port = '5432'

def get_connection(dbname):
    return psycopg2.connect(
        dbname=dbname,
        user=db_user,
        password=db_password,
        host=db_host,
        port=db_port
    )

tables_to_copy = [
    'users',
    'supplier',
    'item_category',
    'material_profile',
    'operation_type',
    'work_center',
    'location',
    'operator',
    'work_center_operation_type',
    'operator_work_center',
    'component_type',
    'component_bom',
    'die_type',
    'die_type_component'
]

def main():
    print("Connecting to databases...")
    conn_src = get_connection(source_db)
    conn_tgt = get_connection(target_db)
    
    cur_src = conn_src.cursor()
    cur_tgt = conn_tgt.cursor()

    try:
        # Truncate tables first (in reverse order to be clean, using CASCADE to handle dependents)
        print("Truncating target tables...")
        for table in reversed(tables_to_copy):
            print(f"Truncating {table}...")
            cur_tgt.execute(sql.SQL("TRUNCATE TABLE {} CASCADE").format(sql.Identifier(table)))
        
        for table in tables_to_copy:
            print(f"Copying {table}...")
            
            # Get columns
            cur_src.execute(sql.SQL("SELECT * FROM {} LIMIT 0").format(sql.Identifier(table)))
            columns = [desc[0] for desc in cur_src.description]
            
            # Select data
            cur_src.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(table)))
            rows = cur_src.fetchall()
            
            if rows:
                col_names = sql.SQL(',').join(map(sql.Identifier, columns))
                placeholders = sql.SQL(',').join(sql.Placeholder() * len(columns))
                insert_query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    sql.Identifier(table), col_names, placeholders
                )
                
                # Adapt dicts to json
                adapted_rows = []
                for row in rows:
                    adapted_row = tuple(Json(val) if isinstance(val, (dict, list)) else val for val in row)
                    adapted_rows.append(adapted_row)
                
                cur_tgt.executemany(insert_query, adapted_rows)
                
            # Update sequence if exists
            if 'id' in columns:
                cur_tgt.execute(sql.SQL("SELECT pg_get_serial_sequence('{}', 'id')").format(sql.SQL(table)))
                seq_res = cur_tgt.fetchone()
                if seq_res and seq_res[0]:
                    seq_name = seq_res[0]
                    cur_tgt.execute(sql.SQL("SELECT MAX(id) FROM {}").format(sql.Identifier(table)))
                    max_id = cur_tgt.fetchone()[0]
                    if max_id is not None:
                        cur_tgt.execute(f"ALTER SEQUENCE {seq_name} RESTART WITH {max_id + 1}")
            
            conn_tgt.commit()
            print(f"Copied {len(rows)} rows for {table}.")
            
        print("Adding work_centers as locations...")
        # Get all workcenters from target
        cur_tgt.execute("SELECT id, name FROM work_center")
        work_centers = cur_tgt.fetchall()
        
        for wc in work_centers:
            wc_id, wc_name = wc
            # Check if location exists
            cur_tgt.execute("SELECT id FROM location WHERE work_center_id = %s", (wc_id,))
            loc = cur_tgt.fetchone()
            if not loc:
                cur_tgt.execute(
                    "INSERT INTO location (name, description, location_type, work_center_id, is_active, created_at) "
                    "VALUES (%s, %s, 'WORK_CENTER', %s, true, NOW())",
                    (wc_name, f"Location for work center {wc_name}", wc_id)
                )
                # Omit print with wc_name to avoid encode issues
        
        conn_tgt.commit()
        print("Successfully added work centers as locations.")
            
    except Exception as e:
        print("Error during migration:", e)
        conn_tgt.rollback()
    finally:
        cur_src.close()
        cur_tgt.close()
        conn_src.close()
        conn_tgt.close()

if __name__ == '__main__':
    main()
