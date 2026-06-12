"""Phase C checkpoint per SPEC §9.

Checks:
  1. shapes.ttl + rules.swrl.owl exist
  2. pySHACL on the clean A-Box → 0 violations
  3. pySHACL on a deliberately-bad fixture → catches the expected violation
  4. Pellet + SWRL R1-R4 produces hasRiskTier and hasDecision triples
  5. R5 SPARQL UPDATE adds :Review to every undecided application
  6. No application ends up with two contradicting decisions (disjointness held)
  7. NB03 + NB04 executed cleanly (relies on saved outputs;
     pass --execute to re-run them now)

Dependencies: rdflib, pyshacl, owlready2.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import nbformat
from rdflib import Graph, Namespace

NS_STR = "https://nikko.dev/ontology/credit#"
NS = Namespace(NS_STR)


def check(label: str, ok: bool, detail: str = "") -> bool:
    icon = "✓" if ok else "✗"
    suffix = f" — {detail}" if detail else ""
    print(f"  {icon} {label}{suffix}")
    return ok


def shacl_validate(data_graph: Graph, shapes_graph: Graph) -> tuple[bool, str]:
    from pyshacl import validate

    conforms, _, text = validate(
        data_graph=data_graph,
        shacl_graph=shapes_graph,
        inference="rdfs",
        advanced=True,
        debug=False,
    )
    return conforms, text


def run_reasoner_and_capture() -> Graph:
    """Run reasoner pipeline in-process so we can inspect the result Graph."""
    sys.path.insert(0, str(Path(__file__).parent))
    from run_reasoner import (
        apply_r5_default_review,
        define_swrl_rules,
        export_world_to_rdflib,
        load_combined,
        setup_owlready2,
        to_rdfxml_tempfile,
    )

    project = Path(__file__).resolve().parent.parent
    g = load_combined(
        project / "ontology" / "credit_risk.ttl",
        project / "ontology" / "instances" / "customers.ttl",
        project / "ontology" / "instances" / "applications.ttl",
    )
    rdfxml = to_rdfxml_tempfile(g)
    owlready2 = setup_owlready2()
    world = owlready2.World()
    onto = world.get_ontology(f"file://{rdfxml}").load()
    define_swrl_rules(owlready2, onto)
    with onto:
        owlready2.sync_reasoner_pellet(world, infer_property_values=True, debug=0)
    g_out = export_world_to_rdflib(owlready2, world)
    apply_r5_default_review(g_out)
    return g_out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Re-execute NB03+NB04 (slow). Default: inspect saved outputs.",
    )
    args = parser.parse_args()

    project = Path(__file__).resolve().parent.parent
    shapes_path = project / "ontology" / "shapes.ttl"
    rules_path = project / "ontology" / "rules.swrl.owl"
    nb3 = project / "notebooks" / "03_shacl_validation.ipynb"
    nb4 = project / "notebooks" / "04_swrl_credit_rules.ipynb"

    print("Phase C verification\n")
    passed = []

    # 1. Files exist
    passed.append(check("shapes.ttl exists", shapes_path.exists()))
    passed.append(check("rules.swrl.owl exists", rules_path.exists()))
    passed.append(check("NB03 exists", nb3.exists()))
    passed.append(check("NB04 exists", nb4.exists()))
    if not all(passed):
        return 1

    # 2. SHACL on clean fixture → 0 violations
    data = Graph()
    for f in ["credit_risk.ttl", "instances/customers.ttl", "instances/applications.ttl"]:
        data.parse(str(project / "ontology" / f), format="turtle")
    shapes = Graph()
    shapes.parse(str(shapes_path), format="turtle")
    ok, report = shacl_validate(data, shapes)
    passed.append(check("SHACL clean fixture → conforms", ok, "" if ok else report[:300]))

    # 3. SHACL on bad fixture → caught
    bad = Graph()
    for t in data:
        bad.add(t)
    bad.add((NS.App_M01, NS.hasDecision, NS.Approve))
    bad.add((NS.App_M01, NS.hasDecision, NS.Decline))  # cardinality violation
    ok_bad, _ = shacl_validate(bad, shapes)
    passed.append(
        check(
            "SHACL catches multi-decision fixture",
            not ok_bad,
            "got 0 violations" if ok_bad else "violations reported",
        )
    )

    # 4-6. Reasoner output
    print("  → Running reasoner (10-30s)...")
    try:
        g_out = run_reasoner_and_capture()
    except Exception as exc:
        passed.append(check("Reasoner runs", False, str(exc)[:200]))
        return 1
    passed.append(check("Reasoner runs", True, f"{len(g_out)} triples"))

    risk_low = len(list(g_out.triples((None, NS.hasRiskTier, NS.LowRiskApplication))))
    risk_high = len(list(g_out.triples((None, NS.hasRiskTier, NS.HighRiskApplication))))
    passed.append(check("≥1 :LowRiskApplication tier", risk_low >= 1, f"{risk_low} apps"))
    passed.append(check("≥1 :HighRiskApplication tier", risk_high >= 1, f"{risk_high} apps"))

    decision_review = len(list(g_out.triples((None, NS.hasDecision, NS.Review))))
    passed.append(
        check("R5 added :Review decisions", decision_review > 0, f"{decision_review} Review")
    )

    # Every application has at least one decision
    n_apps = sum(
        1
        for s in g_out.query(f"""
        SELECT DISTINCT ?app WHERE {{
          ?app a ?t .
          FILTER (?t IN (<{NS_STR}CreditApplication>, <{NS_STR}MortgageApplication>,
                         <{NS_STR}PersonalLoanApplication>, <{NS_STR}AutoLoanApplication>))
        }}
    """)
    )
    n_with_decision = sum(
        1
        for s in g_out.query(f"""
        SELECT DISTINCT ?app WHERE {{ ?app <{NS_STR}hasDecision> ?d }}
    """)
    )
    passed.append(
        check(
            "Every application has a decision",
            n_apps == n_with_decision,
            f"{n_with_decision}/{n_apps}",
        )
    )

    # No application has two contradicting decisions (functional + disjoint)
    contradictions = list(
        g_out.query(f"""
        SELECT ?app ?d1 ?d2 WHERE {{
          ?app <{NS_STR}hasDecision> ?d1 .
          ?app <{NS_STR}hasDecision> ?d2 .
          FILTER (?d1 != ?d2)
        }}
    """)
    )
    passed.append(
        check(
            "No contradicting decisions",
            len(contradictions) == 0,
            f"{len(contradictions)} contradictions",
        )
    )

    # 7. Notebooks
    for nb_path, label in [(nb3, "NB03"), (nb4, "NB04")]:
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
                f"/tmp/_verify_{nb_path.stem}.ipynb",
                str(nb_path),
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            passed.append(
                check(
                    f"{label} executes clean",
                    r.returncode == 0,
                    r.stderr.splitlines()[-1] if r.stderr else "OK",
                )
            )
        else:
            nb = nbformat.read(nb_path, as_version=4)
            errors = [
                o
                for c in nb.cells
                if c.cell_type == "code"
                for o in c.get("outputs", [])
                if o.get("output_type") == "error"
            ]
            passed.append(
                check(
                    f"{label} saved output has no errors",
                    not errors,
                    f"{len(errors)} errors" if errors else "clean",
                )
            )

    print()
    if all(passed):
        print("Phase C: ALL CHECKS PASSED ✓")
        return 0
    failed = sum(1 for p in passed if not p)
    print(f"Phase C: {failed} check(s) failed ✗")
    return 1


if __name__ == "__main__":
    sys.exit(main())
