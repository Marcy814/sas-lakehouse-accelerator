{{ config(unique_key='police_id') }}

with nouveaux as (
    select
        trim(police_id)                              as police_id,
        trim(client_id)                              as client_id,
        upper(trim(produit))                         as produit,
        cast(date_debut as date)                     as date_debut,
        cast(date_fin as date)                       as date_fin,
        cast(prime_annuelle as decimal(12, 2))       as prime_annuelle,
        upper(trim(statut))                          as statut,
        cast(date_maj as date)                       as date_maj,
        _batch_id,
        _source_file,
        _ingested_at
    from {{ source('bronze', 'polices') }}
    {% if est_incremental() %}
    where _ingested_at > (select max(_ingested_at) from {{ this }})
    {% endif %}
),

candidats as (
    select * from nouveaux
    {% if est_incremental() %}
    {{ union_par_nom() }}
    select * from {{ this }} where police_id in (select police_id from nouveaux)
    {% endif %}
)

select *
from candidats
qualify row_number() over (partition by police_id order by date_maj desc, _ingested_at desc) = 1
