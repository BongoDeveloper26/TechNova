"""
db.py -> Conexión a PostgreSQL reutilizable.
 
Todos los scripts del generador importan get_connection() de aquí,
así la configuración de la conexión está en un único sitio.
"""
import os
 
import psycopg
from dotenv import load_dotenv
 
load_dotenv()  # lee el archivo .env de la raíz del proyecto
 
 
def get_connection() -> psycopg.Connection:
    """Devuelve una conexión a la base de datos de TechNova."""
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        options="-c search_path=oltp",  # así no hay que escribir oltp. delante de cada tabla
    )