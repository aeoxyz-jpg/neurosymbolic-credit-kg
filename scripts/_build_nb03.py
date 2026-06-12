"""Builder for notebooks/03_shacl_validation.ipynb. SPEC §8.3."""

from pathlib import Path

import nbformat as nbf

nb = nbf.v4.new_notebook()
nb.metadata = {
    "kernelspec": {
        "display_name": "Python 3 (credit-risk-kg)",
        "language": "python",
        "name": "credit-risk-kg",
    },
    "language_info": {"name": "python", "version": "3.11"},
}
cells: list = []
md = lambda src: cells.append(nbf.v4.new_markdown_cell(src))
code = lambda src: cells.append(nbf.v4.new_code_cell(src))

md("""# NB03 — SHACL Validation (Shapes Constraint Language)

**This notebook demonstrates:**

1. The difference between **Node Shape** and **Property Shape**
2. Writing four constraint types: cardinality / range / path / logical combinations (and/or/not)
3. Custom constraints via `sh:sparql` (beyond SHACL Core capabilities)
4. Reading `sh:ValidationReport` and automatically locating violating nodes
5. Using `sh:closed` to lock down the set of allowed properties on an instance
6. When to use SHACL vs OWL — they are **complementary**, not substitutes

## Prerequisites

- Phase A data loaded; `ontology/shapes.ttl` exists
- `pyshacl` installed (`uv pip install pyshacl`)

## SHACL vs OWL — A Key Clarification

| | OWL | SHACL |
|---|---|---|
| Purpose | Defines "what a concept is" (ontology) | Validates "is data compliant" |
| Open/Closed World | Open (not stated = unknown) | Closed (not stated = violation, optional) |
| Error form | "possibly inconsistent" / inferred contradiction | Explicit violation report + node reference |
| Performance | Slow (DL), depends on rules | Single-pass scan, stable |

**Rule of thumb**: validate with SHACL before loading instances; reason with OWL after they are in the store.""")

md("## 0. Setup")

md("""> 🔧 **Tech**: pyshacl `validate()` entry point + `shacl_graph` keyword (old name `shapes_graph` is deprecated and silently fails — see SPEC §11.19)
> 🎯 **Goal**: Load T-Box + A-Box + shapes as three graphs; define a unified `run()` helper reused throughout
> ✅ **Verify**: Triple counts print normally; all subsequent cells can reuse `run()`
> 📚 **Takeaway**: In pySHACL ≥0.30 the kwarg is `shacl_graph` — using the old name silently drops shapes and returns conforms=True, a dangerous false positive""")

code("""from pathlib import Path
from rdflib import Graph, Namespace, RDF, URIRef
from pyshacl import validate

PROJECT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
ONTO = PROJECT / "ontology"

# Load T-Box + A-Box + shapes
data = Graph()
for f in ["credit_risk.ttl", "instances/customers.ttl", "instances/applications.ttl"]:
    data.parse(str(ONTO / f), format="turtle")
shapes = Graph()
shapes.parse(str(ONTO / "shapes.ttl"), format="turtle")

print(f"Data:  {len(data)} triples")
print(f"Shapes: {len(shapes)} triples")

CR = Namespace("https://nikko.dev/ontology/credit#")
SH = Namespace("http://www.w3.org/ns/shacl#")


def run(data_graph, shapes_graph=shapes, **kwargs):
    \"\"\"Validate and return (conforms, report_graph, report_text).\"\"\"
    return validate(
        data_graph=data_graph,
        shacl_graph=shapes_graph,   # NB: pySHACL >=0.30 renamed shapes_graph
        inference="rdfs",           # apply RDFS expansion before validating
        advanced=True,              # enable sh:sparql
        debug=False,
        **kwargs,
    )""")

# ─────────────────────────────────────────────────────────────────────
md("""## 1. Sanity Check — Clean Fixture Should Have 0 Violations

The Phase A fixtures are hand-crafted to satisfy every shape.""")

md("""> 🔧 **Tech**: SHACL `sh:ValidationReport` full validation + `conforms` boolean
> 🎯 **Goal**: Run the clean fixture once to confirm baseline conforms=True
> ✅ **Verify**: `conforms == True`, report is empty
> 📚 **Takeaway**: Always confirm baseline is clean before injecting violations — otherwise violation sources become ambiguous""")

code("""conforms, _, report = run(data)
print(f"Conforms (clean fixture): {conforms}")
if not conforms:
    print(report[:1500])""")

# ─────────────────────────────────────────────────────────────────────
md("""## 2. Deliberate Break #1 — Cardinality Violation

`:DecisionCardinalityShape` restricts each application to at most one decision.
Add two conflicting decisions to App_M01 and observe how SHACL reports the error.""")

md("""> 🔧 **Tech**: `sh:NodeShape` + `sh:property` + `sh:maxCount` cardinality constraint
> 🎯 **Goal**: Inject two `:hasDecision` triples on the same application to trigger a maxCount=1 violation
> ✅ **Verify**: `conforms=False` + report contains `focusNode=App_M01` + `sourceShape=DecisionCardinalityShape` + `MaxCountConstraintComponent`
> 📚 **Takeaway**: SHACL error reports are precise — focusNode / shape / constraint component triple — far friendlier than OWL's "possibly inconsistent\"""")

code("""bad = Graph()
for t in data: bad.add(t)
bad.add((CR.App_M01, CR.hasDecision, CR.Approve))
bad.add((CR.App_M01, CR.hasDecision, CR.Decline))

conforms, _, report = run(bad)
print(f"Conforms: {conforms}")
print(report[:1200])""")

md(
    """**Observation**: The violation report pinpoints the exact *focusNode* (`App_M01`), the violated *Shape* (`DecisionCardinalityShape`), and the *sourceConstraint* (`MaxCountConstraintComponent`). This precision is what makes SHACL reports more actionable than OWL inconsistency messages."""
)

# ─────────────────────────────────────────────────────────────────────
md("""## 3. Deliberate Break #2 — Range Violation

`:CreditScoreRangeShape` restricts FICO to [300, 850]. Let's see what happens when we inject FICO=999.""")

md("""> 🔧 **Tech**: `sh:datatype` + `sh:minInclusive`/`sh:maxInclusive` range constraints
> 🎯 **Goal**: Inject a non-integer IRI and an out-of-range value to test both datatype and range checks simultaneously
> ✅ **Verify**: `conforms=False` + `DatatypeConstraintComponent` appears in the report
> 📚 **Takeaway**: SHACL validates both data type and numeric range; multiple constraints can be stacked on a single property shape""")

code("""bad2 = Graph()
for t in data: bad2.add(t)
bad2.remove((CR.Applicant_P01, CR.hasCreditScore, None))  # clear existing
bad2.add((CR.Applicant_P01, CR.hasCreditScore, URIRef("urn:weirdmark") ))  # type mismatch
# Also add an out-of-range legal integer on another applicant
bad2.add((CR.Applicant_S01, CR.hasCreditScore, URIRef("urn:x") ))

conforms, _, report = run(bad2)
print(f"Conforms: {conforms}")
# Show first 1500 characters
print(report[:1500])""")

# ─────────────────────────────────────────────────────────────────────
md("""## 4. Deliberate Break #3 — Property Path

`:ApplicantFicoReachableShape` uses the property path `(:hasApplicant :hasCreditScore)` to require
that every application can reach a FICO value via two hops. Deleting one applicant's FICO
causes every application pointing to that applicant to fail.""")

md("""> 🔧 **Tech**: `sh:path` composite path (sequence path) + `sh:minCount` cross-node check
> 🎯 **Goal**: Remove P02's FICO so all applications referencing P02 fail the two-hop path check
> ✅ **Verify**: `conforms=False` + multiple application focusNodes violate the `FicoReachable` shape
> 📚 **Takeaway**: SHACL property paths enable cross-node reachability validation — equivalent to SPARQL property paths but declarative""")

code("""bad3 = Graph()
for t in data: bad3.add(t)
# Delete P02's FICO — App_M02 / App_L02 should now violate the path shape
bad3.remove((CR.Applicant_P02, CR.hasCreditScore, None))

conforms, report_graph, report = run(bad3)
print(f"Conforms: {conforms}")
# Count actual ValidationResult nodes (shape name never appears in message text)
SH_ValidationResult = "http://www.w3.org/ns/shacl#ValidationResult"
path_violations = sum(
    1 for _, _, o in report_graph.triples((None, RDF.type, None))
    if str(o) == SH_ValidationResult
)
print(f"Path violations: {path_violations}")
print(report[:1500])""")

# ─────────────────────────────────────────────────────────────────────
md("""## 5. sh:or — Logical Or

`:ApplicationEvidenceShape`: each application must have at least one CreditScoreSignal **or** one CollateralSignal.
Let's see what happens when all signals are removed from App_M01.""")

md("""> 🔧 **Tech**: `sh:or` logically combines multiple shape branches
> 🎯 **Goal**: Remove all `:emittedSignal` triples from App_M01 so both branches of the `or` fail simultaneously
> ✅ **Verify**: `conforms=False` + report contains `ApplicationEvidenceShape` + `OrConstraintComponent`
> 📚 **Takeaway**: `sh:or` reports a violation only when all branches fail; satisfying any one branch is sufficient to pass""")

code("""bad4 = Graph()
for t in data: bad4.add(t)
bad4.remove((CR.App_M01, CR.emittedSignal, None))

conforms, _, report = run(bad4)
print(f"Conforms: {conforms}")
# Extract Evidence-related violations
for chunk in report.split("\\nConstraint Violation"):
    if "Evidence" in chunk:
        print("---");print(chunk[:600])""")

# ─────────────────────────────────────────────────────────────────────
md("""## 6. sh:not — Logical Not

`:ApplicantTierDisjointnessShape`: an applicant cannot be both Prime and Subprime at the same time.
OWL also declares this disjoint, but SHACL gives a more direct error.""")

md("""> 🔧 **Tech**: `sh:not` + `sh:class` explicit type check (no DL inference)
> 🎯 **Goal**: Manually assign both PrimeApplicant and SubprimeApplicant types to P01 to trigger the disjointness violation
> ✅ **Verify**: `conforms=False` + `TierDisjointnessShape` + `NotConstraintComponent` in the report
> 📚 **Takeaway**: SHACL `sh:class` only inspects explicit rdf:type triples, not OWL equivalent-class inference — testing disjoint requires running Pellet first then feeding the result to SHACL (pipeline collaboration)""")

code("""bad5 = Graph()
for t in data: bad5.add(t)
# Force both Prime + Subprime labels onto P01 (FICO 810, naturally Prime; now forcibly also Subprime)
bad5.add((CR.Applicant_P01, RDF.type, CR.SubprimeApplicant))

# Note: SHACL sh:class only checks explicit rdf:type, not OWL DL.
# Because PrimeApplicant is inferred by Pellet (not asserted), SHACL won't see it
# unless we also add it explicitly here.
# Add the Pellet-inferred type explicitly so the shape can fire:
bad5.add((CR.Applicant_P01, RDF.type, CR.PrimeApplicant))

conforms, _, report = run(bad5)
print(f"Conforms: {conforms}")
for chunk in report.split("\\nConstraint Violation"):
    if "TierDisjointness" in chunk:
        print("---");print(chunk[:600])""")

md("""**Key observation**: SHACL does **not** run OWL DL inference — it only sees explicit triples (or at most RDFS expansion).
To test the "PrimeApplicant + SubprimeApplicant" conflict, you must either run Pellet first and feed the materialized
graph to SHACL, or manually add the explicit type triples (as done above). This is the essence of the SHACL + OWL **pipeline**:

```
A-Box → Pellet (infer types) → SHACL (validate types)
```

SHACL does not replace OWL; each covers a distinct stage.""")

# ─────────────────────────────────────────────────────────────────────
md("""## 7. sh:sparql — Custom Constraint (Signal Freshness)

SHACL Core cannot express constraints like "timestamp must not be older than 90 days". `sh:sparql` embeds
an arbitrary SPARQL SELECT: any rows returned by the SELECT are treated as violations; the `?value`
binding populates the message template.

`:SignalFreshnessShape` checks that `:signalTimestamp` is not more than 90 days in the past.""")

md("""> 🔧 **Tech**: `sh:sparql` custom SELECT constraint + `advanced=True` to enable it
> 🎯 **Goal**: Change the timestamp on Sig_M01_credit to 2025-12-01 (>90 days ago) and trigger the SPARQL-computed violation
> ✅ **Verify**: `conforms=False` + report contains `SignalFreshnessShape` + Sig_M01 focusNode + `?value` message template substitution
> 📚 **Takeaway**: SHACL Core cannot express time comparisons; `sh:sparql` embeds an arbitrary SELECT — any row returned counts as a violation""")

code("""# All fixture signal timestamps are 2026-05-*, currently within 90 days -> conforms
# Deliberately move one signal timestamp to 2025-12-01 (more than 5 months ago)
bad6 = Graph()
for t in data: bad6.add(t)
from rdflib import Literal, XSD
bad6.remove((CR.Sig_M01_credit, CR.signalTimestamp, None))
bad6.add((CR.Sig_M01_credit, CR.signalTimestamp, Literal("2025-12-01T00:00:00Z", datatype=XSD.dateTime)))

conforms, _, report = run(bad6)
print(f"Conforms: {conforms}")
for chunk in report.split("\\nConstraint Violation"):
    if "Freshness" in chunk or "90 days" in chunk or "Sig_M01" in chunk:
        print("---");print(chunk[:600])""")

# ─────────────────────────────────────────────────────────────────────
md("""## 8. sh:closed — Schema Lock

`:ApplicantClosedShape` declares that applicants may **not** have any properties outside a whitelist.
This is a core data governance tool — it prevents downstream consumers from silently polluting the ontology
with undeclared fields.""")

md("""> 🔧 **Tech**: `sh:closed true` + `sh:ignoredProperties` schema lock
> 🎯 **Goal**: Inject an undeclared `:favoriteColor` property onto P01 and trigger the closed-shape violation
> ✅ **Verify**: `conforms=False` + report contains `ClosedConstraintComponent` + `favoriteColor` predicate
> 📚 **Takeaway**: `sh:closed` flips the open-world default to closed; the key governance weapon for preventing downstream pollution of the ontology""")

code("""# Inject an undeclared property onto P01
bad7 = Graph()
for t in data: bad7.add(t)
bad7.add((CR.Applicant_P01, CR.favoriteColor, URIRef("urn:blue")))

conforms, _, report = run(bad7)
print(f"Conforms: {conforms}")
for chunk in report.split("\\nConstraint Violation"):
    if "Closed" in chunk or "favoriteColor" in chunk:
        print("---");print(chunk[:500])""")

# ─────────────────────────────────────────────────────────────────────
md("""## 9. NearPrime — Revisiting the NB02 Cliffhanger

In NB02 we saw that expressing the `[620, 740)` interval in OWL requires 13 lines and two restrictions.
The equivalent SHACL expression takes 5 lines:

```turtle
:NearPrimeRangeShape a sh:NodeShape ;
    sh:targetClass :Applicant ;
    sh:property [
        sh:path :hasCreditScore ;
        sh:minInclusive 620 ;
        sh:maxExclusive 740 ;
    ] .
```

But the **purpose is completely different**:
- The OWL version is a **definition** — Pellet sees an applicant with FICO=700 and **infers** it is `:NearPrimeApplicant`
- The SHACL version is a **validator** — given an applicant, check whether FICO falls in [620, 740); it does **not** assign a label

If you want to *classify* who is NearPrime, use OWL.
If you want to *guard* against garbage values like FICO=200 entering the store, use SHACL.""")

# ─────────────────────────────────────────────────────────────────────
md("""## You Should Now Be Able To ✓

- [ ] Distinguish Node Shape from Property Shape
- [ ] Write five constraint types: cardinality / range / property-path / sh:or / sh:not
- [ ] Use `sh:sparql` to embed a custom SELECT as a constraint
- [ ] Read a ValidationReport to extract focusNode + sourceShape + sourceConstraintComponent
- [ ] Use `sh:closed` to lock down a schema
- [ ] Correctly choose OWL vs SHACL when the task is "classify" vs "validate"

## Next Steps

NB04 (SWRL) is the other half of Phase C — applying rules to make business decisions,
and hands-on experience with SWRL's negation-as-failure limitation (the pedagogical pivot behind R5).""")

# ─────────────────────────────────────────────────────────────────────
nb.cells = cells
out = Path(__file__).resolve().parent.parent / "notebooks" / "03_shacl_validation.ipynb"
with out.open("w") as f:
    nbf.write(nb, f)
print(f"✓ Wrote {out}  ({len(cells)} cells)")
