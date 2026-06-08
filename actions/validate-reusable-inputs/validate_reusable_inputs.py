#!/usr/bin/env python3
"""Cross-repo input validation for callers of pinpredict/.github reusable workflows.

See ./action.yml for the rationale and contract. This script is invoked by the
composite action with WORKFLOWS_GLOB, CENTRAL_REPO, and GH_TOKEN in the env.
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
from functools import lru_cache

import yaml

CENTRAL_REPO = os.environ["CENTRAL_REPO"]
WORKFLOWS_GLOB = os.environ["WORKFLOWS_GLOB"]

# `pinpredict/.github/.github/workflows/<file>.yml@<ref>`
USES_RE = re.compile(
    rf"^{re.escape(CENTRAL_REPO)}/\.github/workflows/(?P<file>[^@]+)@(?P<ref>.+)$"
)


@lru_cache(maxsize=None)
def fetch_workflow_inputs(path: str, ref: str) -> dict[str, dict]:
    """Return the `on.workflow_call.inputs` map for a remote workflow file.

    Empty dict if the workflow declares no inputs. Raises on fetch / parse failure
    so the action fails loudly rather than silently passing.
    """
    api = f"repos/{CENTRAL_REPO}/contents/{path}?ref={ref}"
    raw = subprocess.check_output(
        ["gh", "api", "-H", "Accept: application/vnd.github.raw", api],
        text=True,
    )
    doc = yaml.safe_load(raw) or {}
    # `on:` parses as the literal True in PyYAML 1.1 mode; safe_load is 1.1.
    on_block = doc.get(True, doc.get("on", {})) or {}
    if not isinstance(on_block, dict):
        return {}
    wc = on_block.get("workflow_call") or {}
    inputs = (wc.get("inputs") if isinstance(wc, dict) else None) or {}
    return inputs if isinstance(inputs, dict) else {}


def iter_jobs(doc: dict):
    jobs = doc.get("jobs") or {}
    if not isinstance(jobs, dict):
        return
    for name, job in jobs.items():
        if isinstance(job, dict):
            yield name, job


def check_workflow(path: str) -> list[str]:
    """Return a list of human-readable violations for one caller workflow file."""
    with open(path) as f:
        doc = yaml.safe_load(f) or {}
    if not isinstance(doc, dict):
        return []

    violations: list[str] = []
    for job_name, job in iter_jobs(doc):
        uses = job.get("uses")
        if not isinstance(uses, str):
            continue
        m = USES_RE.match(uses.strip())
        if not m:
            continue

        wf_file = f".github/workflows/{m.group('file')}"
        ref = m.group("ref")
        caller_with = job.get("with") or {}
        if not isinstance(caller_with, dict):
            caller_with = {}

        try:
            declared = fetch_workflow_inputs(wf_file, ref)
        except subprocess.CalledProcessError as e:
            violations.append(
                f"{path}: job `{job_name}` references {CENTRAL_REPO}/{wf_file}@{ref} "
                f"but the workflow could not be fetched (gh api exit {e.returncode}). "
                "Check the ref exists and GH_TOKEN has `contents: read`."
            )
            continue

        declared_keys = set(declared.keys())
        caller_keys = set(caller_with.keys())

        unknown = sorted(caller_keys - declared_keys)
        for key in unknown:
            suggestion = ""
            if declared_keys:
                close = sorted(declared_keys, key=lambda k: _similar(k, key), reverse=True)
                suggestion = f" (did you mean `{close[0]}`?)"
            violations.append(
                f"{path}: job `{job_name}` passes unknown input `{key}` to "
                f"{CENTRAL_REPO}/{wf_file}@{ref}{suggestion}"
            )

        required_missing = sorted(
            key
            for key, spec in declared.items()
            if isinstance(spec, dict)
            and spec.get("required") is True
            and spec.get("default") is None
            and key not in caller_keys
        )
        for key in required_missing:
            violations.append(
                f"{path}: job `{job_name}` is missing required input `{key}` for "
                f"{CENTRAL_REPO}/{wf_file}@{ref}"
            )

    return violations


def _similar(a: str, b: str) -> float:
    """Cheap similarity score for did-you-mean hints (no stdlib import bloat)."""
    a, b = a.lower(), b.lower()
    if not a or not b:
        return 0.0
    shared = len(set(a) & set(b))
    return shared / max(len(set(a) | set(b)), 1)


def main() -> int:
    paths: list[str] = []
    for pattern in WORKFLOWS_GLOB.split():
        paths.extend(sorted(glob.glob(pattern)))
    if not paths:
        print(f"validate-reusable-inputs: no files matched `{WORKFLOWS_GLOB}`")
        return 0

    all_violations: list[str] = []
    for path in paths:
        all_violations.extend(check_workflow(path))

    if all_violations:
        print(f"validate-reusable-inputs: {len(all_violations)} violation(s):")
        for v in all_violations:
            print(f"  - {v}")
        return 1

    print(
        f"validate-reusable-inputs: {len(paths)} workflow file(s) scanned, "
        f"all caller `with:` blocks match {CENTRAL_REPO}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
