# Fiche modèle — détection de fraude (fraude-logreg-20260926)

**Usage prévu** : prioriser les sinistres à transmettre à l'unité des enquêtes spéciales. Aide à la décision uniquement : aucun refus de sinistre automatique.

**Données** : gold.ml_features_fraude; étiquettes = conclusions d'enquête. Entraînement sur les sinistres antérieurs au 2025-07-01, test sur les suivants (découpage temporel).

| Jeu | Lignes | Taux de fraude |
|---|---|---|
| Entraînement | 1904 | 17.6% |
| Test | 349 | 20.3% |

## Performance sur le jeu de test

| Métrique | Modèle | Règles SAS (score_risque) |
|---|---|---|
| roc_auc | 0.717 | 0.672 |
| average_precision | 0.457 | 0.365 |
| precision_top_10pct | 0.543 | 0.400 |

`precision_top_10pct` : proportion de fraudes confirmées parmi les 10 % de sinistres les mieux classés, soit la capacité réelle de l'équipe d'enquête.

## Importance des caractéristiques (permutation, baisse d'AUC)

| Caractéristique | Importance |
|---|---|
| flag_debut_police | 0.1198 |
| flag_rapproche | 0.0312 |
| jours_depuis_precedent | 0.0164 |
| est_vol_ou_incendie | 0.0120 |
| reclame_superieur_3x_prime | 0.0085 |
| type_sinistre | 0.0053 |
| flag_declaration_tardive | 0.0035 |
| nb_sinistres_cumul | 0.0026 |
| province | 0.0025 |
| produit | 0.0009 |
| delai_declaration | 0.0007 |
| age | 0.0005 |
| jours_depuis_debut_police | -0.0001 |
| ratio_reclame_prime | -0.0013 |
| segment | -0.0017 |
| montant_reclame | -0.0072 |

## Limites et surveillance

- Biais de sélection : seuls les sinistres signalés et un échantillon des autres sont enquêtés.
- Les variables province et âge exigent une revue d'équité avant usage en production.
- Surveiller la dérive des caractéristiques et le taux de confirmation des enquêtes chaque mois.

Suivi MLflow : run `29265b68048642e3ad3fb97837bdff3d`. Scores écrits dans gold.ml_scores_fraude (6454 sinistres).
