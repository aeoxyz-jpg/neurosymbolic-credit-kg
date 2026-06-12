"""Builder for ontology/rules.swrl.owl.

Generates an OWL/XML file containing only the SWRL rules R1..R4. The file
imports the T-Box ontology so it's loadable standalone.

Pattern: declare rules under the T-Box's `with` context (so entity name lookup
finds CreditApplication etc.) but assign them via `Imp(namespace=rules_onto)`
so they serialize to the rules ontology, not the T-Box.

Run: .venv/bin/python scripts/_build_rules.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rdflib import Graph
from run_reasoner import RULE_DEFS, setup_owlready2  # noqa: E402


def main() -> int:
    project = Path(__file__).resolve().parent.parent
    tbox = project / "ontology" / "credit_risk.ttl"
    out = project / "ontology" / "rules.swrl.owl"

    g = Graph()
    g.parse(str(tbox), format="turtle")
    tmp = tempfile.NamedTemporaryFile(suffix=".owl", delete=False)
    g.serialize(destination=tmp.name, format="xml")

    owlready2 = setup_owlready2()
    world = owlready2.World()
    tbox_onto = world.get_ontology(f"file://{tmp.name}").load()

    rules_onto = world.get_ontology("https://nikko.dev/ontology/credit/rules#")
    rules_onto.imported_ontologies.append(tbox_onto)

    # Declare rules in `rules_onto` (so they serialize there) but pass the
    # T-Box namespace explicitly so set_as_rule can resolve CreditApplication.
    with rules_onto:
        for _name, body in RULE_DEFS:
            r = owlready2.Imp()
            r.set_as_rule(body, namespaces=[tbox_onto, rules_onto])

    rules_onto.save(file=str(out), format="rdfxml")
    print(f"✓ Wrote {out}  ({out.stat().st_size} bytes, {len(RULE_DEFS)} rules)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
