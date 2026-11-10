select
    id_pedido,
    id_cliente,
    canal,
    id_ubicacion,
    id_empleado,
    id_cupon,
    fecha          as fecha_pedido,
    fecha::date    as dia,
    estado
from {{ source('staging', 'oltp_pedido') }}
