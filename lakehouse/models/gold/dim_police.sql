select
    {{ dbt.hash('police_id') }}                  as police_sk,
    police_id,
    client_id,
    produit,
    statut,
    date_debut,
    date_fin,
    {{ jours_diff('date_debut', 'date_fin') }} + 1 as duree_jours,
    prime_annuelle
from {{ ref('silver_polices') }}
