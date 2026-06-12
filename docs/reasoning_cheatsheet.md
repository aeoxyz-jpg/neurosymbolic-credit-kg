# Reasoning Tool Cheatsheet — RL / DL / SHACL / SWRL

> When you face a modeling problem, check this table first. It is not
> exhaustive, but it covers 80% of cases.

---

## One-line summary of each tool

| Tool | One line | Example |
|---|---|---|
| **OWL 2 RL** (Jena built-in) | Forward-chaining rules: transitive subClassOf, transitive/functional/inverse properties | `Applicant ⊑ Person` → infers P01 is a Person |
| **OWL 2 DL** (Pellet) | Everything RL does + equivalent classes with datatype facets + DL-safe SWRL | FICO ≥ 740 ∧ DTI ≤ 0.36 → infers `:PrimeApplicant` |
| **SHACL** | Data-compliance validation; violations are reported as errors | FICO=999 → "must be in [300,850]" violation |
| **SWRL** | Business rules, forward-chaining (runs on Pellet) | Prime ∧ strong signal → label LowRisk |
| **SPARQL Update** | Graph-write operations, relational semantics (supports NOT EXISTS) | Default undecided apps to Review |

---

## Decision flowchart

```
What are you trying to do?
├── Infer "this instance belongs to a class"
│   ├── rdfs:subClassOf is sufficient? ──→ Jena OWL RL
│   └── Need numeric conditions / equivalent class? ──→ Pellet (OWL DL)
│
├── Check "is this data valid?"
│   └── ──→ SHACL
│
├── Write "if A and B then infer C" business rules
│   ├── A, B, C are all monotonic (only grow, never retract)? ──→ SWRL
│   └── Involves "X does not exist / default value / NAF"? ──→ SPARQL UPDATE
│
└── Read the graph to answer a question ──→ SPARQL SELECT
```

---

## Edge cases: same intuition, wrong tool choice

### Case 1 — "Credit score must be in [300, 850]"

| Tool | Expression | Behavior |
|---|---|---|
| OWL | `:hasCreditScore rdfs:range :ValidScore`, `:ValidScore owl:withRestrictions ...` | Scores outside the range are *not* rejected; the reasoner may infer a contradiction (open-world assumption) |
| SHACL | `sh:property [ sh:path :hasCreditScore ; sh:minInclusive 300 ; sh:maxInclusive 850 ]` | Directly reports a violation with the focusNode at validation time |

**Conclusion**: This is a **validation** problem, not a **definition** problem. Use SHACL.

### Case 2 — "FICO ≥ 740 ∧ DTI ≤ 0.36 ∧ employment ≥ 2 years ⇒ Prime"

| Tool | Expression | Behavior |
|---|---|---|
| SHACL | A shape requiring Prime applicants to satisfy all three conditions | Checks whether someone who *claims* to be Prime qualifies — **does not automatically classify qualifying applicants as Prime** |
| OWL equivalent class | `:PrimeApplicant ≡ :Applicant ∩ ...` | Pellet automatically infers Prime for anyone who satisfies the conditions; **bidirectional**: knowing someone is Prime also back-infers that all three conditions hold |
| SWRL | Rule: three conditions → label PrimeApplicant | Unidirectional trigger; logically equivalent but loses back-inference |

**Conclusion**: This is a **concept definition**, not a validation or a one-way rule. Use OWL equivalent class.

### Case 3 — "Applications with no decision default to Review"

| Tool | Expression | Behavior |
|---|---|---|
| SWRL | `Application(?a), missing hasDecision → hasDecision(?a, :Review)` | **Cannot be written**. SWRL does not support negation-as-failure |
| SHACL | `sh:property [ sh:path :hasDecision ; sh:minCount 1 ]` | Reports the missing decision as a violation, but *will not* supply a default |
| SPARQL UPDATE | `INSERT { ?a :hasDecision :Review } WHERE { FILTER NOT EXISTS { ?a :hasDecision ?d } }` | Inserts the default directly; matches the "closed-world / default value" business intent |

**Conclusion**: The Open World Assumption and "default values" are incompatible. For any logic that requires defaults, **bypass OWL** and use SPARQL.

### Case 4 — "Is applicant P01 a Person?"

| Tool | Behavior |
|---|---|
| **No reasoner** | Sees only explicit triples: `P01 a :Applicant`. **Does not know** P01 is a Person |
| Jena RL | Sees `:Applicant rdfs:subClassOf :Person`, **infers** P01 is also a Person |
| Pellet | Same, but ~30× slower — overkill for this |

**Conclusion**: For simple type-hierarchy inference, use Jena RL. Don't invoke Pellet.

---

## Performance intuition

| Triple count | RL | DL (Pellet) | SHACL | SPARQL |
|---|---|---|---|---|
| 1k | < 100ms | 1–5s | < 100ms | < 50ms |
| 10k | 200ms–1s | 10–30s | 200–500ms | < 200ms |
| 100k | 1–5s | 1–5 min | 1–5s | < 1s |
| 1M | 10–30s | **unusable** | 10–30s | 1–5s |
| 10M+ | minutes | **unusable** | minutes / OOM | 5–30s |

Pellet is effectively unusable above 100k triples. Production-scale OWL
reasoning requires one of:
- Restricting the ontology to the OWL 2 RL profile and using Jena's built-in reasoner
- A commercial reasoner (Stardog / RDFox)
- An architectural shift: run DL-requiring inference as an offline batch job;
  queries read only the materialized results

---

## SWRL counter-intuitive rules

1. **SWRL has no disjunction** (`a ∨ b`) in the antecedent.
   Workaround: **split into two rules** with identical heads and one branch each
   (the R2a + R2b pattern in this project).

2. **SWRL has no negation-as-failure** (`¬ ∃ X`).
   Workaround: use SPARQL UPDATE or the SQWRL extension.

3. **SWRL has no if-else priority**. Rule firing is a **set operation** — all
   matching rules fire, with no guaranteed order.
   Workaround: use tighter antecedents (add `differentFrom`, add class
   distinctions) to prevent overlap.

4. **DL-safe rule constraint**: every variable must first appear in a class atom
   or individual atom. `signalValue(?s, ?v), greaterThan(?v, 0.8)` alone is not
   legal — `?s` must be grounded first with `CreditScoreSignal(?s)`.

---

## Reasoner debugging checklist

When the reasoner does not produce the expected inference, check in order:

1. **Namespace consistent?** `grep` all `https://nikko.dev/` occurrences and
   look for typos (see `docs/ontology_design.md §1`).
2. **RL or DL?** Equivalent classes with datatype facets **only fire under DL**
   (see `docs/ontology_design.md §3`).
3. **Correct datatype?** `5^^xsd:int` ≠ `5^^xsd:integer`
   (see `docs/ontology_design.md §8`).
4. **Clean Pellet World?** Reusing `default_world` carries over state from a
   previous run; use `load_fresh_world()`.
5. **`rdfs:subClassOf` declarations complete?** Hierarchy levels the reasoner
   hasn't seen won't be inferred.
6. **Did the data actually reach the reasoner?** Before running Pellet, print
   `len(list(onto.individuals()))` and verify the count is correct.

If none of the above resolves it, add `debug=2` to the `sync_reasoner_pellet`
call and inspect the Pellet output.
