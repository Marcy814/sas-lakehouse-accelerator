import duckdb

from accelerator import reconciliation


def test_reconciliation_complete(lakehouse_available):
    resultats = reconciliation.reconcile_all(db_path=lakehouse_available)
    assert all(r.passed for r in resultats), [r.summary() for r in resultats]


def test_scd2_et_point_in_time(lakehouse_available):
    with duckdb.connect(str(lakehouse_available), read_only=True) as con:
        versions = con.execute("select count(*) from gold.dim_client where no_version > 1").fetchone()[0]
        historiques = con.execute(
            "select count(*) from gold.fct_sinistre f join gold.dim_client d using (client_sk) where not d.est_courant"
        ).fetchone()[0]
        perimees = con.execute("select count(*) from gold.dim_client where ville = 'Ville-Périmée'").fetchone()[0]
    assert versions > 0 and historiques > 0
    assert perimees == 0
