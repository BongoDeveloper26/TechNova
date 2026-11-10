-- HECHO: foto del stock por producto y ubicación

select
    s.id_producto,
    s.id_ubicacion,
    s.fecha_actualizacion::date                       as fecha_foto,
    s.cantidad,
    s.stock_minimo,
    greatest(s.stock_minimo - s.cantidad, 0)          as unidades_faltan,
    case
        when s.cantidad = 0                     then 'ROTURA'
        when s.cantidad < s.stock_minimo / 2.0  then 'CRITICO'
        when s.cantidad < s.stock_minimo        then 'BAJO'
        else 'OK'
    end                                               as nivel_alerta,
    s.cantidad * p.coste                              as valor_stock_eur
from {{ ref('stg_stock') }} s
join {{ ref('stg_productos') }} p on p.id_producto = s.id_producto
