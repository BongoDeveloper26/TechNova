select
    fecha,
    moneda,
    tasa,
    es_interpolado
from {{ source('staging', 'tipo_cambio') }}
