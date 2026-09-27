import json

try:
    import httpx2 as httpx
except ImportError:
    import httpx
from openai import OpenAI

from accelerator.agents.llm import OpenAIClient, Tool, run_tool_loop


def _completion(message: dict) -> dict:
    return {
        "id": "chatcmpl-test", "object": "chat.completion", "created": 0, "model": "gpt-test",
        "choices": [{"index": 0, "message": message,
                     "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 50, "total_tokens": 1050},
    }


def test_boucle_complete_via_le_sdk_openai():
    requetes = []
    reponses = [
        _completion({"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function",
             "function": {"name": "compter", "arguments": json.dumps({"table": "gold.dim_client"})}}]}),
        _completion({"role": "assistant", "content": "Il y a 42 clients."}),
    ]

    def serveur(requete: httpx.Request) -> httpx.Response:
        requetes.append(json.loads(requete.content))
        return httpx.Response(200, json=reponses[len(requetes) - 1])

    sdk = OpenAI(api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(serveur)))
    client = OpenAIClient(model="gpt-test", client=sdk)
    outil = Tool("compter", "Compte les lignes", {"type": "object", "properties": {"table": {"type": "string"}}},
                 lambda e: f"42 lignes dans {e['table']}")

    run = run_tool_loop(client, "Tu es analyste.", "Combien de clients ?", [outil])

    assert run.final_text == "Il y a 42 clients." and run.stop_reason == "end_turn"
    assert run.tool_calls[0].input == {"table": "gold.dim_client"}
    assert (run.usage.input_tokens, run.usage.output_tokens) == (2000, 100)
    assert run.model == "gpt-test" and run.cost_usd is None
    premiere, seconde = requetes
    assert premiere["model"] == "gpt-test"
    assert premiere["messages"][0] == {"role": "system", "content": "Tu es analyste."}
    assert premiere["tools"][0]["function"]["name"] == "compter"
    assert seconde["messages"][2]["tool_calls"][0]["id"] == "call_1"
    assert seconde["messages"][3] == {"role": "tool", "tool_call_id": "call_1",
                                      "content": "42 lignes dans gold.dim_client"}
