-- HECHO: una fila por pedido (cabecera), con pago y envío. Para análisis operativos.

with lineas as (
    select
        id_pedido,
        count(*)                   as num_lineas,
        sum(cantidad)              as unidades,
        sum(importe_neto)          as importe_neto,
        sum(margen)                as margen,
        sum(importe_devuelto)      as importe_devuelto
    from {{ ref('fct_ventas') }}
    group by id_pedido
),

pagos as (
    select
        id_pedido,
        max(metodo) filter (where estado = 'completado')   as metodo_pago,
        count(*)    filter (where estado = 'fallido')      as pagos_fallidos
    from {{ ref('stg_pagos') }}
    group by id_pedido
)

select
    p.id_pedido,
    to_char(p.dia, 'YYYYMMDD')::int                                         as id_fecha,
    p.fecha_pedido,
    p.id_cliente,
    p.id_ubicacion,
    p.id_empleado,
    p.canal,
    p.estado,
    p.id_cupon is not null                                                  as usa_cupon,
    coalesce(l.num_lineas, 0)                                               as num_lineas,
    coalesce(l.unidades, 0)                                                 as unidades,
    coalesce(l.importe_neto, 0)                                             as importe_neto,
    coalesce(l.margen, 0)                                                   as margen,
    coalesce(l.importe_devuelto, 0)                                         as importe_devuelto,
    pa.metodo_pago,
    coalesce(pa.pagos_fallidos, 0)                                          as pagos_fallidos,
    e.transportista,
    e.estado                                                                as estado_envio,
    round(extract(epoch from e.fecha_envio - p.fecha_pedido) / 3600, 1)     as horas_hasta_envio,
    round(extract(epoch from e.fecha_entrega - p.fecha_pedido) / 86400, 2)  as dias_hasta_entrega
from {{ ref('stg_pedidos') }} p
left join lineas                   l  on l.id_pedido  = p.id_pedido
left join pagos                    pa on pa.id_pedido = p.id_pedido
left join {{ ref('stg_envios') }}  e  on e.id_pedido  = p.id_pedido
