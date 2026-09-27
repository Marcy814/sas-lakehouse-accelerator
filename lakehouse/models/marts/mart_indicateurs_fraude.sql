{#- Migration de legacy/sas/04_indicateurs_fraude.sas -#}

with sinistres as (
    select
        client_id,
        sinistre_id,
        date_sinistre,
        date_debut_police,
        delai_declaration,
        montant_reclame
    from {{ ref('mart_sinistres_enrichis') }}
),

historique as (
    select
        *,
        row_number() over (partition by client_id order by date_sinistre, sinistre_id)       as nb_sinistres_cumul,
        sum(montant_reclame) over (
            partition by client_id
            order by date_sinistre, sinistre_id
            rows between unbounded preceding and current row
        )                                                                                   as montant_cumul,
        lag(date_sinistre) over (partition by client_id order by date_sinistre, sinistre_id) as date_precedente
    from sinistres
),

indicateurs as (
    select
        *,
        {{ jours_diff('date_precedente', 'date_sinistre') }}                           as jours_depuis_precedent
    from historique
)

select
    client_id,
    sinistre_id,
    date_sinistre,
    nb_sinistres_cumul,
    montant_cumul,
    jours_depuis_precedent,
    case when jours_depuis_precedent <= 30 then 1 else 0 end                                  as flag_rapproche,
    case when {{ jours_diff('date_debut_police', 'date_sinistre') }} <= 30 then 1 else 0 end as flag_debut_police,
    case when delai_declaration > 90 then 1 else 0 end                                        as flag_declaration_tardive,
    40 * (case when jours_depuis_precedent <= 30 then 1 else 0 end)
        + 35 * (case when {{ jours_diff('date_debut_police', 'date_sinistre') }} <= 30 then 1 else 0 end)
        + 25 * (case when delai_declaration > 90 then 1 else 0 end)                           as score_risque
from indicateurs
