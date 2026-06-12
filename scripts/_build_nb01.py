"""Builder for notebooks/01_sparql_basics.ipynb.

Run: .venv/bin/python scripts/_build_nb01.py
Output: notebooks/01_sparql_basics.ipynb (overwrites existing).

This is a developer tool, not part of the user-facing deliverable. It exists
because hand-editing .ipynb JSON is fragile (SPEC §10.1 / file rules).
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

# ─────────────────────────────────────────────────────────────────────
md("""# NB01 — SPARQL Basics

## Goals

**This notebook demonstrates:**

1. Writing `SELECT` / `ASK` / `DESCRIBE` / `CONSTRUCT` queries
2. Controlling match patterns with `FILTER` / `OPTIONAL` / `UNION`
3. Aggregate queries (`GROUP BY` / `HAVING` / `COUNT` / `AVG`)
4. Multi-hop traversal with property paths (`/`, `*`, `+`, `^`, `|`)
5. Graph mutation with SPARQL `UPDATE` (INSERT / DELETE / INSERT WHERE)

## Prerequisites

- Fuseki running at `http://localhost:3030` (`docker compose up -d`)
- Dataset `credit-risk` loaded with T-Box + two instance files
- If unsure, run: `python scripts/verify_phase_a.py`

## Kernel Reset Instructions

This notebook uses SPARQL UPDATE to modify the graph. **Before re-running INSERT/DELETE cells**, reset to a clean state:
```bash
python scripts/reset_fuseki.py
python scripts/load_ontology.py ontology/credit_risk.ttl
python scripts/load_ontology.py ontology/instances/customers.ttl
python scripts/load_ontology.py ontology/instances/applications.ttl
```""")

# ─────────────────────────────────────────────────────────────────────
md("## 0. Setup — SPARQL Client Helpers")

md(
    "> **🔧 Tech**: SPARQL HTTP Protocol (Query + Update endpoints)  \n"
    "> **💻 Platform**: httpx + Fuseki `/sparql` and `/update` endpoints  \n"
    "> **🎯 Goal**: Define `select` / `ask` / `construct` / `update` helpers and run a connectivity health check  \n"
    "> **✅ Verify**: Returns a DataFrame showing total triple count (should be > 0)  \n"
    "> **📚 Takeaway**: SPARQL protocol is HTTP POST — the `Accept` header determines response format (JSON / Turtle)"
)

code("""import os
from dataclasses import dataclass

import httpx
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

FUSEKI = os.environ.get("FUSEKI_URL", "http://localhost:3030").rstrip("/")
DATASET = os.environ.get("FUSEKI_DATASET", "credit-risk")
SPARQL_QUERY = f"{FUSEKI}/{DATASET}/sparql"
SPARQL_UPDATE = f"{FUSEKI}/{DATASET}/update"

PREFIX = '''
PREFIX :     <https://nikko.dev/ontology/credit#>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:  <http://www.w3.org/2002/07/owl#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
'''.strip()


def select(q: str) -> pd.DataFrame:
    \"\"\"Run a SELECT query, return rows as a DataFrame (column = variable).\"\"\"
    r = httpx.post(SPARQL_QUERY, data={"query": PREFIX + "\\n" + q},
                   headers={"Accept": "application/sparql-results+json"}, timeout=15.0)
    r.raise_for_status()
    j = r.json()
    cols = j["head"]["vars"]
    rows = [
        {c: b.get(c, {}).get("value") for c in cols}
        for b in j["results"]["bindings"]
    ]
    return pd.DataFrame(rows, columns=cols)


def ask(q: str) -> bool:
    r = httpx.post(SPARQL_QUERY, data={"query": PREFIX + "\\n" + q},
                   headers={"Accept": "application/sparql-results+json"}, timeout=15.0)
    r.raise_for_status()
    return r.json()["boolean"]


def construct(q: str) -> str:
    \"\"\"Run CONSTRUCT or DESCRIBE; return Turtle as a string.\"\"\"
    r = httpx.post(SPARQL_QUERY, data={"query": PREFIX + "\\n" + q},
                   headers={"Accept": "text/turtle"}, timeout=15.0)
    r.raise_for_status()
    return r.text


def update(q: str) -> None:
    r = httpx.post(SPARQL_UPDATE, data={"update": PREFIX + "\\n" + q}, timeout=15.0)
    r.raise_for_status()
    print(f"  ✓ update OK ({r.status_code})")


# Health check — confirm Fuseki is reachable and the dataset is populated
print("Fuseki connected, total triple count:")
select("SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }")
""")

# ─────────────────────────────────────────────────────────────────────
md("""## 1. SELECT — Tabular Queries

The most fundamental SPARQL query form, returning variable bindings as rows. Syntax:

```sparql
SELECT ?var1 ?var2 ... WHERE { pattern }
```

Each triple pattern `?s ?p ?o` is a constraint — all variables must satisfy all patterns simultaneously.""")

md(
    "> **🔧 Tech**: SPARQL `SELECT` + triple pattern matching + `;` predicate list shorthand  \n"
    "> **💻 Platform**: Fuseki SPARQL endpoint + pandas DataFrame  \n"
    "> **🎯 Goal**: Retrieve all `:Applicant` entities with their FICO score and DTI, sorted by FICO descending  \n"
    "> **✅ Verify**: Table has at least 20 rows (≥20 applicants), `?fico` column is monotonically decreasing  \n"
    "> **📚 Takeaway**: Triple patterns are equivalent to SQL JOINs — shared subject `?applicant` automatically colocates multiple properties on the same row"
)

code("""# List all :Applicant FICO scores and DTI values
select(\"\"\"
SELECT ?applicant ?fico ?dti WHERE {
  ?applicant a :Applicant ;
             :hasCreditScore ?fico ;
             :hasDebtToIncomeRatio ?dti .
}
ORDER BY DESC(?fico)
\"\"\")""")

md("""**`;` shorthand**: multiple properties on the same subject can be chained with `;` — the above is equivalent to:
```sparql
?applicant a :Applicant .
?applicant :hasCreditScore ?fico .
?applicant :hasDebtToIncomeRatio ?dti .
```
""")

# ─────────────────────────────────────────────────────────────────────
md("""## 2. FILTER — Conditional Filtering

`FILTER` is a boolean expression applied after pattern matching, removing rows that don't satisfy the condition. Common forms:

- `?x > 700` numeric comparison
- `regex(?name, "abc", "i")` regular expressions
- `isURI(?x)` / `isLiteral(?x)` type checks
- `BOUND(?x)` check whether a variable is bound (used with OPTIONAL)""")

md(
    "> **🔧 Tech**: `FILTER` numeric comparison + `&&` logical AND  \n"
    "> **💻 Platform**: Fuseki SPARQL endpoint  \n"
    "> **🎯 Goal**: Return applicants with FICO ≥ 700 and DTI ≤ 0.35  \n"
    "> **✅ Verify**: Every row has `?fico` ≥ 700 and `?dti` ≤ 0.35  \n"
    "> **📚 Takeaway**: `FILTER` is a post-match predicate — it runs after the triple patterns bind variables, keeping only rows where the boolean holds"
)

code("""# Applicants with FICO >= 700 and DTI <= 0.35
select(\"\"\"
SELECT ?applicant ?fico ?dti WHERE {
  ?applicant a :Applicant ;
             :hasCreditScore ?fico ;
             :hasDebtToIncomeRatio ?dti .
  FILTER (?fico >= 700 && ?dti <= 0.35)
}
ORDER BY DESC(?fico)
\"\"\")""")

md(
    "> **🔧 Tech**: `FILTER regex(...)` — regular expression match on string literals  \n"
    "> **💻 Platform**: Fuseki SPARQL endpoint (built-in XPath regex engine)  \n"
    '> **🎯 Goal**: Find applicants whose `rdfs:label` contains "Senior" or "Physician" (case-insensitive)  \n'
    "> **✅ Verify**: Every row's `?label` contains the target keyword, case-insensitively  \n"
    '> **📚 Takeaway**: `regex(?var, pattern, "i")` — the third argument is a flag; `i` = case-insensitive, `s` = single-line mode'
)

code("""# regex: labels containing "Senior" or "Physician"
select(\"\"\"
SELECT ?a ?label WHERE {
  ?a a :Applicant ;
     rdfs:label ?label .
  FILTER regex(?label, "Senior|Physician", "i")
}
\"\"\")""")

# ─────────────────────────────────────────────────────────────────────
md("""## 3. ASK — Boolean Queries

Returns `true` / `false` — answers "does at least one match exist?" Cheaper than SELECT because the engine can short-circuit after finding the first solution.""")

md(
    "> **🔧 Tech**: `ASK` boolean query  \n"
    "> **💻 Platform**: Fuseki SPARQL endpoint  \n"
    "> **🎯 Goal**: Check whether any `:CreditApplication` with amount > $500k exists in the graph  \n"
    "> **✅ Verify**: Returns a Python `bool` (`True` or `False`)  \n"
    "> **📚 Takeaway**: `ASK` is cheaper than `SELECT` — the engine short-circuits on the first match"
)

code("""# Does any application with amount > $500k exist?
ask(\"\"\"
ASK WHERE {
  ?app a :CreditApplication ;
       :requestedAmount ?amt .
  FILTER (?amt > 500000)
}
\"\"\")""")

md(
    "> **🔧 Tech**: `ASK` + `FILTER NOT EXISTS { ... }` — negative existence check  \n"
    "> **💻 Platform**: Fuseki SPARQL endpoint  \n"
    "> **🎯 Goal**: Check whether any `:Applicant` is missing `:hasCreditScore` (data integrity self-check)  \n"
    "> **✅ Verify**: Clean data should return `False`; `True` means seed data is missing a signal  \n"
    '> **📚 Takeaway**: SPARQL implements negation-as-failure via `NOT EXISTS` — under the closed-world assumption, "not found = does not exist"'
)

code("""# Are there any applicants without :hasCreditScore?
no_score = ask(\"\"\"
ASK WHERE {
  ?a a :Applicant .
  FILTER NOT EXISTS { ?a :hasCreditScore ?s }
}
\"\"\")
print("Exists applicant without FICO?", no_score)""")

# ─────────────────────────────────────────────────────────────────────
md("""## 4. DESCRIBE — Entity Snapshot

`DESCRIBE <iri>` returns all triples where the entity appears as subject or object. The result is Turtle text.

The exact scope is engine-defined; Fuseki returns the Concise Bounded Description (CBD) by default.""")

md(
    "> **🔧 Tech**: `DESCRIBE <iri>` — full entity snapshot  \n"
    "> **💻 Platform**: Fuseki (returns Concise Bounded Description) + `Accept: text/turtle`  \n"
    "> **🎯 Goal**: Print all inbound and outbound triples for `:App_M01` (first 1500 characters)  \n"
    "> **✅ Verify**: Output is valid Turtle containing `:App_M01` type and properties  \n"
    '> **📚 Takeaway**: `DESCRIBE` returns a graph (not a table); the exact "description boundary" varies by engine'
)

code("""# Full profile of App_M01
print(construct("DESCRIBE :App_M01")[:1500])""")

# ─────────────────────────────────────────────────────────────────────
md("""## 5. CONSTRUCT — Synthesizing New Graphs

`CONSTRUCT` returns an RDF graph (not a table). Variables in the template are bound by the WHERE clause, producing new triples.
Commonly used as a "view" or ETL step — deriving new relationships from existing data.""")

md(
    "> **🔧 Tech**: `CONSTRUCT { template } WHERE { pattern }` — derive a new graph  \n"
    "> **💻 Platform**: Fuseki SPARQL endpoint + Turtle output  \n"
    '> **🎯 Goal**: Synthesize a `:hasWarning "high-dti"@en` triple for each applicant with DTI > 0.4  \n'
    '> **✅ Verify**: Output Turtle contains several `:hasWarning "high-dti"@en` lines; nothing is written back to Fuseki  \n'
    '> **📚 Takeaway**: `CONSTRUCT` is a read-only "view" — use it to express derived relationships as ETL output without mutating the store'
)

code("""# Synthesize a "high DTI warning" graph: one :hasWarning triple per applicant with DTI > 0.4
print(construct(\"\"\"
CONSTRUCT {
  ?a :hasWarning "high-dti"@en .
} WHERE {
  ?a a :Applicant ; :hasDebtToIncomeRatio ?dti .
  FILTER (?dti > 0.4)
}
\"\"\")[:600])""")

# ─────────────────────────────────────────────────────────────────────
md("""## 6. OPTIONAL — Outer Joins

Patterns inside `OPTIONAL { ... }` don't have to match — if they don't, variables remain unbound but the row is still returned.
Equivalent to SQL `LEFT OUTER JOIN`.""")

md(
    "> **🔧 Tech**: `OPTIONAL { ... }` — SPARQL left outer join  \n"
    "> **💻 Platform**: Fuseki SPARQL endpoint  \n"
    "> **🎯 Goal**: List all `:MortgageApplication` records, showing co-applicant where present and `null` where absent  \n"
    "> **✅ Verify**: Every mortgage appears exactly once; `?coapp` is `None` for sole-applicant rows  \n"
    "> **📚 Takeaway**: `OPTIONAL` ≡ SQL `LEFT OUTER JOIN` — unmatched variables stay unbound, the row still participates"
)

code("""# All mortgage applications — include co-applicant if present, null if not
select(\"\"\"
SELECT ?app ?applicant ?coapp WHERE {
  ?app a :MortgageApplication ;
       :hasApplicant ?applicant .
  OPTIONAL { ?app :hasCoapplicant ?coapp }
}
ORDER BY ?app
\"\"\")""")

# ─────────────────────────────────────────────────────────────────────
md("""## 7. UNION — Set Union

Two pattern blocks — a row is returned if either branch matches. Variables are aligned by name across branches.""")

md(
    "> **🔧 Tech**: `UNION` + `BIND(literal AS ?var)` injecting a constant discriminator column  \n"
    "> **💻 Platform**: Fuseki SPARQL endpoint  \n"
    "> **🎯 Goal**: Combine mortgage and personal loan applications with a `?type` column tagging the source (excluding auto loans)  \n"
    '> **✅ Verify**: Result contains both `?type` values `"mortgage"` and `"personal"`, no auto loan rows  \n'
    '> **📚 Takeaway**: `UNION` is a non-deduplicating union; `BIND` adds a discriminator tag to each branch — a standard "type column" pattern'
)

code("""# All mortgages and personal loans (no auto loans)
select(\"\"\"
SELECT ?app ?type WHERE {
  { ?app a :MortgageApplication . BIND("mortgage" AS ?type) }
  UNION
  { ?app a :PersonalLoanApplication . BIND("personal" AS ?type) }
}
ORDER BY ?type ?app
\"\"\")""")

# ─────────────────────────────────────────────────────────────────────
md("""## 8. Aggregates — GROUP BY / COUNT / AVG / HAVING

Same semantics as SQL. Non-aggregate columns in `SELECT` must appear in `GROUP BY`.""")

md(
    "> **🔧 Tech**: `GROUP BY` + `COUNT(?x)` aggregate + `FILTER (?x IN (...))` set membership  \n"
    "> **💻 Platform**: Fuseki SPARQL endpoint  \n"
    "> **🎯 Goal**: Count applications by type, sorted by count descending  \n"
    "> **✅ Verify**: Three rows, each `?type` is one of mortgage / personal / auto, `?n` is an integer  \n"
    "> **📚 Takeaway**: Non-aggregate columns in the projection must appear in `GROUP BY` — identical to SQL semantics"
)

code("""# Count by application type
select(\"\"\"
SELECT ?type (COUNT(?app) AS ?n) WHERE {
  ?app a ?type .
  FILTER (?type IN (:MortgageApplication, :PersonalLoanApplication, :AutoLoanApplication))
}
GROUP BY ?type
ORDER BY DESC(?n)
\"\"\")""")

md(
    "> **🔧 Tech**: `GROUP BY` + `AVG` + `HAVING` (post-aggregate filter)  \n"
    "> **💻 Platform**: Fuseki SPARQL endpoint  \n"
    "> **🎯 Goal**: Compute average `:CreditScoreSignal` value per bureau, keeping only bureaus with avg ≥ 0.7  \n"
    "> **✅ Verify**: Every row's `?avg_signal` ≥ 0.7, sorted descending  \n"
    "> **📚 Takeaway**: `HAVING` filters groups *after* aggregation; `FILTER` filters rows *before* — they are not interchangeable"
)

code("""# Average signal value per bureau, only bureaus with avg >= 0.7
select(\"\"\"
SELECT ?bureau (AVG(?v) AS ?avg_signal) (COUNT(?s) AS ?n) WHERE {
  ?s a :CreditScoreSignal ;
     :signalValue ?v ;
     :reportedBy ?bureau .
}
GROUP BY ?bureau
HAVING (AVG(?v) >= 0.7)
ORDER BY DESC(?avg_signal)
\"\"\")""")

# ─────────────────────────────────────────────────────────────────────
md("""## 9. Property Paths — Multi-Hop Traversal

No need to introduce intermediate variables — compose paths directly in the predicate position:

| Syntax | Meaning |
|---|---|
| `p/q` | p **then** q (sequence) |
| `p\\|q` | p or q (alternative) |
| `p*` | p zero or more times (reflexive transitive closure) |
| `p+` | p one or more times |
| `^p` | p in reverse direction |

Example — from an Application directly to the Bureau that reported its signal:
`?app :emittedSignal/:reportedBy ?bureau`""")

md(
    "> **🔧 Tech**: Property path `p/q` (sequence — two hops in one expression)  \n"
    "> **💻 Platform**: Fuseki SPARQL endpoint  \n"
    "> **🎯 Goal**: Follow `:emittedSignal/:reportedBy` to jump from Application to Bureau, skipping the signal intermediate variable  \n"
    "> **✅ Verify**: Each row pairs `?app` with `?bureau`, no signal column; at most 10 rows returned  \n"
    "> **📚 Takeaway**: Property paths make multi-hop joins extremely compact, but intermediate nodes are not projectable — if you need them, write explicit triple patterns"
)

code("""# Each application -> its credit-score signal -> the bureau that reported it
select(\"\"\"
SELECT ?app ?bureau WHERE {
  ?app a :CreditApplication ;
       :emittedSignal/a :CreditScoreSignal ;
       :emittedSignal/:reportedBy ?bureau .
}
ORDER BY ?app
LIMIT 10
\"\"\")""")

md(
    "> **🔧 Tech**: Reverse traversal + `GROUP BY` aggregate  \n"
    "> **💻 Platform**: Fuseki SPARQL endpoint  \n"
    "> **🎯 Goal**: Count how many signals each `:CreditBureau` has reported, sorted by count descending  \n"
    "> **✅ Verify**: One row per bureau, `?reported` is the total number of signals it reported  \n"
    "> **📚 Takeaway**: Reverse traversal doesn't require the `^` operator — placing `?bureau` in object position achieves the same result"
)

code("""# How many signals has each bureau reported?
select(\"\"\"
SELECT ?bureau (COUNT(?sig) AS ?reported) WHERE {
  ?bureau a :CreditBureau .
  ?sig :reportedBy ?bureau .
}
GROUP BY ?bureau
ORDER BY DESC(?reported)
\"\"\")""")

# ─────────────────────────────────────────────────────────────────────
md("""## 10. Subqueries — Nested SELECT

Subqueries enable two-phase logic: aggregate first, then filter on the aggregate.""")

md(
    '> **🔧 Tech**: Nested `SELECT` subquery — two-phase "aggregate then filter"  \n'
    "> **💻 Platform**: Fuseki SPARQL endpoint  \n"
    "> **🎯 Goal**: Find bureaus that reported more signals than the average across all bureaus (above-average activity)  \n"
    "> **✅ Verify**: Each result row has `?n` greater than the global `?avg`  \n"
    '> **📚 Takeaway**: Subqueries are the only way to express "aggregate of aggregates" — SPARQL has no window functions'
)

code("""# Bureaus with above-average signal report counts
select(\"\"\"
SELECT ?bureau ?n WHERE {
  {
    SELECT ?bureau (COUNT(?sig) AS ?n) WHERE {
      ?sig :reportedBy ?bureau .
    } GROUP BY ?bureau
  }
  {
    SELECT (AVG(?cnt) AS ?avg) WHERE {
      SELECT (COUNT(?sig) AS ?cnt) WHERE {
        ?sig :reportedBy ?b .
      } GROUP BY ?b
    }
  }
  FILTER (?n > ?avg)
}
\"\"\")""")

# ─────────────────────────────────────────────────────────────────────
md("""## 11. SPARQL UPDATE — Mutating the Graph

SPARQL 1.1 adds write operations. Three core patterns:

- `INSERT DATA { ... }` — insert literal triples directly
- `DELETE DATA { ... }` — delete literal triples directly
- `INSERT { ... } WHERE { ... }` — derive new triples from query results (rule-based derivation)

`INSERT WHERE` is essentially a lightweight rule engine — expressing "if X then Y" derivation in SPARQL.""")

md(
    "> **🔧 Tech**: SPARQL 1.1 `INSERT DATA { ... }` — insert ground triples  \n"
    "> **💻 Platform**: Fuseki `/update` endpoint + language-tagged literals  \n"
    "> **🎯 Goal**: Write a `:hasNote` annotation to `:Applicant_P01`, then SELECT to confirm the write  \n"
    "> **✅ Verify**: Update prints `✓ update OK`; subsequent SELECT returns the note  \n"
    "> **📚 Takeaway**: `INSERT DATA` is a ground form — no variables allowed in the template; only literal triples"
)

code("""# INSERT DATA: add a business annotation to P01
update(\"\"\"
INSERT DATA {
  :Applicant_P01 :hasNote "VIP client, requires 24h response"@en .
}
\"\"\")
select("SELECT ?note WHERE { :Applicant_P01 :hasNote ?note }")""")

md(
    "> **🔧 Tech**: `INSERT { template } WHERE { pattern }` — derive new triples from query results  \n"
    "> **💻 Platform**: Fuseki `/update` endpoint  \n"
    '> **🎯 Goal**: Write `:hasNote "high-dti-warning"@en` to all applicants with DTI > 0.5  \n'
    "> **✅ Verify**: Subsequent SELECT returns multiple rows (the P01 note from above + all derived high-DTI warnings)  \n"
    '> **📚 Takeaway**: `INSERT WHERE` is a lightweight rule engine — it expresses "if X then Y" derivation entirely in SPARQL'
)

code("""# INSERT WHERE: derive warnings for all applicants with DTI > 0.5
update(\"\"\"
INSERT { ?a :hasNote "high-dti-warning"@en }
WHERE  { ?a a :Applicant ; :hasDebtToIncomeRatio ?dti . FILTER(?dti > 0.5) }
\"\"\")
select("SELECT ?a ?note WHERE { ?a :hasNote ?note }")""")

md(
    "> **🔧 Tech**: `DELETE { template } WHERE { pattern }` — pattern-driven bulk delete  \n"
    "> **💻 Platform**: Fuseki `/update` endpoint  \n"
    "> **🎯 Goal**: Remove all `:hasNote` triples, restoring the graph to its initial state (makes the notebook re-runnable)  \n"
    "> **✅ Verify**: COUNT query returns `?n = 0`; all notes cleared  \n"
    "> **📚 Takeaway**: `DELETE WHERE` is an idempotent cleanup — always clean up UPDATE side effects at the end of a notebook section to avoid polluting subsequent runs"
)

code("""# DELETE WHERE: clean up all notes (keep graph reusable)
update("DELETE { ?a :hasNote ?note } WHERE { ?a :hasNote ?note }")
select("SELECT (COUNT(*) AS ?n) WHERE { ?a :hasNote ?note }")""")

# ─────────────────────────────────────────────────────────────────────
md("""## 12. SERVICE — Federated Queries (Preview)

`SERVICE <endpoint> { ... }` delegates part of the query to a remote SPARQL endpoint, merging results locally.
This is a killer feature — a single query can span DBpedia, Wikidata, or a colleague's endpoint.

**This section shows syntax only** — not executed (requires external network access):

```sparql
SELECT ?bureau ?wikiLabel WHERE {
  ?bureau a :CreditBureau ; rdfs:label ?name .
  SERVICE <https://query.wikidata.org/sparql> {
    ?wikiThing rdfs:label ?wikiLabel .
    FILTER (LANG(?wikiLabel) = "en")
    FILTER (STR(?wikiLabel) = STR(?name))
  }
}
```

⚠️ Wikidata enforces strict rate limits — check the `Retry-After` header before issuing queries in production.""")

# ─────────────────────────────────────────────────────────────────────
md("""## Summary

This notebook covered the full SPARQL 1.1 surface area relevant to RDF knowledge graph work:

- [ ] Write a `SELECT` with `FILTER` returning multi-condition rows
- [ ] Use `OPTIONAL` to express nullable associations
- [ ] Use `GROUP BY` + `COUNT`/`AVG` for aggregation
- [ ] Use property paths (`/`, `+`, `^`) instead of intermediate triple patterns
- [ ] Use `INSERT WHERE` to derive new facts
- [ ] Recognize `SERVICE` as federated query syntax (used in later notebooks)

## Next

NB02 (OWL Inference) shows the same "deriving new facts" operation performed by an OWL reasoner instead of SPARQL UPDATE — comparing where each approach fits.""")

# ─────────────────────────────────────────────────────────────────────
nb.cells = cells
out = Path(__file__).resolve().parent.parent / "notebooks" / "01_sparql_basics.ipynb"
out.parent.mkdir(exist_ok=True)
with out.open("w") as f:
    nbf.write(nb, f)
print(f"✓ Wrote {out}  ({len(cells)} cells)")
