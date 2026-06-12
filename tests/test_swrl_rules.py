"""Structural tests over rules.swrl.owl (RDF/XML). No reasoner needed."""

from pathlib import Path

from rdflib import RDF, Graph, Namespace

ROOT = Path(__file__).resolve().parent.parent
SWRL = Namespace("http://www.w3.org/2003/11/swrl#")


def load_rules() -> Graph:
    g = Graph()
    g.parse(str(ROOT / "ontology" / "rules.swrl.owl"), format="xml")
    return g


def test_exactly_five_rules():
    # R1, R2a, R2b, R3, R4. R5 is deliberately a SPARQL UPDATE
    # (SWRL has no negation-as-failure), so it must NOT appear here.
    g = load_rules()
    imps = set(g.subjects(RDF.type, SWRL.Imp))
    assert len(imps) == 5


def test_every_rule_has_body_and_head():
    g = load_rules()
    for imp in g.subjects(RDF.type, SWRL.Imp):
        assert (imp, SWRL.body, None) in g
        assert (imp, SWRL.head, None) in g
