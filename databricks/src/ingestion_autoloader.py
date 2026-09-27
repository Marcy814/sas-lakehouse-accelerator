"""Auto Loader : zone d'atterrissage ADLS/S3 → tables bronze Delta de Unity Catalog.

Chaque fichier n'est lu qu'une fois (checkpoint), les nouvelles colonnes sont ajoutées automatiquement
(schema evolution) et les valeurs mal formées sont conservées dans _rescued_data.
"""

from __future__ import annotations

import argparse

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

TABLES_SOURCES = ("clients", "polices", "sinistres", "enquetes")


def ajouter_metadonnees(df: DataFrame) -> DataFrame:
    fichier = F.col("_metadata.file_name")
    return (
        df.withColumn("_source_file", fichier)
        .withColumn("_batch_id", F.regexp_extract(fichier, r"batch_(\d+)", 1).cast("int"))
        .withColumn("_ingested_at", F.current_timestamp())
    )


def lire_flux(spark: SparkSession, chemin: str, emplacement_schema: str, format_source: str = "cloudFiles") -> DataFrame:
    if format_source == "cloudFiles":
        lecteur = (
            spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "csv")
            .option("cloudFiles.schemaLocation", emplacement_schema)
            .option("cloudFiles.inferColumnTypes", "false")
            .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
            .option("rescuedDataColumn", "_rescued_data")
        )
    else:
        schema = spark.read.option("header", "true").csv(chemin).schema
        lecteur = spark.readStream.format(format_source).schema(schema)
    return lecteur.option("header", "true").load(chemin)


def ecrire_bronze(df: DataFrame, destination: str, checkpoint: str, format_cible: str = "delta"):
    flux = (
        ajouter_metadonnees(df)
        .writeStream.format(format_cible)
        .option("checkpointLocation", checkpoint)
        .option("mergeSchema", "true")
        .trigger(availableNow=True)
    )
    return flux.toTable(destination) if format_cible == "delta" else flux.start(destination)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--landing", required=True, help="ex. abfss://landing@compte.dfs.core.windows.net/extraits")
    parser.add_argument("--catalogue", required=True)
    args = parser.parse_args(argv)

    spark = SparkSession.builder.getOrCreate()
    spark.sql(f"create schema if not exists {args.catalogue}.bronze")
    requetes = []
    for table in TABLES_SOURCES:
        flux = lire_flux(spark, f"{args.landing}/{table}/", f"{args.landing}/_schemas/{table}")
        requetes.append(ecrire_bronze(flux, f"{args.catalogue}.bronze.{table}", f"{args.landing}/_checkpoints/{table}"))
    for requete in requetes:
        requete.awaitTermination()


if __name__ == "__main__":
    main()
