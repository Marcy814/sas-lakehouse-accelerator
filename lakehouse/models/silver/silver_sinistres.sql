{{ config(unique_key='sinistre_id') }}

with nouveaux as (
    select
        trim(sinistre_id)                                        as sinistre_id,
        trim(police_id)                                          as police_id,
        cast(date_sinistre as date)                              as date_sinistre,
        cast(date_declaration as date)                           as date_declaration,
        upper(trim(type_sinistre))                               as type_sinistre,
        cast(montant_reclame as decimal(12, 2))                  as montant_reclame,
        try_cast(nullif(trim(montant_paye), '') as decimal(12, 2)) as montant_paye,
        upper(trim(statut))                                      as statut,
        cast(date_maj as date)                                   as date_maj,
        _batch_id,
        _source_file,
        _ingested_at
    from {{ source('bronze', 'sinistres') }}
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
qualify row_number() over (partition by sinistre_id order by date_maj desc, _ingested_at desc) = 1
