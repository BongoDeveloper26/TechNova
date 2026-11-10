select
    id_linea,
    id_pedido,
    id_producto,
    cantidad,
    precio_unitario,
    descuento
from {{ source('staging', 'oltp_linea_pedido') }}
