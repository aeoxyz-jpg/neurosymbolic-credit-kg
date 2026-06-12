"""Ontology + instance-data sanity tests. Pure rdflib — no Fuseki, no Java."""

from pathlib import Path

from rdflib import RDF, Graph, Namespace

ROOT = Path(__file__).resolve().parent.parent
NS = Namespace("https://nikko.dev/ontology/credit#")


def load(*names: str) -> Graph:
    g = Graph()
    for n in names:
        g.parse(str(ROOT / "ontology" / n), format="turtle")
    return g


def test_tbox_parses_and_is_nontrivial():
    g = load("credit_risk.ttl")
    assert len(g) >= 300


def test_at_least_20_applicants():
    g = load("instances/customers.ttl")
    applicants = set(g.subjects(RDF.type, NS.Applicant))
    assert len(applicants) >= 20


def test_at_least_30_applications():
    g = load("instances/applications.ttl")
    apps = set()
    for cls in (
        NS.MortgageApplication,
        NS.AutoLoanApplication,
        NS.PersonalLoanApplication,
        NS.CreditApplication,
    ):
        apps |= set(g.subjects(RDF.type, cls))
    assert len(apps) >= 30


def test_at_least_50_emitted_signals():
    g = load("instances/applications.ttl")
    signals = list(g.triples((None, NS.emittedSignal, None)))
    assert len(signals) >= 50
