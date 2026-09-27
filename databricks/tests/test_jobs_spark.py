"""Tests des jobs PySpark sur un Spark local (Delta et Auto Loader remplacés par Parquet et le file source)."""

import json
import sys
from pathlib import Path

import pytest

pyspark = pytest.importorskip("pyspark")
from pyspark.sql import SparkSession  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import ingestion_autoloader as ingestion  # noqa: E402
import streaming_sinistres as streaming  # noqa: E402


@pytest.fixture(scope="module")
def spark(tmp_path_factory):
    entrepot = tmp_path_factory.mktemp("spark-warehouse")
    session = (SparkSession.builder.master("local[2]").appName("tests-lakehouse")
               .config("spark.sql.warehouse.dir", str(entrepot))
               .config("spark.ui.enabled", "false").config("spark.sql.shuffle.partitions", "2")
               .config("spark.sql.session.timeZone", "UTC").getOrCreate())
    yield session
    session.stop()


def test_ingestion_ajoute_metadonnees_et_ne_relit_pas(spark, tmp_path):
    landing = tmp_path / "landing" / "clients"
    landing.mkdir(parents=True)
    (landing / "batch_001.csv").write_text("client_id,nom\nCL-1,tremblay\nCL-2,roy\n", encoding="utf-8")
    sortie, checkpoint = str(tmp_path / "bronze"), str(tmp_path / "chk")

    def executer():
        flux = ingestion.lire_flux(spark, str(landing), str(tmp_path / "schema"), format_source="csv")
        ingestion.ecrire_bronze(flux, sortie, checkpoint, format_cible="parquet").awaitTermination()

    executer()
    (landing / "batch_002.csv").write_text("client_id,nom\nCL-3,gagnon\n", encoding="utf-8")
    executer()
    executer()
    bronze = spark.read.parquet(sortie)
    assert bronze.count() == 3
    lots = {r["_batch_id"] for r in bronze.select("_batch_id").collect()}
    assert lots == {1, 2}
    assert {"_source_file", "_ingested_at"} <= set(bronze.columns)


def _evenements(dossier, nom, lignes):
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / nom).write_text("\n".join(json.dumps(e) for e in lignes) + "\n", encoding="utf-8")


def _evt(event_id, heure, province="QC", type_evenement="SINISTRE_DECLARE"):
    return {"event_id": event_id, "type_evenement": type_evenement, "sinistre_id": f"S-{event_id}",
            "police_id": "PO-1", "province": province, "type_sinistre": "VOL", "montant": 100.0,
            "event_time": f"2026-07-01T{heure}:00"}


def test_agregats_filigrane_et_doublons(spark, tmp_path):
    source = tmp_path / "evenements"
    _evenements(source, "lot1.json", [_evt("a", "08:01"), _evt("a", "08:01"), _evt("b", "08:05"),
                                      _evt("c", "08:07", type_evenement="PAIEMENT_EMIS")])
    _evenements(source, "lot2.json", [_evt("z", "10:00", province="ON")])
    sortie, checkpoint = str(tmp_path / "agregats"), str(tmp_path / "chk")

    def executer():
        flux = spark.readStream.schema(streaming.SCHEMA_EVENEMENTS).json(str(source))
        (streaming.agreger(flux).writeStream.format("parquet").outputMode("append")
         .option("checkpointLocation", checkpoint).trigger(availableNow=True).start(sortie)).awaitTermination()

    executer()
    _evenements(source, "lot3.json", [_evt("y", "11:00", province="ON")])
    executer()
    lignes = spark.read.parquet(sortie).collect()
    qc = [r for r in lignes if r["province"] == "QC"]
    assert len(qc) == 1
    assert (qc[0]["nb_declarations"], qc[0]["nb_paiements"]) == (2, 1)


def test_alertes_au_dessus_du_seuil(spark):
    df = spark.createDataFrame(
        [("2026-07-01 08:30:00", "QC", 60, 1.0, 0, 0.0), ("2026-07-01 08:30:00", "ON", 12, 1.0, 0, 0.0)],
        "debut_fenetre string, province string, nb_declarations int, montant_declare double, "
        "nb_paiements int, montant_paye double",
    )
    resultat = streaming.alertes(df, seuil=40).collect()
    assert [(r["province"], r["seuil"]) for r in resultat] == [("QC", 40)]


def test_entrainement_databricks_sur_table_spark(spark, tmp_path, monkeypatch):
    pytest.importorskip("sklearn")
    pytest.importorskip("mlflow")
    import entrainement_fraude
    import numpy as np
    import pandas as pd

    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", (tmp_path / "mlruns").as_uri())
    rng = np.random.default_rng(1)
    n = 600
    debut = rng.random(n) < 0.3
    donnees = pd.DataFrame({
        "sinistre_id": [f"S{i}" for i in range(n)],
        "date_sinistre": pd.to_datetime("2024-01-01") + pd.to_timedelta(rng.integers(0, 900, n), unit="D"),
        "produit": rng.choice(["AUTO", "HABITATION"], n), "type_sinistre": rng.choice(["VOL", "COLLISION"], n),
        "segment": rng.choice(["PME", "PARTICULIER"], n), "province": rng.choice(["QC", "ON"], n),
        "age": rng.integers(20, 80, n).astype(float), "montant_reclame": rng.uniform(100, 5000, n),
        "ratio_reclame_prime": rng.uniform(0, 5, n), "delai_declaration": rng.integers(0, 120, n).astype(float),
        "jours_depuis_debut_police": rng.integers(0, 365, n).astype(float),
        "jours_depuis_precedent": np.where(rng.random(n) < 0.5, np.nan, rng.integers(0, 400, n)),
        "nb_sinistres_cumul": rng.integers(1, 5, n).astype(float), "flag_rapproche": rng.integers(0, 2, n),
        "flag_debut_police": debut.astype(int), "flag_declaration_tardive": rng.integers(0, 2, n),
        "est_vol_ou_incendie": rng.integers(0, 2, n), "reclame_superieur_3x_prime": rng.integers(0, 2, n),
        "score_regles": debut.astype(int) * 35, "est_enquete": True,
        "etiquette_fraude": (debut & (rng.random(n) < 0.7)).astype(float),
    })
    spark.sql("create database if not exists gold")
    spark.createDataFrame(donnees).write.mode("overwrite").saveAsTable("gold.ml_features_fraude")
    run_id = entrainement_fraude.main(["--catalogue", "spark_catalog", "--experience", "tests_fraude"])
    assert run_id and spark.table("spark_catalog.gold.ml_scores_fraude").count() == n


def test_commandes_de_maintenance():
    import maintenance_delta

    sql = maintenance_delta.commandes("assurance_prod")
    assert "OPTIMIZE assurance_prod.gold.fct_sinistre" in sql
    assert all("RETAIN 168 HOURS" in s for s in sql if s.startswith("VACUUM"))
