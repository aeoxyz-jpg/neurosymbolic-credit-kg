"""Guardrail tests: concurrency ceiling, model-name validation, SPARQL gate.
All offline — httpx MockTransport, no daemon, no Fuseki."""

import asyncio
from pathlib import Path

import httpx
import pytest
from ollama_client import LLMRequest, OllamaCloudClient, _validate_model_name
from rdflib import OWL, RDF, Graph
from sparql_guard import validate_sparql

ROOT = Path(__file__).resolve().parent.parent


def test_concurrency_capped_at_3():
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={"response": "ok"})

    async def run() -> int:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as ac:
            cli = OllamaCloudClient(_transport_client=ac)
            async with cli:
                reqs = [LLMRequest(model="glm-5.1:cloud", prompt=f"q{i}") for i in range(10)]
                await cli.parallel(*reqs)
            return cli._max_in_flight

    assert asyncio.run(run()) == 3


def test_empty_model_name_rejected():
    with pytest.raises(ValueError):
        _validate_model_name("")
    _validate_model_name("glm-5.1:cloud")  # must not raise


def test_thinking_model_fallback_to_thinking_field():
    # glm-5.1:cloud may return empty `response` with content in `thinking`.
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "", "thinking": "chain"})

    async def run() -> str:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as ac:
            cli = OllamaCloudClient(_transport_client=ac)
            async with cli:
                return await cli.call(LLMRequest(model="glm-5.1:cloud", prompt="q"))

    assert asyncio.run(run()) == "chain"


@pytest.fixture(scope="module")
def tbox_and_whitelist():
    tbox = Graph()
    tbox.parse(str(ROOT / "ontology" / "credit_risk.ttl"), format="turtle")
    whitelist = {str(p) for p in tbox.subjects(RDF.type, OWL.ObjectProperty)} | {
        str(p) for p in tbox.subjects(RDF.type, OWL.DatatypeProperty)
    }
    return tbox, whitelist


def test_validator_rejects_bad_syntax(tbox_and_whitelist):
    tbox, whitelist = tbox_and_whitelist
    ok, reason = validate_sparql("SELECT WHERE { ?s ?p ?o", whitelist, tbox)
    assert not ok
    assert reason.startswith("syntax")


def test_validator_rejects_hallucinated_predicate(tbox_and_whitelist):
    tbox, whitelist = tbox_and_whitelist
    q = (
        "PREFIX : <https://nikko.dev/ontology/credit#>\n"
        "SELECT ?a WHERE { ?a :hallucinatedProperty ?x }"
    )
    ok, reason = validate_sparql(q, whitelist, tbox)
    assert not ok
    assert "hallucinatedProperty" in reason


def test_validator_accepts_wellformed_query(tbox_and_whitelist):
    tbox, whitelist = tbox_and_whitelist
    q = (
        "PREFIX : <https://nikko.dev/ontology/credit#>\n"
        "SELECT ?a WHERE { ?a a :Applicant ; :hasCreditScore ?s . "
        "FILTER(?s > 700) }"
    )
    ok, _ = validate_sparql(q, whitelist, tbox)
    assert ok
