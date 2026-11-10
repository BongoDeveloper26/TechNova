-- Reconciliación: el importe total de fct_ventas tiene que coincidir con el de
-- las líneas de pedido NO canceladas de staging. Si alguna transformación pierde
-- o duplica filas, este test lo detecta. Devuelve una fila si NO cuadra.

with origen as (
    select sum(l.cantidad * l.precio_unitario - l.descuento) as total
    from {{ source('staging', 'oltp_linea_pedido') }} l
    join {{ source('staging', 'oltp_pedido') }} p on p.id_pedido = l.id_pedido
    where p.estado <> 'cancelado'
),
destino as (
    select sum(importe_neto) as total from {{ ref('fct_ventas') }}
)
select origen.total as total_staging, destino.total as total_fct_ventas
from origen, destino
where abs(origen.total - destino.total) > 0.01
