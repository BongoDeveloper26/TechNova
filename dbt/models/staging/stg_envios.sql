select
    id_envio,
    id_pedido,
    id_direccion,
    transportista,
    fecha_envio,
    fecha_entrega,
    estado
from {{ source('staging', 'oltp_envio') }}
