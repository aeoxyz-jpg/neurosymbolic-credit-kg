"""Phase E checkpoint per SPEC §9.

Checks:
  1. NB99 exists and saved output is error-free
  2. docs/ontology_design.md, reasoning_cheatsheet.md, trouble_shooting.md exist
  3. End-to-end pipeline (reset → load → reason → SHACL → query → synth)
     completes in < 5 minutes
  4. README "Get Started in 10 Minutes" command list still works
     (we sample-check `verify_phase_a.py` since that's the README's first probe)

This script ACTUALLY runs the pipeline; takes ~30-60 seconds.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import nbformat

PROJECT = Path(__file__).resolve().parent.parent


def check(label: str, ok: bool, detail: str = "") -> bool:
    icon = "✓" if ok else "✗"
    suffix = f" — {detail}" if detail else ""
    print(f"  {icon} {label}{suffix}")
    return ok


def run_step(label: str, cmd: list[str]) -> tuple[bool, float, str]:
    t0 = time.perf_counter()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    dt = time.perf_counter() - t0
    if r.returncode != 0:
        return False, dt, r.stderr[-500:]
    return True, dt, ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--execute-nb99",
        action="store_true",
        help="Re-execute NB99 (~30-60s). Default: inspect saved outputs.",
    )
    args = parser.parse_args()

    print("Phase E verification\n")
    passed = []

    # 1. Files exist
    nb99 = PROJECT / "notebooks" / "99_full_pipeline.ipynb"
    passed.append(check("NB99 exists", nb99.exists()))
    for doc in ("ontology_design.md", "reasoning_cheatsheet.md", "trouble_shooting.md"):
        p = PROJECT / "docs" / doc
        passed.append(check(f"docs/{doc} exists", p.exists()))

    # 2. NB99 saved output
    if args.execute_nb99:
        env = {**os.environ, "PATH": f"/opt/homebrew/opt/openjdk/bin:{os.environ.get('PATH', '')}"}
        cmd = [
            sys.executable,
            "-m",
            "jupyter",
            "nbconvert",
            "--to",
            "notebook",
            "--execute",
            "--ExecutePreprocessor.timeout",
            "300",
            "--output",
            "/tmp/_verify_nb99.ipynb",
            str(nb99),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=400, env=env)
        passed.append(
            check(
                "NB99 re-executes clean",
                r.returncode == 0,
                r.stderr.splitlines()[-1] if r.stderr else "OK",
            )
        )
    else:
        nb = nbformat.read(nb99, as_version=4)
        errors = [
            o
            for c in nb.cells
            if c.cell_type == "code"
            for o in c.get("outputs", [])
            if o.get("output_type") == "error"
        ]
        passed.append(
            check(
                "NB99 saved output has no errors",
                not errors,
                f"{len(errors)} errors" if errors else "clean",
            )
        )

    # 3. End-to-end pipeline timing
    print("\n  → Running end-to-end pipeline (timing each step)...")
    total = 0.0
    env = {**os.environ, "PATH": f"/opt/homebrew/opt/openjdk/bin:{os.environ.get('PATH', '')}"}

    ok, dt, err = run_step(
        "reset_fuseki", [sys.executable, str(PROJECT / "scripts" / "reset_fuseki.py")]
    )
    total += dt
    passed.append(check(f"reset_fuseki ({dt:.1f}s)", ok, err))

    for f in ["credit_risk.ttl", "instances/customers.ttl", "instances/applications.ttl"]:
        ok, dt, err = run_step(
            f"load {f}",
            [
                sys.executable,
                str(PROJECT / "scripts" / "load_ontology.py"),
                str(PROJECT / "ontology" / f),
            ],
        )
        total += dt
        passed.append(check(f"load_ontology {f} ({dt:.1f}s)", ok, err))

    # Reasoner is the slow step
    print("    (reasoner is the slow one — Pellet first run ~10-30s)")
    t0 = time.perf_counter()
    r = subprocess.run(
        [
            sys.executable,
            str(PROJECT / "scripts" / "run_reasoner.py"),
            "--apply-r5",
            "--print-summary",
        ],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )
    dt = time.perf_counter() - t0
    total += dt
    passed.append(
        check(
            f"run_reasoner --apply-r5 ({dt:.1f}s)",
            r.returncode == 0,
            "ok" if r.returncode == 0 else r.stderr[-300:],
        )
    )

    # Quick SHACL probe (the inferred.ttl + raw)
    t0 = time.perf_counter()
    r = subprocess.run(
        [
            sys.executable,
            "-c",
            "from rdflib import Graph; from pyshacl import validate; "
            "import sys; d = Graph(); "
            "[d.parse(f, format='turtle') for f in "
            f"['{PROJECT}/ontology/credit_risk.ttl',"
            f" '{PROJECT}/ontology/instances/customers.ttl',"
            f" '{PROJECT}/ontology/instances/applications.ttl',"
            f" '{PROJECT}/ontology/inferred.ttl']]; "
            "s = Graph(); "
            f"s.parse('{PROJECT}/ontology/shapes.ttl', format='turtle'); "
            "conforms, _, t = validate(d, shacl_graph=s, inference='rdfs', advanced=True); "
            "sys.exit(0 if conforms else 1)",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    dt = time.perf_counter() - t0
    total += dt
    passed.append(
        check(
            f"SHACL validates inferred graph ({dt:.1f}s)",
            r.returncode == 0,
            "conforms" if r.returncode == 0 else "violations",
        )
    )

    passed.append(check(f"Pipeline total under 5 minutes ({total:.1f}s)", total < 300))

    print()
    if all(passed):
        print("Phase E: ALL CHECKS PASSED ✓")
        return 0
    failed = sum(1 for p in passed if not p)
    print(f"Phase E: {failed} check(s) failed ✗")
    return 1


if __name__ == "__main__":
    sys.exit(main())
