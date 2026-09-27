"""Entraînement du modèle de fraude sur Databricks : lecture de la table de caractéristiques Unity
Catalog, suivi MLflow, enregistrement du modèle dans Unity Catalog, scores réécrits en gold."""

from __future__ import annotations

import argparse

import mlflow
from pyspark.sql import SparkSession

from accelerator.ml.fraud_model import fit_and_score, log_sklearn_model


def main(argv: list[str] | None = None) -> str:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalogue", required=True)
    parser.add_argument("--experience", default="/Shared/detection_fraude_sinistres")
    parser.add_argument("--enregistrer", action="store_true", help="Enregistrer le modèle dans Unity Catalog")
    args = parser.parse_args(argv)

    spark = SparkSession.builder.getOrCreate()
    donnees = spark.table(f"{args.catalogue}.gold.ml_features_fraude").toPandas()
    pipeline, rapport, scores, exemple = fit_and_score(donnees)

    mlflow.set_experiment(args.experience)
    if args.enregistrer:
        mlflow.set_registry_uri("databricks-uc")
    with mlflow.start_run(run_name=rapport.model_version) as run:
        mlflow.log_metrics({f"test_{k}": v for k, v in rapport.metrics.items()})
        mlflow.log_metrics({f"regles_{k}": v for k, v in rapport.baseline_metrics.items()})
        log_sklearn_model(
            pipeline, exemple, f"{args.catalogue}.ml.detection_fraude" if args.enregistrer else None
        )
    spark.createDataFrame(scores).write.mode("overwrite").option("overwriteSchema", "true") \
        .saveAsTable(f"{args.catalogue}.gold.ml_scores_fraude")
    return run.info.run_id


if __name__ == "__main__":
    main()
