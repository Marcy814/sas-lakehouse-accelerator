# Accélérateur de modernisation de données : SAS, Informatica, DataStage, Cognos → Lakehouse

Migration de bout en bout d'un entrepôt actuariel d'assureur, construit sur **SAS 9**, **Informatica
PowerCenter**, **IBM DataStage** et **IBM Cognos**, vers un **lakehouse médaillon** (bronze / silver / gold)
avec **dbt**. Le projet est exécutable en local sur DuckDB et portable vers **Databricks** et **Snowflake**.
Il inclut :

- une **analyse statique multi-outils** : inventaire, lignage inter-outils, vagues de migration, complexité,
  pièges et évaluation **SAS Viya** ;
- une **réconciliation automatique ligne à ligne** avec les sorties legacy (8 tables, 0 écart), bloquante en CI ;
- un **projet dbt multiplateforme** : macros `adapter.dispatch` pour DuckDB, Databricks et Snowflake,
  compilation vérifiée avec les adaptateurs réels ;
- du **streaming** en micro-lots : checkpoint, filigrane (watermark), dédoublonnage, exactly-once, alertes ;
- un **pipeline d'apprentissage machine** : table de caractéristiques dbt, modèle de fraude suivi avec
  **MLflow**, comparé aux règles SAS ;
- deux **agents IA** : conversion SAS → dbt auto-corrigée par réconciliation, et analyste text-to-SQL avec
  garde-fous et budget ;
- l'**infrastructure en code** : **Terraform Azure** (ADLS Gen2, Databricks en VNet injection, Key Vault,
  private endpoints, identités managées, RBAC, budget) et **AWS** (S3 + KMS, Glue, IAM, budget), avec scan
  **checkov** ;
- l'**orchestration de production** avec un **Databricks Asset Bundle** (Auto Loader, dbt, streaming, ML,
  maintenance Delta), les jobs PySpark étant testés sur Spark local.

Exemples de rapports : [inventaire du parc](docs/exemples/estate_inventory.md) ·
[inventaire SAS](docs/exemples/sas_inventory.md) · [réconciliation](docs/exemples/reconciliation.md) ·
[portabilité](docs/exemples/portability.md) · [fiche modèle ML](docs/exemples/ml_fraude.md).

---

## Le problème

Un assureur exploite depuis 2012 une chaîne de nuit qui alimente l'actuariat :

- **quatre programmes SAS** : clients courants, sinistres enrichis, ratio de sinistralité, indicateurs de fraude ;
- **un mapping Informatica** : sinistres réglés et aiguillage des grands sinistres vers la réassurance ;
- **un job DataStage** : primes mensuelles ;
- **un rapport Cognos** qui consomme le tout.

Il faut tout migrer **sans changer un seul chiffre**, puis ouvrir les données à des usages d'IA.

Les trois vrais risques d'une telle migration sont rarement techniques :

1. **Ne pas savoir ce qu'on migre** : dépendances entre outils, code mort, logique cachée dans les outils ETL.
2. **Changer le comportement sans le voir** : valeurs manquantes SAS, Router Informatica, lookup DataStage,
   ratio « calculé » Cognos.
3. **Ne pas pouvoir le prouver** au métier et à l'audit.



## Démarrage rapide

Prérequis : Python 3.11+ et Git.

```bash
python -m venv .venv
# Windows : .venv\Scripts\activate    |    macOS/Linux : source .venv/bin/activate
python -m pip install -e ".[dev,ml]"

python pipeline.py run-all        # génération → inventaire → ingestion → dbt (2 lots) → legacy → réconciliation
python pipeline.py demo-pitfall   # ce que la réconciliation attrape sur une conversion naïve
python pipeline.py train-fraud    # modèle de fraude + MLflow
python pipeline.py stream         # 6 micro-lots d'événements
python -m pytest
```

Options supplémentaires :

- `python -m pip install -e ".[portability]"` puis `python pipeline.py portability` : compile le projet dbt
  pour Databricks et Snowflake, hors ligne.
- Les agents IA fonctionnent avec **OpenAI** ou **Anthropic** : copier `.env.example` vers `.env` et y
  renseigner la clé.

## Commandes

| Commande | Rôle |
|---|---|
| `generate` | Deux lots d'extraits réalistes (6 000 clients, 11 000 polices, 7 000 sinistres, 2 200 enquêtes) avec anomalies volontaires |
| `analyze` | Inventaire SAS (dont SAS Viya) et inventaire du parc multi-outils, lignage et vagues |
| `ingest [--batch N]` | Chargement idempotent dans bronze |
| `transform [--full-refresh]` | `dbt build` : 17 modèles, snapshot SCD2 et plus de 80 tests de données |
| `legacy` | Tables de référence des traitements SAS, Informatica et DataStage |
| `reconcile` | Réconciliation → `reports/reconciliation.md`, code de sortie ≠ 0 en cas d'écart |
| `demo-pitfall` | Conversion naïve comparée à la conversion dbt |
| `portability` | Compilation dbt pour Databricks et Snowflake, analyse syntaxique du SQL compilé |
| `stream [--batches N]` | Événements de sinistres traités en micro-lots |
| `train-fraud` | Modèle de fraude, suivi MLflow, scores écrits en gold, fiche modèle |
| `migrate <programme>` | Conversion SAS → dbt par agent IA |
| `ask "<question>"` | Question métier à l'agent analytique |

## Méthodologie de migration

| Phase | Outil du dépôt | Livrable |
|---|---|---|
| 1. Inventaire | `sas_analyzer.py`, `legacy_estate.py` | Entrées/sorties de chaque programme, mapping, job et rapport; lignage inter-outils |
| 2. Évaluation | idem | Complexité, effort, pièges localisés, patron cible, compatibilité SAS Viya, **vagues** |
| 3. Conversion | `lakehouse/`, `migration_agent.py` | Modèles dbt multiplateformes, en partie proposés par l'agent |
| 4. Réconciliation | `reconciliation.py` | Lignes, clés absentes/en trop, écarts par colonne avec tolérance, sommes de contrôle |
| 5. Revue et bascule | CI + rapports | Porte de qualité bloquante, points de revue humaine |

## Pièges traités, par outil

| Outil | Piège | Traduction naïve | Traitement |
|---|---|---|---|
| SAS | `if age < 30` est **vrai** si `age` est manquant | `NULL < 30` → branche `else` | Macro `sas_lt()` |
| SAS | `intck('year', …, 'c')` = années révolues | `date_diff('year')` : +1 an pour ~50 % des clients | Macro `age_revolu()` (par plateforme) |
| SAS | `MIN`/`MAX` à plusieurs arguments dans PROC SQL | Agrégats | `least()` / `greatest()` |
| SAS | `RETAIN` / somme cumulée | Cadre `RANGE` : ex æquo additionnés | Cadre `ROWS` et tri total |
| SAS | `LAG`, `FIRST.`, `MERGE IN=`, boucles `%do` | — | Fenêtres, `left join`, boucle Jinja |
| Informatica | **Router** : une ligne d'un groupe ne va pas dans le groupe par défaut | Tout charger dans la table par défaut | Un modèle par groupe + test de partition complète |
| Informatica | Colonne cible `NUMBER(12,6)` : arrondi à l'écriture | Division non arrondie | `round(…, 6)` explicite |
| Informatica | Lookup « Use Any Value », `DECODE`, `IIF`, session « Update else Insert » | — | Test d'unicité, `CASE`, modèle incrémental |
| DataStage | Lookup en échec « Continue » | `INNER JOIN` | `LEFT JOIN` + `coalesce` |
| DataStage | Variable d'étape dépendante de la ligne précédente | — | Détectée; ici code mort, supprimé |
| Cognos | Élément calculé à agrégat « calculated » = ratio des sommes | Moyenne des ratios | Métrique `ratio` de la couche sémantique dbt |
| Cognos | « Prime moyenne » = moyenne de moyennes | — | Moyenne pondérée (somme / nombre) |

`python pipeline.py demo-pitfall` montre l'effet concret : la conversion naïve de `01_clients_courants.sas`
produit **2 953 âges faux et 232 tranches d'âge fausses** sur 6 020 clients; la conversion dbt, aucun.

## Portabilité multiplateforme

Les fonctions propres à une plateforme passent par des macros `adapter.dispatch`. Chaque macro a une
version DuckDB, une version Databricks et une version Snowflake : `propcase`, `age_revolu`, `jours_diff`,
`to_date_id`, `annee_mois`, `make_date`, `jours_entre` (épine de dates), `union_par_nom`. Les
configurations de performance sont propres à chaque cible : `liquid_clustered_by` sur Databricks,
`cluster_by` sur Snowflake, et stratégie incrémentale `merge` sur les deux.

`python pipeline.py portability` compile le projet avec les **vrais adaptateurs** dbt-databricks et
dbt-snowflake, sans connexion. Il analyse ensuite le SQL compilé dans le dialecte de chaque cible et
recherche les fonctions DuckDB résiduelles. Résultat : **17/17 modèles portables** sur chaque plateforme.

## Streaming

`src/accelerator/streaming.py` en local (DuckDB) et `databricks/src/streaming_sinistres.py` sur Databricks
(Structured Streaming) appliquent les mêmes principes :

- **checkpoint** écrit dans la même transaction que les données, donc exactly-once ;
- **filigrane** (watermark) de 30 minutes pour écarter les événements trop tardifs ;
- **dédoublonnage** des événements renvoyés par le bus ;
- **agrégats** par fenêtres de 15 minutes, recalculés pour les seules fenêtres touchées ;
- **alertes** au-delà d'un seuil. Le lot 4 simule une tempête au Québec et déclenche une alerte.

## Apprentissage machine

- **Étiquettes** : les conclusions de l'unité des enquêtes spéciales, avec un biais de sélection réaliste.
- **Caractéristiques** : la table `gold.ml_features_fraude`, produite par dbt.
- **Méthode** : découpage temporel, régression logistique, comparaison au score à base de règles hérité
  de SAS, puis suivi MLflow et fiche modèle.
- **Résultat** sur le jeu de test : AUC **0,72** contre **0,67** pour les règles ; précision au top 10 %
  de **54 %** contre **49 %**.
- **Sur Databricks** : le même cœur (`fit_and_score`) lit la table Unity Catalog et enregistre le modèle
  dans Unity Catalog (`databricks/src/entrainement_fraude.py`).

## Qualité des données

- **Tests génériques** : unicité, non-nullité, valeurs acceptées, intégrité référentielle.
- **Tests personnalisés** : `scd2_sans_chevauchement`, `valeur_entre`.
- **Tests singuliers** : conservation des montants silver → gold, aucune version périmée, partition
  complète du Router Informatica.
- **Sinistres orphelins** : conservés en silver et signalés en *warning*.

## Agents IA

**L'agent de migration** convertit un programme SAS en modèle dbt. Il écrit, compile, réconcilie et se
corrige jusqu'à 0 écart. Il n'utilise que des `ref()` autorisés, n'exécute jamais de DDL ni de DML,
écrit dans un bac à sable désactivé par défaut, et sa promotion reste une décision humaine.

**L'agent analytique** fait du text-to-SQL sur le catalogue gold, enrichi des descriptions dbt et d'un
glossaire métier. Ses garde-fous analysent chaque requête avec sqlglot :

- une seule instruction `SELECT` ;
- aucun DDL ni DML (ni `ATTACH`, `COPY` ou `PRAGMA`) ;
- une liste blanche de schémas ;
- aucune fonction de lecture de fichiers ;
- une limite de lignes ;
- aucun nom de table utilisé comme colonne, un piège silencieux de DuckDB ;
- une connexion en lecture seule, sans accès externe.

**Deux fournisseurs** sont pris en charge : OpenAI et Anthropic. **Côté coûts**, chaque exécution mesure
ses jetons, estime son coût et s'arrête au-delà de `MAX_COST_USD`. Les erreurs de clé, de crédit et de
quota produisent un message clair plutôt qu'un plantage.




### Essayer sur Databricks Free Edition

1. Créer un compte gratuit : [Databricks Free Edition](https://www.databricks.com/learn/free-edition).
2. Installer la CLI (`winget install Databricks.DatabricksCLI`) et se connecter :
   `databricks auth login --host https://<votre-espace>.cloud.databricks.com`.
3. Remplacer l'URL `host` de la cible `free` dans `databricks.yml`.
4. Créer la zone d'atterrissage et y déposer le lot 1 (PowerShell) :

```powershell
databricks schemas create bronze workspace
databricks schemas create ml workspace
databricks volumes create workspace bronze landing MANAGED
python pipeline.py generate
foreach ($t in "clients", "polices", "sinistres", "enquetes") {
    databricks fs cp "data/landing/$t/batch_001.csv" "dbfs:/Volumes/workspace/bronze/landing/extraits/$t/batch_001.csv" --overwrite
}
```

5. Déployer et exécuter : `databricks bundle deploy -t free` puis `databricks bundle run lakehouse_nuit -t free`.
6. Déposer les fichiers `batch_002.csv` de la même façon et relancer le job : Auto Loader ne lit que les
   nouveaux fichiers et le snapshot dbt crée l'historique SCD2.

## Correspondance vers la production

| Ici | Azure Databricks | Snowflake | SAS Viya |
|---|---|---|---|
| Zone d'atterrissage | ADLS Gen2 + Azure Data Factory | Stage externe | Caslib |
| `ingestion.py` | Auto Loader (`databricks/src/ingestion_autoloader.py`) | Snowpipe | PROC CASUTIL |
| `streaming.py` | Structured Streaming (`streaming_sinistres.py`) | Snowpipe Streaming + Dynamic Tables | ESP |
| DuckDB + dbt-duckdb | Delta + Unity Catalog + dbt-databricks | dbt-snowflake | Lift-and-shift sur Compute; CAS après ajustements |
| `pipeline.py run-all` | Asset Bundle / Workflows | Tasks | Jobs Viya |
| MLflow local | MLflow + registre Unity Catalog | Snowpark ML | Model Manager |
| `.env` | Key Vault + secret scope | Intégration de secrets | Vault Viya |

## Limites

- **Sorties de référence** : SAS, Informatica et DataStage ne sont pas exécutables hors de l'environnement
  client. `legacy_reference.py` reproduit leur sémantique pour produire ces sorties ; en mission, elles
  sont extraites des systèmes réels.
- **Analyseurs** : ils sont heuristiques. Un parc réel exige de gérer l'expansion des macros SAS, les
  mapplets et paramètres Informatica, les jobs séquence DataStage et le modèle Framework Manager complet.
- **Validation Terraform** : `terraform validate` s'exécute en CI. Le formatage et la syntaxe ont été
  vérifiés avec OpenTofu, python-hcl2 et checkov.
- **Bundle Databricks** : validé contre le schéma de la CLI Databricks; l'exécution réelle se fait sur un
  espace Databricks (Free Edition suffit).
- **Données** : elles sont synthétiques et générées de façon déterministe (`--seed`).

## Structure du dépôt

```
├── pipeline.py                  # CLI unique
├── databricks.yml               # Databricks Asset Bundle
├── legacy/
│   ├── sas/                     # Programmes SAS 9
│   ├── informatica/             # Export PowerCenter (XML)
│   ├── datastage/               # Export DataStage (DSX)
│   └── cognos/                  # Spécification de rapport + correspondance Framework Manager
├── src/accelerator/
│   ├── sas_analyzer.py          # Inventaire SAS, pièges, SAS Viya
│   ├── legacy_estate.py         # Parseurs Informatica, DataStage, Cognos; lignage et vagues
│   ├── legacy_reference.py      # Sorties de référence des traitements legacy
│   ├── ingestion.py, streaming.py, reconciliation.py, portability.py
│   ├── ml/fraud_model.py        # Modèle de fraude + MLflow
│   └── agents/                  # Boucle d'agent (OpenAI/Anthropic), migration, analyste, garde-fous
├── lakehouse/                   # Projet dbt multiplateforme (silver, snapshots, gold, marts, ml, sémantique)
├── databricks/                  # Jobs PySpark (Auto Loader, streaming, ML, maintenance) + ressources + tests
├── infra/azure, infra/aws       # Terraform
├── migration/migration.yml      # Correspondance legacy → dbt, clés, tolérances
├── tests/                       # Tests Python
└── .github/workflows/ci.yml     # Pipeline, portabilité, Spark, Terraform + checkov
```
