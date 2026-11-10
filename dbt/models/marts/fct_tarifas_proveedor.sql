-- HECHO: precio diario que pide cada proveedor por cada producto (de los CSV)

select
    to_char(t.fecha_tarifa, 'YYYYMMDD')::int                            as id_fecha,
    t.fecha_tarifa,
    t.id_proveedor,
    p.id_producto,
    t.moneda,
    t.precio_coste                                                      as precio_moneda_original,
    t.tipo_cambio,
    t.precio_coste_eur,
    p.coste                                                             as coste_referencia_eur,
    round(100 * (t.precio_coste_eur / p.coste - 1), 2)                  as desviacion_pct,
    t.stock_disponible,
    t.plazo_entrega_dias
from {{ ref('stg_tarifas_proveedor') }} t
join {{ ref('stg_productos') }} p on p.sku = t.sku
