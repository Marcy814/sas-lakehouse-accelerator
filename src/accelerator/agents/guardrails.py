"""Garde-fous SQL pour l'agent analytique : lecture seule, périmètre de tables, volume borné."""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Drop, exp.Create, exp.Alter, exp.Command,
    exp.Copy, exp.Pragma, exp.Attach, exp.Detach, exp.Set, exp.Use, exp.Transaction, exp.Commit,
    exp.Rollback, exp.TruncateTable,
)
FORBIDDEN_FUNCTIONS = {
    "read_csv", "read_csv_auto", "read_parquet", "parquet_scan", "read_json", "read_json_auto",
    "read_text", "read_blob", "glob", "getenv", "current_setting", "duckdb_settings",
    "duckdb_secrets", "query", "query_table", "sniff_csv",
}
QUERY_TYPES = (exp.Select, exp.Union, exp.Intersect, exp.Except)


class GuardrailViolation(ValueError):
    pass


@dataclass(frozen=True)
class GuardedQuery:
    sql: str
    tables: frozenset[str]
    limit_applied: bool


def _function_name(fonction: exp.Func) -> str:
    if isinstance(fonction, exp.Anonymous):
        return str(fonction.name).lower()
    return fonction.sql_name().lower()


def _refuser_table_utilisee_comme_colonne(requete: exp.Expression, ctes: set[str]) -> None:
    """DuckDB accepte un nom de table ou d'alias comme colonne et le traite comme la ligne entière
    (un STRUCT) : la requête s'exécute sans erreur mais trie ou compare sur le mauvais champ."""
    noms_de_tables = set(ctes)
    for table in requete.find_all(exp.Table):
        noms_de_tables.add(table.name.lower())
        if table.alias:
            noms_de_tables.add(table.alias.lower())
    for sous_requete in requete.find_all(exp.Subquery):
        if sous_requete.alias:
            noms_de_tables.add(sous_requete.alias.lower())

    for colonne in requete.find_all(exp.Column):
        if colonne.table or isinstance(colonne.this, exp.Star):
            continue
        if colonne.name.lower() in noms_de_tables:
            raise GuardrailViolation(
                f"« {colonne.name} » est un nom de table ou d'alias utilisé comme colonne : DuckDB le "
                "traiterait comme la ligne entière et le résultat serait faux sans erreur. Appelle "
                "describe_table pour obtenir le vrai nom de la colonne, puis réécris la requête."
            )


def validate_sql(sql: str, allowed_schemas: set[str], max_rows: int = 200) -> GuardedQuery:
    try:
        instructions = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except sqlglot.errors.ParseError as exc:
        raise GuardrailViolation(f"SQL invalide : {str(exc).splitlines()[0]}") from exc
    if len(instructions) != 1:
        raise GuardrailViolation("Une seule instruction SQL est autorisée.")
    requete = instructions[0]
    if not isinstance(requete, QUERY_TYPES):
        raise GuardrailViolation(f"Seules les requêtes SELECT sont autorisées (reçu : {type(requete).__name__}).")

    for noeud in requete.walk():
        if isinstance(noeud, FORBIDDEN_NODES):
            raise GuardrailViolation(f"Opération interdite : {type(noeud).__name__}.")
        if isinstance(noeud, exp.Func) and _function_name(noeud) in FORBIDDEN_FUNCTIONS:
            raise GuardrailViolation(f"Fonction interdite : {_function_name(noeud)}.")

    ctes = {cte.alias_or_name.lower() for cte in requete.find_all(exp.CTE)}
    schemas = {s.lower() for s in allowed_schemas}
    tables = set()
    for table in requete.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise GuardrailViolation("Les fonctions de table ne sont pas autorisées.")
        if table.catalog:
            raise GuardrailViolation("Les références à un autre catalogue ne sont pas autorisées.")
        nom, schema = table.name.lower(), table.db.lower()
        if not schema and nom in ctes:
            continue
        if schema not in schemas:
            raise GuardrailViolation(
                f"Table hors périmètre : {table.sql()} (schémas autorisés : {', '.join(sorted(schemas))})."
            )
        tables.add(f"{schema}.{nom}")

    _refuser_table_utilisee_comme_colonne(requete, ctes)

    limite = requete.args.get("limit")
    limite_appliquee = False
    if limite is None:
        requete = requete.limit(max_rows)
        limite_appliquee = True
    else:
        valeur = limite.expression
        if not (isinstance(valeur, exp.Literal) and valeur.is_int and int(valeur.this) <= max_rows):
            requete = requete.limit(max_rows)
            limite_appliquee = True

    return GuardedQuery(requete.sql(dialect="duckdb"), frozenset(tables), limite_appliquee)
