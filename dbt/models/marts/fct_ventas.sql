-- HECHO principal: una fila por línea vendida.
--
-- Es INCREMENTAL: la primera vez se construye entera; después solo se recalculan
-- los últimos N días (var dias_reproceso). Así una devolución que llega 2 semanas
-- después de la venta se refleja, sin tener que recalcular 3 años cada noche.

{{ config(
    materialized='incremental',
    unique_key='id_linea',
    incremental_strategy='delete+insert',
    on_schema_change='append_new_columns'
) }}

select
    id_linea,
    id_pedido,
    to_char(dia, 'YYYYMMDD')::int               as id_fecha,
    fecha_pedido,
    id_cliente,
    id_producto,
    id_ubicacion,
    id_empleado,
    canal,
    estado_pedido,
    usa_cupon,
    cantidad,
    precio_unitario,
    importe_bruto,
    descuento,
    importe_neto,
    coste_total,
    importe_neto - coste_total                  as margen,
    unidades_devueltas,
    importe_devuelto,
    importe_neto - importe_devuelto             as importe_neto_final,
    dia
from {{ ref('int_lineas_venta') }}

{% if is_incremental() %}
where dia >= (select max(dia) from {{ this }}) - {{ var('dias_reproceso') }}
{% endif %}
