select
    id_empleado,
    tipo,
    desde,
    hasta
from {{ source('staging', 'rrhh_ausencia') }}
