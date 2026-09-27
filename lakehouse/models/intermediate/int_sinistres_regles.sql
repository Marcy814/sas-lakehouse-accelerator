{#- Source Qualifier + Lookup + Expression de m_sinistres_regles, avant l'aiguillage du Router -#}

with sinistres_fermes as (
    select sinistre_id, police_id, produit, date_sinistre, montant_paye
    from {{ ref('mart_sinistres_enrichis') }}
    where statut = 'FERME'
),

avec_prime as (
    select s.*, p.prime_annuelle
    from sinistres_fermes as s
    left join {{ ref('dim_police') }} as p on s.police_id = p.police_id
),

calculs as (
    select
        *,
        {{ annee_mois('date_sinistre') }}                                    as mois_sinistre,
        case produit when 'AUTO' then 500 when 'HABITATION' then 1000 else 0 end as franchise
    from avec_prime
)

select
    sinistre_id,
    produit,
    mois_sinistre,
    montant_paye,
    cast(franchise as decimal(12, 2))                                        as franchise,
    case
        when montant_paye is null then 0
        when montant_paye - franchise < 0 then 0
        else montant_paye - franchise
    end                                                                      as montant_net,
    round(cast(montant_paye as double) / nullif(cast(prime_annuelle as double), 0), 6) as ratio_prime
from calculs
