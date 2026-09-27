from types import SimpleNamespace as NS

import duckdb

from accelerator.agents.llm import Tool, run_tool_loop
from accelerator.agents.migration_agent import MigrationAgent
from accelerator.reconciliation import DatasetSpec
from accelerator.sas_analyzer import SasAnalyzer


class ScriptedClient:
    """Client LLM factice qui rejoue une séquence d'appels d'outils."""

    def __init__(self, script):
        self.script, self.requests = script, []

    def create(self, *, system, messages, tools, max_tokens):
        self.requests.append(messages)
        etape = self.script[len(self.requests) - 1]
        if etape is None:
            return NS(stop_reason="end_turn", content=[NS(type="text", text="Terminé.")])
        blocs = [NS(type="tool_use", id=f"id{len(self.requests)}{i}", name=n, input=a) for i, (n, a) in enumerate(etape)]
        return NS(stop_reason="tool_use", content=blocs)


def test_boucle_transmet_les_resultats_et_les_erreurs():
    outils = [Tool("echo", "", {"type": "object"}, lambda e: e["x"]),
              Tool("boom", "", {"type": "object"}, lambda e: 1 / 0)]
    client = ScriptedClient([[("echo", {"x": "salut"}), ("boom", {})], None])
    run = run_tool_loop(client, "sys", "question", outils)
    assert run.stop_reason == "end_turn" and run.final_text == "Terminé."
    resultats = client.requests[1][2]["content"]
    assert resultats[0]["content"] == "salut" and not resultats[0]["is_error"]
    assert resultats[1]["is_error"] and "division by zero" in resultats[1]["content"]


SAS = """
libname src "/x"; libname dwh "/y";
data dwh.clients_courants; set src.clients; if age < 30 then tranche = 'J'; else tranche = 'S'; run;
"""


def test_agent_de_migration_corrige_apres_reconciliation(tmp_path):
    sas_dir, legacy_dir, sandbox = tmp_path / "sas", tmp_path / "legacy", tmp_path / "sandbox"
    for d in (sas_dir, legacy_dir, sandbox):
        d.mkdir()
    (sas_dir / "01_clients.sas").write_text(SAS, encoding="utf-8")
    (legacy_dir / "clients_courants.csv").write_text("client_id,tranche\nA,J\nB,S\nC,J\n", encoding="utf-8")
    base = tmp_path / "lake.duckdb"
    with duckdb.connect(str(base)) as con:
        con.execute("create schema silver; create schema agent_sandbox")
        con.execute("create table silver.silver_clients as select * from (values ('A', 25), ('B', 40), ('C', null)) t(client_id, age)")

    def build(nom):
        sql = (sandbox / f"{nom}.sql").read_text(encoding="utf-8").split("\n\n", 1)[1]
        sql = sql.replace("{{ ref('silver_clients') }}", "silver.silver_clients")
        sql = sql.replace("{{ sas_lt('age', 30) }}", "(age is null or age < 30)")
        with duckdb.connect(str(base)) as con:
            con.execute(f"create or replace table agent_sandbox.{nom} as {sql}")
        return True, "OK"

    modele = "agent_mart_clients_courants"
    naif = "select client_id, case when age < 30 then 'J' else 'S' end as tranche from {{ ref('silver_clients') }}"
    fidele = naif.replace("age < 30", "{{ sas_lt('age', 30) }}")
    client = ScriptedClient([
        [("write_model", {"model_name": modele, "sql": "select * from {{ ref('mart_interdit') }}"})],
        [("write_model", {"model_name": modele, "sql": naif})],
        [("build_model", {"model_name": modele})],
        [("reconcile", {"model_name": modele})],
        [("write_model", {"model_name": modele, "sql": fidele})],
        [("build_model", {"model_name": modele})],
        [("reconcile", {"model_name": modele})],
        [("submit", {"models": [{"model_name": modele, "confidence": "élevée",
                                 "review_points": ["Confirmer la règle pour l'âge manquant"]}]})],
    ])
    spec = DatasetSpec("dwh.clients_courants", "01_clients", "clients_courants.csv",
                       "mart_clients_courants", "gold", ["client_id"])
    agent = MigrationAgent(client, db_path=base, sas_dir=sas_dir, sandbox_dir=sandbox, legacy_dir=legacy_dir,
                           specs=[spec], inventory=SasAnalyzer().analyze_directory(sas_dir), build_fn=build)
    rapport = agent.convert("01_clients")

    appels = rapport.tool_calls
    assert appels[0].is_error and "non autorisés" in appels[0].output
    assert '"conforme": false' in appels[3].output and "tranche" in appels[3].output
    assert '"conforme": true' in appels[6].output
    assert rapport.stop_reason == "submitted"
    conversion = rapport.datasets[0]
    assert conversion.status.startswith("RÉCONCILIÉ")
    assert conversion.review_points == ["Confirmer la règle pour l'âge manquant"]
    assert "agent_sandbox" in (sandbox / f"{modele}.sql").read_text(encoding="utf-8")
