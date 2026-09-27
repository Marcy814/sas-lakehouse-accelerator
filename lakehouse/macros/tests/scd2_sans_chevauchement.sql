{% test scd2_sans_chevauchement(model, cle, debut, fin, courant) %}
with versions as (
    select
        {{ cle }} as cle,
        {{ debut }} as debut,
        {{ fin }} as fin,
        {{ courant }} as courant,
        lead({{ debut }}) over (partition by {{ cle }} order by {{ debut }}) as debut_suivant
    from {{ model }}
),
anomalies as (
    select cle, 'intervalle invalide' as probleme from versions where fin <= debut
    union all
    select cle, 'trou ou chevauchement' from versions where debut_suivant is not null and debut_suivant <> fin
    union all
    select cle, 'nombre de versions courantes <> 1' from versions group by cle
    having sum(case when courant then 1 else 0 end) <> 1
)
select * from anomalies
{% endtest %}
