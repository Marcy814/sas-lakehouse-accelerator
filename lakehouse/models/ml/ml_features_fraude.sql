{#- Table de caractéristiques (feature table) du modèle de fraude : une ligne par sinistre -#}

with indicateurs as (
    select * from {{ ref('mart_indicateurs_fraude') }}
),

sinistres as (
    select * from {{ ref('mart_sinistres_enrichis') }}
),

polices as (
    select police_id, prime_annuelle from {{ ref('dim_police') }}
),

clients as (
    select client_id, age, segment, province from {{ ref('mart_clients_courants') }}
),

enquetes as (
    select sinistre_id, conclusion from {{ ref('silver_enquetes') }}
)

select
    s.sinistre_id,
    s.date_sinistre,
    s.produit,
    s.type_sinistre,
    c.segment,
    c.province,
    c.age,
    cast(s.montant_reclame as double)                                          as montant_reclame,
    cast(s.montant_reclame as double) / nullif(cast(p.prime_annuelle as double), 0) as ratio_reclame_prime,
    s.delai_declaration,
    {{ jours_diff('s.date_debut_police', 's.date_sinistre') }}        as jours_depuis_debut_police,
    i.jours_depuis_precedent,
    i.nb_sinistres_cumul,
    i.flag_rapproche,
    i.flag_debut_police,
    i.flag_declaration_tardive,
    case when s.type_sinistre in ('VOL', 'INCENDIE') then 1 else 0 end         as est_vol_ou_incendie,
    case when s.montant_reclame > 3 * p.prime_annuelle then 1 else 0 end       as reclame_superieur_3x_prime,
    i.score_risque                                                             as score_regles,
    e.conclusion is not null                                                   as est_enquete,
    case e.conclusion when 'FRAUDE_CONFIRMEE' then 1 when 'NON_FONDEE' then 0 end as etiquette_fraude
from sinistres as s
inner join indicateurs as i on s.sinistre_id = i.sinistre_id
left join polices as p on s.police_id = p.police_id
left join clients as c on s.client_id = c.client_id
left join enquetes as e on s.sinistre_id = e.sinistre_id
