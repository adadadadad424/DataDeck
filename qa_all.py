"""Fuehrt die komplette DataDeck-QA in einer stabilen Reihenfolge aus."""

import subprocess
import sys


QA_SUITES = (
    "qa_test_final.py",
    "qa_ui_quality.py",
    "qa_beta_security.py",
    "qa_production.py",
    "qa_golden_datasets.py",
    "qa_import_pipeline.py",
    "qa_consulting.py",
    "qa_billing.py",
    "qa_runtime.py",
)


def main() -> int:
    for suite in QA_SUITES:
        print(f"\n{'=' * 72}\n{suite}\n{'=' * 72}", flush=True)
        result = subprocess.run([sys.executable, suite], check=False)
        if result.returncode:
            print(f"\nQA abgebrochen: {suite} ist fehlgeschlagen.", file=sys.stderr)
            return result.returncode
    print("\nDataDeck Gesamt-QA: PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
