{#
  Test genérico propio: falla si alguna fila tiene un valor negativo en la columna.
  Uso en un .yml:
      columns:
        - name: importe_neto
          data_tests:
            - no_negativo
#}
{% test no_negativo(model, column_name) %}
    select *
    from {{ model }}
    where {{ column_name }} < 0
{% endtest %}
