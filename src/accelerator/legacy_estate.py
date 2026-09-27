"""Inventaire d'un parc hétérogène : SAS 9, Informatica PowerCenter, IBM DataStage et IBM Cognos.

Chaque artefact est ramené à un modèle commun (Asset) : entrées, sorties, composants, complexité,
pièges de migration et patron cible recommandé. Le lignage est calculé à travers les outils.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from graphlib import TopologicalSorter
from pathlib import Path

import sqlglot
import yaml
from sqlglot import exp

from accelerator import config
from accelerator.sas_analyzer import SasAnalyzer

SCHEMA_ALIASES = {"pa": "src", "policyadmin": "src", "src": "src", "dwh": "dwh"}
LEVELS = [(12, "Faible", 0.5), (25, "Moyenne", 1.5), (float("inf"), "Élevée", 3.0)]


@dataclass
class Finding:
    code: str
    severity: str
    where: str
    message: str
    recommendation: str


@dataclass
class Asset:
    tool: str
    name: str
    kind: str
    path: str
    description: str = ""
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    parameters: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    complexity_score: int = 0
    complexity_level: str = ""
    effort_days: float = 0.0
    target_pattern: str = ""
    depends_on: list[str] = field(default_factory=list)
    wave: int = 0

    def finalize(self, score: int) -> None:
        self.complexity_score = score
        for seuil, niveau, effort in LEVELS:
            if score < seuil:
                self.complexity_level, self.effort_days = niveau, effort
                break


@dataclass
class EstateInventory:
    assets: list[Asset]
    waves: list[list[str]]
    external_sources: list[str]
    tools: dict[str, int]


def normalize_table(nom: str) -> str:
    nom = nom.strip().strip('"').lower()
    nom = re.sub(r"#[^#]+#", "dwh", nom)
    if "." not in nom:
        return f"dwh.{nom}"
    schema, table = nom.rsplit(".", 1)
    return f"{SCHEMA_ALIASES.get(schema, schema)}.{table}"


def tables_in_sql(sql: str) -> list[str]:
    sql = re.sub(r"#[^#]+#", "DWH", sql)
    try:
        arbre = sqlglot.parse_one(sql, read="oracle")
    except sqlglot.errors.ParseError:
        return []
    return [normalize_table(f"{t.db}.{t.name}" if t.db else t.name) for t in arbre.find_all(exp.Table)]


# ----------------------------------------------------------------------------- Informatica PowerCenter

INFA_WEIGHTS = {
    "Source Qualifier": 1, "Expression": 2, "Filter": 1, "Lookup Procedure": 3, "Aggregator": 3,
    "Router": 3, "Joiner": 3, "Update Strategy": 3, "Sequence": 2, "Normalizer": 4, "Rank": 3,
    "Stored Procedure": 5, "Java": 5, "Mapplet": 4,
}
INFA_FUNCTIONS = {
    "DECODE": ("CASE WHEN ... THEN ... ELSE", "DECODE compare aussi les NULL entre eux; CASE WHEN x = NULL ne le fait pas"),
    "IIF": ("CASE WHEN ... THEN ... ELSE ... END", "IIF imbriqués : réécrire en un seul CASE lisible"),
    "ISNULL": ("x IS NULL", ""),
    "NVL": ("COALESCE", ""),
    "TO_CHAR": ("strftime / date_format / to_char selon la cible", "Les masques de format diffèrent (YYYYMM vs %Y%m vs yyyyMM)"),
    "TO_DATE": ("strptime / to_date selon la cible", "Masques de format différents"),
    "LTRIM": ("ltrim", ""),
    "SYSDATE": ("current_timestamp", "Fuseau horaire du serveur Informatica vs UTC de la plateforme"),
}


def parse_informatica(path: Path) -> list[Asset]:
    racine = ET.parse(path).getroot()
    actifs = []
    dossier = racine.find(".//FOLDER")
    sources = {s.get("NAME"): s for s in dossier.findall("SOURCE")}
    cibles = {t.get("NAME"): t for t in dossier.findall("TARGET")}
    sessions = {s.get("MAPPINGNAME"): s for s in dossier.findall("SESSION")}
    for mapping in dossier.findall("MAPPING"):
        nom = mapping.get("NAME")
        actif = Asset("Informatica PowerCenter", nom, "mapping", path.as_posix(), mapping.get("DESCRIPTION", ""))
        score = 2
        for instance in mapping.findall("INSTANCE"):
            if instance.get("TYPE") == "SOURCE":
                source = sources.get(instance.get("TRANSFORMATION_NAME"))
                proprietaire = source.get("OWNERNAME") if source is not None else ""
                actif.inputs.append(normalize_table(f"{proprietaire}.{instance.get('TRANSFORMATION_NAME')}"))
            elif instance.get("TYPE") == "TARGET":
                cible = cibles.get(instance.get("TRANSFORMATION_NAME"))
                proprietaire = cible.get("OWNERNAME") if cible is not None else ""
                actif.outputs.append(normalize_table(f"{proprietaire}.{instance.get('TRANSFORMATION_NAME')}"))

        for trf in mapping.findall("TRANSFORMATION"):
            type_trf, nom_trf = trf.get("TYPE"), trf.get("NAME")
            actif.components.append(f"{type_trf} : {nom_trf}")
            score += INFA_WEIGHTS.get(type_trf, 2)
            attributs = {a.get("NAME"): a.get("VALUE") for a in trf.findall("TABLEATTRIBUTE")}
            if type_trf == "Source Qualifier":
                if attributs.get("Sql Query"):
                    score += 3
                    actif.findings.append(Finding(
                        "INFA-SQ-01", "élevée", nom_trf,
                        "Requête SQL de substitution (SQL override) : la logique réelle est cachée dans le SQ.",
                        "Extraire la requête et la convertir comme un modèle à part entière."))
                if attributs.get("Source Filter"):
                    actif.findings.append(Finding(
                        "INFA-SQ-02", "faible", nom_trf, f"Filtre source : {attributs['Source Filter']}.",
                        "Reporter le filtre dans le WHERE du modèle dbt."))
            if type_trf == "Lookup Procedure":
                table = attributs.get("Lookup table name")
                if table:
                    actif.inputs.append(normalize_table(table))
                politique = attributs.get("Lookup policy on multiple match", "")
                if politique in {"Use Any Value", "Use First Value", "Use Last Value"}:
                    actif.findings.append(Finding(
                        "INFA-LKP-01", "élevée", nom_trf,
                        f"Politique de correspondance multiple « {politique} » : résultat non déterministe si la "
                        "clé n'est pas unique.",
                        "Tester l'unicité de la clé de recherche; sinon QUALIFY row_number() avec un tri explicite."))
                actif.findings.append(Finding(
                    "INFA-LKP-02", "moyenne", nom_trf,
                    "Lookup connecté : une absence de correspondance renvoie NULL (jointure gauche implicite).",
                    "LEFT JOIN explicite et test de complétude sur la colonne ramenée."))
            if type_trf == "Router":
                groupes = [g for g in trf.findall("GROUP")]
                actif.findings.append(Finding(
                    "INFA-RTR-01", "élevée", nom_trf,
                    f"Router à {len(groupes)} groupes : une ligne qui satisfait un groupe n'est PAS envoyée au "
                    "groupe par défaut.",
                    "Un modèle par groupe; le groupe par défaut = NOT (union des conditions des autres groupes)."))
            if type_trf == "Update Strategy":
                actif.findings.append(Finding(
                    "INFA-UPD-01", "moyenne", nom_trf,
                    f"Stratégie de mise à jour : {attributs.get('Update Strategy Expression', '?')}.",
                    "Modèle incrémental dbt (merge / delete+insert) sur la clé primaire de la cible."))
            if type_trf == "Aggregator":
                actif.findings.append(Finding(
                    "INFA-AGG-01", "élevée", nom_trf,
                    "Un port non agrégé et hors GROUP BY renvoie la valeur de la dernière ligne lue.",
                    "Remplacer par any_value() documenté ou par une agrégation explicite."))
            for champ in trf.findall("TRANSFORMFIELD"):
                expression = champ.get("EXPRESSION") or ""
                for fonction, (equivalent, piege) in INFA_FUNCTIONS.items():
                    if re.search(rf"\b{fonction}\s*\(", expression, re.I):
                        score += 1
                        actif.findings.append(Finding(
                            f"INFA-FN-{fonction}", "moyenne" if piege else "faible",
                            f"{nom_trf}.{champ.get('NAME')}",
                            f"Fonction {fonction} : {expression}" + (f" — {piege}." if piege else "."),
                            f"Équivalent : {equivalent}."))
                if "/" in expression:
                    actif.findings.append(Finding(
                        "INFA-NUM-01", "moyenne", f"{nom_trf}.{champ.get('NAME')}",
                        f"Division dans {champ.get('NAME')} écrite dans une colonne de précision "
                        f"{champ.get('PRECISION')},{champ.get('SCALE')} : la base cible arrondit à l'écriture.",
                        f"Reproduire l'arrondi explicitement : round(..., {champ.get('SCALE')}); garder nullif(x, 0)."))

        session = sessions.get(nom)
        if session is not None:
            for attr in session.iter("ATTRIBUTE"):
                if attr.get("NAME") == "Update else Insert" and attr.get("VALUE") == "YES":
                    actif.findings.append(Finding(
                        "INFA-SES-01", "moyenne", session.get("NAME"),
                        "Session en « Update else Insert » : upsert réalisé par le moteur, invisible dans le mapping.",
                        "MERGE / incrémental dbt avec unique_key; documenter la clé."))
        workflows = [w.get("NAME") for w in dossier.findall("WORKFLOW")
                     if any(t.get("TASKNAME") == f"s_{nom}" for t in w.findall("TASKINSTANCE"))]
        if workflows:
            actif.components.append(f"Workflow : {', '.join(workflows)}")
        actif.inputs = list(dict.fromkeys(actif.inputs))
        actif.target_pattern = (
            "dbt : un modèle par groupe du Router (incrémental, unique_key), expressions en CASE/COALESCE, "
            "lookups en LEFT JOIN; orchestration par Databricks Workflows / ADF à la place du workflow"
        )
        actif.finalize(score)
        actifs.append(actif)
    return actifs


# ----------------------------------------------------------------------------- IBM DataStage (.dsx)

DS_WEIGHTS = {
    "OracleConnectorPX": 1, "DB2ConnectorPX": 1, "PxSequentialFile": 1, "PxLookup": 3, "PxJoin": 3,
    "PxAggregator": 3, "CTransformerStage": 3, "PxFunnel": 2, "PxRemDup": 2, "PxSort": 1, "PxChangeCapture": 4,
}
DS_FUNCTIONS = {
    "DateToString": ("strftime / date_format", "Masque %yyyy%mm propre à DataStage"),
    "StringToDate": ("strptime / to_date", "Masque propre à DataStage"),
    "NullToZero": ("coalesce(x, 0)", ""),
    "IsNull": ("x is null", ""),
    "Trim": ("trim", "Trim DataStage réduit aussi les espaces internes multiples"),
    "If ": ("CASE WHEN", ""),
}


def _parse_dsx_blocks(texte: str) -> list[dict]:
    pile: list[dict] = [{"_type": "ROOT", "_children": []}]
    for brute in texte.splitlines():
        ligne = brute.strip()
        if not ligne:
            continue
        if ligne.startswith("BEGIN "):
            bloc = {"_type": ligne[6:].strip(), "_children": []}
            pile[-1]["_children"].append(bloc)
            pile.append(bloc)
        elif ligne.startswith("END "):
            pile.pop()
        else:
            cle, _, valeur = ligne.partition(" ")
            valeur = valeur.strip()
            if valeur.startswith('"') and valeur.endswith('"'):
                valeur = valeur[1:-1].replace('\\"', '"')
            pile[-1][cle] = valeur
    return pile[0]["_children"]


def parse_datastage(path: Path) -> list[Asset]:
    actifs = []
    for job in (b for b in _parse_dsx_blocks(path.read_text(encoding="utf-8")) if b["_type"] == "DSJOB"):
        enregistrements = [r for r in job["_children"] if r["_type"] == "DSRECORD"]
        racine = next(r for r in enregistrements if r.get("OLEType") == "CJobDefn")
        actif = Asset("IBM DataStage", job["Identifier"], "job parallèle", path.as_posix(), racine.get("Description", ""))
        actif.parameters = [s["Name"] for s in racine["_children"] if s["_type"] == "DSSUBRECORD"]
        score = 2
        for rec in enregistrements:
            if rec.get("OLEType") not in {"CCustomStage", "CTransformerStage"}:
                continue
            type_etape, nom = rec.get("StageType", rec.get("OLEType")), rec.get("Name")
            actif.components.append(f"{type_etape} : {nom}")
            score += DS_WEIGHTS.get(type_etape, 2)
            props = {s.get("Name"): s for s in rec["_children"] if s["_type"] == "DSSUBRECORD"}
            if "SelectStatement" in props:
                actif.inputs.extend(tables_in_sql(props["SelectStatement"]["Value"]))
            if "TableName" in props and rec.get("InputPins"):
                actif.outputs.append(normalize_table(props["TableName"]["Value"]))
                mode = props.get("WriteMode", {}).get("Value", "")
                if mode.lower() in {"upsert", "update then insert", "insert then update"}:
                    actif.findings.append(Finding(
                        "DS-TGT-01", "moyenne", nom, f"Écriture en mode {mode} sur {props['UpsertKeys']['Value']}"
                        if "UpsertKeys" in props else f"Écriture en mode {mode}.",
                        "Modèle incrémental dbt avec unique_key composite."))
            if type_etape == "PxLookup":
                echec = props.get("LookupFailure", {}).get("Value", "Fail")
                correspondance = {"Continue": "LEFT JOIN (colonnes nulles)", "Drop": "INNER JOIN",
                                  "Reject": "INNER JOIN + table de rejets", "Fail": "INNER JOIN + test bloquant"}
                actif.findings.append(Finding(
                    "DS-LKP-01", "élevée", nom,
                    f"Échec de recherche = « {echec} » : décide si les lignes sans correspondance sont gardées.",
                    f"Équivalent : {correspondance.get(echec, 'à analyser')}."))
            partition = props.get("Partitioning", props.get("Method", {})).get("Value") if (
                "Partitioning" in props or "Method" in props) else None
            if partition:
                actif.findings.append(Finding(
                    "DS-PAR-01", "faible", nom, f"Partitionnement explicite « {partition} ».",
                    "À supprimer : Spark/Snowflake répartissent seuls; surveiller l'asymétrie (skew) à la place."))
            for sous in rec["_children"]:
                derivation = sous.get("Derivation", "")
                if not derivation:
                    continue
                if sous.get("Kind") == "StageVariable":
                    score += 2
                    utilisee = any(sous["Name"].replace("StageVar_", "sv_") in s.get("Derivation", "")
                                   for s in rec["_children"] if s is not sous)
                    actif.findings.append(Finding(
                        "DS-SV-01", "élevée" if utilisee else "faible", f"{nom}.{sous['Name']}",
                        "Variable d'étape dépendante de la ligne précédente : calcul sensible à l'ordre et au "
                        "partitionnement." + ("" if utilisee else " Elle n'alimente aucune colonne (code mort)."),
                        "Fonction de fenêtre (lag) avec tri explicite, ou suppression si code mort."))
                for fonction, (equivalent, piege) in DS_FUNCTIONS.items():
                    if fonction in derivation:
                        score += 1
                        actif.findings.append(Finding(
                            f"DS-FN-{fonction.strip()}", "moyenne" if piege else "faible", f"{nom}.{sous['Name']}",
                            f"{derivation}" + (f" — {piege}." if piege else "."), f"Équivalent : {equivalent}."))
        if actif.parameters:
            actif.findings.append(Finding(
                "DS-PRM-01", "faible", "paramètres", f"Paramètres de job : {', '.join(actif.parameters)}.",
                "Variables dbt (var()) ou paramètres de job Databricks."))
        actif.inputs = list(dict.fromkeys(actif.inputs))
        actif.target_pattern = (
            "dbt : SELECT source + LEFT JOIN (lookup Continue) + GROUP BY; modèle incrémental sur la clé "
            "d'upsert; paramètres en var(); partitionnement laissé au moteur"
        )
        actif.finalize(score)
        actifs.append(actif)
    return actifs


# ----------------------------------------------------------------------------- IBM Cognos (report spec)

def parse_cognos(path: Path, mapping_path: Path) -> list[Asset]:
    correspondance = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))["query_subjects"]
    racine = ET.parse(path).getroot()
    ns = {"c": racine.tag.split("}")[0].strip("{")}
    actif = Asset("IBM Cognos Analytics", path.stem, "rapport", path.as_posix())
    score = 2
    for requete in racine.findall(".//c:queries/c:query", ns):
        actif.components.append(f"Requête : {requete.get('name')}")
        score += 2
        for item in requete.findall(".//c:dataItem", ns):
            expression = item.findtext("c:expression", default="", namespaces=ns)
            for sujet in re.findall(r"\]\.\[([^\]]+)\]\.\[", expression):
                if sujet in correspondance:
                    actif.inputs.append(correspondance[sujet])
            agregat = item.get("aggregate", "")
            if agregat == "calculated":
                score += 2
                actif.findings.append(Finding(
                    "COG-AGG-01", "élevée", f"{requete.get('name')}.{item.get('name')}",
                    f"Élément calculé « {expression} » avec agrégat « calculated » : Cognos calcule le ratio APRÈS "
                    "agrégation (ratio des sommes), pas la somme des ratios.",
                    "Mesure du modèle sémantique : DIVIDE(SUM(num), SUM(dén)) en Power BI, ratio metric dans la "
                    "couche sémantique dbt ou metric view Databricks."))
            elif agregat == "average":
                actif.findings.append(Finding(
                    "COG-AGG-02", "moyenne", f"{requete.get('name')}.{item.get('name')}",
                    "Moyenne d'une moyenne pré-calculée : biaisée si les groupes n'ont pas la même taille.",
                    "Exposer somme et nombre, calculer la moyenne pondérée dans la mesure."))
            if re.search(r"\brank\s*\(", expression, re.I):
                score += 1
                actif.findings.append(Finding(
                    "COG-FN-01", "moyenne", f"{requete.get('name')}.{item.get('name')}",
                    f"Fonction de rang Cognos : {expression}.",
                    "rank() over (partition by ... order by ... desc); préciser le traitement des ex æquo."))
        for filtre in requete.findall(".//c:filterExpression", ns):
            invites = re.findall(r"\?([^?]+)\?", filtre.text or "")
            actif.parameters.extend(invites)
            if invites:
                actif.findings.append(Finding(
                    "COG-PRM-01", "faible", requete.get("name"), f"Invites : {', '.join(invites)}.",
                    "Paramètres ou segments (slicers) du rapport cible."))
    visuels = [e for e in racine.iter() if e.tag.split("}")[1] in {"crosstab", "list", "combinationChart", "chart"}]
    for visuel in visuels:
        actif.components.append(f"{visuel.tag.split('}')[1]} : {visuel.get('name')}")
        score += 1
    actif.inputs = list(dict.fromkeys(actif.inputs))
    actif.parameters = list(dict.fromkeys(actif.parameters))
    actif.target_pattern = (
        "Modèle sémantique (Power BI / dbt Semantic Layer / Databricks metric views) sur les marts gold; "
        "visuels reconstruits; mesures ratio = somme / somme"
    )
    actif.finalize(score)
    return [actif]


# ----------------------------------------------------------------------------- SAS + assemblage

def sas_assets(sas_dir: Path) -> list[Asset]:
    inventaire = SasAnalyzer().analyze_directory(sas_dir)
    actifs = []
    for programme in inventaire.programs:
        if not programme.steps:
            continue
        actif = Asset("SAS 9.4", programme.name, "programme", programme.path)
        actif.inputs, actif.outputs = list(programme.inputs), list(programme.outputs)
        actif.components = [f"{s.kind} {s.name if s.kind == 'PROC' else ''}".strip() for s in programme.steps]
        actif.findings = [Finding(p.code, p.severity, f"ligne {p.line}", p.message, p.recommendation)
                          for p in programme.pitfalls]
        actif.findings += [Finding("SAS-VIYA", "info", "SAS Viya", n, "") for n in programme.viya_notes]
        actif.target_pattern = (
            f"dbt (Databricks/Snowflake). SAS Viya : {programme.viya_readiness}"
        )
        actif.complexity_score, actif.complexity_level = programme.complexity_score, programme.complexity_level
        actif.effort_days = programme.effort_days
        actifs.append(actif)
    return actifs


def build_inventory(legacy_dir: Path = config.LEGACY_DIR) -> EstateInventory:
    actifs = sas_assets(legacy_dir / "sas")
    for fichier in sorted((legacy_dir / "informatica").glob("*.xml")):
        actifs += parse_informatica(fichier)
    for fichier in sorted((legacy_dir / "datastage").glob("*.dsx")):
        actifs += parse_datastage(fichier)
    correspondance = legacy_dir / "cognos" / "framework_manager_mapping.yml"
    for fichier in sorted((legacy_dir / "cognos").glob("*.xml")):
        actifs += parse_cognos(fichier, correspondance)

    producteurs = {sortie: a.name for a in actifs for sortie in a.outputs}
    graphe = {}
    for actif in actifs:
        actif.depends_on = sorted({producteurs[e] for e in actif.inputs if e in producteurs} - {actif.name})
        graphe[actif.name] = set(actif.depends_on)
    tri = TopologicalSorter(graphe)
    tri.prepare()
    vagues, par_nom = [], {a.name: a for a in actifs}
    while tri.is_active():
        pret = sorted(tri.get_ready())
        vagues.append(pret)
        for nom in pret:
            par_nom[nom].wave = len(vagues)
        tri.done(*pret)
    externes = sorted({e for a in actifs for e in a.inputs if e not in producteurs})
    outils: dict[str, int] = {}
    for actif in actifs:
        outils[actif.tool] = outils.get(actif.tool, 0) + 1
    return EstateInventory(actifs, vagues, externes, outils)


TOOL_CLASSES = {
    "SAS 9.4": "sas", "Informatica PowerCenter": "infa", "IBM DataStage": "ds", "IBM Cognos Analytics": "cog",
}


def _id(nom: str) -> str:
    return re.sub(r"\W", "_", nom)


def lineage_mermaid(inventaire: EstateInventory) -> str:
    lignes = ["flowchart LR"]
    for actif in inventaire.assets:
        aid = "a_" + _id(actif.name)
        lignes.append(f'    {aid}["{actif.name}<br/><i>{actif.tool}</i>"]:::{TOOL_CLASSES[actif.tool]}')
        for entree in actif.inputs:
            lignes.append(f'    t_{_id(entree)}[("{entree}")] --> {aid}')
        for sortie in actif.outputs:
            lignes.append(f'    {aid} --> t_{_id(sortie)}[("{sortie}")]')
    lignes += [
        "    classDef sas fill:#1f6feb,color:#fff",
        "    classDef infa fill:#e8590c,color:#fff",
        "    classDef ds fill:#2f9e44,color:#fff",
        "    classDef cog fill:#7048e8,color:#fff",
    ]
    return "\n".join(lignes)


def to_markdown(inventaire: EstateInventory) -> str:
    effort = sum(a.effort_days for a in inventaire.assets)
    lignes = [
        "# Inventaire du parc legacy (multi-outils)", "",
        "| Outil | Artefacts |", "|---|---|",
        *[f"| {outil} | {n} |" for outil, n in inventaire.tools.items()],
        "", f"Effort de conversion indicatif : **{effort:.1f} jours-personne**. "
        f"Sources externes : {', '.join(f'`{s}`' for s in inventaire.external_sources)}.",
        "", "## Vagues de migration", "",
        "Une vague ne dépend que des vagues précédentes (tri topologique à travers les outils).", "",
    ]
    for i, vague in enumerate(inventaire.waves, 1):
        lignes.append(f"{i}. {', '.join(f'`{n}`' for n in vague)}")
    lignes += ["", "## Artefacts", "",
               "| Vague | Outil | Artefact | Type | Score | Complexité | Entrées | Sorties | Patron cible |",
               "|---|---|---|---|---|---|---|---|---|"]
    for a in sorted(inventaire.assets, key=lambda x: (x.wave, x.tool, x.name)):
        lignes.append(
            f"| {a.wave} | {a.tool} | `{a.name}` | {a.kind} | {a.complexity_score} | {a.complexity_level} | "
            f"{', '.join(a.inputs) or '-'} | {', '.join(a.outputs) or '-'} | {a.target_pattern} |"
        )
    lignes += ["", "## Constats par artefact (hors SAS, détaillé dans sas_inventory.md)", ""]
    for a in inventaire.assets:
        if a.tool.startswith("SAS"):
            continue
        lignes += [f"### {a.tool} — `{a.name}`", "", a.description, "",
                   f"Composants : {'; '.join(a.components)}", ""]
        lignes += ["| Code | Sévérité | Où | Constat | Recommandation |", "|---|---|---|---|---|"]
        lignes += [f"| {f.code} | {f.severity} | {f.where} | {f.message} | {f.recommendation} |" for f in a.findings]
        lignes.append("")
    sas = [a for a in inventaire.assets if a.tool.startswith("SAS")]
    lignes += ["## Évaluation SAS Viya", "",
               "| Programme | Serveur Compute (lift-and-shift) et CAS |", "|---|---|"]
    for a in sas:
        notes = [f.message for f in a.findings if f.code == "SAS-VIYA"]
        lignes.append(f"| `{a.name}` | {a.target_pattern.split('SAS Viya : ')[1]}<br/>{'<br/>'.join(notes)} |")
    lignes += ["", "## Lignage inter-outils", "", "```mermaid", lineage_mermaid(inventaire), "```", ""]
    return "\n".join(lignes)


def write_reports(inventaire: EstateInventory, reports_dir: Path = config.REPORTS_DIR) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "estate_inventory.json").write_text(
        json.dumps(asdict(inventaire), indent=2, ensure_ascii=False), encoding="utf-8")
    chemin = reports_dir / "estate_inventory.md"
    chemin.write_text(to_markdown(inventaire), encoding="utf-8")
    return chemin
