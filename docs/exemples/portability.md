# Portabilité du projet dbt

Compilation avec l'adaptateur réel de chaque plateforme (sans connexion), puis analyse syntaxique du SQL compilé dans le dialecte cible et recherche de fonctions propres à DuckDB.

## databricks — 17/17 modèles portables

| Modèle | Syntaxe | Fonctions DuckDB résiduelles |
|---|---|---|
| `dim_client` | ✅ | - |
| `dim_date` | ✅ | - |
| `dim_police` | ✅ | - |
| `fct_sinistre` | ✅ | - |
| `int_sinistres_regles` | ✅ | - |
| `mart_clients_courants` | ✅ | - |
| `mart_grands_sinistres` | ✅ | - |
| `mart_indicateurs_fraude` | ✅ | - |
| `mart_primes_mensuelles` | ✅ | - |
| `mart_ratio_sinistralite` | ✅ | - |
| `mart_sinistres_enrichis` | ✅ | - |
| `mart_sinistres_regles` | ✅ | - |
| `ml_features_fraude` | ✅ | - |
| `silver_clients` | ✅ | - |
| `silver_enquetes` | ✅ | - |
| `silver_polices` | ✅ | - |
| `silver_sinistres` | ✅ | - |

## snowflake — 17/17 modèles portables

| Modèle | Syntaxe | Fonctions DuckDB résiduelles |
|---|---|---|
| `dim_client` | ✅ | - |
| `dim_date` | ✅ | - |
| `dim_police` | ✅ | - |
| `fct_sinistre` | ✅ | - |
| `int_sinistres_regles` | ✅ | - |
| `mart_clients_courants` | ✅ | - |
| `mart_grands_sinistres` | ✅ | - |
| `mart_indicateurs_fraude` | ✅ | - |
| `mart_primes_mensuelles` | ✅ | - |
| `mart_ratio_sinistralite` | ✅ | - |
| `mart_sinistres_enrichis` | ✅ | - |
| `mart_sinistres_regles` | ✅ | - |
| `ml_features_fraude` | ✅ | - |
| `silver_clients` | ✅ | - |
| `silver_enquetes` | ✅ | - |
| `silver_polices` | ✅ | - |
| `silver_sinistres` | ✅ | - |
