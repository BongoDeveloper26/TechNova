-- HECHO: una fila por empleado y día trabajado (de los Excel de fichajes)

select
    to_char(f.fecha, 'YYYYMMDD')::int        as id_fecha,
    f.fecha,
    f.id_empleado,
    f.id_ubicacion,
    f.entrada,
    f.salida,
    f.pausa_min,
    f.horas,
    least(f.horas, 8)                        as horas_ordinarias,
    greatest(f.horas - 8, 0)                 as horas_extra
from {{ ref('stg_rrhh_fichajes') }} f
