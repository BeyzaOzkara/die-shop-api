import psycopg2

conn = psycopg2.connect(
    dbname='kaliphaneNew',
    user='arslan',
    password='gqTYe5HdX0VQ',
    host='192.168.150.230',
    port='5432'
)
cur = conn.cursor()
cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'location';")
print("Location columns:", cur.fetchall())

cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'work_center';")
print("WorkCenter columns:", cur.fetchall())

cur.close()
conn.close()
