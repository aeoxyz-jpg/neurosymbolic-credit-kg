"""Phase B checkpoint per SPEC §9.

Checks:
  1. NB01 (01_sparql_basics.ipynb) executes top-to-bottom on a fresh kernel
  2. NB02 (02_owl_inference.ipynb) executes top-to-bottom on a fresh kernel
  3. NB02 output contains at least one :PrimeApplicant materialized by Pellet

Note: this script ACTUALLY executes the notebooks. Takes ~1-2 min total.
Pass --skip-execute to only sanity-check pre-recorded outputs (faster).

Dependencies: nbformat, jupyter-client (via jupyter nbconvert).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import nbformat


def execute_notebook(path: Path, timeout: int = 180) -> tuple[bool, str]:
    """Run nbconvert --execute on a clean copy of the notebook.
    Uses sys.executable so the venv's installed deps are visible.
    Returns (ok, error_summary)."""
    cmd = [
        sys.executable,
        "-m",
        "jupyter",
        "nbconvert",
        "--to",
        "notebook",
        "--execute",
        "--ExecutePreprocessor.timeout",
        str(timeout),
        "--output",
        f"/tmp/_verify_{path.stem}.ipynb",
        str(path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30)
    if r.returncode != 0:
        return False, r.stderr[-1500:]
    return True, ""


def has_prime_output(executed_path: Path) -> bool:
    """Confirm NB02's executed output mentions a PrimeApplicant individual."""
    nb = nbformat.read(executed_path, as_version=4)
    for cell in nb.cells:
        if cell.cell_type != "code":
            continue
        for out in cell.get("outputs", []):
            text = out.get("text", "") or ""
            for d in out.get("data", {}).values() if "data" in out else []:
                text += d if isinstance(d, str) else ""
            if re.search(r"Applicant_P0\d", text) and "Prime" in text:
                return True
    return False


def check(label: str, ok: bool, detail: str = "") -> bool:
    icon = "✓" if ok else "✗"
    suffix = f" — {detail}" if detail else ""
    print(f"  {icon} {label}{suffix}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--skip-execute",
        action="store_true",
        help="Don't re-execute notebooks; just inspect their existing outputs.",
    )
    args = parser.parse_args()

    project = Path(__file__).resolve().parent.parent
    nb1 = project / "notebooks" / "01_sparql_basics.ipynb"
    nb2 = project / "notebooks" / "02_owl_inference.ipynb"

    print("Phase B verification\n")
    passed = []

    for nb_path, label in [(nb1, "NB01 exists"), (nb2, "NB02 exists")]:
        passed.append(check(label, nb_path.exists(), str(nb_path)))
    if not all(passed):
        return 1

    if args.skip_execute:
        print("\n  (skipping execution — inspecting existing outputs)")
        for nb_path, label in [(nb1, "NB01"), (nb2, "NB02")]:
            nb = nbformat.read(nb_path, as_version=4)
            errors = [
                o
                for c in nb.cells
                if c.cell_type == "code"
                for o in c.get("outputs", [])
                if o.get("output_type") == "error"
            ]
            passed.append(
                check(
                    f"{label} no errors in recorded output",
                    not errors,
                    f"{len(errors)} error outputs" if errors else "clean",
                )
            )
        prime = has_prime_output(nb2)
        passed.append(check("NB02 output mentions a materialized :PrimeApplicant", prime))
    else:
        for nb_path, label in [(nb1, "NB01 executes clean"), (nb2, "NB02 executes clean")]:
            ok, err = execute_notebook(nb_path)
            passed.append(check(label, ok, err.splitlines()[-1] if err else "fresh kernel run OK"))
        # Inspect the executed-into-tmp copy of NB02 for the PrimeApplicant evidence
        executed_nb2 = Path(f"/tmp/_verify_{nb2.stem}.ipynb")
        prime = executed_nb2.exists() and has_prime_output(executed_nb2)
        passed.append(check("NB02 output mentions a materialized :PrimeApplicant", prime))

    print()
    if all(passed):
        print("Phase B: ALL CHECKS PASSED ✓")
        return 0
    failed = sum(1 for p in passed if not p)
    print(f"Phase B: {failed} check(s) failed ✗")
    return 1


if __name__ == "__main__":
    sys.exit(main())
