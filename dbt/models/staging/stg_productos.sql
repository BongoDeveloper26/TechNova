select
    id_producto,
    sku,
    nombre      as producto,
    id_categoria,
    id_marca,
    precio_venta,
    coste,
    meses_garantia,
    activo,
    fecha_alta
from {{ source('staging', 'oltp_producto') }}
