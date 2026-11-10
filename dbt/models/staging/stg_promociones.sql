select
    id_promocion,
    nombre,
    -- 'Black Friday 2024' -> 'Black Friday' (para agrupar la misma campaña de distintos años)
    regexp_replace(nombre, '\s\d{4}$', '')   as campania,
    tipo_descuento,
    valor,
    fecha_inicio,
    fecha_fin
from {{ source('staging', 'oltp_promocion') }}
