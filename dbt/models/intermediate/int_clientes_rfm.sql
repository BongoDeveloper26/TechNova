-- Segmentación RFM de los clientes que han comprado alguna vez
--   R = Recency   (hace cuánto compró)    F = Frequency (cuántos pedidos)
--   M = Monetary  (cuánto ha gastado)     Cada uno puntúa de 1 a 5 con NTILE(5)

with referencia as (
    select max(dia) as hoy from {{ ref('int_lineas_venta') }}
),

metricas as (
    select
        id_cliente,
        min(dia)                                       as primera_compra,
        max(dia)                                       as ultima_compra,
        count(distinct id_pedido)                      as num_pedidos,
        sum(importe_neto - importe_devuelto)           as gasto_total,
        mode() within group (order by canal)           as canal_preferido
    from {{ ref('int_lineas_venta') }}
    group by id_cliente
),

puntuaciones as (
    select
        m.*,
        r.hoy - m.ultima_compra                                 as dias_sin_comprar,
        ntile(5) over (order by m.ultima_compra)                as r_score,
        ntile(5) over (order by m.num_pedidos, m.gasto_total)   as f_score,
        ntile(5) over (order by m.gasto_total)                  as m_score
    from metricas m
    cross join referencia r
)

select
    *,
    case
        when r_score >= 4 and f_score >= 4 and m_score >= 4 then 'Campeones'
        when f_score >= 4 and m_score >= 3                  then 'Leales'
        when r_score >= 4 and f_score <= 2                  then 'Nuevos'
        when r_score <= 2 and f_score >= 3                  then 'En riesgo'
        when r_score <= 2 and f_score <= 2                  then 'Perdidos'
        else 'Potenciales'
    end as segmento_rfm
from puntuaciones
