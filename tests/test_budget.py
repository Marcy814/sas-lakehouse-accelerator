from types import SimpleNamespace as NS

from accelerator.agents.llm import Tool, Usage, model_prices, run_tool_loop


class ClientBavard:
    """Appelle toujours un outil et consomme 100 000 jetons d'entrée par tour."""

    model = "gpt-4.1"

    def __init__(self):
        self.appels = 0

    def create(self, **_):
        self.appels += 1
        return NS(
            stop_reason="tool_use",
            content=[NS(type="tool_use", id=f"c{self.appels}", name="ping", input={})],
            usage=NS(input_tokens=100_000, output_tokens=1_000),
        )


def test_tarifs_et_cout():
    assert model_prices("gpt-4.1-mini-2025-04-14") == (0.40, 1.60)
    assert model_prices("gpt-4.1") == (2.00, 8.00)
    assert model_prices("modele-inconnu") is None
    assert round(Usage(1_000_000, 100_000).cost_usd("gpt-4.1-mini"), 4) == 0.56


def test_arret_au_plafond_de_depense():
    client = ClientBavard()
    run = run_tool_loop(client, "sys", "q", [Tool("ping", "", {"type": "object"}, lambda e: "pong")],
                        max_turns=50, max_cost_usd=0.50)
    assert run.stop_reason == "budget"
    assert client.appels == 3
    assert run.usage.input_tokens == 300_000 and 0.50 <= run.cost_usd < 0.70
    assert "budget" in run.final_text


def test_plafond_lu_dans_l_environnement(monkeypatch):
    monkeypatch.setenv("MAX_COST_USD", "0.10")
    run = run_tool_loop(ClientBavard(), "sys", "q", [Tool("ping", "", {"type": "object"}, lambda e: "pong")])
    assert run.stop_reason == "budget" and run.turns == 1
