select
    id_proveedor,
    proveedor,
    cif,
    pais,
    moneda,
    moneda = 'EUR'   as factura_en_euros
from {{ ref('stg_proveedores') }}
