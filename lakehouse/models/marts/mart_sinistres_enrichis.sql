{#- Migration de legacy/sas/02_sinistres_enrichis.sas -#}

with faits as (
    select * from {{ ref('fct_sinistre') }}
),

sinistres as (
    select sinistre_id, police_id, date_sinistre, date_declaration from {{ ref('silver_sinistres') }}
),

polices as (
    select police_sk, police_id, client_id, produit, date_debut from {{ ref('dim_police') }}
),

clients_courants as (
    select client_id, province, segment from {{ ref('mart_clients_courants') }}
)

select
    f.sinistre_id,
    p.police_id,
    p.client_id,
    p.produit,
    c.province,
    c.segment,
    p.date_debut                                           as date_debut_police,
    s.date_sinistre,
    s.date_declaration,
    f.type_sinistre,
    f.statut,
    f.montant_reclame,
    f.montant_paye,
    f.delai_declaration_jours                              as delai_declaration,
    case
        when {{ sas_lt('f.montant_paye', 1000) }} then 'PETIT'
        when f.montant_paye < 10000 then 'MOYEN'
        else 'GRAND'
    end                                                    as tranche_montant,
    cast(f.montant_paye as double) / nullif(cast(f.montant_reclame as double), 0) as taux_paiement,
    year(s.date_sinistre)                                  as annee_sinistre
from faits as f
inner join sinistres as s on f.sinistre_id = s.sinistre_id
inner join polices as p on f.police_sk = p.police_sk
left join clients_courants as c on p.client_id = c.client_id
