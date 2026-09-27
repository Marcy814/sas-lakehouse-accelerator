-- Le Router Informatica répartit chaque sinistre réglé dans exactement un groupe.
with repartition as (
    select sinistre_id from {{ ref('mart_sinistres_regles') }}
    union all
    select sinistre_id from {{ ref('mart_grands_sinistres') }}
)

select i.sinistre_id
from {{ ref('int_sinistres_regles') }} as i
left join repartition as r using (sinistre_id)
group by i.sinistre_id
having count(r.sinistre_id) <> 1
