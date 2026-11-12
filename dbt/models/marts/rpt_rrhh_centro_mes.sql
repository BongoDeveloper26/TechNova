-- INFORME: indicadores de RRHH por centro y mes

with jornadas as (
    select id_ubicacion, date_trunc('month', fecha)::date as mes,
           count(distinct id_empleado)  as empleados_con_fichaje,
           sum(horas)                   as horas,
           sum(horas_extra)             as horas_extra
    from {{ ref('fct_jornadas') }}
    group by 1, 2
),

ausencias as (
    select id_ubicacion, date_trunc('month', fecha)::date as mes,
           count(*) filter (where tipo = 'baja_medica')     as dias_baja,
           count(*) filter (where tipo = 'vacaciones')      as dias_vacaciones,
           count(*) filter (where tipo in ('asuntos_propios', 'permiso')) as dias_permiso
    from {{ ref('fct_ausencias') }}
    group by 1, 2
),

coste as (
    select id_ubicacion, mes, count(*) as plantilla, sum(coste_total) as coste_personal
    from {{ ref('fct_nominas') }}
    group by 1, 2
),

laborables as (
    select date_trunc('month', fecha)::date as mes, count(*) as dias_laborables
    from {{ ref('dim_fecha') }}
    where es_laborable
    group by 1
),

ventas as (
    select id_ubicacion, date_trunc('month', dia)::date as mes, sum(importe_neto) as ventas
    from {{ ref('fct_ventas') }}
    where canal = 'tienda'
    group by 1, 2
)

select
    c.mes,
    to_char(c.mes, 'YYYYMMDD')::int                                          as id_fecha,
    u.id_ubicacion,
    u.ubicacion                                                               as centro,
    u.tipo,
    c.plantilla,
    coalesce(j.horas, 0)                                                      as horas,
    coalesce(j.horas_extra, 0)                                                as horas_extra,
    coalesce(a.dias_baja, 0)                                                  as dias_baja,
    coalesce(a.dias_vacaciones, 0)                                            as dias_vacaciones,
    coalesce(a.dias_permiso, 0)                                               as dias_permiso,
    -- Absentismo = días de baja / días que la plantilla debería haber trabajado
    round(coalesce(a.dias_baja, 0)::numeric / nullif(c.plantilla * l.dias_laborables, 0), 4) as absentismo,
    c.coste_personal,
    round(coalesce(v.ventas, 0), 2)                                           as ventas,
    round(c.coste_personal / nullif(v.ventas, 0), 4)                          as coste_personal_sobre_ventas
from coste c
join {{ ref('dim_ubicacion') }} u on u.id_ubicacion = c.id_ubicacion
join laborables l                  on l.mes = c.mes
left join jornadas  j on j.id_ubicacion = c.id_ubicacion and j.mes = c.mes
left join ausencias a on a.id_ubicacion = c.id_ubicacion and a.mes = c.mes
left join ventas    v on v.id_ubicacion = c.id_ubicacion and v.mes = c.mes
