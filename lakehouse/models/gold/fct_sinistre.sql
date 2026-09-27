{{ config(
    liquid_clustered_by=['date_sinistre_id'] if target.type == 'databricks' else none,
    cluster_by=['date_sinistre_id'] if target.type == 'snowflake' else none
) }}

with sinistres as (
    select * from {{ ref('silver_sinistres') }}
),

polices as (
    select * from {{ ref('dim_police') }}
),

clients as (
    select client_sk, client_id, valide_de, valide_jusqua from {{ ref('dim_client') }}
)

select
    s.sinistre_id,
    p.police_sk,
    c.client_sk,
    {{ to_date_id('s.date_sinistre') }}                          as date_sinistre_id,
    {{ to_date_id('s.date_declaration') }}                       as date_declaration_id,
    s.type_sinistre,
    s.statut,
    s.montant_reclame,
    s.montant_paye,
    {{ jours_diff('s.date_sinistre', 's.date_declaration') }} as delai_declaration_jours,
    s.date_maj
from sinistres as s
inner join polices as p
    on s.police_id = p.police_id
left join clients as c
    on  p.client_id = c.client_id
    and s.date_sinistre >= c.valide_de
    and s.date_sinistre <  c.valide_jusqua
