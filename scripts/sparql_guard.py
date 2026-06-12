"""Whitelist validator for LLM-generated SPARQL.

Rejects queries that (a) fail to parse, or (b) reference any IRI in the
project namespace that is not a declared property, class, or individual.
This is the symbolic gate between LLM output and the triple store.

Usage:
    from sparql_guard import validate_sparql
    ok, reason = validate_sparql(query, whitelist, tbox_graph)

Dependencies: rdflib.
"""

from __future__ import annotations

import re

from rdflib import OWL, RDF, Graph
from rdflib.plugins.sparql import prepareQuery


def validate_sparql(query: str, whitelist: set[str], tbox: Graph) -> tuple[bool, str]:
    """Returns (ok, reason). Fails if syntax is broken OR any project-namespace
    IRI is not whitelisted."""
    try:
        prepareQuery(query)
    except Exception as e:
        return False, f"syntax: {type(e).__name__}"
    prefixes = dict(re.findall(r"PREFIX\s+(\w*):\s*<([^>]+)>", query))
    # Strip out PREFIX declarations before scanning for IRI usage, otherwise
    # the namespace IRI itself shows up as "unknown".
    body = re.sub(r"PREFIX\s+\w*:\s*<[^>]+>", "", query)
    iris = set(re.findall(r"<(https?://[^>]+)>", body))
    iris_resolved = set()
    for prefix, local in re.findall(r"(?:^|\s)(\w*):([A-Za-z_][\w-]*)", body):
        if prefix in prefixes:
            iris_resolved.add(prefixes[prefix] + local)
    classes = {str(c) for c in tbox.subjects(RDF.type, OWL.Class)}
    indivs = {str(i) for i in tbox.subjects(RDF.type, OWL.NamedIndividual)}
    allowed = whitelist | classes | indivs | {"http://www.w3.org/1999/02/22-rdf-syntax-ns#type"}
    unknown = [
        iri
        for iri in (iris | iris_resolved)
        if iri.startswith("https://nikko.dev") and iri not in allowed
    ]
    if unknown:
        return False, f"unknown predicates/classes: {unknown[:2]}"
    return True, "ok"
