-- HECHO: una fila por empleado y mes (del Excel de la gestoría)

select
    to_char(n.mes, 'YYYYMMDD')::int     as id_fecha,
    n.mes,
    n.id_empleado,
    e.id_ubicacion,
    n.salario_base,
    n.plus_ventas,
    n.horas_extra,
    n.importe_horas_extra,
    n.total_devengado,
    n.ss_empresa,
    n.coste_total
from {{ ref('stg_rrhh_nominas') }} n
join {{ ref('stg_empleados') }} e on e.id_empleado = n.id_empleado
