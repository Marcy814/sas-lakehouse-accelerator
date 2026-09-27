"""Boucle d'agent générique à appels d'outils, compatible Anthropic et OpenAI.

Le format interne des messages suit l'API Messages d'Anthropic; OpenAIClient le traduit vers
l'API Chat Completions et retraduit les réponses.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Protocol

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
DEFAULT_MAX_COST_USD = 0.50

PRICES_USD_PER_MILLION = {
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "claude-sonnet": (3.00, 15.00),
    "claude-haiku": (1.00, 5.00),
}


def model_prices(model: str) -> tuple[float, float] | None:
    """Tarif (entrée, sortie) en USD par million de jetons; surchargeable par l'environnement."""
    entree, sortie = os.environ.get("LLM_PRICE_INPUT_PER_M"), os.environ.get("LLM_PRICE_OUTPUT_PER_M")
    if entree and sortie:
        return float(entree), float(sortie)
    for prefixe in sorted(PRICES_USD_PER_MILLION, key=len, reverse=True):
        if model.startswith(prefixe):
            return PRICES_USD_PER_MILLION[prefixe]
    return None


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def cost_usd(self, model: str) -> float | None:
        prix = model_prices(model)
        if prix is None:
            return None
        return (self.input_tokens * prix[0] + self.output_tokens * prix[1]) / 1_000_000

    def describe(self, model: str) -> str:
        cout = self.cost_usd(model)
        estimation = f"≈ {cout:.4f} $ US" if cout is not None else "coût inconnu pour ce modèle"
        return f"{self.input_tokens:,} jetons en entrée, {self.output_tokens:,} en sortie ({model}, {estimation})"


class LLMClient(Protocol):
    def create(self, *, system: str, messages: list[dict], tools: list[dict], max_tokens: int) -> Any: ...


class AnthropicClient:
    def __init__(self, model: str | None = None):
        from anthropic import Anthropic

        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY absente : renseigner le fichier .env (voir .env.example).")
        self._client = Anthropic()
        self.model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_ANTHROPIC_MODEL

    def create(self, *, system: str, messages: list[dict], tools: list[dict], max_tokens: int) -> Any:
        return self._client.messages.create(
            model=self.model, system=system, messages=messages, tools=tools, max_tokens=max_tokens
        )


def to_openai_messages(system: str, messages: list[dict]) -> list[dict]:
    sortie: list[dict] = [{"role": "system", "content": system}]
    for message in messages:
        contenu = message["content"]
        if isinstance(contenu, str):
            sortie.append({"role": message["role"], "content": contenu})
            continue
        if message["role"] == "assistant":
            texte = "\n".join(b["text"] for b in contenu if b["type"] == "text") or None
            appels = [
                {"id": b["id"], "type": "function",
                 "function": {"name": b["name"], "arguments": json.dumps(b["input"], ensure_ascii=False)}}
                for b in contenu if b["type"] == "tool_use"
            ]
            entree: dict = {"role": "assistant", "content": texte}
            if appels:
                entree["tool_calls"] = appels
            sortie.append(entree)
        else:
            for bloc in contenu:
                if bloc["type"] == "tool_result":
                    sortie.append({"role": "tool", "tool_call_id": bloc["tool_use_id"], "content": bloc["content"]})
                elif bloc["type"] == "text":
                    sortie.append({"role": "user", "content": bloc["text"]})
    return sortie


def to_openai_tools(tools: list[dict]) -> list[dict]:
    return [
        {"type": "function",
         "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
        for t in tools
    ]


def from_openai_response(reponse: Any) -> SimpleNamespace:
    message = reponse.choices[0].message
    blocs = []
    if message.content:
        blocs.append(SimpleNamespace(type="text", text=message.content))
    for appel in message.tool_calls or []:
        arguments = json.loads(appel.function.arguments or "{}")
        blocs.append(SimpleNamespace(type="tool_use", id=appel.id, name=appel.function.name, input=arguments))
    arret = "tool_use" if message.tool_calls else "end_turn"
    usage = getattr(reponse, "usage", None)
    return SimpleNamespace(
        content=blocs,
        stop_reason=arret,
        usage=SimpleNamespace(
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        ),
    )


class OpenAIClient:
    def __init__(self, model: str | None = None, client: Any = None):
        if client is None:
            from openai import OpenAI

            if not os.environ.get("OPENAI_API_KEY"):
                raise RuntimeError("OPENAI_API_KEY absente : renseigner le fichier .env (voir .env.example).")
            client = OpenAI()
        self._client = client
        self.model = model or os.environ.get("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL

    def create(self, *, system: str, messages: list[dict], tools: list[dict], max_tokens: int) -> Any:
        reponse = self._client.chat.completions.create(
            model=self.model,
            messages=to_openai_messages(system, messages),
            tools=to_openai_tools(tools),
            max_completion_tokens=max_tokens,
        )
        return from_openai_response(reponse)


def make_client(model: str | None = None) -> LLMClient:
    fournisseur = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if not fournisseur:
        fournisseur = "openai" if os.environ.get("OPENAI_API_KEY") else "anthropic"
    if fournisseur == "openai":
        return OpenAIClient(model)
    if fournisseur == "anthropic":
        return AnthropicClient(model)
    raise ValueError(f"LLM_PROVIDER inconnu : {fournisseur} (valeurs possibles : openai, anthropic)")


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict], str]
    terminal: bool = False

    @property
    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


@dataclass
class ToolCall:
    name: str
    input: dict
    output: str
    is_error: bool


@dataclass
class AgentRun:
    final_text: str
    stop_reason: str
    turns: int
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = ""

    @property
    def cost_usd(self) -> float | None:
        return self.usage.cost_usd(self.model)


def _block_to_dict(block: Any) -> dict:
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    raise ValueError(f"Bloc non géré : {block.type}")


def run_tool_loop(
    client: LLMClient,
    system: str,
    user_message: str,
    tools: list[Tool],
    max_turns: int = 12,
    max_tokens: int = 4096,
    on_tool_call: Callable[[ToolCall], None] | None = None,
    max_cost_usd: float | None = None,
) -> AgentRun:
    outils = {t.name: t for t in tools}
    messages: list[dict] = [{"role": "user", "content": user_message}]
    appels: list[ToolCall] = []
    texte = ""
    modele = str(getattr(client, "model", ""))
    usage = Usage()
    if max_cost_usd is None:
        max_cost_usd = float(os.environ.get("MAX_COST_USD") or DEFAULT_MAX_COST_USD)

    def fin(raison: str, tours: int) -> AgentRun:
        return AgentRun(texte, raison, tours, appels, usage, modele)

    for tour in range(1, max_turns + 1):
        reponse = client.create(
            system=system, messages=messages, tools=[t.spec for t in tools], max_tokens=max_tokens
        )
        consommation = getattr(reponse, "usage", None)
        usage.input_tokens += getattr(consommation, "input_tokens", 0) or 0
        usage.output_tokens += getattr(consommation, "output_tokens", 0) or 0
        blocs = list(reponse.content)
        messages.append({"role": "assistant", "content": [_block_to_dict(b) for b in blocs]})
        texte = "\n".join(b.text for b in blocs if b.type == "text").strip() or texte
        demandes = [b for b in blocs if b.type == "tool_use"]
        if reponse.stop_reason != "tool_use" or not demandes:
            return fin(reponse.stop_reason, tour)

        resultats, termine = [], False
        for demande in demandes:
            outil = outils.get(demande.name)
            try:
                if outil is None:
                    raise ValueError(f"outil inconnu : {demande.name}")
                sortie, erreur = outil.handler(dict(demande.input)), False
                termine = termine or outil.terminal
            except Exception as exc:
                sortie, erreur = f"ERREUR : {exc}", True
            appel = ToolCall(demande.name, dict(demande.input), sortie, erreur)
            appels.append(appel)
            if on_tool_call:
                on_tool_call(appel)
            resultats.append(
                {"type": "tool_result", "tool_use_id": demande.id, "content": sortie, "is_error": erreur}
            )
        messages.append({"role": "user", "content": resultats})
        if termine:
            return fin("submitted", tour)
        cout = usage.cost_usd(modele)
        if cout is not None and cout >= max_cost_usd:
            texte = texte or f"Arrêt : budget de {max_cost_usd:.2f} $ US atteint."
            return fin("budget", tour)

    return fin("max_turns", max_turns)


def to_json(valeur: Any) -> str:
    return json.dumps(valeur, ensure_ascii=False, default=str, indent=1)
