select
    id_empleado,
    nombre || ' ' || apellidos   as empleado,
    puesto,
    id_ubicacion,
    id_jefe,
    fecha_contratacion
from {{ source('staging', 'oltp_empleado') }}
