select
    fecha_tarifa,
    id_proveedor,
    sku,
    moneda,
    precio_coste,
    tipo_cambio,
    precio_coste_eur,
    stock_disponible,
    plazo_entrega_dias
from {{ source('staging', 'proveedor_tarifa') }}
