-- INFORME: productividad de cada vendedor por mes.
-- Junta tres fuentes que llegan por caminos distintos:
--   ventas (base de datos de la tienda) + horas (Excel de fichajes) + coste (Excel de nóminas)

with ventas as (
    select id_empleado, date_trunc('month', dia)::date as mes,
           count(distinct id_pedido) as pedidos,
           sum(importe_neto)         as ventas
    from {{ ref('fct_ventas') }}
    where canal = 'tienda'
    group by 1, 2
),

horas as (
    select id_empleado, date_trunc('month', fecha)::date as mes,
           count(*)          as dias_trabajados,
           sum(horas)        as horas,
           sum(horas_extra)  as horas_extra
    from {{ ref('fct_jornadas') }}
    group by 1, 2
)

select
    h.mes,
    to_char(h.mes, 'YYYYMMDD')::int                                    as id_fecha,
    e.id_empleado,
    e.empleado,
    e.ubicacion                                                         as tienda,
    h.dias_trabajados,
    h.horas,
    h.horas_extra,
    coalesce(v.pedidos, 0)                                              as pedidos,
    round(coalesce(v.ventas, 0), 2)                                     as ventas,
    round(coalesce(v.ventas, 0) / nullif(h.horas, 0), 2)                as ventas_por_hora,
    n.coste_total,
    round(coalesce(v.ventas, 0) / nullif(n.coste_total, 0), 2)          as ventas_por_euro_de_coste
from horas h
join {{ ref('dim_empleado') }} e on e.id_empleado = h.id_empleado
left join ventas v                  on v.id_empleado = h.id_empleado and v.mes = h.mes
left join {{ ref('fct_nominas') }} n on n.id_empleado = h.id_empleado and n.mes = h.mes
where e.puesto = 'Vendedor'
