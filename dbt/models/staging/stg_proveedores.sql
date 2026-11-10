select
    id_proveedor,
    nombre      as proveedor,
    cif,
    pais,
    moneda
from {{ source('staging', 'oltp_proveedor') }}
