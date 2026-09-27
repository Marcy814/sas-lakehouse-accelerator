"""Point d'entrée unique de l'accélérateur : python pipeline.py <commande> --help"""

from __future__ import annotations

import argparse
import shutil
import sys
import time

from dotenv import load_dotenv

from accelerator import config, data_generator, ingestion, legacy_estate, legacy_reference, reconciliation
from accelerator.dbt_runner import run_dbt
from accelerator.sas_analyzer import SasAnalyzer
from accelerator.sas_analyzer import write_reports as write_inventory


def titre(texte: str) -> None:
    print(f"\n=== {texte} ===")


def cmd_generate(args) -> int:
    titre("Génération des extraits PolicyAdmin")
    for fichier, lignes in data_generator.generate(seed=args.seed).items():
        print(f"  {fichier:<22} {lignes:>7} lignes")
    return 0


def cmd_ingest(args) -> int:
    titre(f"Ingestion bronze{'' if args.batch is None else f' (lot {args.batch})'}")
    for r in ingestion.ingest(batch=args.batch):
        etat = "déjà ingéré, ignoré" if r.skipped else f"{r.rows} lignes"
        print(f"  bronze.{r.table:<10} {r.file_name:<16} {etat}")
    return 0


def cmd_transform(args) -> int:
    titre("Transformation dbt (silver → snapshot SCD2 → gold)")
    commande = ["build"]
    if args.full_refresh:
        commande.append("--full-refresh")
    return 0 if run_dbt(commande, stream=True).success else 1


def cmd_legacy(_args) -> int:
    titre("Exécution de référence des programmes SAS (sorties legacy)")
    for nom, lignes in legacy_reference.run().items():
        print(f"  dwh.{nom:<22} {lignes:>7} lignes")
    return 0


def cmd_analyze(_args) -> int:
    titre("Analyse statique du parc SAS (dont compatibilité SAS Viya)")
    inventaire = SasAnalyzer().analyze_directory(config.SAS_DIR)
    for p in inventaire.programs:
        if p.steps:
            print(f"  {p.name:<24} score={p.complexity_score:>3}  {p.complexity_level:<8} "
                  f"pièges={len(p.pitfalls)}  dépend de={', '.join(p.depends_on) or '-'}")
    print(f"  Ordre de migration : {' → '.join(inventaire.migration_order)}")
    _, md = write_inventory(inventaire, config.REPORTS_DIR)
    print(f"  Rapport SAS : {md.relative_to(config.ROOT)}")

    titre("Inventaire du parc multi-outils (SAS, Informatica, DataStage, Cognos)")
    parc = legacy_estate.build_inventory()
    for outil, nombre in parc.tools.items():
        print(f"  {outil:<26} {nombre} artefact(s)")
    for rang, vague in enumerate(parc.waves, 1):
        print(f"  Vague {rang} : {', '.join(vague)}")
    print(f"  Rapport parc : {legacy_estate.write_reports(parc).relative_to(config.ROOT)}")
    return 0


def cmd_reconcile(_args) -> int:
    titre("Réconciliation legacy ↔ lakehouse")
    resultats = reconciliation.reconcile_all()
    for r in resultats:
        print(f"  {'OK   ' if r.passed else 'ÉCART'} {r.summary()}")
    chemin = reconciliation.write_reports(resultats)
    print(f"  Rapport : {chemin.relative_to(config.ROOT)}")
    return 0 if all(r.passed for r in resultats) else 1


NAIVE_CONVERSION = """
create or replace table agent_sandbox.conversion_naive_clients_courants as
select
    client_id, nom_complet, date_naissance,
    date_diff('year', date_naissance, date '{date_ref}') as age,
    case
        when date_diff('year', date_naissance, date '{date_ref}') < 30 then '18-29'
        when date_diff('year', date_naissance, date '{date_ref}') < 50 then '30-49'
        when date_diff('year', date_naissance, date '{date_ref}') < 65 then '50-64'
        else '65+'
    end as tranche_age,
    province, ville, segment, date_maj
from gold.dim_client
where est_courant
"""


def cmd_demo_pitfall(_args) -> int:
    import duckdb

    titre("Démonstration : conversion ligne à ligne naïve de 01_clients_courants.sas")
    spec = next(s for s in reconciliation.load_specs() if s.legacy == "dwh.clients_courants")
    with duckdb.connect(str(config.DB_PATH)) as con:
        con.execute("create schema if not exists agent_sandbox")
        con.execute(NAIVE_CONVERSION.format(date_ref=config.DATE_REF.isoformat()))
        naive = reconciliation.reconcile_dataset(
            con, spec, target_table="agent_sandbox.conversion_naive_clients_courants"
        )
        migree = reconciliation.reconcile_dataset(con, spec)
    print(f"  Conversion naïve : {naive.summary()}")
    with duckdb.connect(str(config.DB_PATH), read_only=True) as con:
        sans_naissance = con.execute(
            "select count(*) from gold.mart_clients_courants where date_naissance is null"
        ).fetchone()[0]
    print(f"      dont {sans_naissance} clients sans date de naissance : SAS les classe en 18-29 "
          "(valeur manquante < 30), le SQL naïf en 65+.")
    for s in naive.samples[:6]:
        print(f"      {s['cle']} {s['colonne']}: SAS={s['legacy']} naïf={s['cible']}")
    print(f"  Conversion dbt   : {migree.summary()}")
    return 0


def cmd_run_all(args) -> int:
    debut = time.perf_counter()
    if not args.keep:
        for dossier in (config.WAREHOUSE_DIR, config.LANDING_DIR, config.LEGACY_OUTPUT_DIR):
            shutil.rmtree(dossier, ignore_errors=True)
    etapes = [
        (cmd_generate, argparse.Namespace(seed=args.seed)),
        (cmd_analyze, None),
        (cmd_ingest, argparse.Namespace(batch=1)),
        (cmd_transform, argparse.Namespace(full_refresh=False)),
        (cmd_ingest, argparse.Namespace(batch=2)),
        (cmd_transform, argparse.Namespace(full_refresh=False)),
        (cmd_legacy, None),
        (cmd_reconcile, None),
    ]
    for fonction, arguments in etapes:
        code = fonction(arguments)
        if code:
            print(f"\nÉchec à l'étape {fonction.__name__}.")
            return code
    print(f"\nPipeline complet en {time.perf_counter() - debut:.1f} s.")
    return 0


def cmd_portability(_args) -> int:
    from accelerator import portability

    titre("Portabilité du projet dbt vers Databricks et Snowflake (compilation hors ligne)")
    resultats = portability.run()
    for r in resultats:
        if not r.available or not r.compiled:
            print(f"  {r.target:<11} non vérifié : {r.message.splitlines()[0] if r.message else ''}")
        else:
            print(f"  {r.target:<11} compilation OK | {sum(m.ok for m in r.models)}/{len(r.models)} modèles portables")
    print(f"  Rapport : {(config.REPORTS_DIR / 'portability.md').relative_to(config.ROOT)}")
    verifies = [r for r in resultats if r.compiled]
    return 0 if all(all(m.ok for m in r.models) for r in verifies) else 1


def cmd_stream(args) -> int:
    from accelerator import streaming

    titre("Streaming : événements de sinistres en micro-lots (checkpoint, filigrane, fenêtres de 15 min)")
    if not args.keep:
        streaming.reset()
    processeur = streaming.StreamProcessor()
    deja = len(list(streaming.STREAM_DIR.glob("evenements_*.jsonl")))
    for numero in range(deja + 1, deja + args.batches + 1):
        streaming.generate_batch(numero)
        for metriques in processeur.process_available():
            print(f"  {metriques.summary()}")
    rejeu = processeur.process_available()
    print(f"  Relance immédiate : {len(rejeu)} lot retraité (exactly-once grâce au checkpoint)")
    print("  Résultats : gold.sinistres_par_fenetre, gold.alertes_temps_reel, stream.metriques_lots")
    return 0


def cmd_train_fraud(_args) -> int:
    import os
    import warnings

    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    warnings.filterwarnings("ignore")
    try:
        from accelerator.ml import fraud_model
    except ImportError:
        print("Dépendances ML absentes : python -m pip install -e \".[ml]\"")
        return 1
    titre("Entraînement du modèle de fraude (gold.ml_features_fraude)")
    rapport = fraud_model.train()
    print(f"  Entraînement : {rapport.train_rows} sinistres enquêtés | test : {rapport.test_rows}")
    for cle, valeur in rapport.metrics.items():
        print(f"  {cle:<22} modèle={valeur:.3f}   règles SAS={rapport.baseline_metrics[cle]:.3f}")
    print(f"  Run MLflow : {rapport.mlflow_run_id or 'non journalisé'} | scores : gold.ml_scores_fraude")
    print(f"  Fiche modèle : {(config.REPORTS_DIR / 'ml_fraude.md').relative_to(config.ROOT)}")
    return 0


def cmd_migrate(args) -> int:
    from accelerator.agents.llm import make_client
    from accelerator.agents.migration_agent import MigrationAgent

    titre(f"Agent de migration : {args.program}.sas")
    agent = MigrationAgent(make_client(args.model))

    def journal(appel):
        print(f"  ↳ {appel.name}{' (erreur)' if appel.is_error else ''} : {' '.join(appel.output.split())[:140]}")

    rapport = agent.convert(args.program, max_turns=args.max_turns, on_tool_call=journal, max_cost_usd=args.max_cost)
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    chemin = config.REPORTS_DIR / f"migration_{args.program}.md"
    chemin.write_text(rapport.to_markdown(), encoding="utf-8")
    for d in rapport.datasets:
        print(f"  {d.model_name}: {d.status}")
    print(f"  Consommation : {rapport.usage_summary}")
    if rapport.stop_reason == "budget":
        print("  Arrêt anticipé : plafond de dépense atteint (MAX_COST_USD dans .env ou --max-cost).")
    print(f"  Rapport : {chemin.relative_to(config.ROOT)}")
    return 0 if all(d.status.startswith("RÉCONCILIÉ") for d in rapport.datasets) else 1


def cmd_ask(args) -> int:
    from accelerator.agents.analyst_agent import AnalystAgent, print_tool_call
    from accelerator.agents.llm import make_client

    agent = AnalystAgent(make_client(args.model))
    reponse = agent.ask(args.question, on_tool_call=print_tool_call, max_cost_usd=args.max_cost)
    print("\n" + reponse.answer)
    print(f"\n[Consommation : {reponse.run.usage.describe(reponse.run.model)}]")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv(config.ROOT / ".env")
    parser = argparse.ArgumentParser(description="Accélérateur de migration SAS → Lakehouse")
    sous = parser.add_subparsers(dest="commande", required=True)

    p = sous.add_parser("generate", help="Générer les extraits sources (2 lots)")
    p.add_argument("--seed", type=int, default=42)
    p.set_defaults(func=cmd_generate)

    p = sous.add_parser("ingest", help="Charger la zone d'atterrissage dans bronze (idempotent)")
    p.add_argument("--batch", type=int, default=None)
    p.set_defaults(func=cmd_ingest)

    p = sous.add_parser("transform", help="dbt build (silver, snapshot, gold, tests)")
    p.add_argument("--full-refresh", action="store_true")
    p.set_defaults(func=cmd_transform)

    sous.add_parser("legacy", help="Produire les sorties SAS de référence").set_defaults(func=cmd_legacy)
    sous.add_parser("analyze", help="Inventaire, lignage et complexité du code SAS").set_defaults(func=cmd_analyze)
    sous.add_parser("reconcile", help="Réconcilier legacy et lakehouse").set_defaults(func=cmd_reconcile)
    sous.add_parser("demo-pitfall", help="Montrer un écart détecté par la réconciliation").set_defaults(
        func=cmd_demo_pitfall
    )

    p = sous.add_parser("run-all", help="Chaîne complète de bout en bout")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--keep", action="store_true", help="Ne pas repartir d'un entrepôt vide")
    p.set_defaults(func=cmd_run_all)

    sous.add_parser("portability", help="Compiler le projet dbt pour Databricks et Snowflake").set_defaults(
        func=cmd_portability
    )

    p = sous.add_parser("stream", help="Simuler l'arrivée d'événements et les traiter en micro-lots")
    p.add_argument("--batches", type=int, default=6)
    p.add_argument("--keep", action="store_true", help="Continuer le flux existant au lieu de repartir à zéro")
    p.set_defaults(func=cmd_stream)

    sous.add_parser("train-fraud", help="Entraîner le modèle de fraude (suivi MLflow)").set_defaults(
        func=cmd_train_fraud
    )

    p = sous.add_parser("migrate", help="Convertir un programme SAS avec l'agent IA")
    p.add_argument("program", help="ex. 04_indicateurs_fraude")
    p.add_argument("--max-turns", type=int, default=16)
    p.add_argument("--model", default=None, help="ex. gpt-4.1 (défaut : OPENAI_MODEL du .env)")
    p.add_argument("--max-cost", type=float, default=None, help="Plafond en $ US (défaut : MAX_COST_USD du .env)")
    p.set_defaults(func=cmd_migrate)

    p = sous.add_parser("ask", help="Poser une question métier à l'agent analytique")
    p.add_argument("question")
    p.add_argument("--model", default=None, help="ex. gpt-4.1-mini (défaut : OPENAI_MODEL du .env)")
    p.add_argument("--max-cost", type=float, default=None, help="Plafond en $ US (défaut : MAX_COST_USD du .env)")
    p.set_defaults(func=cmd_ask)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        message = explain_llm_error(exc)
        if message is None:
            raise
        print(f"\nErreur du fournisseur d'IA : {message}")
        return 2


def explain_llm_error(exc: Exception) -> str | None:
    if isinstance(exc, RuntimeError) and "API_KEY" in str(exc):
        return str(exc)
    statut = getattr(exc, "status_code", None)
    if statut is None or not type(exc).__module__.startswith(("openai", "anthropic")):
        return None
    texte = f"{exc} {getattr(exc, 'body', '')}"
    if statut == 401:
        return "clé API refusée (401). Vérifier la valeur dans .env ou créer une nouvelle clé."
    if statut == 429 and ("insufficient_quota" in texte or "credit" in texte):
        return ("crédit épuisé (429). Ajouter du crédit dans la page Billing du fournisseur, "
                "ou vérifier la limite de budget du projet.")
    if statut == 429:
        return "limite de débit atteinte (429). Réessayer dans une minute."
    if statut == 404:
        return "modèle introuvable (404). Vérifier OPENAI_MODEL / ANTHROPIC_MODEL dans .env."
    return f"statut {statut} : {texte[:300]}"


if __name__ == "__main__":
    sys.exit(main())
