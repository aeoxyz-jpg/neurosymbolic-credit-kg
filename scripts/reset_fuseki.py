"""Wipe the default graph of the Fuseki dataset (clean-slate for re-load).

Usage:
    python scripts/reset_fuseki.py
    python scripts/reset_fuseki.py --all-graphs   # also drop named graphs

Idempotent: deleting an already-empty graph is a no-op (HTTP 204/404 OK).
Dependencies: httpx, python-dotenv.
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx
from dotenv import load_dotenv


def sparql_update(fuseki_url: str, dataset: str, query: str) -> None:
    endpoint = f"{fuseki_url.rstrip('/')}/{dataset}/update"
    resp = httpx.post(
        endpoint,
        data={"update": query},
        timeout=30.0,
    )
    if resp.status_code not in (200, 204):
        raise SystemExit(f"✗ Fuseki rejected update ({resp.status_code}): {resp.text[:500]}")


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
    parser.add_argument(
        "--all-graphs",
        action="store_true",
        help="Also DROP ALL named graphs, not just the default graph.",
    )
    args = parser.parse_args()

    if args.all_graphs:
        query = "DROP ALL"
        target = "all graphs"
    else:
        query = "CLEAR DEFAULT"
        target = "default graph"

    print(f"→ {query} on {args.url}/{args.dataset} ({target}) ...")
    sparql_update(args.url, args.dataset, query)
    print(f"  ✓ Cleared {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
