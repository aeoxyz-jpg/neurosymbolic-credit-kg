"""Builder for notebooks/04_swrl_credit_rules.ipynb. SPEC §8.4."""

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

md("""# NB04 — SWRL Credit Rules

**This notebook demonstrates:**

1. The four SWRL atom types (class, object-property, data-property, built-in predicate)
2. Implementing rules R1–R4 and materializing them with Pellet
3. The **"two rules for one disjunction"** SWRL idiom (R2a + R2b)
4. **Hitting the R5 negation-as-failure wall head-on** — and understanding why SWRL cannot do it
5. SPARQL UPDATE as the correct fallback, forming a hybrid (SWRL + SPARQL) decision pipeline
6. The fundamental tension between the OWL Open World Assumption and business rules that require default values

## Prerequisites

- Phase B notebooks run cleanly (especially Pellet setup)
- `scripts/run_reasoner.py` exists; `ontology/rules.swrl.owl` has been generated
- Java 25+ on PATH

## ⚠ Kernel Reset

Each cell that runs Pellet creates a fresh `World()`. This prevents owlready2 global state
from leaking prior reasoning results into subsequent runs.""")

md("## 0. Setup")

md("""> **🔧 Tech**: rdflib Turtle parsing + RDF/XML serialisation + owlready2 World isolation
> **🎯 Goal**: Build a `load_fresh_world()` helper that returns a new `World()` on every call,
>   giving each reasoning experiment a clean slate
> **✅ Verify**: Prints "✓ Setup done"; `JAVA_EXE` points to Homebrew openjdk 25
> **📚 Takeaway**: owlready2 shares `default_world` by default — re-running a cell leaks state;
>   creating a new `World()` each time is mandatory hygiene for Pellet notebooks""")

code("""import sys, os, tempfile
from pathlib import Path
from rdflib import Graph, Namespace, URIRef

PROJECT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
ONTO = PROJECT / "ontology"
sys.path.insert(0, str(PROJECT / "scripts"))

import owlready2
owlready2.JAVA_EXE = "/opt/homebrew/opt/openjdk/bin/java"

CR = Namespace("https://nikko.dev/ontology/credit#")

# Merge T-Box + A-Box into a single RDF/XML temp file, then load into a fresh World
def load_fresh_world():
    \"\"\"Returns (world, onto) — fresh state every time.\"\"\"
    g = Graph()
    for f in ["credit_risk.ttl", "instances/customers.ttl", "instances/applications.ttl"]:
        g.parse(str(ONTO / f), format="turtle")
    tmp = tempfile.NamedTemporaryFile(suffix=".owl", delete=False)
    g.serialize(destination=tmp.name, format="xml")
    world = owlready2.World()
    onto = world.get_ontology(f"file://{tmp.name}").load()
    return world, onto

print("✓ Setup done")""")

# ---------------------------------------------------------
md("""## 1. SWRL Atom Types

A SWRL rule has the form `antecedent → consequent`; both sides are comma-separated atom lists,
where comma means AND.

| Atom type | Example | Meaning |
|---|---|---|
| Class atom | `CreditApplication(?app)` | ?app is a CreditApplication |
| Object-property atom | `hasApplicant(?app, ?a)` | ?app is linked to ?a via hasApplicant |
| Data-property atom | `signalValue(?s, ?v)` | signalValue of ?s is ?v |
| Built-in predicate | `greaterThanOrEqual(?v, 0.8)` | swrlb:greaterThanOrEqual built-in |
| Same-individual atom | `sameAs(?a, ?b)` | two individuals are OWL-same |

**Key constraint (DL-safe rules)**: every variable in the antecedent must be grounded by a
class atom or a named individual — you cannot conjure a variable from nothing.""")

# ---------------------------------------------------------
md("""## 2. R1 — Prime + Strong Signal → LowRisk (signal fusion entry point)

Full rule (SPEC §6 R1):

```
CreditApplication(?app), hasApplicant(?app, ?a), PrimeApplicant(?a),
emittedSignal(?app, ?s), CreditScoreSignal(?s),
signalValue(?s, ?v), greaterThanOrEqual(?v, 0.8)
→ hasRiskTier(?app, LowRiskApplication)
```

Interpretation: **only if** the applicant is in the Prime tier **and** the application
emitted a credit-score signal with value ≥ 0.8 do we classify it as LowRisk.
Being Prime is a necessary but not sufficient condition — hard evidence is also required.""")

md("""> **🔧 Tech**: SWRL Horn-clause rule + `swrlb:greaterThanOrEqual` built-in predicate
> **🎯 Goal**: Declare R1 via `Imp().set_as_rule()`, run Pellet, query which applications
>   received the LowRisk tier
> **✅ Verify**: Prints "R1 fires on N applications" and includes applications belonging
>   to Prime applicants (P01, P02, …)
> **📚 Takeaway**: Three atom types in combination — class, property, and data comparison;
>   Pellet treats the rule as part of the T-Box and materializes the consequences forward""")

code("""world, onto = load_fresh_world()
with onto:
    r1 = owlready2.Imp()
    r1.set_as_rule(
        "CreditApplication(?app), hasApplicant(?app, ?a), PrimeApplicant(?a), "
        "emittedSignal(?app, ?s), CreditScoreSignal(?s), "
        "signalValue(?s, ?v), greaterThanOrEqual(?v, 0.8) "
        "-> hasRiskTier(?app, LowRiskApplication)"
    )

# Run Pellet to fire R1
print("Running Pellet (R1 only)...")
with onto:
    owlready2.sync_reasoner_pellet(world, infer_property_values=True, debug=0)

# Query which applications got the LowRisk tier
hasRiskTier = onto.search(hasRiskTier=onto["LowRiskApplication"])
print(f"R1 fires on {len(hasRiskTier)} applications:")
for app in sorted(hasRiskTier, key=lambda x: x.name)[:8]:
    print(f"  - {app.name}")""")

# ---------------------------------------------------------
md("""## 3. R2 — Two Rules for One Disjunction (SWRL idiom)

A natural business requirement might read:
> "If the applicant is Subprime **or** the credit signal is < 0.3, classify as HighRisk"

SWRL **does not support disjunction** in the antecedent. The standard idiom is to
**split into two rules**, each capturing one branch. Both rules share the same consequent,
making their combined effect equivalent to OR (technically an OR-of-ANDs, not a first-class
disjunction).""")

md("""> **🔧 Tech**: Two SWRL rules sharing a consequent + `swrlb:lessThan` built-in
> **🎯 Goal**: Declare R2a (Subprime applicant) and R2b (weak signal < 0.3) separately;
>   their union covers all HighRisk applications
> **✅ Verify**: Prints HighRisk application count; applications from Subprime customers
>   and applications with weak signals are both covered
> **📚 Takeaway**: SWRL antecedents forbid disjunction — any OR logic must be decomposed
>   into multiple Horn rules (OR-of-ANDs pattern)""")

code("""world, onto = load_fresh_world()
with onto:
    r2a = owlready2.Imp()
    r2a.set_as_rule(
        "CreditApplication(?app), hasApplicant(?app, ?a), SubprimeApplicant(?a) "
        "-> hasRiskTier(?app, HighRiskApplication)"
    )
    r2b = owlready2.Imp()
    r2b.set_as_rule(
        "CreditApplication(?app), emittedSignal(?app, ?s), CreditScoreSignal(?s), "
        "signalValue(?s, ?v), lessThan(?v, 0.3) "
        "-> hasRiskTier(?app, HighRiskApplication)"
    )

# infer_property_values=True is required so Pellet materializes :SubprimeApplicant
# membership (a DL-defined class) before R2a's class atom can match anyone.
with onto: owlready2.sync_reasoner_pellet(world, infer_property_values=True, debug=0)

high = onto.search(hasRiskTier=onto["HighRiskApplication"])
print(f"R2a+R2b combined fire on {len(high)} applications:")
for app in sorted(high, key=lambda x: x.name):
    print(f"  - {app.name}")""")

md("""**What if R2a and R2b both fire on the same application?**

No problem — `hasRiskTier` is an `owl:FunctionalProperty`, so asserting the same value twice
is idempotent. But **if two rules derive conflicting values** (e.g. R2a says HighRisk and a
hypothetical R2c says LowRisk), OWL detects a functional-property clash and Pellet raises an
inconsistency. That is exactly what the next section demonstrates.""")

# ---------------------------------------------------------
md("""## 4. Rule Conflict Detection (FunctionalProperty + differentFrom tiers)

Write a deliberately conflicting rule: force the Subprime applications to be simultaneously
LowRisk **and** HighRisk. Because `:hasRiskTier` is functional, asserting two values forces
Pellet to infer `:LowRiskApplication owl:sameAs :HighRiskApplication`.

**A subtle but important point**: the tier classes are *punned* (class + individual), and
`owl:AllDisjointClasses` only constrains the **classes**, not the punned **individuals** that
`:hasRiskTier` actually ranges over. So disjointness alone does **not** raise a contradiction
here. We make the clash real by injecting `owl:differentFrom` between the two tier individuals
— now `sameAs` between two declared-distinct individuals is a genuine inconsistency.""")

md("""> **🔧 Tech**: `owl:FunctionalProperty` + `owl:differentFrom` triggers the DL consistency check
> **🎯 Goal**: Intentionally write a rule that conflicts with R2a (same application tagged
>   both Low and High) and let Pellet raise `OwlReadyInconsistentOntologyError`
> **✅ Verify**: Exception is caught and "✓ Pellet detected inconsistency" is printed
> **📚 Takeaway**: OWL DL surfaces contradictions immediately — but on *punned* individuals
>   you need explicit individual-level distinctness (differentFrom / AllDifferent), not just
>   disjoint classes, to force the clash""")

code("""from rdflib import RDF
from rdflib.namespace import OWL

# The tier classes are PUNNED (class + NamedIndividual). owl:AllDisjointClasses
# constrains the *classes*, but :hasRiskTier ranges over the tier *individuals*.
# A functional-property clash forces Pellet to infer LowRisk owl:sameAs HighRisk —
# which is only a contradiction if the two individuals are declared distinct.
# So we inject owl:differentFrom between them before loading into owlready2.
def load_world_with_distinct_tiers():
    g = Graph()
    for f in ["credit_risk.ttl", "instances/customers.ttl", "instances/applications.ttl"]:
        g.parse(str(ONTO / f), format="turtle")
    g.add((CR.LowRiskApplication, OWL.differentFrom, CR.HighRiskApplication))
    tmp = tempfile.NamedTemporaryFile(suffix=".owl", delete=False)
    g.serialize(destination=tmp.name, format="xml")
    world = owlready2.World()
    onto = world.get_ontology(f"file://{tmp.name}").load()
    return world, onto

world, onto = load_world_with_distinct_tiers()
with onto:
    # Normal R2a
    r2a = owlready2.Imp()
    r2a.set_as_rule(
        "CreditApplication(?app), hasApplicant(?app, ?a), SubprimeApplicant(?a) "
        "-> hasRiskTier(?app, HighRiskApplication)"
    )
    # Deliberate conflict: tag the same Subprime applications LowRisk too
    # (Subprime → R2a fires HighRisk while r_bad fires LowRisk — contradiction)
    r_bad = owlready2.Imp()
    r_bad.set_as_rule(
        "CreditApplication(?app), hasApplicant(?app, ?a), SubprimeApplicant(?a) "
        "-> hasRiskTier(?app, LowRiskApplication)"
    )

try:
    # infer_property_values=True materializes :SubprimeApplicant membership, so both
    # R2a (HighRisk) and r_bad (LowRisk) actually fire and clash on the functional
    # :hasRiskTier — combined with the differentFrom tiers, Pellet must raise.
    with onto:
        owlready2.sync_reasoner_pellet(world, infer_property_values=True, debug=0)
    print("✗ Expected a contradiction but Pellet succeeded")
except owlready2.OwlReadyInconsistentOntologyError as e:
    print("✓ Pellet detected inconsistency:")
    print(f"  {type(e).__name__}: {str(e)[:200]}")""")

md("""**Observation**: Pellet refuses to continue because a functional property cannot
simultaneously bind to two individuals declared `differentFrom` each other. This is why
OWL DL does not permit silent logic drift — contradictions surface immediately rather than
propagating silently.""")

# ---------------------------------------------------------
md("""## 5. R3 + R4 — Full Decision Pipeline

Run R1–R4 together to see the complete tier → decision chain:

- R1: Prime + strong signal → LowRisk
- R2a/b: Subprime / weak signal → HighRisk
- R3: HighRisk → Decline
- R4: LowRisk + stable employment + amount ≤ 100k → Approve""")

md("""> **🔧 Tech**: Reuse `run_reasoner.RULE_DEFS` and `define_swrl_rules` — same rule source
>   as the production script
> **🎯 Goal**: Fire R1–R4 in one Pellet run; count the tier and decision distribution
> **✅ Verify**: Approve ≈ 4, Decline ≈ 8, Review = 0 (R5 has not run yet);
>   total applications > Approve + Decline, confirming a gap
> **📚 Takeaway**: SWRL monotonic rules leave mid-range (MidRisk) applications with no
>   decision at all — exposing exactly why R5 fallback is necessary""")

code("""from run_reasoner import RULE_DEFS, define_swrl_rules  # reuse canonical rule definitions

world, onto = load_fresh_world()
define_swrl_rules(owlready2, onto)
print(f"Declared {len(RULE_DEFS)} rules: {[n for n, _ in RULE_DEFS]}")

with onto: owlready2.sync_reasoner_pellet(world, infer_property_values=True, debug=0)

# Count tier and decision assignments
def count(prop_name, val_name):
    p = onto[prop_name]
    v = onto[val_name]
    return sum(1 for _ in onto.search(**{prop_name: v}))

print()
print(f"Tier:    Low={count('hasRiskTier','LowRiskApplication')}, "
      f"Mid={count('hasRiskTier','MediumRiskApplication')}, "
      f"High={count('hasRiskTier','HighRiskApplication')}")
print(f"Decision: Approve={count('hasDecision','Approve')}, "
      f"Review={count('hasDecision','Review')}, "
      f"Decline={count('hasDecision','Decline')}")""")

md("""**Expected numbers** (based on fixture design):

| | LowRisk | MidRisk | HighRisk |
|---|---|---|---|
| Tier count | ~12 | 0 | ~8 |

| | Approve | Review | Decline |
|---|---|---|---|
| Decision count | ~4 | 0 (R5 not yet run) | ~8 |

The remaining ~18 applications have **no decision** — they are neither LowRisk nor HighRisk
(the middle segment), so neither R3 nor R4 fires. That gap is precisely what R5 is designed
to fill.""")

# ---------------------------------------------------------
md("""## 6. R5 — Hitting the Negation-as-Failure Wall

The natural business rule is: **"If an application has no decision, mark it Review"**.

SWRL cannot express this. The reason is the **Open World Assumption (OWA)**: absence of a
`:hasDecision` triple does not mean the decision is absent — it might simply mean the data
has not arrived yet. Under OWA, missing data cannot trigger a default conclusion.

The cell below proves this by attempting to simulate NAF via `differentFrom`.""")

md("""> **🔧 Tech**: Counter-example attempt — using `differentFrom` to mimic NAF; SWRL has
>   **no** non-existence quantifier
> **🎯 Goal**: Write a rule that tries to express "no hasDecision" and observe that it
>   cannot achieve NAF semantics
> **✅ Verify**: No application receives the default `:Review`;
>   confirms SWRL cannot simulate NAF; the fake rule fires on nobody
> **📚 Takeaway**: OWL monotonicity + OWA together mean DL reasoners refuse NAF; this is
>   a deliberate design choice, not a limitation to work around""")

code("""# Attempt: SWRL has no 'NOT EXISTS' predicate — it simply cannot be written
world, onto = load_fresh_world()
define_swrl_rules(owlready2, onto)

# differentFrom only tests individual identity, not triple absence.
# Even if accepted, Pellet will not interpret this as NAF.
with onto:
    r5_fake = owlready2.Imp()
    # This antecedent is meaningless as NAF — differentFrom(?app, ?app) is
    # never satisfiable, so the rule matches nobody and produces no :Review.
    r5_fake.set_as_rule(
        "CreditApplication(?app), differentFrom(?app, ?app) "
        "-> hasDecision(?app, Review)"
    )
    owlready2.sync_reasoner_pellet(world, infer_property_values=True, debug=0)

# Count how many applications the fake rule defaulted to :Review.
fake_reviews = sum(1 for _ in onto.search(hasDecision=onto["Review"]))
if fake_reviews == 0:
    print(f"✓ As expected, the fake NAF rule produced {fake_reviews} :Review decisions")
    print("  SWRL has no 'NOT EXISTS' predicate — differentFrom(?app, ?app) cannot mimic it.")
else:
    print(f"✗ Surprising: fake rule produced {fake_reviews} :Review default(s)")""")

md("""**Why SWRL cannot do NAF**:

Short answer: **monotonicity**. OWL DL guarantees that adding more facts will
**never invalidate** previously derived conclusions. NAF breaks monotonicity:
if an application had no `:hasDecision` and we inferred `:Review`, then a new
real decision triple arrives and the `:Review` should be retracted — violating
monotonicity. DL reasoners (Pellet, HermiT) reject this semantic. It is a
deliberate design choice, not a bug.""")

# ---------------------------------------------------------
md("""## 7. R5 (Real) — SPARQL UPDATE Takes Over

SPARQL uses relational (closed-world) semantics like SQL. `FILTER NOT EXISTS`
directly expresses "this triple does not exist" without assuming anything about
absent data.

R5 implementation:""")

md("""> **🔧 Tech**: ⭐ **Core pivot** — SPARQL UPDATE `INSERT ... WHERE ... FILTER NOT EXISTS`
>   (the canonical NAF pattern in RDF)
> **🎯 Goal**: Serialize the Pellet-materialized world into rdflib, run the R5 SPARQL UPDATE,
>   and fill every application that has no `:hasDecision` with `:Review`
> **✅ Verify**: Prints "R5 added N :Review decisions", N ≈ 18 (the mid-range applications
>   without a prior decision); after the update every application has `:hasDecision`
> **📚 Takeaway**: **The pedagogical climax of this notebook** — SWRL is monotonic and
>   NAF-free, so defaults/fallbacks **must** use SPARQL UPDATE. DL reasoners and relational
>   semantics are complementary, not substitutes. Hybrid orchestration is real-world practice,
>   not a workaround.""")

code("""# Run the FULL R1-R4 pipeline in a fresh world so the graph actually carries
# the Approve/Decline decisions (infer_property_values=True is essential — without
# it the DL-defined tiers never materialize and R5 would over-fill every app).
world, onto = load_fresh_world()
define_swrl_rules(owlready2, onto)
with onto: owlready2.sync_reasoner_pellet(world, infer_property_values=True, debug=0)

# Export the reasoned world to an rdflib graph
tmp = tempfile.NamedTemporaryFile(suffix=".rdf", delete=False)
world.save(file=tmp.name, format="rdfxml")
g = Graph()
g.parse(tmp.name, format="xml")
print(f"Graph after reasoning: {len(g)} triples")

# Run the R5 SPARQL UPDATE
before = sum(1 for _ in g.triples((None, CR.hasDecision, None)))
g.update('''
PREFIX : <https://nikko.dev/ontology/credit#>
INSERT { ?app :hasDecision :Review }
WHERE {
    ?app a ?type .
    FILTER (?type IN (:CreditApplication, :MortgageApplication,
                       :PersonalLoanApplication, :AutoLoanApplication))
    FILTER NOT EXISTS { ?app :hasDecision ?d }
}
''')
after = sum(1 for _ in g.triples((None, CR.hasDecision, None)))
print(f"R5 added {after - before} :Review decisions ({before} → {after})")""")

# ---------------------------------------------------------
md("""## 8. The Hybrid Pipeline at a Glance

```
A-Box
  │
  ├── Pellet  (DL reasoning: materializes PrimeApplicant etc.)
  │     │
  │     └── SWRL R1-R4 (monotonic rules)
  │             │
  │             └→ hasRiskTier, hasDecision (partial)
  │
  └── SPARQL UPDATE R5 (NAF: no decision → Review)
        │
        └→ every application has a decision
```

**Lesson**: no single tool does everything.

| Expressiveness need | Right tool |
|---|---|
| Class membership (definitions) | OWL equivalent class + Pellet |
| Monotonic business rules | SWRL + Pellet |
| Data compliance checks | SHACL |
| **Default values / NAF / relational operations** | **SPARQL UPDATE** |

Hybrid orchestration is the standard Knowledge Layer pattern, not a fallback.""")

# ---------------------------------------------------------
md("""## 9. Performance Notes

Our fixture is on the order of hundreds of triples; Pellet takes roughly 10–15 seconds,
and four SWRL rules add little overhead.

**Real-world scale pain points** (for reference, not demonstrated here):
- 1K–10K triples: Pellet is sub-second to seconds — acceptable
- 10K–100K: minutes — consider batching or switching to OWL 2 RL subset + Jena RL
- > 1M: change strategy entirely — RDFox / Stardog / commercial reasoner,
  or fall back to SHACL + SPARQL

**Rule count is also a bottleneck**: the longer each rule's antecedent, the worse the
combinatorial explosion. Projects with 20+ rules should consider layering (run
concept-classification rules and decision rules in separate reasoner passes).""")

# ---------------------------------------------------------
md("""## You Should Now Be Able To ✓

- [ ] Write a SWRL rule with class atoms, property atoms, and built-in predicates
- [ ] Split an "A or B → C" business rule into R2a / R2b SWRL rules
- [ ] Diagnose which two rules caused a Pellet `InconsistentOntologyError`
- [ ] **Explain to a colleague** why R5 (default Review) must use SPARQL and cannot use SWRL
- [ ] Run the complete pipeline with `scripts/run_reasoner.py --apply-r5`

## Next Steps

NB05 (Phase D) integrates ollama-cloud for NL ↔ SPARQL translation, wrapping this
reasoning engine into a neurosymbolic system that can answer natural-language questions.""")

# ---------------------------------------------------------
nb.cells = cells
out = Path(__file__).resolve().parent.parent / "notebooks" / "04_swrl_credit_rules.ipynb"
with out.open("w") as f:
    nbf.write(nb, f)
print(f"✓ Wrote {out}  ({len(cells)} cells)")
