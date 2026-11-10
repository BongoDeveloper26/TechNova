select
    e.id_empleado,
    e.empleado,
    e.puesto,
    u.ubicacion,
    j.empleado                                                  as jefe,
    e.fecha_contratacion,
    extract(year from age(current_date, e.fecha_contratacion))::int as antiguedad_anios
from {{ ref('stg_empleados') }} e
join {{ ref('stg_ubicaciones') }}  u on u.id_ubicacion = e.id_ubicacion
left join {{ ref('stg_empleados') }} j on j.id_empleado = e.id_jefe
