"""Analyse statique d'un parc de programmes SAS : inventaire, lignage, complexité et pièges de migration."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from graphlib import TopologicalSorter
from pathlib import Path

CONSTRUCT_WEIGHTS = {
    "DATA_STEP": 2,
    "PROC_SQL": 2,
    "PROC_SORT": 1,
    "PROC_SUMMARY": 3,
    "PROC_OTHER": 2,
    "BY_FIRST_LAST": 2,
    "RETAIN": 3,
    "SUM_STATEMENT": 2,
    "LAG": 3,
    "MERGE_IN": 3,
    "MACRO_DEF": 3,
    "MACRO_LOOP": 4,
    "DYNAMIC_DATASET": 2,
    "SQL_ROW_MINMAX": 2,
    "SAS_DATE_FUNC": 1,
    "SAS_STRING_FUNC": 1,
}

LEVELS = [(12, "Faible", 0.5), (25, "Moyenne", 1.5), (float("inf"), "Élevée", 3.0)]

PITFALL_CATALOG = {
    "SAS-MISS-01": (
        "élevée",
        "Comparaison « < » ou « <= » dans un IF : en SAS, une valeur manquante est inférieure à tout "
        "nombre, alors qu'en SQL NULL < n est inconnu (faux).",
        "Rendre explicite le traitement des NULL (ex. `x is null or x < n`) puis valider la règle "
        "avec le métier.",
    ),
    "SAS-BY-01": (
        "moyenne",
        "Traitement BY avec FIRST./LAST. : dépend de l'ordre physique produit par PROC SORT.",
        "ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...) avec QUALIFY, ordre de tri total et "
        "déterministe.",
    ),
    "SAS-RET-01": (
        "moyenne",
        "RETAIN / instruction somme : accumulation ligne à ligne propre au DATA step.",
        "SUM() / COUNT() OVER (PARTITION BY ... ORDER BY ... ROWS UNBOUNDED PRECEDING).",
    ),
    "SAS-LAG-01": (
        "élevée",
        "LAG() est une file d'attente et non une fonction de fenêtre ; exécuté sous condition, il "
        "retourne des valeurs inattendues.",
        "LAG() OVER (PARTITION BY ... ORDER BY ...) ; vérifier que l'appel SAS est inconditionnel.",
    ),
    "SAS-MRG-01": (
        "moyenne",
        "MERGE avec IN= : jointure positionnelle, comportement particulier en plusieurs-à-plusieurs.",
        "JOIN explicite (LEFT/INNER selon IN=) et test d'unicité des clés de chaque côté.",
    ),
    "SAS-SQL-01": (
        "élevée",
        "MIN()/MAX() à plusieurs arguments dans PROC SQL : fonctions ligne, pas des agrégats.",
        "LEAST() / GREATEST().",
    ),
    "SAS-DATE-01": (
        "moyenne",
        "INTCK('YEAR', ..., 'C') calcule des années révolues ; DATE_DIFF('year') compte les "
        "changements d'année.",
        "Utiliser AGE() / date_part('year', age(...)) et tester les anniversaires.",
    ),
    "SAS-MAC-01": (
        "moyenne",
        "Boucle macro générant du code ou des tables à nom dynamique.",
        "Boucle Jinja dans dbt, ou mieux, une table de paramètres jointe (range/generate_series).",
    ),
    "SAS-STR-01": (
        "faible",
        "Fonctions de chaîne SAS sans équivalent direct (PROPCASE, CATX, STRIP).",
        "Macro dbt dédiée et tests sur les caractères accentués et les traits d'union.",
    ),
}


@dataclass
class Pitfall:
    code: str
    severity: str
    line: int
    message: str
    recommendation: str


@dataclass
class Step:
    kind: str
    name: str
    line: int
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    constructs: list[str] = field(default_factory=list)
    in_macro: str | None = None


@dataclass
class Program:
    name: str
    path: str
    lines_of_code: int
    includes: list[str] = field(default_factory=list)
    macro_vars_defined: list[str] = field(default_factory=list)
    macros_defined: list[str] = field(default_factory=list)
    librefs: list[str] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    constructs: dict[str, int] = field(default_factory=dict)
    pitfalls: list[Pitfall] = field(default_factory=list)
    complexity_score: int = 0
    complexity_level: str = ""
    effort_days: float = 0.0
    depends_on: list[str] = field(default_factory=list)
    viya_readiness: str = ""
    viya_notes: list[str] = field(default_factory=list)


@dataclass
class Inventory:
    programs: list[Program]
    migration_order: list[str]
    external_sources: list[str]
    final_outputs: list[str]


def _strip_comments(code: str) -> str:
    return re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), code, flags=re.S)


def _split_statements(code: str) -> list[tuple[str, int]]:
    statements: list[tuple[str, int]] = []
    buffer: list[str] = []
    line, start_line, quote = 1, 1, None
    for char in code:
        if not buffer and char.isspace():
            if char == "\n":
                line += 1
            continue
        if not buffer:
            start_line = line
        if quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == ";":
            text = " ".join("".join(buffer).split())
            if text and not text.startswith("*"):
                statements.append((text, start_line))
            buffer = []
            continue
        if char == "\n":
            line += 1
        buffer.append(char)
    return statements


def _dataset_name(token: str) -> str | None:
    token = token.split("(")[0].strip().lower()
    if not token or token.startswith(("%", "_")) or token in {"_null_", "_data_", "_last_"}:
        return None
    if not re.fullmatch(r"[a-z_&][\w&]*(\.[a-z_&][\w&]*)?", token):
        return None
    return token if "." in token else f"work.{token}"


def _strip_options(text: str) -> str:
    result, depth = [], 0
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(depth - 1, 0)
        elif depth == 0:
            result.append(char)
    return "".join(result)


def assess_viya(program: Program, code: str) -> tuple[str, list[str]]:
    """Compatibilité d'un programme SAS 9 avec SAS Viya : serveur Compute (lift-and-shift) et moteur CAS."""
    if not program.steps:
        return "", []
    notes: list[str] = []
    c = program.constructs
    if c.get("BY_FIRST_LAST") or c.get("RETAIN") or c.get("LAG") or c.get("SUM_STATEMENT"):
        notes.append("CAS : DATA step multithread; BY/FIRST., RETAIN et LAG ne voient que les lignes du même "
                     "fil. Exécuter avec single=yes ou garantir que chaque groupe BY est traité par un seul fil.")
    if c.get("PROC_SORT"):
        notes.append("CAS : PROC SORT est inutile (tables CAS non ordonnées); le BY du DATA step regroupe à la volée.")
    if c.get("PROC_SQL"):
        notes.append("CAS : PROC SQL s'exécute sur le serveur Compute, pas dans CAS; passer à PROC FEDSQL pour CAS.")
    if c.get("PROC_SUMMARY"):
        notes.append("CAS : remplacer PROC SUMMARY par PROC MDSUMMARY ou l'action simple.summary.")
    if c.get("MERGE_IN"):
        notes.append("CAS : MERGE exige un BY et ne garantit pas l'ordre des lignes en sortie.")
    if re.search(r"^\s*libname\s+\w+\s+[\"']/", code, re.I | re.M) or re.search(r"%include\s+[\"']/", code, re.I):
        notes.append("Chemins de fichiers absolus (libname, %include) à remplacer par des caslibs ou des chemins "
                     "du serveur Compute.")
    cas = "ajustements requis" if len(notes) > 1 or (notes and not notes[-1].startswith("Chemins")) else "compatible"
    return f"Compute : compatible (lift-and-shift); CAS : {cas}", notes


class SasAnalyzer:
    def __init__(self, known_librefs: set[str] | None = None):
        self.known_librefs = {"work"} | (known_librefs or set())

    def _two_level_refs(self, text: str) -> list[str]:
        refs = []
        for lib, member in re.findall(r"\b([a-z_]\w*)\.([a-z_&][\w&]*)", text.lower()):
            if lib in self.known_librefs:
                refs.append(f"{lib}.{member}")
        return refs

    def _analyze_data_step(self, step: Step, statements: list[str]) -> None:
        header = _strip_options(statements[0][4:])
        step.outputs = [d for d in (_dataset_name(t) for t in header.split()) if d]
        for stmt in statements[1:]:
            low = stmt.lower()
            keyword = low.split()[0]
            if keyword in {"set", "merge", "update", "modify"}:
                sans_macro = re.sub(r"%do\s+\w+\s*=.*?%to\s+\S+", " ", _strip_options(stmt), flags=re.I)
                for token in sans_macro.split()[1:]:
                    name = _dataset_name(token)
                    if name:
                        step.inputs.append(name)
            else:
                step.inputs.extend(self._two_level_refs(_strip_options(stmt)))
        step.inputs = [i for i in dict.fromkeys(step.inputs) if i not in step.outputs]

    def _analyze_proc(self, step: Step, statements: list[str]) -> None:
        body = " ".join(statements)
        low = body.lower()
        if step.name == "sql":
            step.outputs = [_dataset_name(m) for m in re.findall(r"create\s+table\s+([\w.&]+)", low)]
            sources = re.findall(r"\b(?:from|join)\s+([\w.&]+)", low)
            step.inputs = [d for d in (_dataset_name(s) for s in sources) if d]
        else:
            step.inputs = [_dataset_name(m) for m in re.findall(r"\bdata\s*=\s*([\w.&]+)", low)]
            step.outputs = [_dataset_name(m) for m in re.findall(r"\bout\s*=\s*([\w.&]+)", low)]
            if not step.outputs and step.name == "sort":
                step.outputs = list(step.inputs)
        step.inputs = [d for d in dict.fromkeys(step.inputs) if d and d not in step.outputs]
        step.outputs = [d for d in dict.fromkeys(step.outputs) if d]

    def _detect(self, step: Step, statements: list[tuple[str, int]], program: Program) -> None:
        found = set()
        if step.kind == "DATA":
            found.add("DATA_STEP")
        elif step.name == "sql":
            found.add("PROC_SQL")
        elif step.name == "sort":
            found.add("PROC_SORT")
        elif step.name in {"summary", "means"}:
            found.add("PROC_SUMMARY")
        else:
            found.add("PROC_OTHER")

        def pitfall(code: str, line: int) -> None:
            severity, message, reco = PITFALL_CATALOG[code]
            if not any(p.code == code and p.line == line for p in program.pitfalls):
                program.pitfalls.append(Pitfall(code, severity, line, message, reco))

        for stmt, line in statements:
            low = stmt.lower()
            if re.search(r"\b(first|last)\.\w+", low):
                found.add("BY_FIRST_LAST")
                pitfall("SAS-BY-01", line)
            if re.match(r"retain\b", low):
                found.add("RETAIN")
                pitfall("SAS-RET-01", line)
            if re.fullmatch(r"[a-z_]\w*\s*\+\s*[\w.]+", low):
                found.add("SUM_STATEMENT")
                pitfall("SAS-RET-01", line)
            if re.search(r"\blag\d*\s*\(", low):
                found.add("LAG")
                pitfall("SAS-LAG-01", line)
            if re.match(r"merge\b", low) and "in=" in low.replace(" ", ""):
                found.add("MERGE_IN")
                pitfall("SAS-MRG-01", line)
            if step.kind == "DATA" and re.match(r"if\s+[a-z_]\w*\s*(<|<=|lt|le)\s*-?\d", low):
                pitfall("SAS-MISS-01", line)
            if step.name == "sql" and re.search(r"\b(min|max)\s*\([^()]*(\([^()]*\)[^()]*)*,", low):
                found.add("SQL_ROW_MINMAX")
                pitfall("SAS-SQL-01", line)
            if re.search(r"\bintck\s*\(\s*'year'", low):
                found.add("SAS_DATE_FUNC")
                pitfall("SAS-DATE-01", line)
            if re.search(r"\b(mdy|intnx|intck|today|datepart)\s*\(", low):
                found.add("SAS_DATE_FUNC")
            if re.search(r"\b(propcase|catx|compress|scan|tranwrd)\s*\(", low):
                found.add("SAS_STRING_FUNC")
                pitfall("SAS-STR-01", line)
            if "%do" in low:
                found.add("MACRO_LOOP")
                pitfall("SAS-MAC-01", line)
        if any("&" in d for d in step.inputs + step.outputs):
            found.add("DYNAMIC_DATASET")
        if step.in_macro:
            found.add("MACRO_DEF")
        step.constructs = sorted(found)

    def analyze_file(self, path: Path) -> Program:
        raw = path.read_text(encoding="utf-8")
        code = _strip_comments(raw)
        program = Program(
            name=path.stem,
            path=path.as_posix(),
            lines_of_code=sum(1 for ligne in code.splitlines() if ligne.strip()),
        )
        statements = _split_statements(code)
        macro_stack: list[str] = []
        current: list[tuple[str, int]] = []
        current_step: Step | None = None

        def close_step() -> None:
            nonlocal current, current_step
            if current_step is None:
                return
            texts = [s for s, _ in current]
            if current_step.kind == "DATA":
                self._analyze_data_step(current_step, texts)
            else:
                self._analyze_proc(current_step, texts)
            self._detect(current_step, current, program)
            program.steps.append(current_step)
            current, current_step = [], None

        for stmt, line in statements:
            low = stmt.lower()
            if low.startswith("%macro"):
                name = re.match(r"%macro\s+(\w+)", low).group(1)
                macro_stack.append(name)
                program.macros_defined.append(name)
                continue
            if low.startswith("%mend"):
                close_step()
                if macro_stack:
                    macro_stack.pop()
                continue
            if low.startswith("%include"):
                program.includes.append(Path(re.search(r"[\"']([^\"']+)", stmt).group(1)).stem)
                continue
            if low.startswith("%let"):
                program.macro_vars_defined.append(re.match(r"%let\s+(\w+)", low).group(1))
                continue
            if low.startswith("libname"):
                libref = low.split()[1]
                program.librefs.append(libref)
                self.known_librefs.add(libref)
                continue
            if re.match(r"data\s+(?!=)", low) and (current_step is None or current_step.kind != "PROC"
                                                   or current_step.name != "sql"):
                close_step()
                current_step = Step("DATA", "data", line, in_macro=macro_stack[-1] if macro_stack else None)
                current = [(stmt, line)]
                continue
            if low.startswith("proc "):
                close_step()
                current_step = Step("PROC", low.split()[1], line,
                                    in_macro=macro_stack[-1] if macro_stack else None)
                current = [(stmt, line)]
                continue
            if low in {"run", "quit"}:
                close_step()
                continue
            if current_step is not None:
                current.append((stmt, line))
        close_step()

        produced: set[str] = set()
        inputs, outputs = [], []
        for step in program.steps:
            for ds in step.inputs:
                if ds not in produced and not ds.startswith("work."):
                    inputs.append(ds)
            produced.update(step.outputs)
            outputs.extend(o for o in step.outputs if not o.startswith("work."))
            for construct in step.constructs:
                program.constructs[construct] = program.constructs.get(construct, 0) + 1
        program.inputs = list(dict.fromkeys(inputs))
        program.outputs = list(dict.fromkeys(outputs))
        program.complexity_score = sum(CONSTRUCT_WEIGHTS[c] * n for c, n in program.constructs.items())
        for seuil, niveau, effort in LEVELS:
            if program.complexity_score < seuil:
                program.complexity_level, program.effort_days = niveau, effort
                break
        program.pitfalls.sort(key=lambda p: p.line)
        program.viya_readiness, program.viya_notes = assess_viya(program, code)
        return program

    def analyze_directory(self, directory: Path) -> Inventory:
        fichiers = sorted(directory.glob("*.sas"))
        for fichier in fichiers:
            for match in re.findall(r"^\s*libname\s+(\w+)", fichier.read_text(encoding="utf-8"), re.M | re.I):
                self.known_librefs.add(match.lower())
        programs = [self.analyze_file(f) for f in fichiers]

        producers = {ds: p.name for p in programs for ds in p.outputs}
        graph: dict[str, set[str]] = {}
        for program in programs:
            deps = {producers[ds] for ds in program.inputs if ds in producers and producers[ds] != program.name}
            deps.update(i for i in program.includes if any(p.name == i for p in programs))
            program.depends_on = sorted(deps)
            graph[program.name] = deps
        order = list(TopologicalSorter(graph).static_order())

        consumed = {ds for p in programs for ds in p.inputs}
        external = sorted({ds for p in programs for ds in p.inputs if ds not in producers})
        final = sorted(ds for ds in producers if ds not in consumed)
        return Inventory(programs, order, external, final)


def _node_id(name: str) -> str:
    return re.sub(r"\W", "_", name)


def lineage_mermaid(inventory: Inventory) -> str:
    lignes = ["flowchart LR"]
    for program in inventory.programs:
        if not program.steps:
            continue
        pid = "prg_" + _node_id(program.name)
        lignes.append(f'    {pid}["{program.name}.sas"]:::prog')
        for ds in program.inputs:
            lignes.append(f'    ds_{_node_id(ds)}[("{ds}")] --> {pid}')
        for ds in program.outputs:
            lignes.append(f'    {pid} --> ds_{_node_id(ds)}[("{ds}")]')
    lignes.append("    classDef prog fill:#1f6feb,color:#fff,stroke:#0b3d91")
    return "\n".join(lignes)


def to_markdown(inventory: Inventory) -> str:
    out = ["# Inventaire du parc SAS", ""]
    total_effort = sum(p.effort_days for p in inventory.programs if p.steps)
    out += [
        f"- Programmes analysés : **{len(inventory.programs)}**",
        f"- Sources externes : {', '.join(f'`{s}`' for s in inventory.external_sources)}",
        f"- Sorties finales : {', '.join(f'`{s}`' for s in inventory.final_outputs)}",
        f"- Effort de conversion indicatif : **{total_effort:.1f} jours-personne**",
        "",
        "## Programmes",
        "",
        "| Ordre | Programme | Lignes | Étapes | Score | Complexité | Entrées | Sorties |",
        "|---|---|---|---|---|---|---|---|",
    ]
    by_name = {p.name: p for p in inventory.programs}
    for rang, name in enumerate(inventory.migration_order, 1):
        p = by_name[name]
        out.append(
            f"| {rang} | `{p.name}` | {p.lines_of_code} | {len(p.steps)} | {p.complexity_score} | "
            f"{p.complexity_level if p.steps else 'config'} | {', '.join(p.inputs) or '-'} | "
            f"{', '.join(p.outputs) or '-'} |"
        )
    out += ["", "## Pièges de migration détectés", "",
            "| Programme | Ligne | Code | Sévérité | Constat | Recommandation |", "|---|---|---|---|---|---|"]
    for p in inventory.programs:
        for pit in p.pitfalls:
            out.append(
                f"| `{p.name}` | {pit.line} | {pit.code} | {pit.severity} | {pit.message} | {pit.recommendation} |"
            )
    out += ["", "## Lignage", "", "```mermaid", lineage_mermaid(inventory), "```", ""]
    return "\n".join(out)


def write_reports(inventory: Inventory, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "sas_inventory.json"
    md_path = reports_dir / "sas_inventory.md"
    json_path.write_text(json.dumps(asdict(inventory), indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(to_markdown(inventory), encoding="utf-8")
    return json_path, md_path
