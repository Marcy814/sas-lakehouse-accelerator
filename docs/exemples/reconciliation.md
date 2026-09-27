# Rapport de réconciliation SAS → Lakehouse

**8/8 jeux de données conformes.**

| Jeu legacy | Table cible | Lignes legacy | Lignes cible | Absentes | En trop | Colonnes en écart | Statut |
|---|---|---|---|---|---|---|---|
| `dwh.clients_courants` | `gold.mart_clients_courants` | 6020 | 6020 | 0 | 0 | - | ✅ |
| `dwh.polices_courantes` | `silver.silver_polices` | 11020 | 11020 | 0 | 0 | - | ✅ |
| `dwh.sinistres_enrichis` | `gold.mart_sinistres_enrichis` | 6454 | 6454 | 0 | 0 | - | ✅ |
| `dwh.ratio_sinistralite` | `gold.mart_ratio_sinistralite` | 9 | 9 | 0 | 0 | - | ✅ |
| `dwh.indicateurs_fraude` | `gold.mart_indicateurs_fraude` | 6454 | 6454 | 0 | 0 | - | ✅ |
| `dwh.sinistres_regles` | `gold.mart_sinistres_regles` | 4872 | 4872 | 0 | 0 | - | ✅ |
| `dwh.grands_sinistres` | `gold.mart_grands_sinistres` | 8 | 8 | 0 | 0 | - | ✅ |
| `dwh.primes_mensuelles` | `gold.mart_primes_mensuelles` | 363 | 363 | 0 | 0 | - | ✅ |

## Sommes de contrôle (colonnes numériques)

| Jeu | Colonne | Somme legacy | Somme cible |
|---|---|---|---|
| `dwh.clients_courants` | age | 298,376.00 | 298,376.00 |
| `dwh.polices_courantes` | prime_annuelle | 15,966,511.36 | 15,966,511.36 |
| `dwh.sinistres_enrichis` | montant_reclame | 16,017,941.13 | 16,017,941.13 |
| `dwh.sinistres_enrichis` | montant_paye | 9,040,478.46 | 9,040,478.46 |
| `dwh.sinistres_enrichis` | delai_declaration | 104,293.00 | 104,293.00 |
| `dwh.sinistres_enrichis` | taux_paiement | 3,625.83 | 3,625.83 |
| `dwh.sinistres_enrichis` | annee_sinistre | 13,061,164.00 | 13,061,164.00 |
| `dwh.ratio_sinistralite` | primes_acquises | 9,497,364.29 | 9,497,364.29 |
| `dwh.ratio_sinistralite` | nb_sinistres | 3,702.00 | 3,702.00 |
| `dwh.ratio_sinistralite` | total_reclame | 9,283,342.89 | 9,283,342.89 |
| `dwh.ratio_sinistralite` | total_paye | 5,307,993.69 | 5,307,993.69 |
| `dwh.ratio_sinistralite` | ratio_sinistralite | 4.77 | 4.77 |
| `dwh.indicateurs_fraude` | nb_sinistres_cumul | 12,149.00 | 12,149.00 |
| `dwh.indicateurs_fraude` | montant_cumul | 30,146,583.16 | 30,146,583.16 |
| `dwh.indicateurs_fraude` | jours_depuis_precedent | 892,694.00 | 892,694.00 |
| `dwh.indicateurs_fraude` | flag_rapproche | 606.00 | 606.00 |
| `dwh.indicateurs_fraude` | flag_debut_police | 443.00 | 443.00 |
| `dwh.indicateurs_fraude` | flag_declaration_tardive | 223.00 | 223.00 |
| `dwh.indicateurs_fraude` | score_risque | 45,320.00 | 45,320.00 |
| `dwh.sinistres_regles` | mois_sinistre | 985,982,846.00 | 985,982,846.00 |
| `dwh.sinistres_regles` | montant_paye | 8,733,689.00 | 8,733,689.00 |
| `dwh.sinistres_regles` | franchise | 3,477,000.00 | 3,477,000.00 |
| `dwh.sinistres_regles` | montant_net | 5,830,675.56 | 5,830,675.56 |
| `dwh.sinistres_regles` | ratio_prime | 6,441.38 | 6,441.38 |
| `dwh.grands_sinistres` | mois_sinistre | 1,618,851.00 | 1,618,851.00 |
| `dwh.grands_sinistres` | montant_net | 303,789.46 | 303,789.46 |
| `dwh.primes_mensuelles` | nb_polices | 10,980.00 | 10,980.00 |
| `dwh.primes_mensuelles` | primes_emises | 15,910,813.85 | 15,910,813.85 |
| `dwh.primes_mensuelles` | prime_moyenne | 459,250.92 | 459,250.92 |
