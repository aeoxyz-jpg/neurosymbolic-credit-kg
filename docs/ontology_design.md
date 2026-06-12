# Ontology Design — Why We Modeled It This Way

> This document explains the "could have been simpler" design choices in
> `ontology/credit_risk.ttl`. Every decision has a concrete downstream
> consequence — read the relevant section before making changes.

---

## 1. Namespace `https://nikko.dev/ontology/credit#`

**Choice**: Use an `https://` IRI, not `urn:` or `nikko.local`.

**Rationale**:
- Some reasoners (especially older Pellet builds) have poor compatibility with
  `urn:` IRIs; Jena will emit warnings.
- `.local` is an mDNS-reserved TLD; some validators flag it.
- `nikko.dev` is a real resolvable domain — but **DNS resolution is not
  required**; the IRI is just an identifier.

**Downstream constraint**: **All** `.ttl` files, SWRL rules, SHACL shapes, and
SPARQL prefixes must use the same base IRI. Mixing IRIs is the #1 cause of
"why didn't the reasoner fire" failures (see `docs/architecture.md`).

---

## 2. Risk-tier classes are punned (class + individual)

```turtle
:LowRiskApplication a owl:Class, owl:NamedIndividual ;
    rdfs:subClassOf :CreditApplication .
```

**Choice**: Make `:LowRiskApplication` both a class (`owl:Class`) and an
individual (`owl:NamedIndividual`).

**Rationale**: SWRL rules such as:
```
... → hasRiskTier(?app, :LowRiskApplication)
```
require `:LowRiskApplication` to appear in object position — i.e., to be
referenced as an individual. At the same time it must be a *class* so we can
issue `?app a :LowRiskApplication` type-membership queries.

OWL 2 DL permits **punning** (name collision is legal; context disambiguates),
and both Pellet and HermiT handle it correctly. At the RDF level the same IRI
simply appears in two roles — there is no "triple conflict."

**Alternatives considered**:
- Model risk tiers as three named individuals of a `:RiskTier` class
  (`:LowRisk` / `:MediumRisk` / `:HighRisk`), rewriting R1 as
  `hasRiskTier(?app, :LowRisk)`. This avoids punning but loses the class-hierarchy
  semantics.
- **Rejected** — the class-hierarchy semantics carry pedagogical value in NB02
  (demonstrating transitive `rdfs:subClassOf` inference); punning is the smaller
  deviation.

**Downstream**: Requires an OWL 2 DL reasoner. Pellet OK, HermiT OK. Jena RL
will ignore individual-level type-membership inference (but will not error).

---

## 3. Equivalent classes use datatype facets — Prime / NearPrime / Subprime

```turtle
:PrimeApplicant owl:equivalentClass [
    owl:intersectionOf (
        :Applicant
        [ owl:onProperty :hasCreditScore ;
          owl:someValuesFrom [ owl:withRestrictions ( [ xsd:minInclusive 740 ] ) ] ]
        ...
    )
] .
```

**Choice**: Express "FICO ≥ 740" with `owl:withRestrictions` + `xsd:minInclusive`.

**Rationale**: This is an **OWL 2 DL** datatype restriction, which is **not in
the OWL 2 RL profile**. Jena's built-in OWL RL reasoner **will not** infer
`:PrimeApplicant` membership — Pellet is required.

This choice is the project's core demo: NB02 intentionally shows RL vs. DL
side-by-side to illustrate "when you must use DL." Pedagogical value outweighs
performance.

**Alternatives considered**:
- Use SHACL `sh:minInclusive 740` for validation — but SHACL does not classify;
  it can only *check* whether an applicant who claims to be Prime has a high
  enough score. It cannot infer "this person is Prime" from raw data. The two
  tools solve different problems.
- Write a SWRL rule `hasCreditScore(?a, ?s), greaterThanOrEqual(?s, 740), ... →
  PrimeApplicant(?a)`. This works but loses the *bidirectional* inference of an
  equivalent class (knowing someone is Prime lets you back-infer FICO ≥ 740).
- **We use equivalent class** — it most closely captures the semantics of a
  concept *definition*, and it is bidirectional.

**Performance**: Pellet with datatype facets is somewhat slower than pure class
hierarchy, but the fixture size is small enough that the difference is not
observable.

---

## 4. The NearPrime interval `[620, 740)` is intentionally verbose

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

**Choice**: Express the range as two separate restrictions intersected, rather
than combining them into a single `withRestrictions` list.

**Rationale**: OWL 2 does not allow both `xsd:minInclusive` and
`xsd:maxExclusive` in a single `withRestrictions` list — the spec requires *two
restriction nodes joined by intersection*.

This is an intentional **teaching contrast**: expressing a numeric range in OWL
takes 13 lines of Turtle and two nested restriction nodes; the equivalent SHACL
expression is 5 lines: `sh:minInclusive 620 ; sh:maxExclusive 740`. NB02 / NB03
use this contrast for the "when to use OWL vs. SHACL" discussion.

**Do not "optimize" this**: SHACL is more concise, yes — but **SHACL does not
classify**. Switching to SHACL removes the ability to automatically classify an
applicant as NearPrime from raw score data.

---

## 5. The Signal layer is load-bearing, not decorative

```turtle
:CreditScoreSignal a owl:Class ;
    rdfs:subClassOf :RiskSignal .
:signalValue a owl:DatatypeProperty ;
    rdfs:domain :RiskSignal ; rdfs:range xsd:decimal .
```

**Choice**: `:RiskSignal` + 6 subclasses + `:emittedSignal` links, with SWRL
rules R1 / R2b / R4 **required** to read signal values.

**Rationale**: The project is a **signal-fusion** system. If SWRL rules read
`:hasCreditScore` directly and bypass the signal layer, the signal layer becomes
dead ontology.

Design decision (early design review): make R1–R4 **require** the three-hop
path `emittedSignal / CreditScoreSignal / signalValue` to reach any value. This
gives the signal layer a real business function and lets it carry metadata:
confidence, timestamp, bureau source, etc.

**Downstream**:
- Every application in `applications.ttl` **must** emit at least one signal, or
  SWRL rules will not fire.
- Adding a new signal type (e.g. `:FraudSignal`) only requires adding a subclass
  and one SWRL rule — the schema is unchanged.
- The bureau chain (`:reportedBy`) is meaningful — different bureaus may emit
  different signals for the same applicant.

---

## 6. `:Decision` is a class; Approve / Review / Decline are individuals

```turtle
:Decision a owl:Class .
:Approve a owl:NamedIndividual, :Decision .
:Review  a owl:NamedIndividual, :Decision .
:Decline a owl:NamedIndividual, :Decision .

[ a owl:AllDifferent ; owl:distinctMembers ( :Approve :Review :Decline ) ] .
```

**Choice**: Decision outcomes are named individuals (enumeration values), not
punned classes, not strings.

**Rationale**:
- SWRL R3 `→ hasDecision(?app, :Decline)` requires `:Decline` to be an individual.
- `owl:AllDifferent` ensures the reasoner knows these three cannot be equal —
  preventing the functional property `hasDecision` from inferring absurdities
  like "Approve sameAs Decline."
- Using enumeration values instead of strings (e.g. `"approve"`) enables
  type-safe SHACL / SPARQL queries such as `?d IN (:Approve, :Review)`.

**Alternative**: Model decisions as classes (`:ApproveDecision` /
`:DeclineDecision`) and classify applications: `?app a :ApproveDecision`. This
works, but the functional-property semantics are lost (an app could simultaneously
be `:ApproveDecision` and `:DeclineDecision`, requiring additional disjointness
axioms). The current design is tighter.

---

## 7. `:Explanation` + `:derivedFromRule` (transitive)

```turtle
:Explanation a owl:Class .
:derivedFromRule a owl:ObjectProperty, owl:TransitiveProperty ;
    rdfs:domain :Explanation ; rdfs:range :Explanation .
```

**Choice**: Represent proof chains as reified `:Explanation` nodes linked by
the transitive property `:derivedFromRule`.

**Rationale and key clarification**:
- `:Explanation` instances are **not** emitted directly by SWRL rules (that
  would require writing each rule twice).
- They are reconstructed after the fact from Pellet's inference results. NB05's
  `explain_decision()` function implements this reconstruction.
- The transitive property `:derivedFromRule` lets a single SPARQL
  `?e :derivedFromRule+ ?root` query traverse an entire proof chain.

**Why not PROV-O**: PROV-O is a more standard provenance vocabulary, but its
layering is complex and would make the ontology look intimidating. For a teaching
project, illustrative beats standards-compliance. A production system should use
PROV-O.

---

## 8. `xsd:integer` vs. `xsd:int`

We use `xsd:integer` (arbitrary-precision integer) throughout, never `xsd:int`
(32-bit).

**Rationale**: Pellet's support for `xsd:int` is slightly weaker than for
`xsd:integer`, and FICO scores / month counts will never overflow 32 bits but
unbounded integer is the safer convention.

**Pitfall**: owlready2's Python ↔ XSD mapping defaults to `xsd:integer`. Mixing
the two causes the reasoner to treat `5^^xsd:integer` and `5^^xsd:int` as
distinct values — equivalent-class axioms will not fire. **Keep it consistent.**

---

## Before modifying this ontology

1. **Parse-check first**: `python -c "from rdflib import Graph; Graph().parse('ontology/credit_risk.ttl', format='ttl')"`
2. Run `python scripts/verify_phase_a.py` to confirm baseline data is intact.
3. If you changed an equivalent-class definition, run
   `python scripts/run_reasoner.py --print-summary` and verify the inferred
   classification matches expectations.
4. If you changed the namespace IRI, **every file in the project** must be
   updated — grep and replace, no exceptions.

After modifying the ontology, reference the relevant section of this document
in the commit message (e.g. `docs/ontology_design.md §3`).
