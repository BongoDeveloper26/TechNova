select
    id_ubicacion,
    nombre      as ubicacion,
    tipo,
    id_ciudad,
    direccion,
    fecha_apertura
from {{ source('staging', 'oltp_ubicacion') }}
