-- HECHO: una fila por empleado y DÍA LABORABLE de ausencia.
-- Los Excel traen periodos (del 3 al 14); aquí se "despliegan" en días sueltos
-- para poder sumar días de ausencia por mes, centro o tipo.
-- Si dos ausencias se solapan (una baja durante las vacaciones), cuenta una sola
-- por día, con esta prioridad: baja médica > permiso > asuntos propios > vacaciones.

with dias as (
    select
        d.id_fecha,
        d.fecha,
        a.id_empleado,
        e.id_ubicacion,
        a.tipo,
        case a.tipo
            when 'baja_medica'     then 1
            when 'permiso'         then 2
            when 'asuntos_propios' then 3
            else 4
        end as prioridad
    from {{ ref('stg_rrhh_ausencias') }} a
    join {{ ref('dim_fecha') }}     d on d.fecha between a.desde and a.hasta
    join {{ ref('stg_empleados') }} e on e.id_empleado = a.id_empleado
    where d.es_laborable
)

select distinct on (id_empleado, fecha)
    id_fecha, fecha, id_empleado, id_ubicacion, tipo
from dias
order by id_empleado, fecha, prioridad
