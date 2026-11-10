select
    id_categoria,
    nombre,
    id_categoria_padre
from {{ source('staging', 'oltp_categoria') }}
