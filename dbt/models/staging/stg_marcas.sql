select
    id_marca,
    nombre      as marca,
    pais_origen
from {{ source('staging', 'oltp_marca') }}
