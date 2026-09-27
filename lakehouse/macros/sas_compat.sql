{#- Équivalents SQL de comportements SAS 9 à préserver lors de la migration.
    Chaque macro a une implémentation par plateforme (DuckDB, Databricks, Snowflake) via adapter.dispatch. -#}

{% macro sas_lt(expression, seuil) -%}
    ({{ expression }} is null or {{ expression }} < {{ seuil }})
{%- endmacro %}


{% macro propcase(expression) -%}
    {{ return(adapter.dispatch('propcase')(expression)) }}
{%- endmacro %}

{% macro default__propcase(expression) -%}
    array_to_string(
        list_transform(
            string_split(lower(trim({{ expression }})), ' '),
            mot -> array_to_string(
                list_transform(string_split(mot, '-'), part -> upper(left(part, 1)) || substr(part, 2)),
                '-'
            )
        ),
        ' '
    )
{%- endmacro %}

{% macro databricks__propcase(expression) -%}
    array_join(
        transform(
            split(lower(trim({{ expression }})), ' '),
            mot -> array_join(
                transform(split(mot, '-'), part -> concat(upper(substr(part, 1, 1)), substr(part, 2))),
                '-'
            )
        ),
        ' '
    )
{%- endmacro %}

{% macro snowflake__propcase(expression) -%}
    initcap(lower(trim({{ expression }})), ' -')
{%- endmacro %}


{% macro age_revolu(date_naissance, date_reference) -%}
    {{ return(adapter.dispatch('age_revolu')(date_naissance, date_reference)) }}
{%- endmacro %}

{% macro default__age_revolu(date_naissance, date_reference) -%}
    cast(date_part('year', age(cast({{ date_reference }} as timestamp), cast({{ date_naissance }} as timestamp))) as integer)
{%- endmacro %}

{% macro databricks__age_revolu(date_naissance, date_reference) -%}
    cast(floor(months_between(cast({{ date_reference }} as date), cast({{ date_naissance }} as date)) / 12) as int)
{%- endmacro %}

{% macro snowflake__age_revolu(date_naissance, date_reference) -%}
    datediff(year, {{ date_naissance }}, {{ date_reference }}::date)
        - iff(dateadd(year, datediff(year, {{ date_naissance }}, {{ date_reference }}::date), {{ date_naissance }})
              > {{ date_reference }}::date, 1, 0)
{%- endmacro %}
