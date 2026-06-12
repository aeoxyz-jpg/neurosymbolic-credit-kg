# Architecture

A neurosymbolic credit-risk knowledge graph. A large language model proposes —
it translates natural language into SPARQL and renders results back into prose —
while a W3C semantic-reasoning stack (OWL, SHACL, SPARQL, SWRL) verifies every
claim and reconstructs the proof chain behind it. The symbolic layer is the
source of truth; the LLM is a fluent but untrusted front end whose output is
gated, validated, and grounded against the graph.

The thesis is concrete: an LLM asked "why was application APP-007 declined?"
will produce a plausible, fluent, and possibly fabricated answer. The same
question routed through this system answers from the actual inference trace —
which rules fired, on which signal values, producing which tier and decision.
The system trades the LLM's fluency-when-wrong for determinism and verifiable
citations.

---

## 1. System Overview

End to end, a question flows through five stages:

1. **Translate** — an LLM converts the natural-language question into a SPARQL
   query, prompted with the ontology's class and property vocabulary.
2. **Gate** — a whitelist validator parses the generated SPARQL and rejects any
   query that references a predicate, class, or individual not declared in the
   T-Box, before it ever reaches the store.
3. **Reason** — Pellet materializes OWL 2 DL inferences (applicant tiers) and
   fires the SWRL rule set (signal fusion → risk tier → decision); a SPARQL
   UPDATE applies the default-to-Review rule.
4. **Validate** — SHACL shapes act as a closed-world gate over the data,
   surfacing constraint violations as human-readable reports.
5. **Explain** — the proof chain behind any inference is reconstructed by
   walking the materialized graph in reverse (decision → tier → rule
   preconditions → signal values) into a structured dict, then handed to the LLM
   for natural-language synthesis, with a second LLM call checking that synthesis
   against the same reconstructed chain.

The data is split into three layers: a **T-Box** (`ontology/credit_risk.ttl`)
holding all class and property definitions; an **A-Box**
(`ontology/instances/*.ttl`) holding ~20 applicants and ~30 applications with
their emitted risk signals; and a **rule layer** (`ontology/rules.swrl.owl`)
holding business rules, kept separate because rules evolve faster than schema.

---

## 2. Ontology Design

The ontology is the cognitive core. Its class hierarchy:

```
owl:Thing
├── :LegalEntity
│     ├── :Person
│     │     ├── :Applicant
│     │     │     ├── :PrimeApplicant        (equivalent class — inferred)
│     │     │     ├── :NearPrimeApplicant    (equivalent class — inferred)
│     │     │     └── :SubprimeApplicant     (equivalent class — inferred)
│     │     └── :Coapplicant
│     └── :Organization
│           ├── :Employer
│           └── :CreditBureau
│
├── :CreditApplication
│     ├── :MortgageApplication / :PersonalLoanApplication / :AutoLoanApplication
│     └── :LowRiskApplication / :MediumRiskApplication / :HighRiskApplication
│
├── :RiskSignal
│     ├── :CreditScoreSignal / :IncomeSignal / :DebtRatioSignal
│     └── :EmploymentStabilitySignal / :BehavioralSignal / :CollateralSignal
│
├── :Decision  ─ :Approve / :Review / :Decline   (named individuals)
└── :Explanation                                  (proof-chain carrier)
```

Disjointness axioms hold the model honest: the three decisions are pairwise
disjoint, the three application risk tiers are pairwise disjoint, the three
applicant tiers are pairwise disjoint, and `:Person` is disjoint with
`:Organization`. Applicant raw attributes (FICO, debt-to-income, employment
years) are datatype properties on `:Applicant`; applications carry
`:requestedAmount` and `:requestedTermMonths` and link to signals via
`:emittedSignal`.

Three design choices carry the weight of the project.

### 2.1 Applicant tiers via OWL 2 DL datatype facets

`:PrimeApplicant`, `:NearPrimeApplicant`, and `:SubprimeApplicant` are not
assigned by code — they are defined as **equivalent classes** using datatype
facet restrictions. Prime, for example, is the intersection of `:Applicant`
with FICO ≥ 740, debt-to-income ≤ 0.36, and employment ≥ 2 years, each expressed
as an `owl:Restriction` over a custom datatype (`rdfs:Datatype` with
`owl:onDatatype` and `owl:withRestrictions`). Assert a raw FICO of 750, a
debt-to-income of 0.30, and 5 years of employment on a customer, and the
reasoner *derives* `a :PrimeApplicant` with no imperative logic.

The deliberate consequence: `owl:withRestrictions` over user-defined datatypes
sits **outside the OWL 2 RL profile**, which explicitly excludes user-defined
datatypes. Jena's built-in OWL RL reasoner provably leaves these axioms inert —
it materializes nothing for the applicant tiers. Only an OWL 2 DL reasoner
(Pellet, via owlready2) fires them. Notebook 02 runs the same A-Box through both
reasoners side by side: Jena RL infers no tiers, Pellet materializes
`:PrimeApplicant`. That contrast is the point, not an implementation detail — it
marks the exact boundary between the lightweight RL profile and full DL.

`:NearPrimeApplicant` (620 ≤ FICO < 740) is intentionally verbose in OWL —
two restrictions intersected to express one interval — to expose how awkward OWL
is for ranges, motivating the much terser SHACL equivalent
(`sh:minInclusive 620 ; sh:maxExclusive 740`) and the OWL-inference-vs-SHACL-
validation boundary discussion.

### 2.2 Punning: tier classes are also individuals

The three application risk-tier classes are *punned* — each is declared both
`owl:Class` and `owl:NamedIndividual`. The class facet lets an application be a
member (`:app-1 a :LowRiskApplication`); the individual facet lets a tier appear
as the *object* of a property assertion, which is what SWRL atoms like
`hasRiskTier(?app, :LowRiskApplication)` require. OWL 2 DL permits this dual use
under punning, and Pellet handles it correctly. Without punning, the rules in §3
could not name a tier as a value.

### 2.3 Explanations reconstructed, not asserted

The proof chain is **not** emitted by the SWRL rules themselves — doing so would
force every rule to be written twice and couple the rule layer to a reification
schema. Instead it is reconstructed after the fact, against the
already-materialized graph. `explain_decision(app_iri, g)` (notebook 05) takes an
application's IRI and walks the known rule structure in reverse: it reads the
application's `:hasDecision`, then its `:hasRiskTier`, then back to the rule
preconditions and signal values that produced them — `Decline → R3 →
HighRisk → (R2a Subprime applicant | R2b weak credit signal)`, `Approve →
R4 → LowRisk → R1`, and an absent decision as `R5` (default Review). It returns a
structured Python dict (`rules_fired`, `evidence`, `decision`, `tier`) rather than
new triples.

That dict is the contract for the LLM synthesis step (§5): the thinking model
turns it into a credit-officer-readable narrative and a second, fast model judges
that narrative against the same dict, so every fact in the prose traces back to a
materialized triple. Reconstruction keeps the rule files declarative while still
giving a downstream consumer "show every rule that fired in deriving the Decline
for application X" — answered deterministically from the trace, not from the LLM.

Pellet's `explain_inference` API is the natural upgrade path here: it would yield
axiom-level OWL justifications (which restriction or disjointness axiom forced a
classification) rather than the hand-coded rule-level walk. That is future work,
not current behavior — today's mechanism is the reverse walk described above.

---

## 3. Signal Fusion & Rules

Rules consume `:RiskSignal` instances, not raw datatype properties. The
convention: an applicant's raw attributes (FICO, debt-to-income, employment)
live on `:Applicant`, but each application emits one or more `:RiskSignal`
instances whose `:signalValue` is a normalized 0–1 score computed at ingest.
The reasoner fuses signals into a risk tier, then a tier into a decision. This
makes the demonstration a genuine signal-fusion story rather than a thin wrapper
over datatype comparisons — the signal layer is actually exercised.

Five rules form the decision pipeline. R1–R4 are SWRL; R5 is a SPARQL UPDATE.

| Rule | Plain-English reading |
|---|---|
| **R1** | If the applicant is Prime tier and the application emits a credit-score signal with normalized value ≥ 0.8, the application is **Low Risk**. |
| **R2a** | If the applicant is Subprime tier, the application is **High Risk**. |
| **R2b** | If the application emits a credit-score signal with normalized value < 0.3, the application is **High Risk**. |
| **R3** | If the application is High Risk, its decision is **Decline**. |
| **R4** | If the application is Low Risk *and* emits an employment-stability signal ≥ 0.7 *and* the requested amount ≤ 100,000, its decision is **Approve** (auto-approval fusing two signal types). |

R2 is split into R2a and R2b because SWRL has no disjunction in the antecedent —
the "two rules for one disjunction" pattern is the standard SWRL/Datalog idiom.
R4 demonstrates fusion across two distinct signal types (credit-score-derived
tier plus employment stability) gated by a numeric threshold on the requested
amount.

### 3.1 R5: default-to-Review as a SPARQL UPDATE

R5 — "any application with no decision defaults to Manual Review" — is
**deliberately not a SWRL rule**. SWRL has no negation-as-failure; under the
open-world assumption and the monotonicity of DL reasoning, "no decision asserted"
cannot be distinguished from "decision unknown." R5 is therefore implemented as a
post-hoc SPARQL UPDATE:

```sparql
INSERT { ?app :hasDecision :Review }
WHERE {
    ?app a ?type .
    FILTER (?type IN (:CreditApplication, :MortgageApplication,
                      :PersonalLoanApplication, :AutoLoanApplication))
    FILTER NOT EXISTS { ?app :hasDecision ?d }
}
```

The subtypes are enumerated explicitly because rdflib's `.update()` runs without
subclass reasoning: a plain `?app a :CreditApplication` would not match a
`:MortgageApplication` individual, so the update would silently skip every
application declared only as a subtype. `FILTER NOT EXISTS` then gives the
closed-world negation that SWRL structurally cannot.
The system is honest about this: it is a hybrid stack — SWRL for monotonic
derivations, SPARQL UPDATE for defaults, SHACL for guardrails — not a workaround.
This is exactly where a formalized ontology does *not* beat a procedural
if/else fallthrough, and the design surfaces that rather than hiding it.

---

## 4. Validation Layer

SHACL shapes (`ontology/shapes.ttl`) validate the *shape of the data* —
distinct from OWL, which *infers new facts*. The distinction is closed-world
versus open-world: OWL never concludes a constraint is violated because a
missing fact is merely unknown; SHACL treats the graph as complete and reports
what is absent or malformed. OWL is the inference engine; SHACL is the gate.

Eight shapes cover the SHACL taxonomy:

| # | Shape | Constrains |
|---|---|---|
| 1 | `:CreditApplicationShape` | Node shape: every application has exactly one applicant, a positive requested amount, and a term ≥ 1 month. |
| 2 | `:DecisionCardinalityShape` | Cardinality: at most one decision per application (enforces the functional property). |
| 3 | `:CreditScoreRangeShape` | Value range: FICO is an integer in [300, 850]. |
| 4 | `:ApplicantFicoReachableShape` | Property path `(:hasApplicant :hasCreditScore)`: the application's applicant must have a credit score. |
| 5 | `:ApplicationEvidenceShape` | `sh:or`: an application must emit at least one `:CreditScoreSignal` or `:CollateralSignal` (minimal evidence for any decision). |
| 6 | `:ApplicantTierDisjointnessShape` | `sh:not`: an applicant cannot be both Prime and Subprime (a friendlier restatement of the OWL disjointness axiom). |
| 7 | `:SignalFreshnessShape` | SPARQL constraint: a signal's timestamp may not be older than 90 days (`NOW() - "P90D"^^xsd:duration`). |
| 8 | `:ApplicantClosedShape` | Closed shape: an applicant may not carry properties outside the declared vocabulary (declared datatype properties plus a small RDF/OWL allow-list are ignored). |

Each shape carries a human-readable `sh:message` so violation reports read
clearly. (Validation runs on pySHACL with the `shacl_graph` argument explicitly —
the older argument name is silently dropped, which would leave the validator with
no shapes and falsely report conformance.)

---

## 5. LLM Integration Contract

The LLM never holds a credential and never decides anything the symbolic layer
cannot verify.

**Routing.** A local Ollama daemon on `http://127.0.0.1:11434` serves the model
calls. Model names carry a `:cloud` suffix as a routing hint — the daemon
forwards suffixed names to the cloud (authenticated out-of-band by a one-time
`ollama signin`) and loads bare names from local disk weights. The Python client
talks only to localhost and never carries an API key. A fast non-thinking model
(`gemini-3-flash-preview:cloud`) handles SPARQL generation, classification, and
validation; a thinking model (`glm-5.1:cloud`) handles natural-language
synthesis.

**Concurrency.** An `asyncio.Semaphore(3)` caps in-flight requests at three —
matching the upstream Pro-plan quota (over which the cloud returns HTTP 429) and
keeping local models from saturating the Apple Silicon worker pool.

**API specifics.** Output length is set with `num_predict`, not `max_tokens`
(the latter is silently ignored). Thinking models emit chain-of-thought into a
separate `thinking` field while `response` stays empty until reasoning ends; with
too small a `num_predict` budget the request terminates mid-thought with an empty
response, so thinking models use `num_predict ≥ 1000` and the client falls back
to the `thinking` field when `response` is empty.

**The SPARQL whitelist gate.** `scripts/sparql_guard.py` is the symbolic gate
between LLM output and the store. `validate_sparql(query, whitelist, tbox)`
first prepares (parses) the query and rejects syntax errors, then scans every
project-namespace IRI used — both fully-qualified IRIs and prefixed names
resolved against the query's own `PREFIX` declarations — and rejects any that is
not a declared property (whitelist), class, or named individual in the T-Box.
PREFIX declarations are stripped before scanning so the namespace base IRI does
not register as an unknown usage. A hallucinated predicate is caught here,
cheaply, before touching Fuseki.

**Proof-chain explanation flow.** Once an inference is reached, its
reconstructed proof-chain dict (§2.3) is fed to the thinking model to produce a
justification a credit officer could read. A second call to the fast model acts
as an LLM judge, checking the synthesis for hallucinations against that same
chain. The result: answers cite the actual rules that fired (e.g.
R2b → R3) with their signal values, re-run deterministically, and remain
human-verifiable against the chain.

---

## 6. Infrastructure

**Triple store.** Apache Jena Fuseki (with the TDB2 persistent store) runs in
Docker — the only containerized component — on port 3030, pinned to a
`linux/arm64` image for Apple Silicon. TDB2 requires its on-disk location to
exist before startup, so the database directory is created on the host before the
container boots; the store is persisted through a mounted volume.

**Python on the host.** Everything else — reasoning, validation, the LLM client,
the notebooks — runs in a `uv`-managed virtual environment on the host, not in a
container. Pellet (via owlready2) needs a modern JDK; the reasoner pins the Java
executable explicitly. Keeping Python on the host avoids containerizing the
Java/Python reasoning toolchain and keeps the feedback loop tight.

**Notebook-only delivery.** There is no web UI, API server, or CLI front end by
design. The work is delivered as a sequence of JupyterLab notebooks (SPARQL, OWL
inference, SHACL, SWRL rules, the neurosymbolic loop, and a full-pipeline
capstone), each executing top to bottom on a fresh kernel. Notebooks make the
reasoning steps inspectable and reproducible without the weight of a service
layer.

---

## 7. Pipeline Performance

The full pipeline — reset the store, load the T-Box and A-Box, run the Pellet
reasoner and the R5 SPARQL UPDATE, validate with SHACL, and query — runs in a few
seconds end to end on Apple Silicon (Mac mini M4). The graph is small by design
(low thousands of triples), so the reasoner stays well under 500 MB of heap in
practice. The constraint is expressiveness and verifiability, not scale: the
value is in what the symbolic layer can *prove* about each decision, delivered
fast enough to iterate inside a notebook.
