from datetime import date

import pandas as pd

from accelerator.legacy_reference import intck_year_continuous, programme_04, propcase, sas_lt


def test_valeur_manquante_inferieure_a_tout_nombre():
    assert sas_lt(None, 30) and sas_lt(float("nan"), -1e9)
    assert not sas_lt(45, 30)


def test_propcase_accents_et_traits_union():
    assert propcase("JEAN-FRANÇOIS") == "Jean-François"
    assert propcase("  marie-ève  ") == "Marie-Ève"


def test_age_en_annees_revolues():
    assert intck_year_continuous(date(1980, 7, 1), date(2026, 6, 30)) == 45
    assert intck_year_continuous(date(1980, 6, 30), date(2026, 6, 30)) == 46
    assert intck_year_continuous(None, date(2026, 6, 30)) is None


def test_lag_reinitialise_par_client():
    df = pd.DataFrame({
        "client_id": ["A", "A", "B"],
        "sinistre_id": ["1", "2", "3"],
        "date_sinistre": [date(2025, 1, 1), date(2025, 1, 20), date(2025, 1, 25)],
        "date_debut_police": [date(2024, 1, 1)] * 3,
        "delai_declaration": [5, 5, 120],
        "montant_reclame": [100.0, 50.0, 10.0],
    })
    resultat = programme_04(df).set_index("sinistre_id")
    assert resultat.loc["2", "jours_depuis_precedent"] == 19
    assert pd.isna(resultat.loc["3", "jours_depuis_precedent"])
    assert resultat.loc["2", "montant_cumul"] == 150.0
    assert resultat.loc["3", "score_risque"] == 25
