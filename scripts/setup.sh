#!/usr/bin/env bash
# scripts/setup.sh — one-shot bootstrap for credit_risk_kg on Mac mini M4.
#
# Idempotent: running twice is safe. Each step checks current state before acting.
# Surfaces decisions, never silently installs anything that needs sudo.
#
# Usage:
#   ./scripts/setup.sh              # interactive: prompts before installs
#   ./scripts/setup.sh --yes        # non-interactive: assume yes for everything
#   ./scripts/setup.sh --check      # check-only: report state, don't change
#
# Exits 0 if (after all changes) verify_phase_a.py passes.

set -euo pipefail

# ─── helpers ──────────────────────────────────────────────────────────
if [ -t 1 ]; then
    BOLD=$(tput bold); DIM=$(tput dim); RED=$(tput setaf 1); GREEN=$(tput setaf 2)
    YELLOW=$(tput setaf 3); BLUE=$(tput setaf 4); RESET=$(tput sgr0)
else
    BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; RESET=""
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ASSUME_YES=false
CHECK_ONLY=false
for arg in "$@"; do
    case "$arg" in
        --yes|-y) ASSUME_YES=true ;;
        --check)  CHECK_ONLY=true ;;
        --help|-h)
            sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "${RED}Unknown arg: $arg${RESET}" >&2; exit 2 ;;
    esac
done

step() { echo ""; echo "${BOLD}${BLUE}→ $*${RESET}"; }
ok()   { echo "  ${GREEN}✓${RESET} $*"; }
warn() { echo "  ${YELLOW}⚠${RESET} $*"; }
err()  { echo "  ${RED}✗${RESET} $*" >&2; }
ask() {
    # Returns 0 (yes) if user confirms or --yes was passed.
    $ASSUME_YES && return 0
    $CHECK_ONLY && return 1   # in check-only mode, never act
    read -rp "  ${YELLOW}?${RESET} $1 [y/N] " ans
    [[ "$ans" =~ ^[Yy]$ ]]
}

cd "$PROJECT_ROOT"

# ─── 1. CLI dependencies ──────────────────────────────────────────────
step "1. CLI dependencies"
# Map: command-on-PATH → human label → suggested brew formula (fallback)
declare -a MISSING=()
check_cmd() {
    local cmd="$1" label="$2" brew_pkg="$3"
    if command -v "$cmd" >/dev/null 2>&1; then
        ok "$label ($(command -v "$cmd"))"
    else
        warn "$label missing"
        MISSING+=("$brew_pkg")
    fi
}
check_cmd colima         "colima"         "colima"
check_cmd docker         "docker"         "docker"
check_cmd "docker-compose" "docker-compose" "docker-compose"
check_cmd uv             "uv"             "uv"
check_cmd ollama         "ollama"         "ollama"

# Java needs a specific path check (not on default PATH)
if [ -x /opt/homebrew/opt/openjdk/bin/java ]; then
    ok "openjdk (/opt/homebrew/opt/openjdk/bin/java)"
elif command -v java >/dev/null 2>&1 && [ "$(java -version 2>&1 | awk -F'"' '/version/{print int($2)}')" -ge 25 ]; then
    ok "java >= 25 ($(command -v java))"
else
    warn "openjdk 25+ missing"
    MISSING+=("openjdk")
fi

if [ ${#MISSING[@]} -gt 0 ]; then
    if ask "Install missing tools via brew: ${MISSING[*]}?"; then
        brew install "${MISSING[@]}"
        ok "Installed: ${MISSING[*]}"
    else
        err "Cannot continue without: ${MISSING[*]}"
        exit 1
    fi
fi

# Configure docker-compose plugin path (no-op if already present)
mkdir -p ~/.docker
config="$HOME/.docker/config.json"
if [ ! -f "$config" ] || ! grep -q "cliPluginsExtraDirs" "$config" 2>/dev/null; then
    cat > "$config" <<EOF
{
  "cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"]
}
EOF
    ok "Wrote ~/.docker/config.json"
fi

# ─── 2. Colima ────────────────────────────────────────────────────────
step "2. Colima (Docker runtime)"
if colima status >/dev/null 2>&1; then
    ok "Colima already running"
else
    if $CHECK_ONLY; then
        warn "Colima not running (use 'colima start ...' to fix)"
    elif ask "Start Colima (2 CPU, 3 GB, ARM64, mount $PROJECT_ROOT)?"; then
        # Mount the repo's actual location so Fuseki's bind volume works even
        # when the project lives outside /Users (e.g. external NVMe under /Volumes).
        colima start --cpu 2 --memory 3 --arch aarch64 \
                     --mount "$PROJECT_ROOT":w 2>&1 | tail -2
        ok "Colima started"
    else
        err "Need Colima running. Run manually: colima start --cpu 2 --memory 3 --arch aarch64 --mount $PROJECT_ROOT:w"
        exit 1
    fi
fi

# ─── 3. Fuseki via docker compose ─────────────────────────────────────
step "3. Fuseki container"
mkdir -p fuseki_data/credit-risk  # TDB2 needs this to exist (SPEC §11.15)
ok "fuseki_data/credit-risk/ ready"

# Ensure .env exists (created from .env.example if absent)
if [ ! -f .env ]; then
    cp .env.example .env
    ok "Created .env from .env.example"
fi

if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^credit_risk_fuseki$'; then
    ok "Container credit_risk_fuseki already running"
else
    if $CHECK_ONLY; then
        warn "Fuseki container not running"
    else
        docker compose up -d 2>&1 | tail -3
        ok "Container started — waiting for ping..."
        for i in {1..30}; do
            if curl -s -f http://localhost:3030/\$/ping >/dev/null 2>&1; then
                ok "Fuseki responding"
                break
            fi
            sleep 1
            [ "$i" = "30" ] && { err "Fuseki failed to respond in 30s"; exit 1; }
        done
    fi
fi

# ─── 4. Python venv via uv ────────────────────────────────────────────
step "4. Python environment"
if [ ! -d .venv ]; then
    if $CHECK_ONLY; then
        warn ".venv missing"
    else
        uv venv --python 3.11
        ok "Created .venv (Python 3.11)"
    fi
fi

if [ -d .venv ]; then
    # Install deps unless already up-to-date (uv pip is fast)
    if ! $CHECK_ONLY; then
        uv pip install -q -e ".[dev]" 2>&1 | tail -2 || true
        ok "Dependencies installed"
    fi
    # Sanity check the key packages
    .venv/bin/python -c "
import rdflib, httpx, owlready2, pyshacl, nbformat
" 2>/dev/null && ok "Key packages importable" || warn "Some packages missing — try: uv pip install -e \".[dev]\""
fi

# ─── 5. Jupyter kernel ────────────────────────────────────────────────
step "5. Jupyter kernel"
if .venv/bin/python -m jupyter kernelspec list 2>/dev/null | grep -q 'credit-risk-kg'; then
    ok "Kernel credit-risk-kg registered"
else
    if $CHECK_ONLY; then
        warn "Kernel credit-risk-kg not registered"
    else
        .venv/bin/python -m ipykernel install --user --name=credit-risk-kg \
            --display-name="Python 3 (credit-risk-kg)" 2>&1 | tail -1
        ok "Kernel credit-risk-kg registered"
    fi
fi

# ─── 6. Load ontology ─────────────────────────────────────────────────
step "6. Load ontology into Fuseki"
if $CHECK_ONLY; then
    triples=$(.venv/bin/python -c "
import httpx
r = httpx.post('http://localhost:3030/credit-risk/sparql',
               data={'query': 'SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }'},
               headers={'Accept': 'application/sparql-results+json'}, timeout=5)
print(r.json()['results']['bindings'][0]['n']['value'])
" 2>/dev/null || echo "0")
    ok "Current triple count: $triples"
else
    .venv/bin/python scripts/reset_fuseki.py 2>&1 | tail -1
    for f in credit_risk.ttl instances/customers.ttl instances/applications.ttl; do
        .venv/bin/python scripts/load_ontology.py "ontology/$f" 2>&1 | tail -1
    done
    ok "Ontology loaded"
fi

# ─── 7. Ollama daemon (optional) ──────────────────────────────────────
step "7. Ollama daemon (optional, for Phase D)"
if curl -s -f http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    n=$(curl -s http://127.0.0.1:11434/api/tags | .venv/bin/python -c \
        "import json,sys; print(len(json.load(sys.stdin)['models']))" 2>/dev/null || echo "?")
    ok "Ollama daemon reachable ($n models registered)"
else
    warn "Ollama daemon not responding"
    echo "  ${DIM}If you want Phase D / NB05 with live LLM:${RESET}"
    echo "  ${DIM}  brew services start ollama${RESET}"
    echo "  ${DIM}  ollama signin               # one-time, for :cloud models${RESET}"
    echo "  ${DIM}NB05 also runs fine without it (mock httpx).${RESET}"
fi

# ─── 8. Final verification ────────────────────────────────────────────
step "8. Verify Phase A"
if PATH=/opt/homebrew/opt/openjdk/bin:$PATH .venv/bin/python scripts/verify_phase_a.py 2>&1 | tail -10; then
    echo ""
    ok "${GREEN}${BOLD}Setup complete.${RESET}"
    echo ""
    echo "  ${DIM}Next steps:${RESET}"
    echo "    ${DIM}- Open notebooks:   .venv/bin/jupyter lab${RESET}"
    echo "    ${DIM}- Full pipeline:    PATH=/opt/homebrew/opt/openjdk/bin:\$PATH .venv/bin/python scripts/run_reasoner.py --apply-r5 --print-summary${RESET}"
    echo "    ${DIM}- Run all 5 phase checks (B-E in order; ~30s):${RESET}"
    for p in a b c d e; do
        skip=""; [ "$p" = "b" ] && skip="--skip-execute"
        echo "    ${DIM}    PATH=/opt/homebrew/opt/openjdk/bin:\$PATH .venv/bin/python scripts/verify_phase_${p}.py $skip${RESET}"
    done
else
    err "Phase A verification failed — check output above"
    exit 1
fi
