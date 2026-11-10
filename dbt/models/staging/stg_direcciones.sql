select
    id_direccion,
    id_cliente,
    calle,
    codigo_postal,
    id_ciudad,
    es_principal
from {{ source('staging', 'oltp_direccion') }}
