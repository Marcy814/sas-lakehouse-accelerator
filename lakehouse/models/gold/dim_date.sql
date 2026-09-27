with jours as (
    {{ jours_entre('2018-01-01', '2028-01-01') }}
)

select
    {{ to_date_id('date_jour') }}                           as date_id,
    date_jour,
    year(date_jour)                                         as annee,
    quarter(date_jour)                                      as trimestre,
    month(date_jour)                                        as mois,
    {{ nom_mois('month(date_jour)') }}                      as nom_mois,
    {{ jour_semaine_iso('date_jour') }}                     as jour_semaine_iso,
    {{ jour_semaine_iso('date_jour') }} in (6, 7)           as est_fin_de_semaine
from jours
