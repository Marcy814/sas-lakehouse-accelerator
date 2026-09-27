import duckdb

from accelerator.reconciliation import DatasetSpec, reconcile_dataset


def _preparer(tmp_path, cible_sql):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "ventes.csv").write_text(
        "id,region,montant,date_vente\n1,QC,100.00,2025-01-01\n2,ON,50.00,2025-01-02\n3,QC,,2025-01-03\n",
        encoding="utf-8",
    )
    con = duckdb.connect()
    con.execute("create schema gold")
    con.execute(f"create table gold.ventes as {cible_sql}")
    spec = DatasetSpec("dwh.ventes", "p", "ventes.csv", "ventes", "gold", ["id"])
    return con, spec, legacy


def test_jeu_identique(tmp_path):
    con, spec, legacy = _preparer(tmp_path, """
        select * from (values (1, 'QC', 100.004, date '2025-01-01'), (2, 'ON', 50.0, date '2025-01-02'),
                              (3, 'QC', null, date '2025-01-03')) t(id, region, montant, date_vente)""")
    resultat = reconcile_dataset(con, spec, legacy)
    assert resultat.passed, resultat.summary()


def test_ecarts_detectes(tmp_path):
    con, spec, legacy = _preparer(tmp_path, """
        select * from (values (1, 'QC', 100.0, date '2025-01-01'), (2, 'NB', 50.0, date '2025-01-02'),
                              (3, 'QC', 0.0, date '2025-01-03'), (4, 'QC', 1.0, date '2025-01-04'))
        t(id, region, montant, date_vente)""")
    resultat = reconcile_dataset(con, spec, legacy)
    assert not resultat.passed
    assert resultat.extra_in_target == 1 and resultat.missing_in_target == 0
    ecarts = {c.name: c.mismatches for c in resultat.columns}
    assert ecarts == {"region": 1, "montant": 1, "date_vente": 0}
    assert {s["colonne"] for s in resultat.samples} == {"region", "montant"}


def test_colonne_manquante(tmp_path):
    con, spec, legacy = _preparer(tmp_path, "select 1 as id, 'QC' as region")
    resultat = reconcile_dataset(con, spec, legacy)
    assert resultat.error and "montant" in resultat.error
