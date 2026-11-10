{#
  Test genérico propio: la combinación de varias columnas no se puede repetir
  (para tablas cuya clave son varias columnas a la vez).
#}
{% test unique_combinacion(model, columnas) %}
    select {{ columnas | join(', ') }}, count(*) as repeticiones
    from {{ model }}
    group by {{ columnas | join(', ') }}
    having count(*) > 1
{% endtest %}
