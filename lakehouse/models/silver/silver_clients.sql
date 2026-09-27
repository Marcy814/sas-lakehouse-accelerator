{{ config(unique_key='client_id') }}

with nouveaux as (
    select
        trim(client_id)                                   as client_id,
        {{ propcase('prenom') }}                          as prenom,
        {{ propcase('nom') }}                             as nom,
        try_cast(nullif(trim(date_naissance), '') as date) as date_naissance,
        upper(trim(province))                             as province,
        nullif(trim(ville), '')                           as ville,
        upper(trim(segment))                              as segment,
        cast(date_maj as date)                            as date_maj,
        cast(date_maj as timestamp)                       as date_maj_ts,
        _batch_id,
        _source_file,
        _ingested_at
    from {{ source('bronze', 'clients') }}
    {% if est_incremental() %}
    where _ingested_at > (select max(_ingested_at) from {{ this }})
    {% endif %}
),

candidats as (
    select * from nouveaux
    {% if est_incremental() %}
    {{ union_par_nom() }}
    select * from {{ this }} where client_id in (select client_id from nouveaux)
    {% endif %}
)

select *
from candidats
qualify row_number() over (partition by client_id order by date_maj desc, _ingested_at desc) = 1
