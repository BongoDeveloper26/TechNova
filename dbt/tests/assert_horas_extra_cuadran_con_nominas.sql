-- Las horas extra que paga la gestoría deben coincidir con las de los fichajes.
-- Tolerancia: 2 horas por empleado y mes, porque los fichajes rechazados por el ETL
-- (salida antes que la entrada, sin salida...) no se cuentan aquí pero la gestoría sí los pagó.
-- Si este test falla, o la gestoría está pagando horas que no se han trabajado, o al revés.
{{ config(severity='warn') }}

with fichadas as (
    select id_empleado, date_trunc('month', fecha)::date as mes, sum(horas_extra) as horas_extra
    from {{ ref('fct_jornadas') }}
    group by 1, 2
)
select n.mes, n.id_empleado, n.horas_extra as pagadas, f.horas_extra as fichadas
from {{ ref('fct_nominas') }} n
join fichadas f using (id_empleado, mes)
where abs(n.horas_extra - f.horas_extra) > 2
