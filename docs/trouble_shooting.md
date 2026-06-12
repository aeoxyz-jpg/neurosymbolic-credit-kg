# Troubleshooting — Indexed by Symptom

> Every trap actually encountered in this project, indexed by **symptom**.

---

## Startup

### Q: `docker compose up` fails with `image with reference ... was found but does not provide the specified platform (linux/arm64)`

A: The image has no ARM64 build. Our `docker-compose.yml` uses
`conceptkernel/jena-fuseki:6.0.0-1` (multi-arch verified). If you switch
images, run `docker manifest inspect <image> | grep arm64` first to confirm an
arm64 manifest exists. `stain/jena-fuseki:5.x` currently has no arm64 build.

---

### Q: Fuseki container exits immediately with `Directory does not exist: /fuseki/databases/credit-risk`

A: TDB2 does not create its data directory automatically. Pre-create it on the
host:
```bash
mkdir -p fuseki_data/credit-risk
docker compose up -d
```

---

### Q: After Colima starts, `docker compose` reports `cd: /Volumes/...: No such file or directory`

A: Colima only mounts `/Users` by default; `/Volumes/*` is not mounted. Restart
with an explicit mount:
```bash
colima stop
colima start --cpu 2 --memory 3 --arch aarch64 --mount /Volumes/<your-drive>:w
```

---

### Q: `curl http://localhost:3030/$/datasets` returns 403 "only localhost access allowed"

A: Fuseki's Shiro configuration restricts admin endpoints to container-internal
localhost. Accessing from the host is treated as a remote connection and is
rejected. **Solution**: don't probe `/$/datasets`; instead issue a SPARQL
`ASK { ?s ?p ?o }` against `/credit-risk/sparql` (the public endpoint).

---

## Python / Reasoning

### Q: `java.lang.UnsupportedClassVersionError: ... class file version 69.0`

A: Your JDK is too old. The bundled Pellet JARs were compiled for Java 25.
Install the latest OpenJDK:
```bash
brew install openjdk  # NOT openjdk@21!
```
`brew install --cask temurin` also works but requires a sudo password.

---

### Q: owlready2 raises `OwlReadyOntologyParsingError: NTriples parsing error` when loading a `.ttl` file

A: owlready2 does not natively support Turtle. Convert to RDF/XML first using
rdflib:
```python
from rdflib import Graph
import tempfile
g = Graph()
g.parse("ontology.ttl", format="turtle")
tmp = tempfile.NamedTemporaryFile(suffix=".owl", delete=False)
g.serialize(destination=tmp.name, format="xml")
onto = owlready2.get_ontology(f"file://{tmp.name}").load()
```
This is encapsulated in `scripts/run_reasoner.py:to_rdfxml_tempfile()`; reuse
it directly.

---

### Q: `set_as_rule(...)` raises `ValueError: Cannot find entity 'CreditApplication'!`

A: `set_as_rule`'s entity lookup does not cross ontology imports. If rules live
in a separate ontology from the T-Box, pass both namespaces explicitly:
```python
r.set_as_rule(body, namespaces=[tbox_onto, rules_onto])
```
See `scripts/_build_rules.py` for the reference implementation.

---

### Q: Running NB02 twice gives different results the second time

A: owlready2 uses a global `default_world` by default; state leaks across cells
and notebook re-executions. Use a fresh `World()` each time:
```python
world = owlready2.World()
onto = world.get_ontology(...).load()
```
NB02 and NB04 both wrap this in a `load_fresh_world()` helper.

---

### Q: I cannot write a SWRL rule for "if no decision exists, default to Review"

A: SWRL does not support negation-as-failure (consequence of the Open World
Assumption + monotonicity constraint). **This is a design constraint, not a
bug.** Use a SPARQL UPDATE as a fallback:
```sparql
INSERT { ?app :hasDecision :Review }
WHERE {
    ?app a :CreditApplication .
    FILTER NOT EXISTS { ?app :hasDecision ?d }
}
```
This is implemented in NB04 and `run_reasoner.py --apply-r5`.

---

## SHACL

### Q: `pyshacl.validate(...)` always returns `conforms=True` regardless of the data I inject

A: **Critical trap.** In pyshacl ≥ 0.30 the shapes-graph parameter was renamed
from `shapes_graph` to `shacl_graph`. The old name is silently swallowed via
`**kwargs`, so the validator sees zero shapes and always reports conformance.

Fix:
```python
validate(data, shacl_graph=shapes, ...)  # NOT shapes_graph
```

After any upgrade or fresh checkout, run `inspect.signature(pyshacl.validate)`
to confirm the parameter name. **Any case where a deliberately-bad fixture
conforms should be investigated here first.**

---

### Q: SHACL `sh:class :PrimeApplicant` does not flag an applicant with FICO 810

A: SHACL does not run OWL DL inference. `:PrimeApplicant` is defined by an
equivalent class; Pellet must materialize the type assertion before SHACL can
check it. The correct pipeline is:
```
A-Box → Pellet (materialize types) → inferred graph → SHACL (validate types)
```
NB03 §6 demonstrates this combination.

---

## Notebooks / Jupyter

### Q: `jupyter nbconvert --execute` in a verify script raises `ModuleNotFoundError: No module named 'rdflib'`

A: The subprocess resolves `jupyter` from `PATH`, which may point to the system
Python (no venv dependencies). Two fixes are both required:
1. Register the named kernel:
   ```bash
   .venv/bin/python -m ipykernel install --user --name=credit-risk-kg
   ```
2. Set `kernelspec.name` to `credit-risk-kg` in the notebook (builders already
   do this).
3. In verify scripts, launch Jupyter via `[sys.executable, "-m", "jupyter", ...]`.

---

### Q: The notebook runs, but after changing the ontology NB02 shows the same results

A: Most likely owlready2 state was not cleared. Do a full **Restart Kernel and
Run All**, or switch to the `load_fresh_world()` pattern.

---

## LLM Integration (Phase D)

### Q: Ollama tries to pull tens of GB of local weights for `glm-5.1`

A: The model name is missing the `:cloud` suffix. `:cloud` is a **routing
signal to the local daemon** — with it, the daemon forwards the request to
ollama.com using credentials set via `ollama signin`; without it, the daemon
treats the name as a local model and attempts to download the weights.

---

### Q: A `glm-5.1:cloud` call returns `response: ""` but `eval_count` is greater than 0

A: GLM-5.1 is a **thinking model** — chain-of-thought goes into the `thinking`
field; `response` stays empty until the thinking phase completes. If
`num_predict` is too small (< 500), the call stops during the thinking phase and
`response` remains empty.

Fix:
- Set `num_predict ≥ 1500` (typical budget for a thinking model).
- Or switch to `gemini-3-flash-preview:cloud` (also a thinking model but
  converges faster).
- `ollama_client.OllamaCloudClient.call` already falls back to `thinking` when
  `response` is empty, but giving the model enough budget is the cleaner
  solution.

---

### Q: Setting `max_tokens=2000` does not produce longer outputs from Ollama

A: Ollama uses `num_predict`, not `max_tokens`. The OpenAI-compatible layer may
accept both, but the native API only honors `num_predict`.

---

### Q: LLM-generated SPARQL uses `PREFIX ex: <http://example.org/>` instead of our namespace

A: The system prompt did not emphasize the required namespace. Add this
explicitly:
```
Required PREFIX (DO NOT invent your own namespace):
PREFIX : <https://nikko.dev/ontology/credit#>
```
Even then the model may not comply — which is exactly why NB05 includes a
SPARQL validator and falls back to a canned query when validation fails
(the "trust but verify" pattern).

---

### Q: The LLM wraps SPARQL in a ` ```sparql ... ``` ` markdown fence

A: Models wrap output in fences even when told not to. The `NB05.strip_fence()`
helper uses a regex to strip leading and trailing fences before passing the
query to the validator.

---

### Q: I set `asyncio.gather(*[10 requests])` but they run sequentially

A: Most likely the client is not using `httpx.AsyncClient` (sync httpx supports
`gather` at the call site but serializes underneath), or the Semaphore is set
too small. Verify:
```python
print(cli._max_in_flight)  # should equal OLLAMA_CONCURRENCY
```

---

### Q: `curl http://127.0.0.1:11434/api/tags` is refused

A: The Ollama daemon is not running. Start it:
```bash
brew services start ollama   # or: ollama serve (foreground)
```
On first install: `brew install ollama` + `ollama signin` (writes cloud
credentials into the daemon).

---

## Data

### Q: Running `load_ontology.py` three times leaves only the last file's triples in Fuseki

A: You likely have an earlier version (now fixed) that used PUT mode. The
current default is POST (append). Pair it with `reset_fuseki.py` for
idempotency. To intentionally replace an entire named graph:
```bash
python scripts/load_ontology.py --replace ontology/something.ttl
```

---

### Q: SPARQL cannot find `?app a :CreditApplication` but can find `?app a :MortgageApplication`

A: Fuseki does not enable OWL/RDFS inference by default. Superclass queries not
returning results is expected behavior. Two options:
1. UNION all subclasses in SPARQL (what `verify_phase_a.py` does).
2. Enable an inference reasoner in the Fuseki configuration (out of scope for
   this project).

NB02 demonstrates client-side RL inference using rdflib as a workaround.

---

## Last resort

If none of the above resolves your issue:

1. **Full reset**:
   ```bash
   docker compose down -v
   mkdir -p fuseki_data/credit-risk
   docker compose up -d
   python scripts/reset_fuseki.py
   python scripts/load_ontology.py ontology/credit_risk.ttl
   python scripts/load_ontology.py ontology/instances/customers.ttl
   python scripts/load_ontology.py ontology/instances/applications.ttl
   python scripts/verify_phase_a.py
   ```
2. Restart the Jupyter kernel.
3. For inference issues, run `python scripts/run_reasoner.py --print-summary`
   to establish a baseline.
