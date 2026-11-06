import os
import psycopg
from dotenv import load_dotenv

load_dotenv()  # lee el archivo .env

conn = psycopg.connect(
    host="localhost",          # desde tu PC es localhost, no "postgres"
    port=5432,
    dbname=os.getenv("POSTGRES_DB"),
    user=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD"),
)

with conn.cursor() as cur:
    cur.execute("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = 'oltp'
    """)
    print("✅ Conectado. Tablas en oltp:", cur.fetchone()[0])

conn.close()