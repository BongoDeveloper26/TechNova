select
    id_devolucion,
    id_linea,
    cantidad,
    motivo,
    fecha       as fecha_devolucion,
    estado,
    importe_reembolso
from {{ source('staging', 'oltp_devolucion') }}
