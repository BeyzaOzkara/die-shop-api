import psycopg2
from psycopg2 import sql
import json

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

def main():
    conn_src = get_connection(source_db)
    cur_src = conn_src.cursor()
    
    cur_src.execute("SELECT * FROM item_category")
    rows = cur_src.fetchall()
    
    if rows:
        row = rows[0]
        for val in row:
            if isinstance(val, dict):
                print("Found dict:", type(val), val)
            elif isinstance(val, list):
                print("Found list:", type(val), val)
                
    cur_src.close()
    conn_src.close()

if __name__ == '__main__':
    main()
