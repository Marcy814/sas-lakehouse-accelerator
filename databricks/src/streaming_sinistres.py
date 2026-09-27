"""Structured Streaming : événements de sinistres → agrégats par fenêtre de 15 minutes et alertes.

Filigrane (watermark) de 30 minutes, dédoublonnage dans le filigrane, écriture idempotente par
foreachBatch + MERGE Delta (une fenêtre réécrite deux fois donne le même résultat).
"""

from __future__ import annotations

import argparse

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, StringType, StructField, StructType

SCHEMA_EVENEMENTS = StructType([
    StructField("event_id", StringType()),
    StructField("type_evenement", StringType()),
    StructField("sinistre_id", StringType()),
    StructField("police_id", StringType()),
    StructField("province", StringType()),
    StructField("type_sinistre", StringType()),
    StructField("montant", DoubleType()),
    StructField("event_time", StringType()),
])


def agreger(evenements: DataFrame, delai_filigrane: str = "30 minutes", fenetre: str = "15 minutes") -> DataFrame:
    declaration = F.col("type_evenement") == "SINISTRE_DECLARE"
    paiement = F.col("type_evenement") == "PAIEMENT_EMIS"
    return (
        evenements.withColumn("event_time", F.to_timestamp("event_time"))
        .withWatermark("event_time", delai_filigrane)
        .dropDuplicatesWithinWatermark(["event_id"])
        .groupBy(F.window("event_time", fenetre).alias("fenetre"), "province")
        .agg(
            F.sum(F.when(declaration, 1).otherwise(0)).alias("nb_declarations"),
            F.sum(F.when(declaration, F.col("montant")).otherwise(0.0)).alias("montant_declare"),
            F.sum(F.when(paiement, 1).otherwise(0)).alias("nb_paiements"),
            F.sum(F.when(paiement, F.col("montant")).otherwise(0.0)).alias("montant_paye"),
        )
        .select(F.col("fenetre.start").alias("debut_fenetre"), "province", "nb_declarations", "montant_declare",
                "nb_paiements", "montant_paye")
    )


def alertes(agregats: DataFrame, seuil: int) -> DataFrame:
    return (agregats.where(F.col("nb_declarations") >= seuil)
            .select("debut_fenetre", "province", "nb_declarations", F.lit(seuil).alias("seuil"),
                    F.current_timestamp().alias("detectee_a")))


def fusionner_lot(catalogue: str, seuil: int):
    def _fusionner(lot: DataFrame, lot_id: int) -> None:
        from delta.tables import DeltaTable

        spark = lot.sparkSession
        cible = f"{catalogue}.gold.sinistres_par_fenetre"
        if not spark.catalog.tableExists(cible):
            lot.limit(0).write.format("delta").saveAsTable(cible)
        (DeltaTable.forName(spark, cible).alias("c")
         .merge(lot.alias("n"), "c.debut_fenetre = n.debut_fenetre and c.province = n.province")
         .whenMatchedUpdateAll().whenNotMatchedInsertAll().execute())
        alertes(lot, seuil).write.format("delta").mode("append").saveAsTable(f"{catalogue}.gold.alertes_temps_reel")
    return _fusionner


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evenements", required=True, help="Dossier où le bus d'événements dépose les fichiers JSON")
    parser.add_argument("--catalogue", required=True)
    parser.add_argument("--seuil-alerte", type=int, default=40)
    args = parser.parse_args(argv)

    spark = SparkSession.builder.getOrCreate()
    flux = spark.readStream.schema(SCHEMA_EVENEMENTS).json(args.evenements)
    (agreger(flux).writeStream
     .foreachBatch(fusionner_lot(args.catalogue, args.seuil_alerte))
     .outputMode("append")
     .option("checkpointLocation", f"{args.evenements}/_checkpoints/agregats")
     .trigger(availableNow=True)
     .start()
     .awaitTermination())


if __name__ == "__main__":
    main()
