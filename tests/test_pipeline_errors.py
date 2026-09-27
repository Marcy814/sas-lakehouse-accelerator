try:
    import httpx2 as httpx
except ImportError:
    import httpx
import openai

from pipeline import explain_llm_error


def _erreur(statut: int, corps: dict) -> Exception:
    requete = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    reponse = httpx.Response(statut, json=corps, request=requete)
    classe = {401: openai.AuthenticationError, 429: openai.RateLimitError}[statut]
    return classe("erreur", response=reponse, body=corps)


def test_credit_epuise():
    exc = _erreur(429, {"error": {"type": "insufficient_quota", "code": "credit_balance_exhausted"}})
    assert "crédit épuisé" in explain_llm_error(exc)


def test_cle_refusee():
    assert "clé API refusée" in explain_llm_error(_erreur(401, {"error": {"code": "invalid_api_key"}}))


def test_erreur_ordinaire_non_interceptee():
    assert explain_llm_error(ValueError("autre")) is None
