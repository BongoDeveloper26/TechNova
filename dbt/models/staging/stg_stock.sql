select
    id_producto,
    id_ubicacion,
    cantidad,
    stock_minimo,
    fecha_actualizacion
from {{ source('staging', 'oltp_stock') }}
