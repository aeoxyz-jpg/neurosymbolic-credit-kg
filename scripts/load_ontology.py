"""Load a Turtle file into Fuseki via the SPARQL Graph Store Protocol.

Usage:
    python scripts/load_ontology.py ontology/credit_risk.ttl
    python scripts/load_ontology.py ontology/instances/customers.ttl --graph default

By default appends to the dataset's default graph via HTTP POST. Pair with
`reset_fuseki.py` for a clean reload — running `reset` then this script is
idempotent. Pass `--replace` to use PUT, which wipes the target graph first.

Dependencies: httpx, python-dotenv, rdflib (for parse-check).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from rdflib import Graph


def parse_check(path: Path) -> int:
    """Parse the TTL file with rdflib first — fail fast on syntax errors."""
    g = Graph()
    g.parse(str(path), format="ttl")
    return len(g)


def upload(path: Path, fuseki_url: str, dataset: str, graph: str, replace: bool) -> None:
    """Send the TTL contents to Fuseki's graph store endpoint.

    graph="default"  → dataset's default graph (no `?graph` param).
    Any other value  → named graph IRI.
    replace=True     → HTTP PUT (wipes target graph first).
    replace=False    → HTTP POST (appends; pair with reset_fuseki for clean reload).
    """
    endpoint = f"{fuseki_url.rstrip('/')}/{dataset}/data"
    params = {} if graph == "default" else {"graph": graph}
    data = path.read_bytes()
    headers = {"Content-Type": "text/turtle; charset=utf-8"}
    method = httpx.put if replace else httpx.post

    resp = method(endpoint, params=params, content=data, headers=headers, timeout=30.0)
    if resp.status_code not in (200, 201, 204):
        raise SystemExit(f"✗ Fuseki rejected upload ({resp.status_code}): {resp.text[:500]}")


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", type=Path, help="Path to a .ttl file")
    parser.add_argument(
        "--graph",
        default="default",
        help='Target graph: "default" (dataset default graph) or an IRI. Default: "default".',
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("FUSEKI_URL", "http://localhost:3030"),
        help="Fuseki base URL (default: $FUSEKI_URL or http://localhost:3030)",
    )
    parser.add_argument(
        "--dataset",
        default=os.environ.get("FUSEKI_DATASET", "credit-risk"),
        help="Dataset name (default: $FUSEKI_DATASET or credit-risk)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Use HTTP PUT (wipes target graph first) instead of POST (append).",
    )
    args = parser.parse_args()

    if not args.path.exists():
        print(f"✗ File not found: {args.path}", file=sys.stderr)
        return 2

    print(f"→ Parsing {args.path} ...")
    n = parse_check(args.path)
    print(f"  ✓ {n} triples parsed locally")

    method = "PUT (replace)" if args.replace else "POST (append)"
    print(f"→ Uploading to {args.url}/{args.dataset} (graph={args.graph}, {method}) ...")
    upload(args.path, args.url, args.dataset, args.graph, args.replace)
    print("  ✓ Uploaded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
