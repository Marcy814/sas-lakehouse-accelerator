"""Vérifie que le projet dbt compile pour Databricks et Snowflake, sans connexion ni compte.

1. dbt compile avec l'adaptateur réel de chaque plateforme (macros dispatch spécifiques);
2. analyse syntaxique du SQL compilé dans le dialecte cible (sqlglot);
3. détection de fonctions propres à DuckDB qui auraient échappé aux macros.
"""

from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass, field
from pathlib import Path

import sqlglot

from accelerator import config
from accelerator.dbt_runner import run_dbt

TARGETS = {
    "databricks": {"module": "dbt.adapters.databricks", "dialect": "databricks", "env": {
        "DATABRICKS_HOST": "adb-0000000000000000.0.azuredatabricks.net",
        "DATABRICKS_HTTP_PATH": "/sql/1.0/warehouses/hors-ligne", "DATABRICKS_TOKEN": "hors-ligne"}},
    "snowflake": {"module": "dbt.adapters.snowflake", "dialect": "snowflake", "env": {
        "SNOWFLAKE_ACCOUNT": "hors-ligne", "SNOWFLAKE_USER": "hors-ligne", "SNOWFLAKE_PRIVATE_KEY_PATH": "hors-ligne"}},
}
DUCKDB_ONLY = {
    r"\bage\s*\(": "age()", r"\blist_transform\s*\(": "list_transform()", r"\bstring_split\s*\(": "string_split()",
    r"\bstrftime\s*\(": "strftime()", r"\bisodow\s*\(": "isodow()", r"\brange\s*\(\s*date": "range() de dates",
    r"union\s+all\s+by\s+name": "UNION ALL BY NAME", r"\bdate_diff\s*\(\s*'": "date_diff('unité', ...)",
    r"\bunnest\s*\(": "unnest()",
}


@dataclass
class ModelCheck:
    model: str
    target: str
    parsed: bool
    duckdb_functions: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.parsed and not self.duckdb_functions


@dataclass
class TargetResult:
    target: str
    available: bool
    compiled: bool = False
    message: str = ""
    models: list[ModelCheck] = field(default_factory=list)


def adapter_available(target: str) -> bool:
    try:
        return importlib.util.find_spec(TARGETS[target]["module"]) is not None
    except ModuleNotFoundError:
        return False


def check_sql(model: str, target: str, sql: str) -> ModelCheck:
    dialecte = TARGETS[target]["dialect"]
    verification = ModelCheck(model, target, parsed=True)
    try:
        sqlglot.parse_one(sql, read=dialecte)
    except sqlglot.errors.ParseError as exc:
        verification.parsed, verification.error = False, str(exc).splitlines()[0][:200]
    verification.duckdb_functions = [nom for motif, nom in DUCKDB_ONLY.items() if re.search(motif, sql, re.I)]
    return verification


def check_target(target: str) -> TargetResult:
    resultat = TargetResult(target, adapter_available(target))
    if not resultat.available:
        resultat.message = f"adaptateur dbt-{target} absent (python -m pip install -e \".[portability]\")"
        return resultat
    dossier = config.DBT_DIR / f"target_{target}"
    execution = run_dbt(
        ["--no-populate-cache", "compile", "--target", target, "--no-introspect",
         "--vars", "{compilation_hors_ligne: true}", "--target-path", str(dossier)],
        extra_env=TARGETS[target]["env"],
    )
    resultat.compiled = execution.success
    if not execution.success:
        resultat.message = execution.tail(8)
        return resultat
    racine = dossier / "compiled" / "lakehouse_assurance" / "models"
    for fichier in sorted(racine.rglob("*.sql")):
        if any(parent.suffix == ".yml" for parent in fichier.parents):
            continue
        resultat.models.append(check_sql(fichier.stem, target, fichier.read_text(encoding="utf-8")))
    return resultat


def to_markdown(resultats: list[TargetResult]) -> str:
    lignes = ["# Portabilité du projet dbt", "",
              "Compilation avec l'adaptateur réel de chaque plateforme (sans connexion), puis analyse syntaxique "
              "du SQL compilé dans le dialecte cible et recherche de fonctions propres à DuckDB.", ""]
    for r in resultats:
        if not r.available or not r.compiled:
            lignes += [f"## {r.target}", "", f"Non vérifié : {r.message}", ""]
            continue
        ok = sum(m.ok for m in r.models)
        lignes += [f"## {r.target} — {ok}/{len(r.models)} modèles portables", "",
                   "| Modèle | Syntaxe | Fonctions DuckDB résiduelles |", "|---|---|---|"]
        lignes += [f"| `{m.model}` | {'✅' if m.parsed else '❌ ' + m.error} | {', '.join(m.duckdb_functions) or '-'} |"
                   for m in r.models]
        lignes.append("")
    return "\n".join(lignes)


def run(reports_dir: Path = config.REPORTS_DIR) -> list[TargetResult]:
    resultats = [check_target(t) for t in TARGETS]
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "portability.md").write_text(to_markdown(resultats), encoding="utf-8")
    return resultats
