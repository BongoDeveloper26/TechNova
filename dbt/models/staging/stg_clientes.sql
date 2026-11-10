select
    id_cliente,
    nombre,
    apellidos,
    nombre || ' ' || apellidos   as nombre_completo,
    lower(email)                 as email,
    telefono,
    fecha_nacimiento,
    fecha_registro::date         as fecha_registro,
    puntos,
    id_nivel
from {{ source('staging', 'oltp_cliente') }}
