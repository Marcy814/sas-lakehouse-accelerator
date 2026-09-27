"""Modèle de détection de fraude entraîné sur la couche gold, suivi avec MLflow.

Découpage temporel (on entraîne sur le passé, on évalue sur les sinistres récents), comparaison
avec le score à base de règles hérité de SAS, écriture des scores dans gold.ml_scores_fraude.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from accelerator import config

CATEGORIELLES = ["produit", "type_sinistre", "segment", "province"]
NUMERIQUES = [
    "age", "montant_reclame", "ratio_reclame_prime", "delai_declaration", "jours_depuis_debut_police",
    "nb_sinistres_cumul", "flag_rapproche", "flag_debut_police", "flag_declaration_tardive",
    "est_vol_ou_incendie", "reclame_superieur_3x_prime",
]
PREMIER_SINISTRE = ["jours_depuis_precedent"]
DATE_COUPURE = date(2025, 7, 1)
TAUX_REVUE = 0.10


@dataclass
class TrainingReport:
    model_version: str
    train_rows: int
    test_rows: int
    fraud_rate_train: float
    fraud_rate_test: float
    metrics: dict[str, float] = field(default_factory=dict)
    baseline_metrics: dict[str, float] = field(default_factory=dict)
    feature_importance: dict[str, float] = field(default_factory=dict)
    mlflow_run_id: str | None = None
    scored_rows: int = 0


def load_features(db_path: Path = config.DB_PATH) -> pd.DataFrame:
    with duckdb.connect(str(db_path), read_only=True) as con:
        return con.execute("select * from gold.ml_features_fraude").df()


def build_pipeline():
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline, make_pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    pretraitement = ColumnTransformer(
        [
            ("cat", make_pipeline(SimpleImputer(strategy="constant", fill_value="INCONNU"),
                                  OneHotEncoder(handle_unknown="ignore")), CATEGORIELLES),
            ("num", make_pipeline(SimpleImputer(strategy="median"), StandardScaler()), NUMERIQUES),
            ("premier", make_pipeline(SimpleImputer(strategy="constant", fill_value=3650), StandardScaler()),
             PREMIER_SINISTRE),
        ],
        verbose_feature_names_out=False,
    )
    modele = LogisticRegression(C=0.5, max_iter=2000)
    return Pipeline([("pretraitement", pretraitement), ("modele", modele)])


def precision_at(y_true: np.ndarray, scores: np.ndarray, taux: float) -> float:
    n = max(1, int(round(len(scores) * taux)))
    ordre = np.argsort(-scores, kind="mergesort")[:n]
    return float(np.mean(y_true[ordre]))


def evaluate(y_true: np.ndarray, scores: np.ndarray) -> dict[str, float]:
    from sklearn.metrics import average_precision_score, roc_auc_score

    return {
        "roc_auc": float(roc_auc_score(y_true, scores)),
        "average_precision": float(average_precision_score(y_true, scores)),
        f"precision_top_{int(TAUX_REVUE * 100)}pct": precision_at(y_true, scores, TAUX_REVUE),
    }


def prepare(donnees: pd.DataFrame) -> pd.DataFrame:
    donnees = donnees.copy()
    donnees[NUMERIQUES + PREMIER_SINISTRE] = donnees[NUMERIQUES + PREMIER_SINISTRE].astype("float64")
    donnees[CATEGORIELLES] = donnees[CATEGORIELLES].astype(object).where(donnees[CATEGORIELLES].notna(), None)
    return donnees


def fit_and_score(donnees: pd.DataFrame):
    """Cœur indépendant de la plateforme : entraîne, évalue, puis score tous les sinistres.

    Utilisé en local (DuckDB) et sur Databricks (databricks/src/entrainement_fraude.py).
    """
    from sklearn.inspection import permutation_importance

    donnees = prepare(donnees)
    etiquetees = donnees[donnees["etiquette_fraude"].notna()].copy()
    etiquetees["etiquette_fraude"] = etiquetees["etiquette_fraude"].astype(int)
    dates = pd.to_datetime(etiquetees["date_sinistre"])
    entrainement, test = etiquetees[dates < pd.Timestamp(DATE_COUPURE)], etiquetees[dates >= pd.Timestamp(DATE_COUPURE)]
    colonnes = CATEGORIELLES + NUMERIQUES + PREMIER_SINISTRE

    pipeline = build_pipeline()
    pipeline.fit(entrainement[colonnes], entrainement["etiquette_fraude"])
    y_test = test["etiquette_fraude"].to_numpy()
    proba_test = pipeline.predict_proba(test[colonnes])[:, 1]

    version = f"fraude-logreg-{date.today():%Y%m%d}"
    rapport = TrainingReport(
        model_version=version,
        train_rows=len(entrainement),
        test_rows=len(test),
        fraud_rate_train=float(entrainement["etiquette_fraude"].mean()),
        fraud_rate_test=float(y_test.mean()),
        metrics=evaluate(y_test, proba_test),
        baseline_metrics=evaluate(y_test, test["score_regles"].to_numpy(dtype=float)),
    )
    importance = permutation_importance(
        pipeline, test[colonnes], y_test, scoring="roc_auc", n_repeats=5, random_state=42
    )
    rapport.feature_importance = dict(sorted(
        zip(colonnes, importance.importances_mean.round(4).tolist()), key=lambda kv: -kv[1]
    ))

    pipeline.fit(etiquetees[colonnes], etiquetees["etiquette_fraude"])
    scores = donnees[["sinistre_id", "score_regles", "est_enquete"]].copy()
    scores["proba_fraude"] = pipeline.predict_proba(donnees[colonnes])[:, 1].round(6)
    scores["rang"] = scores["proba_fraude"].rank(ascending=False, method="first").astype(int)
    scores["a_revoir"] = scores["rang"] <= int(len(scores) * TAUX_REVUE)
    scores["modele_version"] = version
    rapport.scored_rows = len(scores)
    return pipeline, rapport, scores, etiquetees[colonnes].head(5)


def train(db_path: Path = config.DB_PATH, reports_dir: Path = config.REPORTS_DIR,
          tracking_dir: Path = config.ROOT / "mlruns") -> TrainingReport:
    pipeline, rapport, scores, exemple = fit_and_score(load_features(db_path))
    rapport.mlflow_run_id = _log_mlflow(pipeline, rapport, exemple, tracking_dir)
    with duckdb.connect(str(db_path)) as con:
        con.register("scores_df", scores)
        con.execute("create or replace table gold.ml_scores_fraude as select * from scores_df")
    _write_model_card(rapport, reports_dir)
    return rapport


def _log_mlflow(pipeline, rapport: TrainingReport, exemple: pd.DataFrame, tracking_dir: Path) -> str | None:
    try:
        import mlflow
        import mlflow.sklearn
    except ImportError:
        return None
    os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
    tracking_dir.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI") or tracking_dir.resolve().as_uri())
    mlflow.set_experiment("detection_fraude_sinistres")
    with mlflow.start_run(run_name=rapport.model_version) as run:
        mlflow.log_params({
            "algorithme": "LogisticRegression",
            "date_coupure": DATE_COUPURE.isoformat(),
            "caracteristiques": ",".join(CATEGORIELLES + NUMERIQUES + PREMIER_SINISTRE),
            **{k: v for k, v in pipeline.named_steps["modele"].get_params().items() if k in {"C", "max_iter"}},
        })
        mlflow.log_metrics({f"test_{k}": v for k, v in rapport.metrics.items()})
        mlflow.log_metrics({f"regles_{k}": v for k, v in rapport.baseline_metrics.items()})
        log_sklearn_model(pipeline, exemple)
        return run.info.run_id


def log_sklearn_model(pipeline, exemple: pd.DataFrame, registered_model_name: str | None = None) -> None:
    """Journalise le pipeline dans le run MLflow actif (format skops sûr si disponible)."""
    import mlflow.sklearn

    try:
        import skops  # noqa: F401
        options = {"serialization_format": "skops", "skops_trusted_types": ["numpy.dtype"]}
    except ImportError:
        options = {"serialization_format": "cloudpickle"}
    mlflow.sklearn.log_model(pipeline, name="modele", input_example=exemple,
                             registered_model_name=registered_model_name, **options)


def _write_model_card(rapport: TrainingReport, reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "ml_fraude.json").write_text(json.dumps(asdict(rapport), indent=2), encoding="utf-8")
    cle_top = f"precision_top_{int(TAUX_REVUE * 100)}pct"
    lignes = [
        f"# Fiche modèle — détection de fraude ({rapport.model_version})", "",
        "**Usage prévu** : prioriser les sinistres à transmettre à l'unité des enquêtes spéciales. "
        "Aide à la décision uniquement : aucun refus de sinistre automatique.", "",
        "**Données** : gold.ml_features_fraude; étiquettes = conclusions d'enquête. Entraînement sur les "
        f"sinistres antérieurs au {DATE_COUPURE.isoformat()}, test sur les suivants (découpage temporel).", "",
        "| Jeu | Lignes | Taux de fraude |", "|---|---|---|",
        f"| Entraînement | {rapport.train_rows} | {rapport.fraud_rate_train:.1%} |",
        f"| Test | {rapport.test_rows} | {rapport.fraud_rate_test:.1%} |", "",
        "## Performance sur le jeu de test", "",
        "| Métrique | Modèle | Règles SAS (score_risque) |", "|---|---|---|",
        *[f"| {k} | {v:.3f} | {rapport.baseline_metrics[k]:.3f} |" for k, v in rapport.metrics.items()], "",
        f"`{cle_top}` : proportion de fraudes confirmées parmi les {int(TAUX_REVUE * 100)} % de sinistres les "
        "mieux classés, soit la capacité réelle de l'équipe d'enquête.", "",
        "## Importance des caractéristiques (permutation, baisse d'AUC)", "",
        "| Caractéristique | Importance |", "|---|---|",
        *[f"| {k} | {v:.4f} |" for k, v in rapport.feature_importance.items()], "",
        "## Limites et surveillance", "",
        "- Biais de sélection : seuls les sinistres signalés et un échantillon des autres sont enquêtés.",
        "- Les variables province et âge exigent une revue d'équité avant usage en production.",
        "- Surveiller la dérive des caractéristiques et le taux de confirmation des enquêtes chaque mois.",
        "",
        f"Suivi MLflow : run `{rapport.mlflow_run_id or 'non journalisé (mlflow absent)'}`. "
        f"Scores écrits dans gold.ml_scores_fraude ({rapport.scored_rows} sinistres).",
    ]
    chemin = reports_dir / "ml_fraude.md"
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return chemin
