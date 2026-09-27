with versions as (
    select
        *,
        row_number() over (partition by client_id order by dbt_valid_from) as no_version
    from {{ ref('snap_clients') }}
)

select
    {{ dbt.hash("client_id || '|' || cast(dbt_valid_from as " ~ dbt.type_string() ~ ")") }} as client_sk,
    client_id,
    prenom,
    nom,
    concat_ws(' ', prenom, nom)                                                    as nom_complet,
    date_naissance,
    province,
    ville,
    segment,
    date_maj,
    no_version,
    case when no_version = 1 then cast('1900-01-01' as date) else cast(dbt_valid_from as date) end as valide_de,
    cast(dbt_valid_to as date)                                                     as valide_jusqua,
    cast(dbt_valid_to as date) = cast('9999-12-31' as date)                        as est_courant
from versions
