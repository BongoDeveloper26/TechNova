-- Una fila por línea de pedido NO cancelado, con el contexto del pedido
-- y lo que se ha devuelto de ella. Es la base de fct_ventas y del RFM.

with devoluciones as (
    -- Solo cuentan las devoluciones en las que se ha devuelto el dinero (o se va a devolver)
    select
        id_linea,
        sum(cantidad)                          as unidades_devueltas,
        sum(coalesce(importe_reembolso, 0))    as importe_devuelto
    from {{ ref('stg_devoluciones') }}
    where estado in ('reembolsada', 'aceptada')
    group by id_linea
)

select
    l.id_linea,
    p.id_pedido,
    p.fecha_pedido,
    p.dia,
    p.canal,
    p.estado                                         as estado_pedido,
    p.id_cliente,
    p.id_ubicacion,
    p.id_empleado,
    p.id_cupon is not null                           as usa_cupon,
    l.id_producto,
    l.cantidad,
    l.precio_unitario,
    l.cantidad * l.precio_unitario                   as importe_bruto,
    l.descuento,
    l.cantidad * l.precio_unitario - l.descuento     as importe_neto,
    l.cantidad * pr.coste                            as coste_total,
    coalesce(d.unidades_devueltas, 0)                as unidades_devueltas,
    coalesce(d.importe_devuelto, 0)                  as importe_devuelto
from {{ ref('stg_lineas_pedido') }} l
join {{ ref('stg_pedidos') }}   p  on p.id_pedido   = l.id_pedido
join {{ ref('stg_productos') }} pr on pr.id_producto = l.id_producto
left join devoluciones          d  on d.id_linea    = l.id_linea
where p.estado <> 'cancelado'
