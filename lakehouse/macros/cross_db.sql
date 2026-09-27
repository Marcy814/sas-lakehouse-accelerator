{#- Macros multiplateformes : le même projet dbt compile pour DuckDB, Databricks et Snowflake. -#}

{% macro to_date_id(expression) -%}
    {{ return(adapter.dispatch('to_date_id')(expression)) }}
{%- endmacro %}

{% macro default__to_date_id(expression) -%}
    cast(strftime({{ expression }}, '%Y%m%d') as integer)
{%- endmacro %}

{% macro databricks__to_date_id(expression) -%}
    cast(date_format({{ expression }}, 'yyyyMMdd') as int)
{%- endmacro %}

{% macro snowflake__to_date_id(expression) -%}
    to_number(to_char({{ expression }}, 'YYYYMMDD'))
{%- endmacro %}


{% macro annee_mois(expression) -%}
    {{ return(adapter.dispatch('annee_mois')(expression)) }}
{%- endmacro %}

{% macro default__annee_mois(expression) -%}
    strftime({{ expression }}, '%Y%m')
{%- endmacro %}

{% macro databricks__annee_mois(expression) -%}
    date_format({{ expression }}, 'yyyyMM')
{%- endmacro %}

{% macro snowflake__annee_mois(expression) -%}
    to_char({{ expression }}, 'YYYYMM')
{%- endmacro %}


{% macro make_date(annee, mois, jour) -%}
    {{ return(adapter.dispatch('make_date')(annee, mois, jour)) }}
{%- endmacro %}

{% macro default__make_date(annee, mois, jour) -%}
    make_date({{ annee }}, {{ mois }}, {{ jour }})
{%- endmacro %}

{% macro snowflake__make_date(annee, mois, jour) -%}
    date_from_parts({{ annee }}, {{ mois }}, {{ jour }})
{%- endmacro %}


{% macro jour_semaine_iso(expression) -%}
    {{ return(adapter.dispatch('jour_semaine_iso')(expression)) }}
{%- endmacro %}

{% macro default__jour_semaine_iso(expression) -%}
    isodow({{ expression }})
{%- endmacro %}

{% macro databricks__jour_semaine_iso(expression) -%}
    (((dayofweek({{ expression }}) + 5) % 7) + 1)
{%- endmacro %}

{% macro snowflake__jour_semaine_iso(expression) -%}
    dayofweekiso({{ expression }})
{%- endmacro %}


{% macro jours_entre(debut, fin_exclue) -%}
    {{ return(adapter.dispatch('jours_entre')(debut, fin_exclue)) }}
{%- endmacro %}

{% macro default__jours_entre(debut, fin_exclue) -%}
    select cast(d as date) as date_jour
    from range(date '{{ debut }}', date '{{ fin_exclue }}', interval 1 day) as t(d)
{%- endmacro %}

{% macro databricks__jours_entre(debut, fin_exclue) -%}
    select explode(sequence(date '{{ debut }}', date_sub(date '{{ fin_exclue }}', 1), interval 1 day)) as date_jour
{%- endmacro %}

{% macro snowflake__jours_entre(debut, fin_exclue) -%}
    select dateadd(day, row_number() over (order by seq4()) - 1, '{{ debut }}'::date) as date_jour
    from table(generator(rowcount => {{ (modules.datetime.date.fromisoformat(fin_exclue) - modules.datetime.date.fromisoformat(debut)).days }}))
{%- endmacro %}


{% macro union_par_nom() -%}
    {{ return(adapter.dispatch('union_par_nom')()) }}
{%- endmacro %}

{% macro default__union_par_nom() -%}
    union all by name
{%- endmacro %}

{% macro databricks__union_par_nom() -%}
    union all
{%- endmacro %}

{% macro snowflake__union_par_nom() -%}
    union all
{%- endmacro %}


{% macro valeurs_en_table(valeurs, colonne) -%}
    {%- for valeur in valeurs %}
    select {{ valeur }} as {{ colonne }}{% if not loop.last %} union all{% endif %}
    {%- endfor %}
{%- endmacro %}


{% macro nom_mois(expression) -%}
    case {{ expression }}
        {%- for nom in ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août',
                        'septembre', 'octobre', 'novembre', 'décembre'] %}
        when {{ loop.index }} then '{{ nom }}'
        {%- endfor %}
    end
{%- endmacro %}


{% macro jours_diff(debut, fin) -%}
    {{ return(adapter.dispatch('jours_diff')(debut, fin)) }}
{%- endmacro %}

{% macro default__jours_diff(debut, fin) -%}
    date_diff('day', {{ debut }}, {{ fin }})
{%- endmacro %}

{% macro databricks__jours_diff(debut, fin) -%}
    datediff({{ fin }}, {{ debut }})
{%- endmacro %}

{% macro snowflake__jours_diff(debut, fin) -%}
    datediff(day, {{ debut }}, {{ fin }})
{%- endmacro %}
