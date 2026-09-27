-- Les montants payés des sinistres rattachés à une police valide doivent être identiques
-- entre la couche silver et la table de faits.
with silver as (
    select coalesce(sum(s.montant_paye), 0) as total
    from {{ ref('silver_sinistres') }} as s
    inner join {{ ref('silver_polices') }} as p on s.police_id = p.police_id
),

gold as (
    select coalesce(sum(montant_paye), 0) as total from {{ ref('fct_sinistre') }}
)

select silver.total as total_silver, gold.total as total_gold
from silver cross join gold
where silver.total <> gold.total
