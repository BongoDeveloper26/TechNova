-- Calendario: una fila por día, con todo lo que sirve para analizar por fechas.
-- Se genera con SQL (generate_series), no viene de ninguna tabla.

with dias as (
    select d::date as fecha
    from generate_series(
        '{{ var("fecha_inicio_calendario") }}'::date,
        '{{ var("fecha_fin_calendario") }}'::date,
        interval '1 day'
    ) as d
),

campanias as (
    -- Qué campaña de descuento estaba activa cada día (puede haber dos solapadas)
    select
        d.fecha,
        string_agg(p.campania, ' + ' order by p.fecha_inicio) as campania
    from dias d
    join {{ ref('stg_promociones') }} p
      on d.fecha between p.fecha_inicio and p.fecha_fin
     and p.tipo_descuento = 'porcentaje'
    group by d.fecha
),

black_friday as (
    -- La promo "Black Friday" va de una semana antes al Cyber Monday (BF + 3 días)
    select fecha_fin - 3 as fecha
    from {{ ref('stg_promociones') }}
    where campania = 'Black Friday'
)

select
    to_char(d.fecha, 'YYYYMMDD')::int                    as id_fecha,
    d.fecha,
    extract(year from d.fecha)::int                      as anio,
    extract(quarter from d.fecha)::int                   as trimestre,
    extract(month from d.fecha)::int                     as mes,
    (array['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto',
           'Septiembre','Octubre','Noviembre','Diciembre'])[extract(month from d.fecha)::int] as nombre_mes,
    to_char(d.fecha, 'YYYY-MM')                          as anio_mes,
    extract(week from d.fecha)::int                      as semana_iso,
    extract(day from d.fecha)::int                       as dia_mes,
    extract(isodow from d.fecha)::int                    as dia_semana,      -- 1 = lunes ... 7 = domingo
    (array['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo'])[extract(isodow from d.fecha)::int] as nombre_dia,
    extract(isodow from d.fecha) in (6, 7)               as es_fin_de_semana,
    f.fecha is not null                                  as es_festivo,
    f.festivo                                            as nombre_festivo,
    extract(isodow from d.fecha) < 6 and f.fecha is null as es_laborable,
    c.campania,
    bf.fecha is not null                                 as es_black_friday
from dias d
left join {{ ref('festivos_nacionales') }} f  on f.fecha  = d.fecha
left join campanias                        c  on c.fecha  = d.fecha
left join black_friday                     bf on bf.fecha = d.fecha
