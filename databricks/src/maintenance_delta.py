"""Maintenance Delta après le chargement de nuit : compactage (OPTIMIZE), statistiques, nettoyage (VACUUM)."""

from __future__ import annotations

import argparse

from pyspark.sql import SparkSession

TABLES_GOLD = ("fct_sinistre", "dim_client", "mart_sinistres_enrichis", "ml_features_fraude")
TABLES_SILVER = ("silver_clients", "silver_polices", "silver_sinistres", "silver_enquetes")


def commandes(catalogue: str, retention_heures: int = 168) -> list[str]:
    sql = []
    for table in TABLES_GOLD:
        sql.append(f"OPTIMIZE {catalogue}.gold.{table}")
        sql.append(f"ANALYZE TABLE {catalogue}.gold.{table} COMPUTE STATISTICS FOR ALL COLUMNS")
    sql += [f"VACUUM {catalogue}.silver.{table} RETAIN {retention_heures} HOURS" for table in TABLES_SILVER]
    return sql


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalogue", required=True)
    args = parser.parse_args(argv)
    spark = SparkSession.builder.getOrCreate()
    for instruction in commandes(args.catalogue):
        spark.sql(instruction)


if __name__ == "__main__":
    main()
