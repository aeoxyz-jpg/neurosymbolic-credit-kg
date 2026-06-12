"""Builder for notebooks/99_full_pipeline.ipynb. SPEC §8.6 capstone."""

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

md("""# NB99 — Full Pipeline

**This notebook demonstrates:**

- End-to-end pipeline from reset → load → reason → validate → query → explain
- Per-step performance profiling using a `step()` context manager
- Intentional data injection to confirm SHACL catches violations

## Pipeline

```
[1] reset_fuseki + load TTL files
       │
[2] Pellet + SWRL R1-R4 reasoning  ──┐
       │                              │
[3] R5 SPARQL UPDATE fallback         ├→ inferred.ttl
       │                              │
[4] Push inferred back to Fuseki     ┘
       │
[5] SHACL validation (expect 0 violations)
       │
[6] SPARQL query all decisions
       │
[7] Select 3 cases for NL explanation (LLM)
       │
[8] Inject bad data → SHACL catches it
```

## Prerequisites

- Phases A–D complete
- Fuseki running on localhost:3030
- (Optional) Ollama daemon running (`http://127.0.0.1:11434`); if absent, LLM step uses canned output""")

md("## 0. Setup + Timer")

md("""> **🔧 Tech**: Pipeline orchestration + per-step profiling
> **🎯 Goal**: Prepare a `step()` context manager that records each step duration in `timings`
> **✅ Verify**: "Capstone start." is printed; `timings = {}` initialized
> **📚 Learn**: The capstone skeleton — every subsequent step is wrapped in `with step("name"):` for performance analysis""")

code("""import os, sys, time, json, subprocess
from pathlib import Path
from contextlib import contextmanager
from dataclasses import dataclass

PROJECT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
sys.path.insert(0, str(PROJECT / "scripts"))

timings: dict[str, float] = {}

@contextmanager
def step(name: str):
    print(f"\\n→ [{name}] starting...")
    t0 = time.perf_counter()
    yield
    dt = time.perf_counter() - t0
    timings[name] = dt
    print(f"  ✓ [{name}] done in {dt:.2f}s")

print("Capstone start.")""")

# ─────────────────────────────────────────────────────────────────────
md("## Step 1 — Reset + Load (Phase A recap)")

md("""> **🔧 Tech**: Dataset reset + bulk Turtle ingestion (T-Box + A-Box)
> **🎯 Goal**: Clear the `credit-risk` dataset, then load ontology + customer instances + application instances
> **✅ Verify**: Both subprocess calls return code 0; ~925 triples loaded into Fuseki
> **📚 Learn**: The "reset-load" pattern makes experiments reproducible; idempotency comes from PUT, not POST""")

code("""with step("reset_fuseki"):
    r = subprocess.run([sys.executable, str(PROJECT / "scripts" / "reset_fuseki.py")],
                        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

with step("load_3_files"):
    for f in ["credit_risk.ttl", "instances/customers.ttl", "instances/applications.ttl"]:
        r = subprocess.run([
            sys.executable, str(PROJECT / "scripts" / "load_ontology.py"),
            str(PROJECT / "ontology" / f)
        ], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr""")

# ─────────────────────────────────────────────────────────────────────
md("## Step 2 + 3 — Pellet + SWRL R1-R4 + R5 SPARQL UPDATE (Phase C)")

md("""> **🔧 Tech**: OWL 2 DL classification + SWRL forward chaining + SPARQL UPDATE fallback
> **🎯 Goal**: Run Pellet to materialize `:PrimeApplicant` DL inferences + SWRL R1-R4; then R5 SPARQL UPDATE fills undecided applications
> **✅ Verify**: returncode=0; stdout summary shows 20+ new inferences + R5 filled some Review decisions
> **📚 Learn**: SWRL cannot handle negation-as-failure (R5 needs "no decision yet"), so R5 must be a SPARQL UPDATE — this is the capability boundary between W3C standards""")

code("""with step("reasoner_full_pipeline"):
    env = {**os.environ, "PATH": f"/opt/homebrew/opt/openjdk/bin:{os.environ.get('PATH','')}"}
    r = subprocess.run([
        sys.executable, str(PROJECT / "scripts" / "run_reasoner.py"),
        "--apply-r5", "--print-summary",
        "--output", str(PROJECT / "ontology" / "inferred.ttl"),
    ], capture_output=True, text=True, env=env)
    print(r.stdout[-1500:])
    assert r.returncode == 0, r.stderr""")

# ─────────────────────────────────────────────────────────────────────
md("## Step 4 — Push inferred.ttl to Fuseki (named graph, keeps ABox clean)")

md("""> **🔧 Tech**: SPARQL Graph Store Protocol — named graph upload
> **🎯 Goal**: PUT `inferred.ttl` into a named graph so the original ABox is not polluted
> **✅ Verify**: HTTP 200/201/204 + printed byte count matches file size
> **📚 Learn**: Named graphs separate "raw facts" from "inferred triples" — provenance is immediately clear when tracing back decisions""")

code("""import httpx
INFERRED_GRAPH = "urn:graph:inferred"

with step("upload_inferred"):
    data = (PROJECT / "ontology" / "inferred.ttl").read_bytes()
    r = httpx.put(
        f"{os.environ.get('FUSEKI_URL','http://localhost:3030')}/credit-risk/data",
        params={"graph": INFERRED_GRAPH},
        content=data,
        headers={"Content-Type": "text/turtle"},
        timeout=30.0,
    )
    print(f"  uploaded {len(data)} bytes → graph <{INFERRED_GRAPH}>")
    assert r.status_code in (200, 201, 204), r.text""")

# ─────────────────────────────────────────────────────────────────────
md("## Step 5 — SHACL Validation (on post-inference graph)")

md("""> **🔧 Tech**: SHACL constraint validation on post-inference graph
> **🎯 Goal**: Merge T-Box + A-Box + inferred into one rdflib Graph; run SHACL shape checks
> **✅ Verify**: `conforms=True`, violations=0 (clean data should have zero violations)
> **📚 Learn**: SHACL is most meaningful *after* reasoning — e.g. "Prime applicant must have SSN" depends on Pellet having classified the applicant as PrimeApplicant first""")

code("""from pyshacl import validate
from rdflib import Graph

with step("shacl_validate"):
    data = Graph()
    for f in ["credit_risk.ttl", "instances/customers.ttl", "instances/applications.ttl"]:
        data.parse(str(PROJECT / "ontology" / f), format="turtle")
    data.parse(str(PROJECT / "ontology" / "inferred.ttl"), format="turtle")

    shapes = Graph()
    shapes.parse(str(PROJECT / "ontology" / "shapes.ttl"), format="turtle")

    conforms, _, report = validate(data, shacl_graph=shapes,
                                    inference="rdfs", advanced=True)
    print(f"  Conforms: {conforms}")
    n_v = report.count("Constraint Violation")
    print(f"  Violations: {n_v}")
    if not conforms:
        # Show first 3 violations
        for chunk in report.split("Constraint Violation")[1:4]:
            print("  ----")
            print("    " + chunk[:200].strip().replace("\\n", "\\n    "))""")

# ─────────────────────────────────────────────────────────────────────
md("## Step 6 — SPARQL Query: All Decisions (default graph + named inferred graph union)")

md("""> **🔧 Tech**: SPARQL SELECT with OPTIONAL + GRAPH clauses
> **🎯 Goal**: Cross-query default graph (ABox) and named graph (inferred) to retrieve tier + decision for every application
> **✅ Verify**: DataFrame has ≥ 30 rows; `tier` / `decision` value_counts show a reasonable distribution
> **📚 Learn**: SPARQL's `GRAPH <iri>` makes named graphs addressable — the key capability that upgrades plain RDF to a *quad store*""")

code("""import pandas as pd

with step("sparql_summary"):
    SPARQL = f"{os.environ.get('FUSEKI_URL','http://localhost:3030')}/credit-risk/sparql"
    query = '''
    PREFIX : <https://nikko.dev/ontology/credit#>
    SELECT ?app ?tier ?decision WHERE {{
        {{ ?app a ?type . FILTER (?type IN (:MortgageApplication, :PersonalLoanApplication, :AutoLoanApplication)) }}
        OPTIONAL {{ GRAPH <{INFERRED_GRAPH}> {{ ?app :hasRiskTier ?tier }} }}
        OPTIONAL {{ GRAPH <{INFERRED_GRAPH}> {{ ?app :hasDecision ?decision }} }}
    }} ORDER BY ?app
    '''.format(INFERRED_GRAPH=INFERRED_GRAPH)
    r = httpx.post(SPARQL, data={"query": query},
                    headers={"Accept": "application/sparql-results+json"}, timeout=15)
    j = r.json()
    rows = [{c: b.get(c,{}).get("value","").split("#")[-1]
             for c in j["head"]["vars"]}
            for b in j["results"]["bindings"]]
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
    print(f"\\nTier distribution:\\n{df['tier'].value_counts().to_string()}")
    print(f"\\nDecision distribution:\\n{df['decision'].value_counts().to_string()}")""")

# ─────────────────────────────────────────────────────────────────────
md("## Step 7 — NL Explanation for Three Cases (LLM)")

md("""> **🔧 Tech**: Proof-chain extraction from inferred graph + case selection
> **🎯 Goal**: Inline simplified `explain()` — extracts the rule chain for each decision from the inferred graph; selects one Approve, one Decline, one Review case
> **✅ Verify**: `cases` dict holds 3 app IDs with distinct decisions; `LIVE` reflects daemon status
> **📚 Learn**: Explainable AI is not post-hoc storytelling — the proof chain comes directly from the symbolic reasoner; the LLM only translates it into natural language""")

code("""import asyncio
from rdflib import Namespace, URIRef
from ollama_client import OllamaCloudClient, LLMRequest, fast_model, deep_model
from dotenv import load_dotenv; load_dotenv()

CR = Namespace("https://nikko.dev/ontology/credit#")
NS_STR = "https://nikko.dev/ontology/credit#"
def _daemon_reachable() -> bool:
    try:
        return httpx.get(os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
                         + "/api/tags", timeout=1.5).status_code == 200
    except Exception:
        return False

LIVE = _daemon_reachable()

# Inline simplified explain_decision (reused from NB05 pattern)
def explain(app_iri: URIRef, g: Graph) -> dict:
    chain = {"app": app_iri.split("#")[-1], "rules": [], "evidence": {}}
    decisions = list(g.objects(app_iri, CR.hasDecision))
    if not decisions: return chain
    d = str(decisions[0]).split("#")[-1]
    chain["decision"] = d
    if d == "Decline":
        chain["rules"].append("R3 (HighRisk → Decline)")
        a = next(g.objects(app_iri, CR.hasApplicant), None)
        if a and CR.SubprimeApplicant in g.objects(a, None):
            chain["rules"].insert(0, "R2a (Subprime)")
            chain["evidence"]["applicant"] = str(a).split("#")[-1]
    elif d == "Approve":
        chain["rules"] += ["R1 (Prime+strong signal)", "R4 (LowRisk+stable+small)"]
    elif d == "Review":
        chain["rules"].append("R5 (default fallthrough)")
    return chain

# Pick one case per decision type
cases = {}
for app, tier, dec in zip(df["app"], df["tier"], df["decision"]):
    if dec and dec not in cases:
        cases[dec] = app
    if len(cases) == 3: break

print("Selected cases:", cases)""")

md("""> **🔧 Tech**: Async LLM synthesis with deterministic canned fallback
> **🎯 Goal**: Feed proof chain to LLM for a natural-language explanation; fall back to canned text when daemon is offline
> **✅ Verify**: All three cases print chain + NL explanation; when LIVE=True the explanation is model-generated
> **📚 Learn**: The neural layer (LLM) handles *expression*; the symbolic layer (rule chain) guarantees *correctness* — this is the core division of labor in neurosymbolic AI""")

code("""async def explain_with_llm(app_id: str) -> tuple[dict, str]:
    iri = URIRef(NS_STR + app_id)
    chain = explain(iri, data)

    canned_synth = {
        "Decline": f"Application declined. Reason: {chain['evidence'].get('applicant','-')} is subprime tier (R2a triggers HighRisk); R3 declines.",
        "Approve": "Application approved. Prime tier + strong credit signal → R1 LowRisk; stable employment and compliant loan amount → R4 Approve.",
        "Review":  "Application sent to manual review. No automatic rule (R1-R4) fired a clear classification; R5 defaulted to Review.",
    }

    if LIVE:
        async with OllamaCloudClient() as cli:
            text = await cli.call(LLMRequest(
                model=deep_model(),
                system="You are a credit-decision explainer. In one or two sentences explain the decision reason, fact-driven.",
                prompt=json.dumps(chain, ensure_ascii=False),
                temperature=0.2, num_predict=1500))  # thinking model
    else:
        text = canned_synth.get(chain.get("decision", ""), "(no canned)")
    return chain, text

with step("nl_synthesis_3_cases"):
    for decision_type, app_id in cases.items():
        chain, explanation = await explain_with_llm(app_id)
        print(f"\\n• {app_id} → {decision_type}")
        print(f"  Chain: {chain['rules']}")
        print(f"  NL:    {explanation}")""")

# ─────────────────────────────────────────────────────────────────────
md("""## Step 8 — Inject Bad Data; SHACL Catches It

Add a second contradictory decision to one application, then run SHACL to confirm the violation is caught.""")

md("""> **🔧 Tech**: SHACL `sh:maxCount 1` cardinality constraint — negative test
> **🎯 Goal**: Copy the clean graph; add both Approve and Decline to `:App_M01`; run SHACL and confirm the contradiction is caught
> **✅ Verify**: `conforms=False`; at least 1 violation (maxCount on :hasDecision)
> **📚 Learn**: A validator proves its worth on *bad* data — clean data passing is not enough (SPEC §11.19 false-positive trap)""")

code("""with step("shacl_catches_bad_data"):
    bad = Graph()
    for t in data: bad.add(t)
    bad.add((CR.App_M01, CR.hasDecision, CR.Approve))
    bad.add((CR.App_M01, CR.hasDecision, CR.Decline))

    conforms, _, report = validate(bad, shacl_graph=shapes,
                                    inference="rdfs", advanced=True)
    print(f"  Conforms after injection: {conforms}")
    assert not conforms, "SHACL did not catch the contradiction — check shapes.ttl + pyshacl version"
    n_v = report.count("Constraint Violation")
    print(f"  Caught {n_v} violations (expected >= 1)")""")

# ─────────────────────────────────────────────────────────────────────
md("## Performance Profile")

md("""> **🔧 Tech**: End-to-end performance profiling + ASCII bar chart
> **🎯 Goal**: Print each step's duration in descending order with a bar chart; summarize total
> **✅ Verify**: Total < 60s (mock) / < 120s (live LLM); Pellet is the dominant cost
> **📚 Learn**: Neurosymbolic AI performance profile — the symbolic backbone (Pellet/SHACL) has predictable cost; the neural surface (LLM) varies with network; decoupling makes the system both deterministic and flexible""")

code("""print("Timing breakdown:")
for k, v in sorted(timings.items(), key=lambda kv: -kv[1]):
    bar = "█" * int(v * 2)
    print(f"  {k:32}  {v:6.2f}s  {bar}")
print(f"\\nTotal: {sum(timings.values()):.2f}s")""")

md("""**Typical bottlenecks** (Mac mini M4 16 GB):

- `reasoner_full_pipeline` (Pellet + SWRL): **most expensive** ~10-25s
- `load_3_files`: ~2-3s (three HTTP POST requests)
- `shacl_validate`: ~1-2s
- `sparql_summary` / `upload_inferred`: < 1s
- `nl_synthesis_3_cases`: depends on LLM (mock < 1s; live ~5-10s/request, ~15-30s total serial)

Total < 1 minute (mock) / ~1 minute (live) — well within the SPEC §9 Phase E 5-minute gate.

**First run may add 10-20s** (Pellet JIT warm-up + image pull).""")

# ─────────────────────────────────────────────────────────────────────
md("""## You Should Now Be Able To

- [ ] Run the full reset → load → reason → validate → query → explain pipeline
- [ ] Identify Pellet as the current bottleneck in the performance profile
- [ ] Extract `focusNode` + `sourceShape` from a SHACL ValidationReport
- [ ] Know which `.ttl` file or SWRL rule to edit for a new requirement (e.g. "raise mortgage approval threshold to 80k")
- [ ] Explain to a non-technical colleague why this system is more reliable than an if/else business-rules engine

## Next Steps

Phase E code is now complete. Remaining optional deliverables:
- `docs/ontology_design.md` — class hierarchy + property design rationale
- `docs/reasoning_cheatsheet.md` — RL/DL/SHACL/SWRL decision intuition
- `docs/trouble_shooting.md` — user-friendly version of the pitfalls in SPEC §11""")

# ─────────────────────────────────────────────────────────────────────
nb.cells = cells
out = Path(__file__).resolve().parent.parent / "notebooks" / "99_full_pipeline.ipynb"
with out.open("w") as f:
    nbf.write(nb, f)
print(f"✓ Wrote {out}  ({len(cells)} cells)")
