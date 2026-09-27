import duckdb

from accelerator import ingestion


def _landing(tmp_path):
    for table in ("clients", "polices", "sinistres"):
        dossier = tmp_path / "landing" / table
        dossier.mkdir(parents=True)
        (dossier / "batch_001.csv").write_text("id,valeur\n1,a\n2,b\n", encoding="utf-8")
    return tmp_path / "landing"


def test_ingestion_idempotente(tmp_path):
    landing, base = _landing(tmp_path), tmp_path / "lake.duckdb"
    premier = ingestion.ingest(landing_dir=landing, db_path=base)
    second = ingestion.ingest(landing_dir=landing, db_path=base)
    assert all(not r.skipped and r.rows == 2 for r in premier)
    assert all(r.skipped for r in second)
    with duckdb.connect(str(base)) as con:
        assert con.execute("select count(*) from bronze.clients").fetchone()[0] == 2
        colonnes = {r[0] for r in con.execute("describe bronze.clients").fetchall()}
    assert {"_source_file", "_batch_id", "_ingested_at"} <= colonnes


def test_nouveau_lot_ajoute(tmp_path):
    landing, base = _landing(tmp_path), tmp_path / "lake.duckdb"
    ingestion.ingest(landing_dir=landing, db_path=base)
    (landing / "clients" / "batch_002.csv").write_text("id,valeur\n3,c\n", encoding="utf-8")
    resultats = ingestion.ingest(landing_dir=landing, db_path=base)
    assert [r.rows for r in resultats if not r.skipped] == [1]
    with duckdb.connect(str(base)) as con:
        assert con.execute("select max(_batch_id), count(*) from bronze.clients").fetchone() == (2, 3)
