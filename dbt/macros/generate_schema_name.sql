{#
  Por defecto dbt llama a los esquemas "<esquema_del_perfil>_<esquema_del_modelo>"
  (por ejemplo "marts_stg"). Con esta macro se usa directamente el nombre
  que pongamos en +schema: stg, int, marts, seeds, snapshots.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
