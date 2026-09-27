"""Métadonnées des tables du lakehouse (schéma physique + descriptions dbt)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from accelerator import config


@dataclass
class TableInfo:
    schema: str
    name: str
    description: str = ""
    columns: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def fqn(self) -> str:
        return f"{self.schema}.{self.name}"

    def render(self) -> str:
        lignes = [f"{self.fqn} — {self.description or 'sans description'}"]
        lignes += [f"  - {nom} ({type_}){' : ' + desc if desc else ''}" for nom, type_, desc in self.columns]
        return "\n".join(lignes)


def _dbt_descriptions(manifest_path: Path) -> dict[str, dict]:
    if not manifest_path.exists():
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    descriptions = {}
    for noeud in manifest.get("nodes", {}).values():
        if noeud.get("resource_type") in {"model", "snapshot"}:
            descriptions[f"{noeud['schema']}.{noeud['name']}"] = {
                "description": noeud.get("description", ""),
                "columns": {c: v.get("description", "") for c, v in noeud.get("columns", {}).items()},
            }
    return descriptions


def load_catalog(
    schemas: set[str],
    db_path: Path = config.DB_PATH,
    manifest_path: Path = config.DBT_DIR / "target" / "manifest.json",
) -> dict[str, TableInfo]:
    descriptions = _dbt_descriptions(manifest_path)
    catalogue: dict[str, TableInfo] = {}
    with duckdb.connect(str(db_path), read_only=True) as con:
        lignes = con.execute(
            "select table_schema, table_name, column_name, data_type from information_schema.columns "
            "where table_schema in (select unnest(?)) order by table_schema, table_name, ordinal_position",
            [sorted(schemas)],
        ).fetchall()
    for schema, table, colonne, type_ in lignes:
        cle = f"{schema}.{table}"
        meta = descriptions.get(cle, {})
        info = catalogue.setdefault(cle, TableInfo(schema, table, meta.get("description", "").strip()))
        info.columns.append((colonne, type_, meta.get("columns", {}).get(colonne, "")))
    return catalogue
