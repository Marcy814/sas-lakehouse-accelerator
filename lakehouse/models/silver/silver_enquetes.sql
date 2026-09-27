{{ config(unique_key='sinistre_id') }}

with nouveaux as (
    select
        trim(enquete_id)                               as enquete_id,
        trim(sinistre_id)                              as sinistre_id,
        cast(date_ouverture as date)                   as date_ouverture,
        cast(date_conclusion as date)                  as date_conclusion,
        upper(trim(conclusion))                        as conclusion,
        cast(montant_recupere as decimal(12, 2))       as montant_recupere,
        _batch_id,
        _source_file,
        _ingested_at
    from {{ source('bronze', 'enquetes') }}
    {% if est_incremental() %}
    where _ingested_at > (select max(_ingested_at) from {{ this }})
    {% endif %}
),

candidats as (
    select * from nouveaux
    {% if est_incremental() %}
    {{ union_par_nom() }}
    select * from {{ this }} where sinistre_id in (select sinistre_id from nouveaux)
    {% endif %}
)

select *
from candidats
qualify row_number() over (partition by sinistre_id order by date_conclusion desc, _ingested_at desc) = 1
