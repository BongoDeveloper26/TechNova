select
    id_nivel,
    nombre      as nivel,
    puntos_minimos,
    descuento_pct
from {{ source('staging', 'oltp_nivel_fidelidad') }}
