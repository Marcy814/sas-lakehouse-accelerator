"""Agent analytique text-to-SQL sur la couche gold, en lecture seule."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from accelerator import config
from accelerator.agents.catalog import load_catalog
from accelerator.agents.guardrails import GuardrailViolation, validate_sql
from accelerator.agents.llm import AgentRun, LLMClient, Tool, ToolCall, run_tool_loop, to_json

ALLOWED_SCHEMAS = {"gold"}
MAX_ROWS = 200

SYSTEM_PROMPT = """\
Tu es l'analyste de données d'un assureur de dommages et de personnes canadien. Tu réponds aux
questions métier en interrogeant l'entrepôt DuckDB (dialecte SQL DuckDB) au moyen de tes outils.

Règles :
- N'affirme jamais un chiffre qui ne provient pas d'une requête exécutée pendant cette conversation.
- Explore d'abord le catalogue (list_tables, describe_table) si tu n'es pas certain des colonnes.
- Tu n'as accès qu'au schéma gold, en lecture seule. Les résultats sont limités à {max_rows} lignes :
  agrège dans SQL plutôt que de rapatrier des lignes détaillées.
- Réponds dans la langue de la question, de façon concise, avec les chiffres clés et une phrase
  d'interprétation. Termine par la requête SQL principale dans un bloc ```sql.
- Si la question est ambiguë ou hors du périmètre des données, dis-le clairement.

Glossaire métier :
- Ratio de sinistralité = total payé / primes acquises (mart_ratio_sinistralite, par produit et année).
- Primes acquises : prime annuelle au prorata des jours de couverture dans l'année.
- dim_client est une dimension SCD type 2 : filtrer est_courant = true pour l'état actuel; fct_sinistre
  est déjà rattachée à la version du client en vigueur à la date du sinistre (client_sk).
- fct_sinistre : un sinistre par ligne; montant_paye est NULL tant que le sinistre est ouvert.
- mart_indicateurs_fraude.score_risque va de 0 à 100 (40 rapproché + 35 début de police + 25 tardif).
"""


@dataclass
class AnalystAnswer:
    question: str
    answer: str
    queries: list[str] = field(default_factory=list)
    run: AgentRun | None = None


def _format_rows(colonnes: list[str], lignes: list[tuple]) -> str:
    return to_json({"colonnes": colonnes, "nb_lignes": len(lignes), "lignes": [list(r) for r in lignes]})


class AnalystAgent:
    def __init__(self, client: LLMClient, db_path: Path = config.DB_PATH):
        self.client = client
        self.db_path = db_path
        self.catalog = load_catalog(ALLOWED_SCHEMAS, db_path)
        self.executed: list[str] = []

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.db_path), read_only=True, config={"enable_external_access": False})

    def list_tables(self, _: dict) -> str:
        return "\n".join(f"{t.fqn} — {t.description or 'sans description'}" for t in self.catalog.values())

    def describe_table(self, entree: dict) -> str:
        table = self.catalog.get(entree["table"].lower())
        if not table:
            raise ValueError(f"table inconnue : {entree['table']}. Utilise list_tables.")
        return table.render()

    def run_sql(self, entree: dict) -> str:
        try:
            requete = validate_sql(entree["sql"], ALLOWED_SCHEMAS, MAX_ROWS)
        except GuardrailViolation as exc:
            return f"REFUSÉ PAR LES GARDE-FOUS : {exc}"
        with self._connect() as con:
            curseur = con.execute(requete.sql)
            colonnes = [d[0] for d in curseur.description]
            lignes = curseur.fetchall()
        self.executed.append(requete.sql)
        return _format_rows(colonnes, lignes)

    def tools(self) -> list[Tool]:
        return [
            Tool("list_tables", "Liste les tables disponibles (schéma gold) avec leur description.",
                 {"type": "object", "properties": {}}, self.list_tables),
            Tool("describe_table", "Décrit les colonnes d'une table (nom qualifié, ex. gold.fct_sinistre).",
                 {"type": "object", "properties": {"table": {"type": "string"}}, "required": ["table"]},
                 self.describe_table),
            Tool("run_sql", "Exécute une requête SELECT en lecture seule (DuckDB) et retourne les lignes en JSON.",
                 {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]},
                 self.run_sql),
        ]

    def ask(self, question: str, on_tool_call=None, max_cost_usd: float | None = None) -> AnalystAnswer:
        self.executed = []
        run = run_tool_loop(
            self.client,
            SYSTEM_PROMPT.format(max_rows=MAX_ROWS),
            question,
            self.tools(),
            max_turns=10,
            max_cost_usd=max_cost_usd,
            on_tool_call=on_tool_call,
        )
        return AnalystAnswer(question, run.final_text, list(self.executed), run)


def print_tool_call(appel: ToolCall) -> None:
    if appel.name == "run_sql":
        print(f"  ↳ run_sql : {' '.join(appel.input.get('sql', '').split())[:160]}")
    else:
        print(f"  ↳ {appel.name} {appel.input or ''}")
