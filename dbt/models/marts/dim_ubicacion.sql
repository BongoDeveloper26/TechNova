select
    u.id_ubicacion,
    u.ubicacion,
    u.tipo,
    c.ciudad,
    c.provincia,
    u.fecha_apertura
from {{ ref('stg_ubicaciones') }} u
join {{ ref('stg_ciudades') }} c on c.id_ciudad = u.id_ciudad
