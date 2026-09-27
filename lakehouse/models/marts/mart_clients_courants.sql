{#- Migration de legacy/sas/01_clients_courants.sas -#}

with clients as (
    select
        *,
        {{ age_revolu('date_naissance', "'" ~ var('date_ref') ~ "'") }} as age
    from {{ ref('dim_client') }}
    where est_courant
)

select
    client_id,
    nom_complet,
    date_naissance,
    age,
    case
        when {{ sas_lt('age', 30) }} then '18-29'
        when age < 50 then '30-49'
        when age < 65 then '50-64'
        else '65+'
    end as tranche_age,
    province,
    ville,
    segment,
    date_maj
from clients
