select
    id_ciudad,
    nombre      as ciudad,
    provincia,
    pais
from {{ source('staging', 'oltp_ciudad') }}
