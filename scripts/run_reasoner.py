"""Pellet + SWRL R1-R4 + R5 SPARQL UPDATE — the full Phase C reasoner.

Workflow:
  1. Load T-Box + A-Box via rdflib (handles Turtle), convert to RDF/XML.
  2. Load into owlready2; declare SWRL rules R1..R4 (SPEC §6).
  3. Run Pellet — derives PrimeApplicant tier classification AND fires SWRL.
  4. Export reasoned world to an rdflib graph.
  5. (Optional, --apply-r5) Run a SPARQL UPDATE that assigns :Review to any
     application still without a decision — the negation-as-failure case
     SWRL cannot express (SPEC §6 R5).
  6. Serialize the result to <output> (default ontology/inferred.ttl).

Usage:
  python scripts/run_reasoner.py
  python scripts/run_reasoner.py --apply-r5 --output ontology/inferred.ttl
  python scripts/run_reasoner.py --apply-r5 --print-summary

Dependencies: rdflib, owlready2, Java 25+ in PATH or JAVA_EXE env.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from rdflib import Graph, Namespace

NS_STR = "https://nikko.dev/ontology/credit#"
NS = Namespace(NS_STR)


def setup_owlready2():
    """Configure owlready2 to use the right Java."""
    import owlready2

    java_exe = os.environ.get("JAVA_EXE", "/opt/homebrew/opt/openjdk/bin/java")
    if Path(java_exe).exists():
        owlready2.JAVA_EXE = java_exe
    return owlready2


def load_combined(*ttl_paths: Path) -> Graph:
    g = Graph()
    for p in ttl_paths:
        g.parse(str(p), format="turtle")
    return g


def to_rdfxml_tempfile(g: Graph) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".owl", delete=False)
    g.serialize(destination=tmp.name, format="xml")
    return Path(tmp.name)


# Single source of truth for the SWRL rule bodies (also used by _build_rules.py).
RULE_DEFS: list[tuple[str, str]] = [
    (
        "R1_PrimeLowRisk",
        "CreditApplication(?app), hasApplicant(?app, ?a), PrimeApplicant(?a), "
        "emittedSignal(?app, ?s), CreditScoreSignal(?s), "
        "signalValue(?s, ?v), greaterThanOrEqual(?v, 0.8) "
        "-> hasRiskTier(?app, LowRiskApplication)",
    ),
    (
        "R2a_SubprimeHighRisk",
        "CreditApplication(?app), hasApplicant(?app, ?a), SubprimeApplicant(?a) "
        "-> hasRiskTier(?app, HighRiskApplication)",
    ),
    (
        "R2b_WeakSignalHighRisk",
        "CreditApplication(?app), emittedSignal(?app, ?s), CreditScoreSignal(?s), "
        "signalValue(?s, ?v), lessThan(?v, 0.3) "
        "-> hasRiskTier(?app, HighRiskApplication)",
    ),
    (
        "R3_HighRiskDecline",
        "CreditApplication(?app), hasRiskTier(?app, HighRiskApplication) "
        "-> hasDecision(?app, Decline)",
    ),
    (
        "R4_LowRiskApprove",
        "CreditApplication(?app), hasRiskTier(?app, LowRiskApplication), "
        "emittedSignal(?app, ?es), EmploymentStabilitySignal(?es), "
        "signalValue(?es, ?ev), greaterThanOrEqual(?ev, 0.7), "
        "requestedAmount(?app, ?amt), lessThanOrEqual(?amt, 100000) "
        "-> hasDecision(?app, Approve)",
    ),
]


def define_swrl_rules(owlready2, onto):
    """Declare R1, R2a, R2b, R3, R4 in `onto` (R5 is post-hoc SPARQL).

    Rules follow SPEC §6 verbatim. Pellet fires forward-chaining; class atoms
    on the antecedent require Pellet to have classified instances first
    (which it does in the same pass).
    """
    declared = []
    with onto:
        for name, body in RULE_DEFS:
            r = owlready2.Imp()
            r.set_as_rule(body)
            declared.append((name, body))
    return declared


def export_world_to_rdflib(owlready2, world) -> Graph:
    """Serialize owlready2 world (post-reasoning) to a fresh rdflib Graph."""
    tmp = tempfile.NamedTemporaryFile(suffix=".rdf", delete=False)
    world.save(file=tmp.name, format="rdfxml")
    g = Graph()
    g.parse(tmp.name, format="xml")
    return g


def apply_r5_default_review(g: Graph) -> int:
    """SPARQL UPDATE — assign :Review to applications without any decision.

    Returns the number of decisions added.
    """
    before = len(list(g.triples((None, NS.hasDecision, None))))
    g.update("""
        PREFIX : <https://nikko.dev/ontology/credit#>
        INSERT { ?app :hasDecision :Review }
        WHERE {
            ?app a ?type .
            FILTER (?type IN (:CreditApplication, :MortgageApplication,
                              :PersonalLoanApplication, :AutoLoanApplication))
            FILTER NOT EXISTS { ?app :hasDecision ?d }
        }
    """)
    after = len(list(g.triples((None, NS.hasDecision, None))))
    return after - before


def summarize(g: Graph) -> dict[str, int]:
    """Quick tally of inferred predicates of interest."""
    counts: dict[str, int] = {}
    for tier in ("LowRiskApplication", "MediumRiskApplication", "HighRiskApplication"):
        q = f"SELECT (COUNT(?app) AS ?n) WHERE {{ ?app <{NS_STR}hasRiskTier> <{NS_STR}{tier}> }}"
        n = int(next(iter(g.query(q)))[0])
        counts[f"hasRiskTier→{tier}"] = n
    for d in ("Approve", "Review", "Decline"):
        q = f"SELECT (COUNT(?app) AS ?n) WHERE {{ ?app <{NS_STR}hasDecision> <{NS_STR}{d}> }}"
        n = int(next(iter(g.query(q)))[0])
        counts[f"hasDecision→{d}"] = n
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tbox", default="ontology/credit_risk.ttl")
    parser.add_argument(
        "--abox",
        action="append",
        default=[
            "ontology/instances/customers.ttl",
            "ontology/instances/applications.ttl",
        ],
    )
    parser.add_argument(
        "--output", default="ontology/inferred.ttl", help="Where to write the materialized graph"
    )
    parser.add_argument(
        "--apply-r5", action="store_true", help="Apply the R5 SPARQL UPDATE (default → :Review)"
    )
    parser.add_argument(
        "--print-summary", action="store_true", help="Print a tier+decision tally after reasoning"
    )
    args = parser.parse_args()

    project = Path(__file__).resolve().parent.parent
    tbox = project / args.tbox
    aboxes = [project / a for a in args.abox]
    out = project / args.output

    print("→ Loading T-Box + A-Box via rdflib...")
    g = load_combined(tbox, *aboxes)
    print(f"  ✓ {len(g)} input triples")

    print("→ Converting to RDF/XML for owlready2...")
    rdfxml = to_rdfxml_tempfile(g)

    print("→ Loading into owlready2 world...")
    owlready2 = setup_owlready2()
    world = owlready2.World()
    onto = world.get_ontology(f"file://{rdfxml}").load()

    print("→ Declaring SWRL rules R1-R4...")
    rules = define_swrl_rules(owlready2, onto)
    for name, _ in rules:
        print(f"  ✓ {name}")

    print("→ Running Pellet (this can take ~10-30s)...")
    with onto:
        owlready2.sync_reasoner_pellet(world, infer_property_values=True, debug=0)
    print("  ✓ Pellet done")

    print("→ Exporting reasoned world back to rdflib...")
    g_out = export_world_to_rdflib(owlready2, world)
    print(f"  ✓ {len(g_out)} output triples")

    if args.apply_r5:
        added = apply_r5_default_review(g_out)
        print(f"→ R5 SPARQL UPDATE: added {added} :Review decisions")

    if args.print_summary:
        print("\nSummary:")
        for k, v in summarize(g_out).items():
            print(f"  {k:36}  {v}")

    out.parent.mkdir(parents=True, exist_ok=True)
    g_out.serialize(destination=str(out), format="turtle")
    # Show repo-relative path so notebook outputs don't leak absolute host paths
    try:
        shown = out.relative_to(project)
    except ValueError:
        shown = out
    print(f"\n✓ Wrote {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
