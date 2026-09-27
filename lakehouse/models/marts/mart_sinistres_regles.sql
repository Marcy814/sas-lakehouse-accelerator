{#- Migration de legacy/informatica/m_sinistres_regles.xml (groupe DEFAULT du Router) -#}

select
    sinistre_id,
    produit,
    mois_sinistre,
    montant_paye,
    franchise,
    montant_net,
    ratio_prime
from {{ ref('int_sinistres_regles') }}
where not coalesce(montant_net >= {{ var('seuil_grand_sinistre') }}, false)
