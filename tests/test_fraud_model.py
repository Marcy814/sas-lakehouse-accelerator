import numpy as np
import pandas as pd
import pytest

pytest.importorskip("sklearn")

from accelerator.ml import fraud_model  # noqa: E402


def test_precision_au_sommet():
    y = np.array([1, 0, 1, 0, 0, 0, 0, 0, 0, 0])
    scores = np.array([0.9, 0.8, 0.7, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1])
    assert fraud_model.precision_at(y, scores, 0.2) == 0.5
    assert fraud_model.precision_at(y, scores, 0.3) == pytest.approx(2 / 3)


def test_pipeline_gere_categories_inconnues_et_valeurs_manquantes():
    rng = np.random.default_rng(0)
    n = 400
    donnees = pd.DataFrame({
        "produit": rng.choice(["AUTO", "HABITATION"], n),
        "type_sinistre": rng.choice(["VOL", "COLLISION"], n),
        "segment": rng.choice(["PME", None], n),
        "province": rng.choice(["QC", "ON"], n),
        **{c: rng.normal(size=n) for c in fraud_model.NUMERIQUES},
        "jours_depuis_precedent": np.where(rng.random(n) < 0.5, np.nan, rng.integers(0, 400, n)),
    })
    y = (donnees["flag_debut_police"] > 0.5).astype(int)
    colonnes = fraud_model.CATEGORIELLES + fraud_model.NUMERIQUES + fraud_model.PREMIER_SINISTRE
    pipeline = fraud_model.build_pipeline().fit(donnees[colonnes], y)
    nouveau = donnees[colonnes].head(3).assign(province="BC")
    proba = pipeline.predict_proba(nouveau)[:, 1]
    assert proba.shape == (3,) and np.all((proba >= 0) & (proba <= 1))


def test_entrainement_sur_le_lakehouse(lakehouse_available, tmp_path):
    rapport = fraud_model.train(reports_dir=tmp_path, tracking_dir=tmp_path / "mlruns")
    assert rapport.train_rows > 1000 and rapport.test_rows > 100
    assert rapport.metrics["roc_auc"] > rapport.baseline_metrics["roc_auc"]
    assert (tmp_path / "ml_fraude.md").exists()
