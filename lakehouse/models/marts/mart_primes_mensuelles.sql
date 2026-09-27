{#- Migration de legacy/datastage/j_primes_mensuelles.dsx -#}

with polices as (
    select police_id, client_id, produit, date_debut, prime_annuelle
    from {{ ref('dim_police') }}
    where statut <> 'ANNULEE'
),

avec_segment as (
    select
        p.*,
        coalesce(c.segment, 'INCONNU') as segment
    from polices as p
    left join {{ ref('mart_clients_courants') }} as c on p.client_id = c.client_id
)

select
    {{ annee_mois('date_debut') }}                   as mois_emission,
    trim(produit)                                    as produit,
    segment,
    count(*)                                         as nb_polices,
    sum(coalesce(prime_annuelle, 0))                 as primes_emises,
    avg(cast(coalesce(prime_annuelle, 0) as double)) as prime_moyenne,
    {{ make_date('year(date_debut)', 'month(date_debut)', 1) }} as debut_mois
from avec_segment
group by 1, 2, 3, 7
