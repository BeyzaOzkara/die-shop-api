import psycopg2

conn = psycopg2.connect(
    dbname='kaliphaneNew',
    user='arslan',
    password='gqTYe5HdX0VQ',
    host='192.168.150.230',
    port='5432'
)
cur = conn.cursor()
cur.execute("SELECT t.typname, e.enumlabel FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid WHERE t.typname ILIKE '%location%';")
print("Location types:", cur.fetchall())

cur.close()
conn.close()
