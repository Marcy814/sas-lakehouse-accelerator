from accelerator import config
from accelerator.legacy_estate import build_inventory, normalize_table, parse_cognos, parse_datastage, parse_informatica, tables_in_sql

LEGACY = config.LEGACY_DIR


def test_normalisation_des_noms():
    assert normalize_table("PA.POLICES") == "src.polices"
    assert normalize_table("#P_SCHEMA_DWH#.PRIMES_MENSUELLES") == "dwh.primes_mensuelles"
    assert tables_in_sql("SELECT a FROM #P_SCHEMA_DWH#.CLIENTS_COURANTS c JOIN PA.POLICES p ON 1=1") == [
        "dwh.clients_courants", "src.polices"]


def test_informatica_entrees_sorties_et_pieges():
    (mapping,) = parse_informatica(LEGACY / "informatica" / "m_sinistres_regles.xml")
    assert mapping.inputs == ["dwh.sinistres_enrichis", "dwh.polices_courantes"]
    assert mapping.outputs == ["dwh.sinistres_regles", "dwh.grands_sinistres"]
    codes = {f.code for f in mapping.findings}
    assert {"INFA-RTR-01", "INFA-LKP-01", "INFA-NUM-01", "INFA-SES-01", "INFA-FN-DECODE"} <= codes


def test_datastage_etapes_lookup_et_code_mort():
    (job,) = parse_datastage(LEGACY / "datastage" / "j_primes_mensuelles.dsx")
    assert job.outputs == ["dwh.primes_mensuelles"]
    assert set(job.inputs) == {"dwh.polices_courantes", "dwh.clients_courants"}
    assert job.parameters == ["P_DATE_TRAITEMENT", "P_SCHEMA_DWH"]
    variable = next(f for f in job.findings if f.code == "DS-SV-01")
    assert "code mort" in variable.message
    assert any(f.code == "DS-LKP-01" and "Continue" in f.message for f in job.findings)


def test_cognos_ratio_calcule_et_invites():
    (rapport,) = parse_cognos(LEGACY / "cognos" / "rapport_performance_actuarielle.xml",
                              LEGACY / "cognos" / "framework_manager_mapping.yml")
    assert set(rapport.inputs) == {"dwh.ratio_sinistralite", "dwh.primes_mensuelles", "dwh.grands_sinistres"}
    assert {"COG-AGG-01", "COG-AGG-02", "COG-FN-01"} <= {f.code for f in rapport.findings}
    assert rapport.parameters == ["p_annee_debut", "p_annee_fin"]


def test_vagues_inter_outils():
    parc = build_inventory()
    rang = {a.name: a.wave for a in parc.assets}
    assert rang["01_clients_courants"] < rang["02_sinistres_enrichis"] < rang["m_sinistres_regles"]
    assert rang["j_primes_mensuelles"] < rang["rapport_performance_actuarielle"]
    assert parc.tools == {"SAS 9.4": 4, "Informatica PowerCenter": 1, "IBM DataStage": 1, "IBM Cognos Analytics": 1}
    sas_03 = next(a for a in parc.assets if a.name == "03_ratio_sinistralite")
    assert "CAS : ajustements requis" in sas_03.target_pattern
