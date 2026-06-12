"""SHACL constraint tests via pySHACL. No Fuseki, no Java."""

from pathlib import Path

from pyshacl import validate
from rdflib import Graph, Namespace

ROOT = Path(__file__).resolve().parent.parent
NS = Namespace("https://nikko.dev/ontology/credit#")


def load_graphs() -> tuple[Graph, Graph]:
    data = Graph()
    for f in ("credit_risk.ttl", "instances/customers.ttl", "instances/applications.ttl"):
        data.parse(str(ROOT / "ontology" / f), format="turtle")
    shapes = Graph()
    shapes.parse(str(ROOT / "ontology" / "shapes.ttl"), format="turtle")
    return data, shapes


def run_shacl(data: Graph, shapes: Graph) -> tuple[bool, str]:
    # kwarg MUST be shacl_graph — the legacy shapes_graph kwarg is silently
    # ignored by modern pySHACL and everything "conforms" vacuously.
    conforms, _, text = validate(
        data_graph=data,
        shacl_graph=shapes,
        inference="rdfs",
        advanced=True,
    )
    return conforms, text


def test_clean_data_conforms():
    data, shapes = load_graphs()
    conforms, text = run_shacl(data, shapes)
    assert conforms, text[:500]


def test_contradictory_decisions_are_caught():
    data, shapes = load_graphs()
    data.add((NS.App_M01, NS.hasDecision, NS.Approve))
    data.add((NS.App_M01, NS.hasDecision, NS.Decline))
    conforms, text = run_shacl(data, shapes)
    assert not conforms
    # Guard: prove the shapes actually saw the bad triples, not a silent no-op.
    assert "hasDecision" in text
