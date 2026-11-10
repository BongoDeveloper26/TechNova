select
    id_pago,
    id_pedido,
    metodo,
    importe,
    fecha       as fecha_pago,
    estado
from {{ source('staging', 'oltp_pago') }}
