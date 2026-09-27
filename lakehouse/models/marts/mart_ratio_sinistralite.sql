{#- Migration de legacy/sas/03_ratio_sinistralite.sas -#}

with annees as (
    {{ valeurs_en_table(var('annees_ratio'), 'annee') }}
),

primes as (
    select
        p.produit,
        a.annee,
        sum(
            cast(p.prime_annuelle as double)
            * ({{ jours_diff(
                    'greatest(p.date_debut, ' ~ make_date('a.annee', 1, 1) ~ ')',
                    'least(p.date_fin, ' ~ make_date('a.annee', 12, 31) ~ ')') }} + 1)
            / 365
        ) as primes_acquises
    from {{ ref('dim_police') }} as p
    inner join annees as a
        on  p.date_debut <= {{ make_date('a.annee', 12, 31) }}
        and p.date_fin   >= {{ make_date('a.annee', 1, 1) }}
    group by p.produit, a.annee
),

sinistres as (
    select
        produit,
        annee_sinistre           as annee,
        count(*)                 as nb_sinistres,
        sum(montant_reclame)     as total_reclame,
        sum(montant_paye)        as total_paye
    from {{ ref('mart_sinistres_enrichis') }}
    group by produit, annee_sinistre
)

select
    p.produit,
    p.annee,
    {{ make_date('p.annee', 1, 1) }}                             as debut_annee,
    p.primes_acquises,
    case when s.produit is null then 0 else s.nb_sinistres end   as nb_sinistres,
    case when s.produit is null then 0 else s.total_reclame end  as total_reclame,
    case when s.produit is null then 0 else s.total_paye end     as total_paye,
    cast(case when s.produit is null then 0 else s.total_paye end as double)
        / nullif(p.primes_acquises, 0)                           as ratio_sinistralite
from primes as p
left join sinistres as s
    on p.produit = s.produit and p.annee = s.annee
