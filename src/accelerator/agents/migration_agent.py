"""Agent de conversion SAS → dbt : génère, compile, réconcilie et corrige en boucle.

Les modèles produits sont écrits dans lakehouse/models/agent_sandbox/ (désactivés par défaut) et
restent des propositions soumises à revue humaine avant d'être promus dans models/marts/.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import duckdb

from accelerator import config
from accelerator.agents.catalog import load_catalog
from accelerator.agents.guardrails import validate_sql
from accelerator.agents.llm import LLMClient, Tool, ToolCall, run_tool_loop, to_json
from accelerator.dbt_runner import run_dbt
from accelerator.reconciliation import DatasetSpec, load_specs, reconcile_dataset
from accelerator.sas_analyzer import Inventory, Program, SasAnalyzer

SANDBOX_SCHEMA = "agent_sandbox"
UPSTREAM_SCHEMAS = {"silver", "gold", "snapshots"}
FORBIDDEN_SQL = re.compile(r"\b(insert|update|delete|drop|create|alter|attach|copy|pragma)\b", re.I)

SYSTEM_PROMPT = """\
Tu es un ingénieur de données senior spécialisé dans la migration de SAS 9 vers dbt (DuckDB).
Ta mission : convertir un programme SAS en un modèle dbt SQL dont la sortie est IDENTIQUE à la table
SAS d'origine, ligne à ligne. La fidélité prime sur l'élégance : un écart de comportement, même
« corrigé », doit être reproduit puis signalé dans les points de revue.

Démarche obligatoire :
1. Lis le programme SAS et les pièges détectés par l'analyse statique.
2. Écris le modèle avec write_model, en utilisant uniquement {{ ref('...') }} vers les modèles autorisés.
3. Exécute build_model; en cas d'erreur, corrige et recommence.
4. Exécute reconcile; analyse les écarts (échantillons fournis) et corrige jusqu'à 0 écart.
5. Termine par submit avec ton niveau de confiance et les points qui exigent une revue humaine.

Conventions :
- SQL DuckDB, CTE nommées en français, une CTE par étape logique du programme SAS.
- Macros disponibles : {{ sas_lt(expr, seuil) }} (sémantique SAS « < » avec valeurs manquantes),
  {{ propcase(expr) }}, {{ age_revolu(date_naissance, date_reference) }}, {{ to_date_id(expr) }}.
- Variables dbt : var('date_ref') (chaîne 'AAAA-MM-JJ', équivaut à &date_ref),
  var('annees_ratio') (liste d'années, équivaut à &annee_debut..&annee_fin).
- Les colonnes et leur ordre doivent correspondre exactement à la table SAS cible.
- Ne produis aucune instruction DDL/DML : un seul SELECT.
"""


@dataclass
class DatasetConversion:
    legacy: str
    model_name: str
    status: str = "NON_TRAITÉ"
    reconciliation: str = ""
    confidence: str = ""
    notes: str = ""
    review_points: list[str] = field(default_factory=list)


@dataclass
class ConversionReport:
    program: str
    started_at: str
    turns: int = 0
    usage_summary: str = ""
    stop_reason: str = ""
    datasets: list[DatasetConversion] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)

    def to_markdown(self) -> str:
        lignes = [
            f"# Conversion assistée par agent — `{self.program}.sas`", "",
            f"- Démarrée : {self.started_at}",
            f"- Tours d'agent : {self.turns} | appels d'outils : {len(self.tool_calls)} | fin : {self.stop_reason}",
            f"- Consommation : {self.usage_summary or 'non mesurée'}",
            "", "| Jeu legacy | Modèle proposé | Statut | Confiance | Réconciliation |", "|---|---|---|---|---|",
        ]
        for d in self.datasets:
            lignes.append(
                f"| `{d.legacy}` | `{d.model_name}` | {d.status} | {d.confidence or '-'} | {d.reconciliation or '-'} |"
            )
        for d in self.datasets:
            if d.notes or d.review_points:
                lignes += ["", f"## Revue humaine — `{d.model_name}`", "", d.notes, ""]
                lignes += [f"- [ ] {p}" for p in d.review_points]
        lignes += ["", "## Journal des appels d'outils", ""]
        for i, appel in enumerate(self.tool_calls, 1):
            resume = " ".join(appel.output.split())[:180]
            lignes.append(f"{i}. `{appel.name}` {'⚠️' if appel.is_error else ''} — {resume}")
        return "\n".join(lignes) + "\n"


class MigrationAgent:
    def __init__(
        self,
        client: LLMClient,
        db_path: Path = config.DB_PATH,
        sas_dir: Path = config.SAS_DIR,
        sandbox_dir: Path = config.AGENT_SANDBOX_DIR,
        legacy_dir: Path = config.LEGACY_OUTPUT_DIR,
        specs: list[DatasetSpec] | None = None,
        inventory: Inventory | None = None,
        build_fn=None,
    ):
        self.client = client
        self.db_path = db_path
        self.sas_dir = sas_dir
        self.sandbox_dir = sandbox_dir
        self.legacy_dir = legacy_dir
        self.specs = specs or load_specs()
        self.inventory = inventory or SasAnalyzer().analyze_directory(sas_dir)
        self.build_fn = build_fn or self._build_with_dbt

    def _program(self, name: str) -> Program:
        for program in self.inventory.programs:
            if program.name == name:
                return program
        raise ValueError(f"programme inconnu : {name}")

    def _allowed_refs(self, program: Program, cibles: list[DatasetSpec]) -> set[str]:
        interdits = {s.target_model for s in self.specs if s.target_schema == "gold"}
        autorises = {s.target_model for s in self.specs if s.legacy in program.inputs}
        catalogue = load_catalog(UPSTREAM_SCHEMAS, self.db_path)
        modeles = {t.name for t in catalogue.values()} - interdits
        return (modeles | autorises) - {c.target_model for c in cibles}

    def _build_with_dbt(self, model_name: str) -> tuple[bool, str]:
        resultat = run_dbt(
            ["run", "--select", model_name, "--vars", "{agent_sandbox: true}"], db_path=self.db_path
        )
        return resultat.success, resultat.tail(25)

    def convert(
        self, program_name: str, max_turns: int = 16, on_tool_call=None, max_cost_usd: float | None = None
    ) -> ConversionReport:
        program = self._program(program_name)
        cibles = [s for s in self.specs if s.program == program_name and s.target_schema == "gold"]
        if not cibles:
            raise ValueError(f"aucun jeu de données cible (gold) défini pour {program_name}")
        autorises = self._allowed_refs(program, cibles)
        conversions = {f"agent_{s.target_model}": DatasetConversion(s.legacy, f"agent_{s.target_model}")
                       for s in cibles}
        spec_par_modele = {f"agent_{s.target_model}": s for s in cibles}
        rapport = ConversionReport(program_name, datetime.now().isoformat(timespec="seconds"))
        self.sandbox_dir.mkdir(parents=True, exist_ok=True)

        def verifier_modele(nom: str) -> DatasetSpec:
            if nom not in spec_par_modele:
                raise ValueError(f"modèle non attendu : {nom}. Attendus : {sorted(spec_par_modele)}")
            return spec_par_modele[nom]

        def write_model(entree: dict) -> str:
            nom, sql = entree["model_name"], entree["sql"]
            verifier_modele(nom)
            if FORBIDDEN_SQL.search(re.sub(r"'[^']*'", "''", sql)):
                raise ValueError("instruction DDL/DML détectée : un seul SELECT est permis")
            refs = set(re.findall(r"ref\(\s*['\"](\w+)['\"]\s*\)", sql))
            hors = refs - autorises
            if hors:
                raise ValueError(f"ref() non autorisés : {sorted(hors)}. Autorisés : {sorted(autorises)}")
            if "source(" in sql:
                raise ValueError("source() interdit : partir des modèles silver/gold")
            entete = (
                f"{{{{ config(schema='{SANDBOX_SCHEMA}', materialized='table', "
                f"enabled=var('agent_sandbox', false) | as_bool) }}}}\n"
                f"-- Généré par l'agent de migration à partir de legacy/sas/{program_name}.sas; revue requise.\n\n"
            )
            (self.sandbox_dir / f"{nom}.sql").write_text(entete + sql.strip() + "\n", encoding="utf-8")
            return f"Modèle {nom} écrit ({len(sql.splitlines())} lignes)."

        def build_model(entree: dict) -> str:
            nom = entree["model_name"]
            verifier_modele(nom)
            succes, journal = self.build_fn(nom)
            return ("SUCCÈS" if succes else "ÉCHEC") + "\n" + journal

        def reconcile(entree: dict) -> str:
            nom = entree["model_name"]
            spec = verifier_modele(nom)
            with duckdb.connect(str(self.db_path), read_only=True) as con:
                resultat = reconcile_dataset(con, spec, self.legacy_dir, target_table=f"{SANDBOX_SCHEMA}.{nom}")
            conversions[nom].reconciliation = "✅ 0 écart" if resultat.passed else "❌ " + resultat.summary()
            return to_json({
                "conforme": resultat.passed,
                "resume": resultat.summary(),
                "colonnes_en_ecart": {c.name: c.mismatches for c in resultat.columns if c.mismatches},
                "echantillons": resultat.samples[:10],
            })

        def preview(entree: dict) -> str:
            requete = validate_sql(entree["sql"], UPSTREAM_SCHEMAS | {SANDBOX_SCHEMA}, max_rows=20)
            with duckdb.connect(str(self.db_path), read_only=True,
                                config={"enable_external_access": False}) as con:
                curseur = con.execute(requete.sql)
                colonnes = [d[0] for d in curseur.description]
                return to_json({"colonnes": colonnes, "lignes": [list(r) for r in curseur.fetchall()]})

        def submit(entree: dict) -> str:
            for item in entree["models"]:
                nom = item["model_name"]
                verifier_modele(nom)
                conversion = conversions[nom]
                conversion.confidence = item.get("confidence", "")
                conversion.notes = item.get("notes", "")
                conversion.review_points = item.get("review_points", [])
            return "Soumission enregistrée."

        schema_modele = {"type": "string", "enum": sorted(spec_par_modele)}
        outils = [
            Tool("write_model", "Écrit (ou remplace) le SQL dbt d'un modèle cible. Un seul SELECT, refs autorisés.",
                 {"type": "object", "properties": {"model_name": schema_modele, "sql": {"type": "string"}},
                  "required": ["model_name", "sql"]}, write_model),
            Tool("build_model", "Compile et exécute le modèle avec dbt; retourne le journal (erreurs incluses).",
                 {"type": "object", "properties": {"model_name": schema_modele}, "required": ["model_name"]},
                 build_model),
            Tool("reconcile", "Compare la sortie du modèle à la table SAS d'origine, ligne à ligne.",
                 {"type": "object", "properties": {"model_name": schema_modele}, "required": ["model_name"]},
                 reconcile),
            Tool("preview", "Exécute un SELECT de diagnostic (20 lignes max) sur silver, gold, snapshots "
                 "ou agent_sandbox.",
                 {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}, preview),
            Tool("submit", "Termine la conversion : confiance (élevée/moyenne/faible), notes et points de revue.",
                 {"type": "object", "properties": {"models": {"type": "array", "items": {
                     "type": "object",
                     "properties": {"model_name": schema_modele, "confidence": {"type": "string"},
                                    "notes": {"type": "string"},
                                    "review_points": {"type": "array", "items": {"type": "string"}}},
                     "required": ["model_name", "confidence", "review_points"]}}},
                  "required": ["models"]}, submit, terminal=True),
        ]

        message = self._user_message(program, cibles, autorises)
        run = run_tool_loop(self.client, SYSTEM_PROMPT, message, outils, max_turns=max_turns,
                            max_tokens=8192, on_tool_call=on_tool_call, max_cost_usd=max_cost_usd)
        rapport.turns, rapport.stop_reason, rapport.tool_calls = run.turns, run.stop_reason, run.tool_calls
        rapport.usage_summary = run.usage.describe(run.model)
        for conversion in conversions.values():
            if conversion.reconciliation.startswith("✅"):
                conversion.status = "RÉCONCILIÉ — À REVOIR"
            elif (self.sandbox_dir / f"{conversion.model_name}.sql").exists():
                conversion.status = "ÉCARTS — INTERVENTION REQUISE"
        rapport.datasets = list(conversions.values())
        return rapport

    def _user_message(self, program: Program, cibles: list[DatasetSpec], autorises: set[str]) -> str:
        source = (self.sas_dir / f"{program.name}.sas").read_text(encoding="utf-8")
        catalogue = load_catalog(UPSTREAM_SCHEMAS, self.db_path)
        schemas_amont = "\n\n".join(t.render() for t in catalogue.values() if t.name in autorises)
        attendus = []
        for spec in cibles:
            chemin = self.legacy_dir / spec.legacy_file
            entete = chemin.read_text(encoding="utf-8").splitlines()[0] if chemin.exists() else "?"
            attendus.append(
                f"- agent_{spec.target_model} ⇐ {spec.legacy} | clé : {spec.keys} | colonnes (ordre) : {entete}"
            )
        pieges = "\n".join(f"- ligne {p.line} [{p.code}] {p.message} → {p.recommendation}" for p in program.pitfalls)
        correspondances = "\n".join(
            f"- {s.legacy} → ref('{s.target_model}')" for s in self.specs if s.target_model in autorises
        )
        return (
            f"# Programme à convertir : {program.name}.sas\n\n```sas\n{source}\n```\n\n"
            f"# Modèles à produire\n" + "\n".join(attendus) + "\n\n"
            f"# Pièges détectés par l'analyse statique\n{pieges or '- aucun'}\n\n"
            f"# Correspondance des tables SAS déjà migrées\n{correspondances or '- aucune'}\n"
            "- src.clients / src.polices / src.sinistres → silver_clients / silver_polices / silver_sinistres "
            "(déjà dédoublonnés sur la date_maj la plus récente et typés)\n\n"
            f"# Modèles autorisés dans ref() et leurs colonnes\n{schemas_amont}\n\n"
            f"# Informations complémentaires\n{json.dumps({'complexite': program.complexity_level}, ensure_ascii=False)}\n"
        )
