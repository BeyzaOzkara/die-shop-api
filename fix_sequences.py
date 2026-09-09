import psycopg2

def fix_sequences():
    try:
        print("Connecting to kaliphane1...")
        conn = psycopg2.connect('postgresql://arslan:gqTYe5HdX0VQ@192.168.150.230:5432/kaliphane1')
        cur = conn.cursor()
        
        # Get all tables in the public schema
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
              AND table_type = 'BASE TABLE';
        """)
        tables = [row[0] for row in cur.fetchall()]
        
        for table in tables:
            # Check if the table has an 'id' column
            cur.execute(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_schema = 'public' 
                  AND table_name = '{table}' 
                  AND column_name = 'id';
            """)
            has_id = cur.fetchone()
            
            if has_id:
                try:
                    # Update sequence to max(id) + 1
                    query = f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), coalesce(max(id), 0) + 1, false) FROM {table};"
                    cur.execute(query)
                    print(f"Updated sequence for table: {table}")
                except Exception as e:
                    # Some tables might not use a serial sequence for 'id', we just skip them
                    conn.rollback()
                    print(f"Skipped table {table} (no sequence associated with 'id')")
                    continue
                
                conn.commit()
                
        print("\nAll applicable sequences have been updated successfully!")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if 'cur' in locals() and cur: cur.close()
        if 'conn' in locals() and conn: conn.close()

if __name__ == "__main__":
    fix_sequences()
