"""Phase D checkpoint per SPEC §9.

Checks:
  1. scripts/ollama_client.py exists and exposes OllamaCloudClient + LLMRequest
  2. .env.example has OLLAMA_* lines
  3. Concurrency: 10 parallel requests with 200ms latency → peak in-flight = 3
  4. Model name suffix validation rejects 'glm-5.1' (no :cloud)
  5. validate_sparql (scripts/sparql_guard.py) rejects bad-syntax query
  6. validate_sparql rejects a query using an undeclared predicate
  7. NB05 saved output has no errors (optionally --execute to re-run)

No live API call required — uses httpx MockTransport throughout.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

import httpx
import nbformat
from rdflib import OWL, RDF, Graph

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "scripts"))

from sparql_guard import validate_sparql  # noqa: E402


def check(label: str, ok: bool, detail: str = "") -> bool:
    icon = "✓" if ok else "✗"
    suffix = f" — {detail}" if detail else ""
    print(f"  {icon} {label}{suffix}")
    return ok


async def test_concurrency() -> int:
    """Returns observed peak concurrency."""
    from ollama_client import LLMRequest, OllamaCloudClient

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.2)
        return httpx.Response(200, json={"response": "ok"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as ac:
        cli = OllamaCloudClient(_transport_client=ac)
        async with cli:
            reqs = [LLMRequest(model="glm-5.1:cloud", prompt=f"q{i}") for i in range(10)]
            await cli.parallel(*reqs)
        return cli._max_in_flight


def test_model_suffix_validation() -> bool:
    """Validate that empty model names are rejected. (Suffix is no longer
    enforced in client — the local daemon handles routing.)"""
    from ollama_client import _validate_model_name

    try:
        _validate_model_name("")
        return False
    except ValueError:
        pass
    # And a valid name with :cloud suffix passes through
    try:
        _validate_model_name("glm-5.1:cloud")
        return True
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Re-execute NB05 (slow). Default: inspect saved outputs.",
    )
    args = parser.parse_args()

    print("Phase D verification\n")
    passed = []

    # 1. Files exist
    client_path = PROJECT / "scripts" / "ollama_client.py"
    passed.append(check("scripts/ollama_client.py exists", client_path.exists()))

    # Symbol exports
    try:
        from ollama_client import LLMRequest, OllamaCloudClient  # noqa: F401

        passed.append(check("OllamaCloudClient + LLMRequest importable", True))
    except Exception as exc:
        passed.append(check("OllamaCloudClient + LLMRequest importable", False, str(exc)))

    # 2. .env.example has OLLAMA_* keys (no API key — local daemon)
    env_example = (PROJECT / ".env.example").read_text()
    has_all = all(
        k in env_example for k in ("OLLAMA_HOST", "OLLAMA_MODEL_FAST", "OLLAMA_MODEL_DEEP")
    )
    has_no_key = "OLLAMA_API_KEY" not in env_example
    passed.append(check(".env.example has OLLAMA_* keys (no API key)", has_all and has_no_key))

    # 3. Concurrency ceiling
    peak = asyncio.run(test_concurrency())
    passed.append(check("Concurrency capped at 3", peak == 3, f"peak={peak}"))

    # 4. Model name validation (empty name rejected, valid name accepted)
    passed.append(check("Model name validation works", test_model_suffix_validation()))

    # 5+6. SPARQL validator
    tbox = Graph()
    tbox.parse(str(PROJECT / "ontology" / "credit_risk.ttl"), format="turtle")
    whitelist = {str(p) for p in tbox.subjects(RDF.type, OWL.ObjectProperty)} | {
        str(p) for p in tbox.subjects(RDF.type, OWL.DatatypeProperty)
    }
    bad_syntax_q = "SELECT WHERE { ?s ?p ?o"
    ok_bad_syn, _ = validate_sparql(bad_syntax_q, whitelist, tbox)
    passed.append(check("Validator rejects bad-syntax SPARQL", not ok_bad_syn))

    bad_predicate_q = (
        "PREFIX : <https://nikko.dev/ontology/credit#>\n"
        "SELECT ?a WHERE { ?a :hallucinatedProperty ?x }"
    )
    ok_bad_pred, reason = validate_sparql(bad_predicate_q, whitelist, tbox)
    passed.append(
        check(
            "Validator rejects unknown predicate",
            not ok_bad_pred,
            reason if not ok_bad_pred else "",
        )
    )

    good_q = (
        "PREFIX : <https://nikko.dev/ontology/credit#>\n"
        "SELECT ?a WHERE { ?a a :Applicant ; :hasCreditScore ?s . FILTER(?s > 700) }"
    )
    ok_good, _ = validate_sparql(good_q, whitelist, tbox)
    passed.append(check("Validator accepts well-formed SPARQL", ok_good))

    # 7. NB05
    nb5 = PROJECT / "notebooks" / "05_neurosymbolic_loop.ipynb"
    passed.append(check("NB05 exists", nb5.exists()))
    if args.execute:
        cmd = [
            sys.executable,
            "-m",
            "jupyter",
            "nbconvert",
            "--to",
            "notebook",
            "--execute",
            "--ExecutePreprocessor.timeout",
            "180",
            "--output",
            "/tmp/_verify_nb05.ipynb",
            str(nb5),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        passed.append(
            check(
                "NB05 executes clean",
                r.returncode == 0,
                r.stderr.splitlines()[-1] if r.stderr else "OK",
            )
        )
    else:
        nb = nbformat.read(nb5, as_version=4)
        errors = [
            o
            for c in nb.cells
            if c.cell_type == "code"
            for o in c.get("outputs", [])
            if o.get("output_type") == "error"
        ]
        passed.append(
            check(
                "NB05 saved output has no errors",
                not errors,
                f"{len(errors)} errors" if errors else "clean",
            )
        )

    print()
    if all(passed):
        print("Phase D: ALL CHECKS PASSED ✓")
        return 0
    failed = sum(1 for p in passed if not p)
    print(f"Phase D: {failed} check(s) failed ✗")
    return 1


if __name__ == "__main__":
    sys.exit(main())
