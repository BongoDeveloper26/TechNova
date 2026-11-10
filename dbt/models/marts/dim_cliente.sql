-- Situación ACTUAL de cada cliente (el historial de cambios está en snp_clientes)

with direccion_principal as (
    select d.id_cliente, c.ciudad, c.provincia
    from {{ ref('stg_direcciones') }} d
    join {{ ref('stg_ciudades') }} c on c.id_ciudad = d.id_ciudad
    where d.es_principal
)

select
    c.id_cliente,
    c.nombre_completo,
    c.email,
    c.fecha_nacimiento,
    extract(year from age(current_date, c.fecha_nacimiento))::int  as edad,
    case
        when extract(year from age(current_date, c.fecha_nacimiento)) < 25 then '18-24'
        when extract(year from age(current_date, c.fecha_nacimiento)) < 35 then '25-34'
        when extract(year from age(current_date, c.fecha_nacimiento)) < 45 then '35-44'
        when extract(year from age(current_date, c.fecha_nacimiento)) < 55 then '45-54'
        when extract(year from age(current_date, c.fecha_nacimiento)) < 65 then '55-64'
        else '65+'
    end                                                     as rango_edad,
    c.fecha_registro,
    dp.ciudad,
    dp.provincia,
    n.nivel                                                 as nivel_fidelidad,
    c.puntos,
    coalesce(r.segmento_rfm, 'Sin compras')                 as segmento_rfm,
    r.r_score,
    r.f_score,
    r.m_score,
    r.primera_compra,
    r.ultima_compra,
    r.dias_sin_comprar,
    coalesce(r.num_pedidos, 0)                              as num_pedidos,
    coalesce(r.gasto_total, 0)                              as gasto_total,
    r.canal_preferido
from {{ ref('stg_clientes') }} c
join {{ ref('stg_niveles_fidelidad') }} n  on n.id_nivel    = c.id_nivel
left join direccion_principal           dp on dp.id_cliente = c.id_cliente
left join {{ ref('int_clientes_rfm') }} r  on r.id_cliente  = c.id_cliente
