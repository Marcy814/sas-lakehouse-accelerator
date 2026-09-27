"""Génération déterministe des extraits du système source (PolicyAdmin) en deux lots."""

from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from accelerator import config

PRENOMS = [
    "jean", "marie", "louis", "sophie", "mathieu", "isabelle", "olivier", "catherine", "gabriel",
    "émilie", "félix", "chloé", "étienne", "geneviève", "samuel", "julie", "jean-françois",
    "marie-ève", "pierre-luc", "anne-sophie", "alexandre", "noémie", "william", "léa", "david",
]
NOMS = [
    "tremblay", "gagnon", "roy", "côté", "bouchard", "gauthier", "morin", "lavoie", "fortin",
    "gagné", "ouellet", "pelletier", "bélanger", "lévesque", "bergeron", "leblanc", "paquette",
    "girard", "simard", "boucher", "caron", "beaulieu", "cloutier", "dubé", "poirier", "smith",
    "martin", "nguyen", "haddad", "saint-pierre",
]
VILLES = {
    "QC": ["Montréal", "Québec", "Laval", "Gatineau", "Sherbrooke", "Trois-Rivières", "Lévis"],
    "ON": ["Toronto", "Ottawa", "Mississauga", "Hamilton"],
    "NB": ["Moncton", "Fredericton"],
    "NS": ["Halifax"],
    "AB": ["Calgary", "Edmonton"],
    "BC": ["Vancouver", "Victoria"],
}
PROVINCE_POIDS = {"QC": 0.55, "ON": 0.22, "NB": 0.06, "NS": 0.05, "AB": 0.06, "BC": 0.06}
PRODUITS = {"AUTO": 0.5, "HABITATION": 0.4, "VIE": 0.1}
PRIME_BASE = {"AUTO": 1400.0, "HABITATION": 1100.0, "VIE": 650.0}
TYPES_SINISTRE = {
    "AUTO": ["COLLISION", "VOL", "BRIS_GLACE"],
    "HABITATION": ["DEGAT_EAU", "INCENDIE", "VOL"],
    "VIE": ["DECES"],
}

CLIENT_COLS = ["client_id", "prenom", "nom", "date_naissance", "province", "ville", "segment", "date_maj"]
POLICE_COLS = [
    "police_id", "client_id", "produit", "date_debut", "date_fin", "prime_annuelle", "statut", "date_maj",
]
SINISTRE_COLS = [
    "sinistre_id", "police_id", "date_sinistre", "date_declaration", "type_sinistre",
    "montant_reclame", "montant_paye", "statut", "date_maj",
]
ENQUETE_COLS = ["enquete_id", "sinistre_id", "date_ouverture", "date_conclusion", "conclusion", "montant_recupere"]


@dataclass
class Volumes:
    clients: int = 6000
    polices: int = 11000
    sinistres: int = 6000
    orphelins: int = 12
    maj_clients: int = 150
    demenagements: int = 60
    versions_tardives: int = 5
    nouveaux_clients: int = 20
    annulations: int = 40
    nouveaux_sinistres: int = 400
    reglements: int = 700
    doublons: int = 50


@dataclass
class Extract:
    clients: list[dict] = field(default_factory=list)
    polices: list[dict] = field(default_factory=list)
    sinistres: list[dict] = field(default_factory=list)


def _choix_pondere(rng: random.Random, poids: dict[str, float]) -> str:
    return rng.choices(list(poids), weights=list(poids.values()), k=1)[0]


def _date_aleatoire(rng: random.Random, debut: date, fin: date) -> date:
    return debut + timedelta(days=rng.randint(0, (fin - debut).days))


def _casse_aleatoire(rng: random.Random, valeur: str) -> str:
    variante = rng.random()
    if variante < 0.3:
        return valeur.upper()
    if variante < 0.6:
        return valeur.lower()
    return valeur.title()


def _province_brute(rng: random.Random, province: str) -> str:
    variante = rng.random()
    if variante < 0.15:
        return f" {province.lower()}"
    if variante < 0.25:
        return f"{province.capitalize()} "
    return province


def _fmt(valeur) -> str:
    if valeur is None:
        return ""
    if isinstance(valeur, float):
        return f"{valeur:.2f}"
    return str(valeur)


class PolicyAdminGenerator:
    def __init__(self, seed: int = 42, volumes: Volumes | None = None):
        self.rng = random.Random(seed)
        self.v = volumes or Volumes()
        self.clients: dict[str, dict] = {}
        self.polices: dict[str, dict] = {}
        self.sinistres: dict[str, dict] = {}
        self._seq_sinistre = 0

    def _nouveau_client(self, idx: int, date_maj_min: date, date_maj_max: date) -> dict:
        rng = self.rng
        province = _choix_pondere(rng, PROVINCE_POIDS)
        naissance = None if rng.random() < 0.015 else _date_aleatoire(rng, date(1945, 1, 1), date(2005, 12, 31))
        return {
            "client_id": f"CL-{idx:06d}",
            "prenom": _casse_aleatoire(rng, rng.choice(PRENOMS)),
            "nom": _casse_aleatoire(rng, rng.choice(NOMS)),
            "date_naissance": naissance,
            "province": _province_brute(rng, province),
            "ville": rng.choice(VILLES[province]),
            "segment": "PME" if rng.random() < 0.18 else "PARTICULIER",
            "date_maj": _date_aleatoire(rng, date_maj_min, date_maj_max),
        }

    def _nouvelle_police(self, idx: int, client_id: str, debut_min: date, debut_max: date) -> dict:
        rng = self.rng
        produit = _choix_pondere(rng, PRODUITS)
        debut = _date_aleatoire(rng, debut_min, debut_max)
        anniversaire = date(debut.year + 1, debut.month, min(debut.day, 28 if debut.month == 2 else 31))
        fin = anniversaire - timedelta(days=1)
        prime = round(PRIME_BASE[produit] * rng.uniform(0.6, 1.8), 2)
        return {
            "police_id": f"PO-{idx:07d}",
            "client_id": client_id,
            "produit": produit,
            "date_debut": debut,
            "date_fin": fin,
            "prime_annuelle": prime,
            "statut": "ACTIVE" if fin >= config.BATCH_EXTRACT_DATES[1] else "EXPIREE",
            "date_maj": debut,
        }

    def _nouveau_sinistre(self, police: dict, date_min: date, date_max: date) -> dict | None:
        rng = self.rng
        debut = max(police["date_debut"], date_min)
        fin = min(police["date_fin"], date_max)
        if debut > fin:
            return None
        self._seq_sinistre += 1
        date_sinistre = _date_aleatoire(rng, debut, fin)
        delai = int(rng.expovariate(1 / 12))
        if rng.random() < 0.04:
            delai += rng.randint(90, 200)
        declaration = min(date_sinistre + timedelta(days=delai), date_max)
        montant = round(math.exp(rng.gauss(7.3, 1.0)), 2)
        if police["produit"] == "VIE":
            montant = round(rng.uniform(10000, 60000), 2)
        statut = rng.choices(["OUVERT", "FERME", "REFUSE"], weights=[0.25, 0.65, 0.10])[0]
        paye = None
        if statut == "FERME":
            paye = round(montant * rng.uniform(0.5, 1.0), 2)
        elif statut == "REFUSE":
            paye = 0.0
        return {
            "sinistre_id": f"SI-{self._seq_sinistre:08d}",
            "police_id": police["police_id"],
            "date_sinistre": date_sinistre,
            "date_declaration": declaration,
            "type_sinistre": rng.choice(TYPES_SINISTRE[police["produit"]]),
            "montant_reclame": montant,
            "montant_paye": paye,
            "statut": statut,
            "date_maj": declaration if statut == "OUVERT" else min(
                declaration + timedelta(days=rng.randint(5, 60)), date_max
            ),
        }

    def _choisir_police_pour_sinistre(self) -> dict:
        polices = list(self.polices.values())
        while True:
            police = self.rng.choice(polices)
            if police["produit"] != "VIE" or self.rng.random() < 0.02:
                return police

    def lot_1(self) -> Extract:
        v, rng = self.v, self.rng
        extrait = Extract()
        fin_lot = config.BATCH_EXTRACT_DATES[1]
        for i in range(1, v.clients + 1):
            client = self._nouveau_client(i, date(2021, 1, 1), date(2025, 12, 31))
            self.clients[client["client_id"]] = client
        ids_clients = list(self.clients)
        for i in range(1, v.polices + 1):
            police = self._nouvelle_police(i, rng.choice(ids_clients), date(2021, 1, 1), date(2025, 12, 31))
            self.polices[police["police_id"]] = police

        recidivistes = rng.sample(ids_clients, 40)
        while len(self.sinistres) < v.sinistres:
            police = self._choisir_police_pour_sinistre()
            sinistre = self._nouveau_sinistre(police, date(2022, 1, 1), fin_lot)
            if sinistre:
                self.sinistres[sinistre["sinistre_id"]] = sinistre
        for client_id in recidivistes:
            polices_client = [p for p in self.polices.values() if p["client_id"] == client_id]
            if not polices_client:
                continue
            police = rng.choice(polices_client)
            ancre = self._nouveau_sinistre(police, date(2022, 1, 1), fin_lot)
            if not ancre:
                continue
            self.sinistres[ancre["sinistre_id"]] = ancre
            proche = self._nouveau_sinistre(
                police, ancre["date_sinistre"], min(ancre["date_sinistre"] + timedelta(days=20), fin_lot)
            )
            if proche:
                self.sinistres[proche["sinistre_id"]] = proche

        for _ in range(v.orphelins):
            fantome = {"police_id": f"PO-9{rng.randint(0, 999999):06d}", "produit": "AUTO",
                       "date_debut": date(2024, 1, 1), "date_fin": date(2024, 12, 31)}
            sinistre = self._nouveau_sinistre(fantome, date(2024, 1, 1), fin_lot)
            self.sinistres[sinistre["sinistre_id"]] = sinistre

        extrait.clients = [dict(c) for c in self.clients.values()]
        extrait.polices = [dict(p) for p in self.polices.values()]
        extrait.sinistres = [dict(s) for s in self.sinistres.values()]
        rng.shuffle(extrait.sinistres)
        return extrait

    def lot_2(self, lot_1: Extract) -> Extract:
        v, rng = self.v, self.rng
        extrait = Extract()
        debut_lot, fin_lot = config.BATCH_EXTRACT_DATES[1] + timedelta(days=1), config.BATCH_EXTRACT_DATES[2]

        cibles = rng.sample(list(self.clients), v.maj_clients)
        for n, client_id in enumerate(cibles):
            ancien = dict(self.clients[client_id])
            nouveau = dict(ancien)
            if n < v.demenagements:
                province = _choix_pondere(rng, PROVINCE_POIDS)
                nouveau["province"] = _province_brute(rng, province)
                nouveau["ville"] = rng.choice(VILLES[province])
            else:
                nouveau["segment"] = "PME" if ancien["segment"] == "PARTICULIER" else "PARTICULIER"
            nouveau["date_maj"] = _date_aleatoire(rng, debut_lot, fin_lot)
            self.clients[client_id] = nouveau
            extrait.clients.append(dict(nouveau))
            if n < v.versions_tardives:
                perime = dict(ancien)
                perime["ville"] = "Ville-Périmée"
                perime["date_maj"] = ancien["date_maj"] - timedelta(days=30)
                extrait.clients.append(perime)

        base = len(self.clients)
        base_police = len(self.polices)
        for i in range(1, v.nouveaux_clients + 1):
            client = self._nouveau_client(base + i, debut_lot, fin_lot)
            self.clients[client["client_id"]] = client
            extrait.clients.append(dict(client))
            police = self._nouvelle_police(base_police + i, client["client_id"], debut_lot, fin_lot)
            police["statut"] = "ACTIVE"
            police["date_maj"] = police["date_debut"]
            self.polices[police["police_id"]] = police
            extrait.polices.append(dict(police))

        actives = [p for p in self.polices.values() if p["statut"] == "ACTIVE" and p["date_debut"] < debut_lot]
        for police in rng.sample(actives, v.annulations):
            annulee = dict(police)
            annulee["statut"] = "ANNULEE"
            annulee["date_fin"] = _date_aleatoire(
                rng, max(police["date_debut"], date(2025, 1, 1)), min(police["date_fin"], fin_lot)
            )
            annulee["date_maj"] = max(annulee["date_fin"], debut_lot)
            self.polices[police["police_id"]] = annulee
            extrait.polices.append(dict(annulee))

        ajoutes = 0
        while ajoutes < v.nouveaux_sinistres:
            police = self._choisir_police_pour_sinistre()
            sinistre = self._nouveau_sinistre(police, debut_lot, fin_lot)
            if sinistre and sinistre["date_sinistre"] <= police["date_fin"]:
                self.sinistres[sinistre["sinistre_id"]] = sinistre
                extrait.sinistres.append(dict(sinistre))
                ajoutes += 1

        ouverts = [s for s in lot_1.sinistres if s["statut"] == "OUVERT"]
        for sinistre in rng.sample(ouverts, min(v.reglements, len(ouverts))):
            regle = dict(sinistre)
            regle["statut"] = "FERME"
            regle["montant_paye"] = round(regle["montant_reclame"] * rng.uniform(0.4, 1.0), 2)
            regle["date_maj"] = _date_aleatoire(rng, debut_lot, fin_lot)
            self.sinistres[regle["sinistre_id"]] = regle
            extrait.sinistres.append(regle)

        extrait.sinistres.extend(dict(s) for s in rng.sample(lot_1.sinistres, v.doublons))
        rng.shuffle(extrait.sinistres)
        return extrait


def generer_enquetes(generateur: PolicyAdminGenerator, seed: int) -> list[dict]:
    """Conclusions de l'unité des enquêtes spéciales (fraude confirmée ou non fondée).

    Seuls les sinistres signalés et un échantillon des autres sont enquêtés (biais de sélection
    réaliste). La probabilité de fraude dépend de signaux observables, plus un bruit important.
    """
    rng = random.Random(seed + 1)
    par_client: dict[str, list[dict]] = {}
    for sinistre in generateur.sinistres.values():
        police = generateur.polices.get(sinistre["police_id"])
        if police:
            par_client.setdefault(police["client_id"], []).append(sinistre)
    enquetes, numero = [], 0
    for client_id in sorted(par_client):
        historique = sorted(par_client[client_id], key=lambda x: (x["date_sinistre"], x["sinistre_id"]))
        precedent = None
        for sinistre in historique:
            police = generateur.polices[sinistre["police_id"]]
            debut = (sinistre["date_sinistre"] - police["date_debut"]).days <= 30
            tardif = (sinistre["date_declaration"] - sinistre["date_sinistre"]).days > 90
            rapproche = precedent is not None and (sinistre["date_sinistre"] - precedent).days <= 30
            eleve = sinistre["montant_reclame"] > 3 * police["prime_annuelle"]
            vol = sinistre["type_sinistre"] in {"VOL", "INCENDIE"}
            precedent = sinistre["date_sinistre"]
            signale = debut or tardif or rapproche
            if not signale and rng.random() > 0.25:
                continue
            logit = -3.2 + 1.6 * debut + 1.3 * tardif + 1.1 * rapproche + 0.9 * eleve + 0.7 * vol + rng.gauss(0, 0.8)
            fraude = rng.random() < 1 / (1 + math.exp(-logit))
            numero += 1
            ouverture = sinistre["date_declaration"] + timedelta(days=rng.randint(3, 30))
            enquetes.append({
                "enquete_id": f"EQ-{numero:07d}",
                "sinistre_id": sinistre["sinistre_id"],
                "date_ouverture": ouverture,
                "date_conclusion": ouverture + timedelta(days=rng.randint(15, 120)),
                "conclusion": "FRAUDE_CONFIRMEE" if fraude else "NON_FONDEE",
                "montant_recupere": round(sinistre["montant_reclame"] * rng.uniform(0.3, 1.0), 2) if fraude else 0.0,
            })
    return enquetes


def _ecrire(lignes: list[dict], colonnes: list[str], chemin: Path) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("w", newline="", encoding="utf-8") as fichier:
        writer = csv.writer(fichier)
        writer.writerow(colonnes)
        for ligne in lignes:
            writer.writerow([_fmt(ligne[c]) for c in colonnes])


def generate(landing_dir: Path = config.LANDING_DIR, seed: int = 42) -> dict[str, int]:
    generateur = PolicyAdminGenerator(seed=seed)
    lot1 = generateur.lot_1()
    lot2 = generateur.lot_2(lot1)
    compte = {}
    for numero, extrait in ((1, lot1), (2, lot2)):
        for table, colonnes in (("clients", CLIENT_COLS), ("polices", POLICE_COLS), ("sinistres", SINISTRE_COLS)):
            lignes = getattr(extrait, table)
            _ecrire(lignes, colonnes, landing_dir / table / f"batch_{numero:03d}.csv")
            compte[f"{table}/batch_{numero:03d}"] = len(lignes)
    enquetes = generer_enquetes(generateur, seed)
    for numero, extrait_date in config.BATCH_EXTRACT_DATES.items():
        precedente = config.BATCH_EXTRACT_DATES.get(numero - 1, date.min)
        lot = [e for e in enquetes if precedente < e["date_conclusion"] <= extrait_date]
        _ecrire(lot, ENQUETE_COLS, landing_dir / "enquetes" / f"batch_{numero:03d}.csv")
        compte[f"enquetes/batch_{numero:03d}"] = len(lot)
    return compte
