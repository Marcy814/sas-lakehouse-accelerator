"""Ingestion idempotente de la zone d'atterrissage vers la couche bronze."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import duckdb

from accelerator import config

LOG_DDL = """
create table if not exists bronze._ingestion_log (
    source_table varchar not null,
    file_name    varchar not null,
    file_sha256  varchar not null,
    batch_id     integer not null,
    row_count    bigint  not null,
    ingested_at  timestamp not null default current_timestamp,
    primary key (source_table, file_sha256)
)
"""


@dataclass
class IngestionResult:
    table: str
    file_name: str
    rows: int
    skipped: bool


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fichier:
        for bloc in iter(lambda: fichier.read(1 << 20), b""):
            digest.update(bloc)
    return digest.hexdigest()


def _batch_id(path: Path) -> int:
    match = re.search(r"batch_(\d+)", path.stem)
    if not match:
        raise ValueError(f"Nom de fichier inattendu (batch_NNN attendu) : {path.name}")
    return int(match.group(1))


def _ingest_file(con: duckdb.DuckDBPyConnection, table: str, path: Path) -> IngestionResult:
    sha = _sha256(path)
    deja = con.execute(
        "select 1 from bronze._ingestion_log where source_table = ? and file_sha256 = ?", [table, sha]
    ).fetchone()
    if deja:
        return IngestionResult(table, path.name, 0, skipped=True)

    batch_id = _batch_id(path)
    lecture = (
        "select *, ? as _source_file, ?::integer as _batch_id, current_timestamp as _ingested_at "
        "from read_csv(?, header = true, all_varchar = true)"
    )
    con.execute("begin transaction")
    try:
        existe = con.execute(
            "select count(*) from information_schema.tables where table_schema = 'bronze' and table_name = ?",
            [table],
        ).fetchone()[0]
        if existe:
            con.execute(f"insert into bronze.{table} by name {lecture}", [path.name, batch_id, str(path)])
        else:
            con.execute(f"create table bronze.{table} as {lecture}", [path.name, batch_id, str(path)])
        lignes = con.execute(
            f"select count(*) from bronze.{table} where _source_file = ? and _batch_id = ?",
            [path.name, batch_id],
        ).fetchone()[0]
        con.execute(
            "insert into bronze._ingestion_log (source_table, file_name, file_sha256, batch_id, row_count) "
            "values (?, ?, ?, ?, ?)",
            [table, path.name, sha, batch_id, lignes],
        )
        con.execute("commit")
    except Exception:
        con.execute("rollback")
        raise
    return IngestionResult(table, path.name, lignes, skipped=False)


def ingest(
    batch: int | None = None,
    landing_dir: Path = config.LANDING_DIR,
    db_path: Path = config.DB_PATH,
) -> list[IngestionResult]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    resultats: list[IngestionResult] = []
    with duckdb.connect(str(db_path)) as con:
        con.execute("create schema if not exists bronze")
        con.execute(LOG_DDL)
        for table in config.SOURCE_TABLES:
            fichiers = sorted((landing_dir / table).glob("batch_*.csv"))
            if batch is not None:
                fichiers = [f for f in fichiers if _batch_id(f) == batch]
            for fichier in fichiers:
                resultats.append(_ingest_file(con, table, fichier))
    return resultats
