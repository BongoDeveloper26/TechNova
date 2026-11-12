select
    mes,
    id_empleado,
    salario_base,
    plus_ventas,
    horas_extra,
    importe_horas_extra,
    total_devengado,
    ss_empresa,
    coste_total
from {{ source('staging', 'rrhh_nomina') }}
