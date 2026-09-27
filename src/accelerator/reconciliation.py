"""Réconciliation ligne à ligne entre les sorties SAS (legacy) et les tables du lakehouse."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import duckdb
import yaml

from accelerator import config

NUMERIC_PREFIXES = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "FLOAT", "DOUBLE", "DECIMAL", "REAL")


@dataclass
class DatasetSpec:
    legacy: str
    program: str
    legacy_file: str
    target_model: str
    target_schema: str
    keys: list[str]
    columns: list[str] | None = None
    tolerances: dict[str, float] = field(default_factory=dict)
    numeric_tolerance: float = 0.01

    @property
    def target_table(self) -> str:
        return f"{self.target_schema}.{self.target_model}"


@dataclass
class ColumnResult:
    name: str
    kind: str
    mismatches: int
    legacy_sum: float | None = None
    target_sum: float | None = None


@dataclass
class DatasetResult:
    dataset: str
    target_table: str
    legacy_rows: int = 0
    target_rows: int = 0
    missing_in_target: int = 0
    extra_in_target: int = 0
    columns: list[ColumnResult] = field(default_factory=list)
    samples: list[dict] = field(default_factory=list)
    error: str | None = None

    @property
    def passed(self) -> bool:
        return (
            self.error is None
            and self.legacy_rows == self.target_rows
            and self.missing_in_target == 0
            and self.extra_in_target == 0
            and all(c.mismatches == 0 for c in self.columns)
        )

    def summary(self) -> str:
        if self.error:
            return f"{self.dataset}: ERREUR - {self.error}"
        ecarts = {c.name: c.mismatches for c in self.columns if c.mismatches}
        statut = "OK" if self.passed else "ÉCART"
        return (
            f"{self.dataset}: {statut} | lignes legacy={self.legacy_rows} cible={self.target_rows} | "
            f"absentes={self.missing_in_target} en_trop={self.extra_in_target} | colonnes en écart={ecarts}"
        )


def load_specs(path: Path = config.MIGRATION_CONFIG) -> list[DatasetSpec]:
    contenu = yaml.safe_load(path.read_text(encoding="utf-8"))
    tolerance = contenu.get("defaults", {}).get("numeric_tolerance", 0.01)
    return [DatasetSpec(numeric_tolerance=tolerance, **d) for d in contenu["datasets"]]


def _is_numeric(type_name: str) -> bool:
    return type_name.upper().startswith(NUMERIC_PREFIXES)


def _q(identifiant: str) -> str:
    return '"' + identifiant.replace('"', '""') + '"'


def reconcile_dataset(
    con: duckdb.DuckDBPyConnection,
    spec: DatasetSpec,
    legacy_dir: Path = config.LEGACY_OUTPUT_DIR,
    target_table: str | None = None,
    sample_size: int = 5,
) -> DatasetResult:
    cible = target_table or spec.target_table
    resultat = DatasetResult(dataset=spec.legacy, target_table=cible)
    chemin = legacy_dir / spec.legacy_file
    if not chemin.exists():
        resultat.error = f"fichier legacy introuvable : {chemin}"
        return resultat

    con.execute(
        "create or replace temp table _legacy as select * from read_csv(?, header = true, sample_size = -1)",
        [str(chemin)],
    )
    types_legacy = {r[0]: r[1] for r in con.execute("describe _legacy").fetchall()}
    try:
        colonnes_cible = {r[0] for r in con.execute(f"describe {cible}").fetchall()}
    except duckdb.Error as exc:
        resultat.error = f"table cible inaccessible : {exc}".splitlines()[0]
        return resultat

    colonnes = spec.columns or list(types_legacy)
    manquantes = [c for c in colonnes if c not in colonnes_cible]
    if manquantes:
        resultat.error = f"colonnes absentes de la cible : {manquantes}"
        return resultat

    resultat.legacy_rows = con.execute("select count(*) from _legacy").fetchone()[0]
    resultat.target_rows = con.execute(f"select count(*) from {cible}").fetchone()[0]

    jointure = " and ".join(f"cast(l.{_q(k)} as varchar) = cast(t.{_q(k)} as varchar)" for k in spec.keys)
    premiere_cle = _q(spec.keys[0])
    base = f"from _legacy as l full outer join {cible} as t on {jointure}"
    resultat.missing_in_target, resultat.extra_in_target = con.execute(
        f"select count(*) filter (where t.{premiere_cle} is null), "
        f"count(*) filter (where l.{premiere_cle} is null) {base}"
    ).fetchone()

    comparables = [c for c in colonnes if c not in spec.keys]
    conditions = {}
    for col in comparables:
        qc = _q(col)
        if _is_numeric(types_legacy[col]):
            tol = spec.tolerances.get(col, spec.numeric_tolerance)
            conditions[col] = (
                "numeric",
                f"(l.{qc} is null) <> (t.{qc} is null) or "
                f"abs(cast(l.{qc} as double) - cast(t.{qc} as double)) > {tol}",
            )
        else:
            conditions[col] = ("text", f"cast(l.{qc} as varchar) is distinct from cast(t.{qc} as varchar)")

    appariees = f"{base} where l.{premiere_cle} is not null and t.{premiere_cle} is not null"
    if conditions:
        expressions = ", ".join(
            f"coalesce(sum(case when {cond} then 1 else 0 end), 0)" for _, cond in conditions.values()
        )
        compte = con.execute(f"select {expressions} {appariees}").fetchone()
        for (col, (kind, cond)), n in zip(conditions.items(), compte):
            colonne = ColumnResult(col, kind, int(n))
            if kind == "numeric":
                qc = _q(col)
                colonne.legacy_sum, colonne.target_sum = con.execute(
                    f"select sum(cast(l.{qc} as double)), sum(cast(t.{qc} as double)) {appariees}"
                ).fetchone()
            resultat.columns.append(colonne)
            if n and len(resultat.samples) < sample_size * 3:
                cles = ", ".join(f"l.{_q(k)} as {_q(k)}" for k in spec.keys)
                qc = _q(col)
                lignes = con.execute(
                    f"select {cles}, cast(l.{qc} as varchar), cast(t.{qc} as varchar) {appariees} and {cond} "
                    f"order by all limit {sample_size}"
                ).fetchall()
                for ligne in lignes:
                    resultat.samples.append({
                        "colonne": col,
                        "cle": dict(zip(spec.keys, [str(v) for v in ligne[: len(spec.keys)]])),
                        "legacy": ligne[-2],
                        "cible": ligne[-1],
                    })
    return resultat


def reconcile_all(
    db_path: Path = config.DB_PATH,
    legacy_dir: Path = config.LEGACY_OUTPUT_DIR,
    specs: list[DatasetSpec] | None = None,
) -> list[DatasetResult]:
    specs = specs or load_specs()
    with duckdb.connect(str(db_path), read_only=True) as con:
        return [reconcile_dataset(con, spec, legacy_dir) for spec in specs]


def to_markdown(resultats: list[DatasetResult]) -> str:
    total_ok = sum(r.passed for r in resultats)
    lignes = [
        "# Rapport de réconciliation SAS → Lakehouse",
        "",
        f"**{total_ok}/{len(resultats)} jeux de données conformes.**",
        "",
        "| Jeu legacy | Table cible | Lignes legacy | Lignes cible | Absentes | En trop | Colonnes en écart | Statut |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in resultats:
        ecarts = ", ".join(f"{c.name} ({c.mismatches})" for c in r.columns if c.mismatches) or "-"
        statut = "✅" if r.passed else ("⛔ " + r.error if r.error else "❌")
        lignes.append(
            f"| `{r.dataset}` | `{r.target_table}` | {r.legacy_rows} | {r.target_rows} | "
            f"{r.missing_in_target} | {r.extra_in_target} | {ecarts} | {statut} |"
        )
    lignes += ["", "## Sommes de contrôle (colonnes numériques)", "",
               "| Jeu | Colonne | Somme legacy | Somme cible |", "|---|---|---|---|"]
    for r in resultats:
        for c in r.columns:
            if c.kind == "numeric" and c.legacy_sum is not None:
                lignes.append(f"| `{r.dataset}` | {c.name} | {c.legacy_sum:,.2f} | {c.target_sum:,.2f} |")
    echantillons = [(r.dataset, s) for r in resultats for s in r.samples]
    if echantillons:
        lignes += ["", "## Échantillon d'écarts", "", "| Jeu | Clé | Colonne | Legacy | Cible |", "|---|---|---|---|---|"]
        for dataset, s in echantillons:
            lignes.append(f"| `{dataset}` | {s['cle']} | {s['colonne']} | {s['legacy']} | {s['cible']} |")
    return "\n".join(lignes) + "\n"


def write_reports(resultats: list[DatasetResult], reports_dir: Path = config.REPORTS_DIR) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "reconciliation.json").write_text(
        json.dumps([asdict(r) | {"passed": r.passed} for r in resultats], indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    chemin = reports_dir / "reconciliation.md"
    chemin.write_text(to_markdown(resultats), encoding="utf-8")
    return chemin
