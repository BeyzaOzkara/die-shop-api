import psycopg2

def get_tables(dbname):
    conn = psycopg2.connect(
        dbname=dbname,
        user='arslan',
        password='gqTYe5HdX0VQ',
        host='192.168.150.230',
        port='5432'
    )
    cur = conn.cursor()
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
    tables = cur.fetchall()
    cur.close()
    conn.close()
    return [t[0] for t in tables]

try:
    print('kaliphaneNew tables:', get_tables('kaliphaneNew'))
    print('kaliphaneDemo1 tables:', get_tables('kaliphaneDemo1'))
except Exception as e:
    print('Error:', e)
