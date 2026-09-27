"""Traitement en continu (micro-lots) des événements de sinistres, avec garantie « exactly-once ».

Même modèle que Spark Structured Streaming / Auto Loader : chaque fichier d'événements arrivé est un
micro-lot; un checkpoint mémorise les fichiers traités dans la MÊME transaction que les écritures;
un filigrane (watermark) borne l'attente des événements en retard; les agrégats par fenêtre de temps
sont recalculés pour les seules fenêtres touchées.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import duckdb

from accelerator import config

STREAM_DIR = config.DATA_DIR / "stream" / "incoming"
DEBUT_SIMULATION = datetime(2026, 7, 1, 8, 0, 0)
DUREE_LOT = timedelta(minutes=10)
PROVINCES = ["QC", "QC", "QC", "ON", "ON", "NB", "NS", "AB", "BC"]

DDL = """
create schema if not exists stream;
create table if not exists stream.checkpoint (
    source_file varchar primary key, lot integer, evenements_lus integer, traite_a timestamp
);
create table if not exists stream.etat (cle varchar primary key, valeur timestamp);
create table if not exists stream.metriques_lots (
    lot integer, source_file varchar, lus integer, doublons integer, en_retard integer, retenus integer,
    filigrane timestamp, fenetres_touchees integer, alertes integer, traite_a timestamp
);
create table if not exists bronze.evenements_sinistres (
    event_id varchar, type_evenement varchar, sinistre_id varchar, police_id varchar, province varchar,
    type_sinistre varchar, montant double, event_time timestamp, _source_file varchar, _ingested_at timestamp
);
create schema if not exists gold;
create table if not exists gold.sinistres_par_fenetre (
    debut_fenetre timestamp, province varchar, nb_declarations integer, montant_declare double,
    nb_paiements integer, montant_paye double, mis_a_jour_a timestamp
);
create table if not exists gold.alertes_temps_reel (
    debut_fenetre timestamp, province varchar, nb_declarations integer, seuil integer, detectee_a timestamp
);
"""


@dataclass
class BatchMetrics:
    lot: int
    source_file: str
    lus: int
    doublons: int
    en_retard: int
    retenus: int
    filigrane: datetime | None
    fenetres_touchees: int
    alertes: int

    def summary(self) -> str:
        return (f"lot {self.lot:>2} | lus={self.lus:>4} doublons={self.doublons:>3} en_retard={self.en_retard:>3} "
                f"retenus={self.retenus:>4} | filigrane={self.filigrane:%H:%M} | fenêtres={self.fenetres_touchees:>2} "
                f"alertes={self.alertes}")


def generate_batch(numero: int, stream_dir: Path = STREAM_DIR, seed: int = 7, taille: int = 60) -> Path:
    """Écrit le micro-lot numéro `numero` (fichier JSON lines) tel qu'un bus d'événements le déposerait."""
    rng = random.Random(seed * 1000 + numero)
    debut = DEBUT_SIMULATION + (numero - 1) * DUREE_LOT
    evenements = []
    for i in range(taille):
        declaration = rng.random() < 0.7
        evenements.append({
            "event_id": f"EV-{numero:03d}-{i:04d}",
            "type_evenement": "SINISTRE_DECLARE" if declaration else "PAIEMENT_EMIS",
            "sinistre_id": f"SI-S{numero:03d}{i:04d}",
            "police_id": f"PO-{rng.randint(1, 11000):07d}",
            "province": rng.choice(PROVINCES),
            "type_sinistre": rng.choice(["COLLISION", "VOL", "DEGAT_EAU", "BRIS_GLACE"]),
            "montant": round(rng.uniform(300, 15000), 2),
            "event_time": (debut + timedelta(seconds=rng.randint(0, int(DUREE_LOT.total_seconds()) - 1))).isoformat(),
        })
    if numero == 4:
        for i in range(40):
            evenements.append({
                "event_id": f"EV-{numero:03d}-T{i:03d}", "type_evenement": "SINISTRE_DECLARE",
                "sinistre_id": f"SI-T{numero:03d}{i:03d}", "police_id": f"PO-{rng.randint(1, 11000):07d}",
                "province": "QC", "type_sinistre": "DEGAT_EAU", "montant": round(rng.uniform(2000, 40000), 2),
                "event_time": (debut + timedelta(seconds=rng.randint(0, 540))).isoformat(),
            })
    for evenement in rng.sample(evenements, k=max(1, len(evenements) // 30)):
        evenements.append(dict(evenement))
    for evenement in rng.sample(evenements, k=max(1, len(evenements) // 25)):
        retard = timedelta(minutes=rng.choice([15, 45, 90]))
        evenement["event_time"] = (datetime.fromisoformat(evenement["event_time"]) - retard).isoformat()
    rng.shuffle(evenements)
    stream_dir.mkdir(parents=True, exist_ok=True)
    chemin = stream_dir / f"evenements_{numero:03d}.jsonl"
    chemin.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in evenements) + "\n", encoding="utf-8")
    return chemin


class StreamProcessor:
    def __init__(self, db_path: Path = config.DB_PATH, stream_dir: Path = STREAM_DIR,
                 delai_filigrane: timedelta = timedelta(minutes=30), fenetre: timedelta = timedelta(minutes=15),
                 seuil_alerte: int = 40):
        self.db_path, self.stream_dir = db_path, stream_dir
        self.delai_filigrane, self.fenetre, self.seuil_alerte = delai_filigrane, fenetre, seuil_alerte

    def _fichiers_en_attente(self, con: duckdb.DuckDBPyConnection) -> list[Path]:
        deja = {r[0] for r in con.execute("select source_file from stream.checkpoint").fetchall()}
        return [f for f in sorted(self.stream_dir.glob("evenements_*.jsonl")) if f.name not in deja]

    def process_available(self) -> list[BatchMetrics]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        resultats = []
        with duckdb.connect(str(self.db_path)) as con:
            con.execute("create schema if not exists bronze")
            con.execute(DDL)
            for fichier in self._fichiers_en_attente(con):
                resultats.append(self._traiter(con, fichier))
        return resultats

    def _traiter(self, con: duckdb.DuckDBPyConnection, fichier: Path) -> BatchMetrics:
        lot = int(fichier.stem.split("_")[-1])
        fenetre_s = int(self.fenetre.total_seconds())
        con.execute("begin transaction")
        try:
            filigrane_prec = con.execute("select valeur from stream.etat where cle = 'filigrane'").fetchone()
            filigrane_prec = filigrane_prec[0] if filigrane_prec else None
            con.execute(
                "create or replace temp table lot as select *, cast(event_time as timestamp) as ts "
                "from read_json(?, format = 'newline_delimited', columns = {event_id: 'varchar', "
                "type_evenement: 'varchar', sinistre_id: 'varchar', police_id: 'varchar', province: 'varchar', "
                "type_sinistre: 'varchar', montant: 'double', event_time: 'varchar'})",
                [str(fichier)],
            )
            lus = con.execute("select count(*) from lot").fetchone()[0]
            con.execute(
                "create or replace temp table uniques as select * from lot "
                "qualify row_number() over (partition by event_id order by ts) = 1"
            )
            con.execute("delete from uniques where event_id in (select event_id from bronze.evenements_sinistres)")
            doublons = lus - con.execute("select count(*) from uniques").fetchone()[0]
            en_retard = 0
            if filigrane_prec is not None:
                en_retard = con.execute("select count(*) from uniques where ts < ?", [filigrane_prec]).fetchone()[0]
                con.execute("delete from uniques where ts < ?", [filigrane_prec])
            retenus = con.execute("select count(*) from uniques").fetchone()[0]

            con.execute(
                "insert into bronze.evenements_sinistres select event_id, type_evenement, sinistre_id, police_id, "
                "province, type_sinistre, montant, ts, ?, current_timestamp from uniques",
                [fichier.name],
            )
            fenetres = f"time_bucket(interval {fenetre_s} second, ts)"
            con.execute(f"create or replace temp table touchees as select distinct {fenetres} as debut_fenetre, "
                        "province from uniques")
            touchees = con.execute("select count(*) from touchees").fetchone()[0]
            con.execute(
                "delete from gold.sinistres_par_fenetre g using touchees t "
                "where g.debut_fenetre = t.debut_fenetre and g.province = t.province"
            )
            con.execute(f"""
                insert into gold.sinistres_par_fenetre
                select {fenetres.replace('ts', 'e.event_time')} as debut_fenetre, e.province,
                       count(*) filter (where type_evenement = 'SINISTRE_DECLARE'),
                       coalesce(sum(montant) filter (where type_evenement = 'SINISTRE_DECLARE'), 0),
                       count(*) filter (where type_evenement = 'PAIEMENT_EMIS'),
                       coalesce(sum(montant) filter (where type_evenement = 'PAIEMENT_EMIS'), 0),
                       current_timestamp
                from bronze.evenements_sinistres e
                join touchees t
                  on {fenetres.replace('ts', 'e.event_time')} = t.debut_fenetre and e.province = t.province
                group by all
            """)
            alertes = con.execute(
                "insert into gold.alertes_temps_reel "
                "select g.debut_fenetre, g.province, g.nb_declarations, ?, current_timestamp "
                "from gold.sinistres_par_fenetre g join touchees t using (debut_fenetre, province) "
                "where g.nb_declarations >= ? and not exists (select 1 from gold.alertes_temps_reel a "
                "where a.debut_fenetre = g.debut_fenetre and a.province = g.province) returning 1",
                [self.seuil_alerte, self.seuil_alerte],
            ).fetchall()

            max_ts = con.execute("select max(ts) from uniques").fetchone()[0]
            candidats = [v for v in (filigrane_prec, max_ts - self.delai_filigrane if max_ts else None) if v]
            filigrane = max(candidats) if candidats else None
            if filigrane is not None:
                con.execute("insert or replace into stream.etat values ('filigrane', ?)", [filigrane])
            con.execute("insert into stream.checkpoint values (?, ?, ?, current_timestamp)", [fichier.name, lot, lus])
            metriques = BatchMetrics(lot, fichier.name, lus, doublons, en_retard, retenus, filigrane, touchees,
                                     len(alertes))
            con.execute("insert into stream.metriques_lots values (?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)",
                        [lot, fichier.name, lus, doublons, en_retard, retenus, filigrane, touchees, len(alertes)])
            con.execute("commit")
        except Exception:
            con.execute("rollback")
            raise
        return metriques


def reset(db_path: Path = config.DB_PATH, stream_dir: Path = STREAM_DIR) -> None:
    for fichier in stream_dir.glob("evenements_*.jsonl"):
        fichier.unlink()
    if db_path.exists():
        with duckdb.connect(str(db_path)) as con:
            con.execute("drop schema if exists stream cascade")
            con.execute("drop table if exists bronze.evenements_sinistres")
            con.execute("drop table if exists gold.sinistres_par_fenetre")
            con.execute("drop table if exists gold.alertes_temps_reel")
