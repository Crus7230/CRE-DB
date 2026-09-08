"""Installed shim: keep all collector behavior in the versioned workspace."""
from pathlib import Path
import runpy
import sys

WORKSPACE = Path("C:/10137_WorkSpace/00. 2025 RA 기획추진/RA dashboard/09. CRE DB Board")

if __name__ == "__main__":
    entrypoint = WORKSPACE / "operations/hermes/daily_cre_articles.py"
    if not entrypoint.is_file():
        raise SystemExit("CRE workspace collector entrypoint is unavailable")
    sys.path.insert(0, str(WORKSPACE))
    runpy.run_path(str(entrypoint), run_name="__main__")
