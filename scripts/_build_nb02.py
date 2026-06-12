"""Builder for notebooks/02_owl_inference.ipynb.

Run: .venv/bin/python scripts/_build_nb02.py
"""

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

md("""# NB02 — OWL Inference: RL vs DL

## Goals

1. Understand the three core concepts: T-Box / A-Box / materialization
2. Use **Jena OWL RL** to demonstrate `rdfs:subClassOf` transitivity, property characteristics (transitive/functional), and disjointness
3. Use **Pellet (via owlready2)** to demonstrate equivalent class auto-classification — `:PrimeApplicant` etc.
4. See firsthand: **same A-Box, RL reasoner cannot infer tier, but DL reasoner can** — this is the project's core demo
5. Build intuition for the "RL vs DL vs SHACL vs SWRL" decision framework

## Prerequisites

- Fuseki running with ontology loaded (NB01 passing is sufficient)
- Java 25+ on PATH (required by Pellet, SPEC §11.1)
- `owlready2` installed (`uv pip install owlready2`)

## Kernel Reset

Pellet modifies owlready2's world state. **If re-executing Part B, either restart the kernel or use a fresh `World()` instance.**""")

# ─────────────────────────────────────────────────────────────────────
md("## 0. Setup — Environment Check")

md("""> **🔧 Tech**: Pre-flight checks for Java runtime + ontology files
> **🎯 Goal**: Confirm Java 25+ is present and all three Turtle files exist
> **✅ Verify**: Java version string + three checkmark lines
> **📚 Takeaway**: Pellet requires Java 24+ (class file v69); LTS 21 is insufficient — SPEC §11.1""")

code("""import os
import subprocess
from pathlib import Path

PROJECT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
ONTO_DIR = PROJECT / "ontology"

# Java check
JAVA = "/opt/homebrew/opt/openjdk/bin/java"
ver = subprocess.run([JAVA, "-version"], capture_output=True, text=True).stderr.splitlines()[0]
print("Java:", ver)
assert "version \\"25" in ver or "version \\"26" in ver or "version \\"24" in ver, "Pellet requires Java 24+ (tested on 25)"

# Project files
for f in ["credit_risk.ttl", "instances/customers.ttl", "instances/applications.ttl"]:
    p = ONTO_DIR / f
    assert p.exists(), f"missing {p}"
    print(f"✓ {p.relative_to(PROJECT)}")""")

# ─────────────────────────────────────────────────────────────────────
md("""## 1. Three Core Concepts

| Concept | Content | In this project |
|---|---|---|
| **T-Box** | Conceptual layer: classes, properties, constraints | `credit_risk.ttl` |
| **A-Box** | Individual layer: concrete instances | `customers.ttl` + `applications.ttl` |
| **Materialization** | Reasoner writes "implicit" triples as "explicit" ones | Main topic of this notebook |

**Two reasoning styles**:
- **OWL 2 RL** (Rule Language): forward-chaining rules, fast, scalable, but limited expressivity
- **OWL 2 DL** (Description Logic): tableau algorithm, slow, not scalable, but expressive (supports datatype facets, equivalent classes, etc.)

Our `:PrimeApplicant` uses `owl:withRestrictions xsd:minInclusive 740` — a **datatype facet** — which **OWL 2 RL does not support**. Pellet (DL) is required.""")

# ─────────────────────────────────────────────────────────────────────
md("""## Part A — What Jena OWL RL Can Do

We use `rdflib` to load the ontology and apply RDFS/OWL-RL inference.""")

md("""> **🔧 Tech**: Load T-Box + A-Box into an in-memory RDF graph
> **🎯 Goal**: Merge three .ttl files into one raw graph as input for subsequent reasoning
> **✅ Verify**: Total triple count printed (should be in the hundreds)
> **📚 Takeaway**: rdflib Graph is the carrier for RL simulation; without reasoning only explicit triples are visible""")

code("""from rdflib import Graph, Namespace, RDF, RDFS, OWL
import rdflib.namespace

CR = Namespace("https://nikko.dev/ontology/credit#")

g_raw = Graph()
for f in ["credit_risk.ttl", "instances/customers.ttl", "instances/applications.ttl"]:
    g_raw.parse(str(ONTO_DIR / f), format="turtle")

print(f"Raw graph: {len(g_raw)} triples")
""")

md("### A.1 — rdfs:subClassOf Transitivity")

md("""> **🔧 Tech**: OWL 2 RL — `rdfs:subClassOf` transitive closure + type promotion
> **🎯 Goal**: Infer that P01 is both `:Person` and `:LegalEntity` via subclass chain
> **✅ Verify**: Before reasoning type is only Applicant; after reasoning Person/LegalEntity appear
> **📚 Takeaway**: This is the most fundamental RL rule; Jena built-in reasoner handles it natively""")

code("""# Before inference: P01's explicit type is :Applicant, but :Applicant subClassOf :Person subClassOf :LegalEntity
# So P01 should also be :Person and :LegalEntity — RL can derive this
explicit_types = list(g_raw.objects(CR.Applicant_P01, RDF.type))
print("P01 explicit types:", [str(t).split('#')[-1] for t in explicit_types])

# rdflib built-in RDFS closure (lightweight RL):
from rdflib.namespace import RDFS as _RDFS
g_rdfs = Graph()
g_rdfs += g_raw  # copy
# Simple subClassOf transitive closure
for s, p, o in list(g_rdfs.triples((None, _RDFS.subClassOf, None))):
    for s2, p2, o2 in g_rdfs.triples((o, _RDFS.subClassOf, None)):
        g_rdfs.add((s, _RDFS.subClassOf, o2))
# Then apply: (?x rdf:type C) AND (C subClassOf D) -> (?x rdf:type D)
for x, _, c in list(g_rdfs.triples((None, RDF.type, None))):
    for _, _, d in g_rdfs.triples((c, _RDFS.subClassOf, None)):
        g_rdfs.add((x, RDF.type, d))

types_after = sorted(str(t).split('#')[-1] for t in g_rdfs.objects(CR.Applicant_P01, RDF.type))
print("P01 inferred types:", types_after)""")

md("""**Observation**: `Applicant_P01` is now inferred to be both `Person` and `LegalEntity` — this is RL's most fundamental and commonly used capability.
""")

md("### A.2 — owl:TransitiveProperty (`:derivedFromRule`)")

md("""> **🔧 Tech**: OWL 2 RL — `owl:TransitiveProperty` closure
> **🎯 Goal**: Inject two triples for e1→e2→e3, then verify the reasoner derives e1→e3
> **✅ Verify**: `e1 derivedFromRule` list includes e3 (not explicitly declared)
> **📚 Takeaway**: This is the foundation of proof-tree chain reasoning; fully covered by the RL profile""")

code("""# Simulate a proof chain: e1 -> e2 -> e3
g_trans = Graph()
g_trans += g_raw
g_trans.add((CR.e1, CR.derivedFromRule, CR.e2))
g_trans.add((CR.e2, CR.derivedFromRule, CR.e3))

# RL rule: if p is transitive and x p y and y p z, then x p z
trans_props = list(g_trans.subjects(RDF.type, OWL.TransitiveProperty))
for p in trans_props:
    while True:
        added = 0
        for x, _, y in list(g_trans.triples((None, p, None))):
            for _, _, z in g_trans.triples((y, p, None)):
                if (x, p, z) not in g_trans:
                    g_trans.add((x, p, z)); added += 1
        if not added: break

inferred = list(g_trans.objects(CR.e1, CR.derivedFromRule))
print("e1 derivedFromRule (transitive closure):", [str(x).split('#')[-1] for x in inferred])""")

md("""**Observation**: `e1 :derivedFromRule e3` is derived — never explicitly declared, but obtained via transitivity closure.
This "chain reasoning" is the foundation of proof trees.
""")

md("### A.3 — owl:disjointWith Inconsistency Detection")

md("""> **🔧 Tech**: OWL 2 RL — `owl:disjointWith` consistency checking
> **🎯 Goal**: Deliberately make P01 both Person and Organization, then scan for contradiction
> **✅ Verify**: violations list is non-empty with (P01, Person, Organization)
> **📚 Takeaway**: RL detects but does not reject — SHACL (NB03) produces structured violation reports""")

code("""# T-Box declares :Person and :Organization as disjoint.
# If we deliberately create a contradiction: assert P01 is simultaneously Person and Organization.
# We start from g_rdfs (RL-inferred graph) so P01 already carries :Person via subClassOf propagation.
# Starting from g_raw would miss that propagation and the check would find nothing.
g_bad = Graph()
g_bad += g_rdfs
g_bad.add((CR.Applicant_P01, RDF.type, CR.Organization))

# RL reasoner does not "reject", but flags the contradiction. Detection approach:
def check_disjoint(graph):
    violations = []
    for c1, _, c2 in graph.triples((None, OWL.disjointWith, None)):
        for x in graph.subjects(RDF.type, c1):
            if (x, RDF.type, c2) in graph:
                violations.append((x, c1, c2))
    return violations

print("Disjoint violations:", check_disjoint(g_bad))""")

md("""**Observation**: The disjoint violation is detected. Note that OWL 2 RL **does not auto-reject** —
it only lets you *detect* the contradiction. **SHACL** gives you a structured violation report (NB03).
""")

md("### A.4 — owl:FunctionalProperty (`:hasDecision`)")

md("""> **🔧 Tech**: OWL 2 RL — `owl:FunctionalProperty` → `owl:sameAs` derivation
> **🎯 Goal**: Give App_M01 two different decisions, watch the reasoner infer sameAs
> **✅ Verify**: Approve sameAs Decline pair appears
> **📚 Takeaway**: functional + AllDifferent together trigger inconsistency — a classic open-world trap""")

code("""# functional: at most one value per subject. If we give App_M01 two decisions, RL infers
# those two decisions are owl:sameAs (equivalent individuals)
g_fun = Graph()
g_fun += g_raw
g_fun.add((CR.App_M01, CR.hasDecision, CR.Approve))
g_fun.add((CR.App_M01, CR.hasDecision, CR.Decline))

# RL rule: if p is functional and x p y and x p z, then y owl:sameAs z
fun_props = list(g_fun.subjects(RDF.type, OWL.FunctionalProperty))
sameas = []
for p in fun_props:
    for x in set(g_fun.subjects(p, None)):
        ys = list(g_fun.objects(x, p))
        for y1 in ys:
            for y2 in ys:
                if y1 != y2:
                    sameas.append((y1, y2))

print("sameAs pairs inferred via FunctionalProperty:")
for a, b in sameas[:5]:
    print(f"  {str(a).split('#')[-1]} = {str(b).split('#')[-1]}")""")

md("""**Observation**: Approve is inferred `owl:sameAs` Decline — but the T-Box declares these three Decision values as `owl:AllDifferent`!
So this ontology becomes **inconsistent** once this erroneous data is added. SHACL (NB03) will give a more user-friendly error report.
""")

md("""### A.5 — What RL Cannot Do: Datatype Facet Equivalent Class

The following query looks for `:PrimeApplicant` instances. On a graph with only RL applied, **the result should be empty**:""")

md("""> **🔧 Tech**: OWL 2 RL boundary — `equivalentClass` + `xsd:withRestrictions` not in profile
> **🎯 Goal**: Query PrimeApplicant count in the RL-simulated graph
> **✅ Verify**: Count = 0 (RL cannot derive datatype facet equivalent classes)
> **📚 Takeaway**: **The first half of this notebook's core contrast** — RL cannot fire `FICO >= 740` style constraints""")

code("""primes_rl = list(g_rdfs.subjects(RDF.type, CR.PrimeApplicant))
print("PrimeApplicant count under Jena RL simulation:", len(primes_rl))
print("(expected 0 — datatype facet equivalent class is outside OWL 2 RL profile)")""")

# ─────────────────────────────────────────────────────────────────────
md("""---

## Part B — What Only Pellet (OWL 2 DL) Can Do

The same A-Box, run through Pellet — watch `:PrimeApplicant` get automatically classified.""")

md("""> **🔧 Tech**: OWL 2 DL loading — owlready2 requires RDF/XML, not Turtle
> **🎯 Goal**: Merge three .ttl files → serialize as RDF/XML → load into isolated owlready2 World
> **✅ Verify**: Class count printed (should be > 10)
> **📚 Takeaway**: SPEC §11.16 (Turtle→RDF/XML conversion) + §11.18 (isolated World avoids global state pollution)""")

code("""import owlready2
import tempfile

owlready2.JAVA_EXE = "/opt/homebrew/opt/openjdk/bin/java"

# owlready2 does not natively support Turtle; use rdflib to merge + convert to RDF/XML
combined = Graph()
for f in ["credit_risk.ttl", "instances/customers.ttl", "instances/applications.ttl"]:
    combined.parse(str(ONTO_DIR / f), format="turtle")

tmp = tempfile.NamedTemporaryFile(suffix=".owl", delete=False)
combined.serialize(destination=tmp.name, format="xml")

# Use isolated World to avoid owlready2 global state pollution
world = owlready2.World()
onto = world.get_ontology(f"file://{tmp.name}").load()
print(f"owlready2 loaded: {len(list(onto.classes()))} classes")""")

md("""> **🔧 Tech**: Pellet DL classification — tableau algorithm, full OWL 2 DL profile
> **🎯 Goal**: Run `sync_reasoner_pellet` to materialize T-Box reasoning results into the World
> **✅ Verify**: "Pellet done." printed, no Java errors
> **📚 Takeaway**: `infer_property_values=True` also derives functional/inverse; slower than RL but far more expressive""")

code("""# Run Pellet (DL reasoner)
# infer_property_values=True also derives functional/inverse properties
with onto:
    owlready2.sync_reasoner_pellet(world,
                                    infer_property_values=True,
                                    debug=0)
print("Pellet done.")""")

md("### B.1 — `:PrimeApplicant` Auto-Classification")

md("""> **🔧 Tech**: OWL 2 DL — `equivalentClass` + datatype facet (`xsd:minInclusive 740`)
> **🎯 Goal**: List all individuals automatically classified as PrimeApplicant
> **✅ Verify**: ~8 individuals (7 P0* + Coapplicant_C01 as a bonus hit)
> **📚 Takeaway**: **The killer demo** — no if/else business logic; the ontology definition drives classification directly""")

code("""ns = "https://nikko.dev/ontology/credit#"
Prime = world[f"{ns}PrimeApplicant"]
primes = sorted(i.name for i in Prime.instances())
print(f"Pellet-inferred Prime ({len(primes)} individuals):")
for p in primes:
    print(f"  - {p}")""")

md("""**Observation**: 7 `Applicant_P*` (designed as Prime) + 1 `Coapplicant_C01` (a bonus: C01's attributes happen to satisfy the Prime definition).
**This is the project's killer demo**: not a single line of if/else business code — pure ontology definition drives Pellet's automatic classification.
""")

md("### B.2 — `:SubprimeApplicant` and `:NearPrimeApplicant`")

md("""> **🔧 Tech**: OWL 2 DL — single-bound facet (Subprime) and interval facet intersection (NearPrime `[620,740)`)
> **🎯 Goal**: List Subprime and NearPrime instances
> **✅ Verify**: Subprime 6 individuals (S01-S06), NearPrime 8 individuals (7 N0* + C02)
> **📚 Takeaway**: OWL expresses intervals via two intersecting restrictions — verbose but correct; see SPEC §4.5""")

code("""Sub  = world[f"{ns}SubprimeApplicant"]
Near = world[f"{ns}NearPrimeApplicant"]

print(f"Sub  ({len(list(Sub.instances()))} individuals): {sorted(i.name for i in Sub.instances())}")
print(f"Near ({len(list(Near.instances()))} individuals): {sorted(i.name for i in Near.instances())}")""")

md("""**Observation**:
- Subprime: 6 individuals, all correct (`S01-S06`)
- NearPrime: 8 individuals — 7 `N0*` + `Coapplicant_C02`

NearPrime is expressed in the ontology as a `[a, b)` interval (`620 <= FICO < 740`), requiring **two** intersecting restrictions.
This is an intentionally preserved teaching case about "OWL's awkward interval expression" (see SPEC §4.5). Next we compare against SHACL.
""")

md("### B.3 — Same Query: RL 0 / DL 14")

md("""> **🔧 Tech**: **RL vs DL data comparison** — same A-Box, two reasoners, dramatically different results
> **🎯 Goal**: Print RL vs DL counts for PrimeApplicant / Subprime
> **✅ Verify**: RL shows two zeros; DL shows actual counts (Prime~8, Subprime=6)
> **📚 Takeaway**: **The signature line of this notebook** — proves that SPEC §4.5's "must use Pellet" is a hard constraint""")

code("""print("Jena RL  -> PrimeApplicant count:", len(list(g_rdfs.subjects(RDF.type, CR.PrimeApplicant))))
print("Pellet DL -> PrimeApplicant count:", len(primes))
print()
print("Jena RL  -> Subprime count:", len(list(g_rdfs.subjects(RDF.type, CR.SubprimeApplicant))))
print("Pellet DL -> Subprime count:", len(list(Sub.instances())))""")

md("""**Conclusion**: For datatype facet equivalent classes, **only the DL reasoner can fire**. SPEC §4.5's "must use Pellet"
is not a suggestion — it is a hard constraint.
""")

md("""### B.4 — NearPrime Interval Verbosity (Preview: SHACL Comparison)

OWL expressing `620 <= FICO < 740`:
```turtle
:NearPrimeApplicant owl:equivalentClass [
    owl:intersectionOf (
        :Applicant
        [ owl:onProperty :hasCreditScore ;
          owl:someValuesFrom [ owl:withRestrictions ( [ xsd:minInclusive 620 ] ) ] ]
        [ owl:onProperty :hasCreditScore ;
          owl:someValuesFrom [ owl:withRestrictions ( [ xsd:maxExclusive 740 ] ) ] ]
    )
] .
```

SHACL equivalent (covered in detail in NB03):
```turtle
:NearPrimeShape a sh:NodeShape ;
    sh:targetClass :Applicant ;
    sh:property [
        sh:path :hasCreditScore ;
        sh:minInclusive 620 ;
        sh:maxExclusive 740 ;
    ] .
```

13 lines of OWL vs 5 lines of SHACL — **not because SHACL is superior to OWL**, but because they solve different problems:
- OWL `equivalentClass` is a **definition** (anything satisfying the conditions IS Prime/NearPrime; the reasoner infers membership)
- SHACL is **validation** (checks whether each instance satisfies constraints; violations are reported)
""")

# ─────────────────────────────────────────────────────────────────────
md("""## 2. Decision Intuition — RL / DL / SHACL / SWRL

| Tool | Purpose | When to use | Performance |
|---|---|---|---|
| **OWL 2 RL** | Forward-chaining: subClassOf transitivity, transitive/functional/inverse properties, disjoint detection | 80% of cases; needed for scale / real-time | Fast; millions of triples OK |
| **OWL 2 DL** (Pellet) | All of RL + equivalent class auto-classification + datatype facets + DL-safe SWRL | When "concept → classification" reasoning is needed and latency is acceptable | Slow; 10K-100K triples is the practical ceiling |
| **SHACL** | Validation: does each instance satisfy its constraints? Report violations. | Data quality checks / ingestion gating | Single-pass scan, moderate speed |
| **SWRL** | Business rules: `if A and B then C` (forward-chaining) | Decision logic, runs on top of DL | Slow (goes through DL); covered in detail in Phase C |

**Rules of thumb**:
- "Are these two things the same thing?" → OWL (equivalent class / sameAs)
- "Does this record violate a constraint?" → SHACL
- "What does my business rule look like?" → SWRL
- "I need real-time queries" → SPARQL, accelerated with RL inference

## You Should Now Be Able To

- [ ] Explain T-Box / A-Box / materialization
- [ ] Know what Jena RL can derive (transitivity, functional, inverse, subClassOf)
- [ ] Know that RL **cannot** derive datatype facet equivalent classes — Pellet is required
- [ ] Run `owlready2.sync_reasoner_pellet()` and query the results
- [ ] Choose the right tool (OWL vs SHACL) for "classification vs validation" scenarios

## Next

NB03 (SHACL) opens with the NearPrime SHACL formulation as a contrast.""")

# ─────────────────────────────────────────────────────────────────────
nb.cells = cells
out = Path(__file__).resolve().parent.parent / "notebooks" / "02_owl_inference.ipynb"
with out.open("w") as f:
    nbf.write(nb, f)
print(f"✓ Wrote {out}  ({len(cells)} cells)")
