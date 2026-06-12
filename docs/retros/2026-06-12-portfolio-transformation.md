# Retro — Portfolio Transformation (2026-06-12)

**Scope:** transformed the repo from a bilingual learning lab into the public
portfolio release: English README/docs/notebooks, 14-test pytest suite,
`sparql_guard` extraction, two-job CI, notebooks committed with executed
outputs, rebuilt single-commit history, published to GitHub with green CI.

The transformation doubled as a full audit: re-executing every notebook and
verifying each narrative claim against its actual output surfaced a dozen
defects that months of "runs without errors" verification never caught.
Lessons below, most specific first.

## Technical lessons

### 1. `owl:AllDisjointClasses` does not constrain punned individuals

The risk-tier classes are punned (`owl:Class` + `owl:NamedIndividual`,
`ontology/credit_risk.ttl:182-195`). A functional-property clash on
`:hasRiskTier` (one application assigned two different tier *individuals*)
does NOT make Pellet report inconsistency: disjointness of the *classes* says
nothing about the punned *individuals*, so the clash collapses to a harmless
`owl:sameAs`. NB04's conflict demo only works after injecting
`owl:differentFrom` between the tier individuals (kept in-cell by design —
the ontology itself does not assert it). If you need UNA-style behavior on
punned individuals, you must assert `owl:differentFrom`/`owl:AllDifferent`
explicitly.

### 2. `sync_reasoner_pellet` without `infer_property_values=True` silently starves SWRL

DL-defined class memberships (`:SubprimeApplicant` via datatype facets) are
not materialized without the flag, so SWRL class atoms like
`SubprimeApplicant(?a)` match nobody — rules "run" and produce zero
inferences with no error. Three NB04 cells had this bug; outputs showed
`fires on 0` while the narrative claimed coverage. Reference implementation:
`scripts/run_reasoner.py` (which always passes the flag).

### 3. pySHACL's text report does not contain shape names

Counting violations by grepping the report text for a shape name returns 0
forever. Count `sh:ValidationResult`-typed nodes in the report *graph* (the
second return value of `validate()`) instead. See `scripts/_build_nb03.py`,
§4 cell.

### 4. `gemini-3-flash-preview:cloud` is a thinking model too

Not just `glm-5.1`. With small `num_predict` (200), the thinking phase eats
the budget and the JSON response truncates mid-fence. Two rules for any LLM
JSON output: `num_predict ≥ 1500`, and strip markdown fences before
`json.loads` (NB05 judge cell does both).

### 5. "Executes with 0 errors" is not "outputs are correct"

Every phase-verify script checked notebooks for *error outputs* and passed
for months. Re-executing with the requirement "committed outputs must support
every narrative claim" exposed: a disjointness check printing `[]` under a
"violation detected" caption (NB02), a violation counter hardwired to 0
(NB03), three rule demos firing on nobody plus an R5 cell inflating 18 to 30
via stale world reuse (NB04), and a judge score of `-1 (unparseable)`
committed as if meaningful (NB05). The working check: for each claim-bearing
cell, read the actual output and ask "does this show what the text says it
shows?" — mechanically, per cell, no skimming.

### 6. Distilling a design spec into public docs promotes aspirations to facts

The internal spec described a planned Pellet `explain_inference` pipeline;
the first draft of `docs/architecture.md` presented it as implemented (down
to a named graph and example query that could never run). The same phantom
claim was then found in NB05's intro and the operator notes — false claims
replicate across artifacts, so after correcting one copy, grep for all
others. Rule: every "the system does X" sentence in public docs needs a
grep-level pointer to the artifact that does X.

### 7. Late data edits invalidate committed execution outputs

Removing `@zh` labels from the ontology (975 → 925 triples) after notebooks
had been executed left committed outputs showing the old count — a fresh
clone would print different numbers than the repo displays. Freeze
data/code first, execute-and-commit outputs last; if data must change late,
re-execute everything downstream and grep docs for the stale numbers.

### 8. `astral-sh/setup-uv@v5` with `python-version` provisions `.venv` itself

A subsequent `uv venv` fails with "already exists" and kills the job. Just
`uv pip install` into the provisioned environment (`.github/workflows/ci.yml`).
This was flagged as a "low risk" review note pre-push and materialized on the
first CI run — environment assumptions that can only be verified on the real
runner deserve a planned fix-forward, not hope.

## Verification methods that earned their keep

- Per-cell narrative↔output table (claim | actual output | match?) for every
  notebook — found all the §5 defects above.
- Claim-by-claim grounding of docs against artifacts (`grep` for the API/IRI
  a sentence names) — found §6.
- Final integration review across the whole change set (not per-task) —
  found §7 and the CI format blocker after all per-task reviews had passed.
- In-memory Fuseki (`--mem`) for CI: tested locally with `docker run` before
  committing the workflow, which eliminated the TDB2 volume-permissions risk
  class entirely.
