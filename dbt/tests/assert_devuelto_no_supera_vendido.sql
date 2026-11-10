-- No se puede devolver más de lo que se vendió (ni en unidades ni en dinero)
select id_linea, cantidad, unidades_devueltas, importe_neto, importe_devuelto
from {{ ref('fct_ventas') }}
where unidades_devueltas > cantidad
   or importe_devuelto > importe_neto + 0.01
