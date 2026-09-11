import psycopg2

try:
    conn_old = psycopg2.connect('postgresql://arslan:gqTYe5HdX0VQ@192.168.150.230:5432/kaliphane')
    cur_old = conn_old.cursor()
    cur_old.execute("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'domain_action_log'
    """)
    cols_old = cur_old.fetchall()
    print('OLD DB COLUMNS (kaliphane):', cols_old)
except Exception as e:
    print('Error connecting to kaliphane:', e)

try:
    conn_new = psycopg2.connect('postgresql://arslan:gqTYe5HdX0VQ@192.168.150.230:5432/kaliphane1')
    cur_new = conn_new.cursor()
    cur_new.execute("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'domain_action_log'
    """)
    cols_new = cur_new.fetchall()
    print('NEW DB COLUMNS (kaliphane1):', cols_new)
except Exception as e:
    print('Error connecting to kaliphane1:', e)
