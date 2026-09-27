{#- Migration de legacy/informatica/m_sinistres_regles.xml (groupe GRANDS du Router) -#}

select
    sinistre_id,
    produit,
    mois_sinistre,
    montant_net
from {{ ref('int_sinistres_regles') }}
where montant_net >= {{ var('seuil_grand_sinistre') }}
