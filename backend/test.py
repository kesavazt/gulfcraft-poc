import psycopg

try:
    conn = psycopg.connect(
        host="localhost",
        port=5432,
        dbname="gulfcraft",
        user="admin",
        password="secret",
        connect_timeout=5,
    )
    print("✅ Connected to PostgreSQL")

    with conn.cursor() as cur:
        cur.execute("SELECT 1;")
        print("Query result:", cur.fetchone())

    conn.close()

except Exception as e:
    print("❌ Connection failed")
    print(e)

