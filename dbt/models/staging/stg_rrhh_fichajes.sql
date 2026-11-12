select
    fecha,
    id_empleado,
    id_ubicacion,
    entrada,
    salida,
    pausa_min,
    horas
from {{ source('staging', 'rrhh_fichaje') }}
