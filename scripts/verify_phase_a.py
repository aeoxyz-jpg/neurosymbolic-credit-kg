"""Phase A checkpoint per SPEC §9.

Checks (each prints ✓ or ✗ and contributes to the exit code):
  1. Fuseki responds at /$/ping
  2. Dataset `credit-risk` exists
  3. SPARQL endpoint returns a triple count > 0
  4. At least 20 :Applicant instances queryable
  5. At least 30 :CreditApplication instances queryable
  6. At least one :emittedSignal triple exists (signals were loaded)

Exit 0 if all pass. Exit 1 with a summary if any fail.
Dependencies: httpx, python-dotenv.
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx
from dotenv import load_dotenv

NS = "https://nikko.dev/ontology/credit#"


def check(label: str, ok: bool, detail: str = "") -> bool:
    icon = "✓" if ok else "✗"
    suffix = f" — {detail}" if detail else ""
    print(f"  {icon} {label}{suffix}")
    return ok


def sparql_select(endpoint: str, query: str) -> dict:
    resp = httpx.post(
        endpoint,
        data={"query": query},
        headers={"Accept": "application/sparql-results+json"},
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()


def scalar(endpoint: str, query: str, var: str) -> int:
    rows = sparql_select(endpoint, query)["results"]["bindings"]
    if not rows:
        return 0
    return int(rows[0][var]["value"])


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--url",
        default=os.environ.get("FUSEKI_URL", "http://localhost:3030"),
    )
    parser.add_argument(
        "--dataset",
        default=os.environ.get("FUSEKI_DATASET", "credit-risk"),
    )
    args = parser.parse_args()
    base = args.url.rstrip("/")
    dataset = args.dataset
    sparql_endpoint = f"{base}/{dataset}/sparql"

    print(f"Phase A verification against {base}/{dataset}\n")
    passed = []

    # 1. Ping
    try:
        r = httpx.get(f"{base}/$/ping", timeout=3.0)
        passed.append(check("Fuseki /$/ping", r.status_code == 200, f"HTTP {r.status_code}"))
    except httpx.HTTPError as exc:
        passed.append(check("Fuseki /$/ping", False, f"connection failed: {exc}"))
        print("\n  Aborting remaining checks — Fuseki unreachable.")
        return 1

    # 2. Dataset reachable. Fuseki's /$/datasets admin endpoint is locked to
    #    localhost-from-inside-container by default Shiro config, so we probe
    #    the dataset directly with an ASK query instead.
    try:
        r = httpx.post(
            sparql_endpoint,
            data={"query": "ASK { ?s ?p ?o }"},
            headers={"Accept": "application/sparql-results+json"},
            timeout=5.0,
        )
        passed.append(
            check(
                f"Dataset '{dataset}' reachable",
                r.status_code == 200,
                f"HTTP {r.status_code}",
            )
        )
    except Exception as exc:
        passed.append(check(f"Dataset '{dataset}' reachable", False, str(exc)))

    # 3. Triple count > 0
    try:
        n = scalar(sparql_endpoint, "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }", "n")
        passed.append(check("Triple count > 0", n > 0, f"{n} triples"))
    except Exception as exc:
        passed.append(check("Triple count > 0", False, str(exc)))
        return 1

    # 4. ≥ 20 Applicants
    try:
        n = scalar(
            sparql_endpoint,
            f"SELECT (COUNT(?a) AS ?n) WHERE {{ ?a a <{NS}Applicant> }}",
            "n",
        )
        passed.append(check("≥ 20 :Applicant instances", n >= 20, f"{n} applicants"))
    except Exception as exc:
        passed.append(check("≥ 20 :Applicant instances", False, str(exc)))

    # 5. ≥ 30 CreditApplications (counted via subclass union; T-Box subClassOf
    #    is not auto-materialized without a reasoner, so we union explicit subtypes.)
    try:
        q = f"""
            SELECT (COUNT(?app) AS ?n) WHERE {{
              {{ ?app a <{NS}MortgageApplication> }}
              UNION {{ ?app a <{NS}PersonalLoanApplication> }}
              UNION {{ ?app a <{NS}AutoLoanApplication> }}
              UNION {{ ?app a <{NS}CreditApplication> }}
            }}
        """
        n = scalar(sparql_endpoint, q, "n")
        passed.append(check("≥ 30 CreditApplication instances", n >= 30, f"{n} applications"))
    except Exception as exc:
        passed.append(check("≥ 30 CreditApplication instances", False, str(exc)))

    # 6. At least one :emittedSignal triple
    try:
        n = scalar(
            sparql_endpoint,
            f"SELECT (COUNT(*) AS ?n) WHERE {{ ?app <{NS}emittedSignal> ?s }}",
            "n",
        )
        passed.append(check("emittedSignal triples present", n > 0, f"{n} edges"))
    except Exception as exc:
        passed.append(check("emittedSignal triples present", False, str(exc)))

    print()
    if all(passed):
        print("Phase A: ALL CHECKS PASSED ✓")
        return 0
    failed = sum(1 for p in passed if not p)
    print(f"Phase A: {failed} check(s) failed ✗")
    return 1


if __name__ == "__main__":
    sys.exit(main())
