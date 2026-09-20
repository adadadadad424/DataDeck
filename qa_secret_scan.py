"""Fail CI when tracked text files contain likely real secrets.

The scanner reports only file names and rule names, never matching values.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MAX_FILE_BYTES = 2_000_000
IGNORED_PATHS = {"qa_secret_scan.py"}
RULES = {
    "google_api_key": re.compile(rb"AIza[0-9A-Za-z_-]{25,}"),
    "stripe_secret_key": re.compile(rb"sk_(?:live|test)_[0-9A-Za-z]{16,}"),
    "stripe_webhook_secret": re.compile(rb"whsec_[0-9A-Za-z]{16,}"),
    "private_key": re.compile(
        rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
    "postgres_password_url": re.compile(
        rb"postgres(?:ql)?://[^\s:/]+:(?!placeholder(?:@|%40))[^\s@]{8,}@",
        re.IGNORECASE,
    ),
}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def scan() -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    for path in tracked_files():
        relative = path.relative_to(ROOT).as_posix()
        if relative in IGNORED_PATHS or not path.is_file():
            continue
        data = path.read_bytes()
        if len(data) > MAX_FILE_BYTES or b"\0" in data:
            continue
        for rule_name, pattern in RULES.items():
            if pattern.search(data):
                findings.append((relative, rule_name))
    return findings


def main() -> int:
    findings = scan()
    if findings:
        print("Secret-Scan: FAIL")
        for filename, rule_name in findings:
            print(f"- {filename}: {rule_name}")
        return 1
    print("Secret-Scan: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
