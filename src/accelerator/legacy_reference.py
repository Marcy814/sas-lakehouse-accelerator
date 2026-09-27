"""Implémentation de référence des traitements legacy (SAS 9, Informatica, DataStage).

Ces moteurs n'étant pas disponibles hors de l'environnement client, ce module reproduit fidèlement
leur sémantique (valeurs manquantes SAS, BY/FIRST., LAG, RETAIN, MERGE IN=; Router et arrondi de
colonne cible Informatica; lookup « Continue » et agrégateur DataStage) afin de produire les sorties
« legacy » utilisées comme référence par la réconciliation.
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import pandas as pd

from accelerator import config


def sas_lt(valeur, seuil) -> bool:
    """Comparaison SAS « < » : une valeur manquante est inférieure à tout nombre."""
    if valeur is None or (isinstance(valeur, float) and math.isnan(valeur)):
        return True
    return valeur < seuil


def sas_missing(valeur) -> bool:
    return valeur is None or (isinstance(valeur, float) and math.isnan(valeur)) or valeur is pd.NaT


def propcase(texte: str) -> str:
    def _mot(mot: str) -> str:
        return "-".join(p[:1].upper() + p[1:] for p in mot.split("-"))

    return " ".join(_mot(m) for m in texte.strip().lower().split(" "))


def intck_year_continuous(debut, fin: date):
    if sas_missing(debut):
        return None
    return fin.year - debut.year - ((fin.month, fin.day) < (debut.month, debut.day))


def _lire_source(landing_dir: Path, table: str, dates: list[str]) -> pd.DataFrame:
    fichiers = sorted((landing_dir / table).glob("batch_*.csv"))
    df = pd.concat(
        [pd.read_csv(f, dtype=str, keep_default_na=False) for f in fichiers], ignore_index=True
    )
    for col in dates:
        df[col] = pd.to_datetime(df[col].replace("", None)).dt.date
    return df


def _numerique(serie: pd.Series) -> pd.Series:
    return pd.to_numeric(serie.replace("", None)).astype(float)


def _premier_par_cle(df: pd.DataFrame, cle: str) -> pd.DataFrame:
    """PROC SORT BY cle DESCENDING date_maj + DATA step « if first.cle »."""
    tri = df.sort_values([cle, "date_maj"], ascending=[True, False], kind="mergesort")
    return tri.drop_duplicates(subset=[cle], keep="first").reset_index(drop=True)


def programme_01(src_clients: pd.DataFrame) -> pd.DataFrame:
    df = _premier_par_cle(src_clients, "client_id")
    df["province"] = df["province"].str.strip().str.upper()
    df["nom_complet"] = [f"{propcase(p)} {propcase(n)}".strip() for p, n in zip(df["prenom"], df["nom"])]
    df["age"] = [intck_year_continuous(d, config.DATE_REF) for d in df["date_naissance"]]

    def tranche(age):
        if sas_lt(age, 30):
            return "18-29"
        if age < 50:
            return "30-49"
        if age < 65:
            return "50-64"
        return "65+"

    df["tranche_age"] = [tranche(a) for a in df["age"]]
    df["age"] = df["age"].astype("Int64")
    colonnes = ["client_id", "nom_complet", "date_naissance", "age", "tranche_age",
                "province", "ville", "segment", "date_maj"]
    return df[colonnes]


def programme_02(src_polices: pd.DataFrame, src_sinistres: pd.DataFrame, clients_courants: pd.DataFrame):
    polices = _premier_par_cle(src_polices, "police_id")
    polices["prime_annuelle"] = _numerique(polices["prime_annuelle"])

    sinistres = _premier_par_cle(src_sinistres, "sinistre_id")
    sinistres["montant_reclame"] = _numerique(sinistres["montant_reclame"])
    sinistres["montant_paye"] = _numerique(sinistres["montant_paye"])

    joints = sinistres.merge(
        polices[["police_id", "client_id", "produit", "date_debut"]], on="police_id", how="inner"
    ).merge(clients_courants[["client_id", "province", "segment"]], on="client_id", how="left")
    joints = joints.rename(columns={"date_debut": "date_debut_police"})
    joints["delai_declaration"] = [
        (d - s).days for d, s in zip(joints["date_declaration"], joints["date_sinistre"])
    ]

    def tranche(montant):
        if sas_lt(montant, 1000):
            return "PETIT"
        if montant < 10000:
            return "MOYEN"
        return "GRAND"

    joints["tranche_montant"] = [tranche(m) for m in joints["montant_paye"]]
    joints["taux_paiement"] = joints["montant_paye"] / joints["montant_reclame"]
    joints["annee_sinistre"] = [d.year for d in joints["date_sinistre"]]
    colonnes = ["sinistre_id", "police_id", "client_id", "produit", "province", "segment",
                "date_debut_police", "date_sinistre", "date_declaration", "type_sinistre", "statut",
                "montant_reclame", "montant_paye", "delai_declaration", "tranche_montant",
                "taux_paiement", "annee_sinistre"]
    return polices, joints[colonnes]


def programme_03(polices_courantes: pd.DataFrame, sinistres_enrichis: pd.DataFrame) -> pd.DataFrame:
    primes = []
    for annee in config.RATIO_YEARS:
        debut_annee, fin_annee = date(annee, 1, 1), date(annee, 12, 31)
        actives = polices_courantes[
            (polices_courantes["date_debut"] <= fin_annee) & (polices_courantes["date_fin"] >= debut_annee)
        ]
        jours = [
            (min(f, fin_annee) - max(d, debut_annee)).days + 1
            for d, f in zip(actives["date_debut"], actives["date_fin"])
        ]
        acquis = actives.assign(acquis=actives["prime_annuelle"] * pd.Series(jours, index=actives.index) / 365)
        agg = acquis.groupby("produit", as_index=False)["acquis"].sum()
        agg["annee"] = annee
        primes.append(agg.rename(columns={"acquis": "primes_acquises"}))
    primes_df = pd.concat(primes, ignore_index=True)

    sin_agg = (
        sinistres_enrichis.groupby(["produit", "annee_sinistre"], as_index=False)
        .agg(nb_sinistres=("sinistre_id", "size"),
             total_reclame=("montant_reclame", lambda s: s.sum(min_count=1)),
             total_paye=("montant_paye", lambda s: s.sum(min_count=1)))
        .rename(columns={"annee_sinistre": "annee"})
    )
    ratio = primes_df.merge(sin_agg, on=["produit", "annee"], how="left", indicator=True)
    absents = ratio["_merge"] == "left_only"
    ratio.loc[absents, ["nb_sinistres", "total_reclame", "total_paye"]] = 0
    ratio = ratio.drop(columns="_merge")
    ratio["nb_sinistres"] = ratio["nb_sinistres"].astype(int)
    ratio["ratio_sinistralite"] = ratio["total_paye"] / ratio["primes_acquises"]
    ratio = ratio.sort_values(["produit", "annee"]).reset_index(drop=True)
    return ratio[["produit", "annee", "primes_acquises", "nb_sinistres", "total_reclame",
                  "total_paye", "ratio_sinistralite"]]


def programme_04(sinistres_enrichis: pd.DataFrame) -> pd.DataFrame:
    tri = sinistres_enrichis.sort_values(["client_id", "date_sinistre", "sinistre_id"], kind="mergesort")
    lignes = []
    client_precedent = object()
    lag_date = None
    nb_cumul = 0
    montant_cumul = 0.0
    for row in tri.itertuples(index=False):
        date_precedente = lag_date
        lag_date = row.date_sinistre
        if row.client_id != client_precedent:
            nb_cumul, montant_cumul, date_precedente = 0, 0.0, None
            client_precedent = row.client_id
        nb_cumul += 1
        montant_cumul = montant_cumul + row.montant_reclame
        jours = None if date_precedente is None else (row.date_sinistre - date_precedente).days
        flag_rapproche = int(jours is not None and jours <= 30)
        flag_debut = int((row.date_sinistre - row.date_debut_police).days <= 30)
        flag_tardive = int(row.delai_declaration > 90)
        lignes.append({
            "client_id": row.client_id,
            "sinistre_id": row.sinistre_id,
            "date_sinistre": row.date_sinistre,
            "nb_sinistres_cumul": nb_cumul,
            "montant_cumul": montant_cumul,
            "jours_depuis_precedent": jours,
            "flag_rapproche": flag_rapproche,
            "flag_debut_police": flag_debut,
            "flag_declaration_tardive": flag_tardive,
            "score_risque": 40 * flag_rapproche + 35 * flag_debut + 25 * flag_tardive,
        })
    df = pd.DataFrame(lignes)
    df["jours_depuis_precedent"] = df["jours_depuis_precedent"].astype("Int64")
    return df


FRANCHISES = {"AUTO": 500.0, "HABITATION": 1000.0}


def mapping_informatica_sinistres_regles(sinistres_enrichis: pd.DataFrame, polices_courantes: pd.DataFrame):
    """legacy/informatica/m_sinistres_regles.xml"""
    sq = sinistres_enrichis[sinistres_enrichis["statut"] == "FERME"]
    df = sq.merge(polices_courantes[["police_id", "prime_annuelle"]], on="police_id", how="left")
    df["mois_sinistre"] = [d.strftime("%Y%m") for d in df["date_sinistre"]]
    df["franchise"] = [FRANCHISES.get(p, 0.0) for p in df["produit"]]
    df["montant_net"] = [
        0.0 if sas_missing(m) else max(m - f, 0.0) for m, f in zip(df["montant_paye"], df["franchise"])
    ]
    df["ratio_prime"] = (df["montant_paye"] / df["prime_annuelle"]).round(6)
    grands = df["montant_net"] >= 25000
    regles = df.loc[~grands, ["sinistre_id", "produit", "mois_sinistre", "montant_paye", "franchise",
                              "montant_net", "ratio_prime"]]
    grands_sinistres = df.loc[grands, ["sinistre_id", "produit", "mois_sinistre", "montant_net"]]
    return regles.reset_index(drop=True), grands_sinistres.reset_index(drop=True)


def job_datastage_primes_mensuelles(polices_courantes: pd.DataFrame, clients_courants: pd.DataFrame):
    """legacy/datastage/j_primes_mensuelles.dsx"""
    polices = polices_courantes[polices_courantes["statut"] != "ANNULEE"]
    df = polices.merge(clients_courants[["client_id", "segment"]], on="client_id", how="left")
    df["segment"] = df["segment"].fillna("INCONNU")
    df["mois_emission"] = [d.strftime("%Y%m") for d in df["date_debut"]]
    df["produit"] = df["produit"].str.strip()
    df["prime"] = df["prime_annuelle"].fillna(0.0)
    agg = (
        df.groupby(["mois_emission", "produit", "segment"], as_index=False)
        .agg(nb_polices=("police_id", "size"), primes_emises=("prime", "sum"), prime_moyenne=("prime", "mean"))
        .sort_values(["mois_emission", "produit", "segment"])
    )
    return agg.reset_index(drop=True)


def run(landing_dir: Path = config.LANDING_DIR, output_dir: Path = config.LEGACY_OUTPUT_DIR) -> dict[str, int]:
    clients = _lire_source(landing_dir, "clients", ["date_naissance", "date_maj"])
    polices = _lire_source(landing_dir, "polices", ["date_debut", "date_fin", "date_maj"])
    sinistres = _lire_source(landing_dir, "sinistres", ["date_sinistre", "date_declaration", "date_maj"])

    clients_courants = programme_01(clients)
    polices_courantes, sinistres_enrichis = programme_02(polices, sinistres, clients_courants)
    ratio = programme_03(polices_courantes, sinistres_enrichis)
    fraude = programme_04(sinistres_enrichis)
    sinistres_regles, grands_sinistres = mapping_informatica_sinistres_regles(sinistres_enrichis, polices_courantes)
    primes_mensuelles = job_datastage_primes_mensuelles(polices_courantes, clients_courants)

    sorties = {
        "clients_courants": clients_courants,
        "polices_courantes": polices_courantes,
        "sinistres_enrichis": sinistres_enrichis,
        "ratio_sinistralite": ratio,
        "indicateurs_fraude": fraude,
        "sinistres_regles": sinistres_regles,
        "grands_sinistres": grands_sinistres,
        "primes_mensuelles": primes_mensuelles,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    for nom, df in sorties.items():
        df.to_csv(output_dir / f"{nom}.csv", index=False)
    return {nom: len(df) for nom, df in sorties.items()}
