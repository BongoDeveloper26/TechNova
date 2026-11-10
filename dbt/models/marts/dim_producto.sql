select
    p.id_producto,
    p.sku,
    p.producto,
    sub.nombre                                      as subcategoria,
    cat.nombre                                      as categoria,
    m.marca,
    m.pais_origen                                   as pais_marca,
    p.precio_venta,
    p.coste,
    p.precio_venta - p.coste                        as margen_unitario,
    round(100 * (p.precio_venta - p.coste) / p.precio_venta, 2) as margen_pct,
    case
        when p.precio_venta < 50   then '1. Menos de 50 €'
        when p.precio_venta < 200  then '2. De 50 a 200 €'
        when p.precio_venta < 500  then '3. De 200 a 500 €'
        when p.precio_venta < 1000 then '4. De 500 a 1.000 €'
        else '5. Más de 1.000 €'
    end                                             as rango_precio,
    p.meses_garantia,
    p.activo,
    p.fecha_alta
from {{ ref('stg_productos') }} p
join {{ ref('stg_categorias') }} sub on sub.id_categoria = p.id_categoria
join {{ ref('stg_categorias') }} cat on cat.id_categoria = sub.id_categoria_padre
join {{ ref('stg_marcas') }}     m   on m.id_marca       = p.id_marca
