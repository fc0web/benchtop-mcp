"""
Regression test for the stale-cache chain break fixed by commit
`3f70c9c` (fix(audit): cross-process lock で並行 append の stale-cache 破断を修理).

- Runs N processes, each holding a SINGLE AuditLogWriter instance for
  M appends over R rounds. The single-instance-per-worker holds the
  cached `last_hash` that the fix protects against staleness.
- multiprocessing.get_context("spawn") is used so each worker is a
  fresh Python process (reproduces the production condition of
  independently-spawned proxy processes).
- multiprocessing.Barrier synchronises the start of every worker's
  append loop so all N workers race under maximum contention every
  round.
- Each append carries a (round, worker, seq) triple in `detail`, so
  we can check completeness (no missing tuple), uniqueness (no
  duplicate tuple), byte-level integrity (last byte is newline, every
  line parses as JSON) after the fact — in addition to chain hash
  verification.

Sizing (N=4, M=10, R=5 -> 200 appends per run):
    Calibration on pre-fix version (git show 3f70c9c^:benchtop_audit_log.py)
    with R=5 rounds observed break_rate = 5/5 across every config in
    {(N,M) ∈ {(2,10),(4,5),(4,10),(4,20),(8,5),(8,10),(8,20)}}. See
    scratchpad/calibrate_prefix.py. The chosen (4, 10) sits in the
    middle of that range, runs in ~5 seconds, and is comfortably in
    the "reliably breaks pre-fix" region rather than at the edge.

Negative control (pre-fix must FAIL):
    Same test body is run against the pre-fix source
    (git show 3f70c9c^:benchtop_audit_log.py) written to a temp file
    and imported by path. If that source happens to keep the chain
    valid on this machine, the test is treated as invalid (see the
    NEGATIVE CONTROL check in main()) and the run fails: we would
    then have no evidence that a PASS on the patched source is
    meaningful.

Design principle:
    This file lives OUTSIDE benchtop_mcp.py's _selftest(). The object
    under diagnosis should not run its own diagnostic — self-tests
    embedded in the module under test can be silenced by the exact
    bugs they are supposed to catch.

Run:
    python tests/test_audit_log_concurrent.py

Exit 0 iff pre-fix broke AND patched held its chain, line count,
uniqueness, completeness, and final-newline check.
"""

from __future__ import annotations

import importlib.util
import json
import multiprocessing
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

N_WORKERS = 4
N_APPENDS_EACH_ROUND = 10
N_ROUNDS = 5
JOIN_TIMEOUT_SEC = 60
PRE_FIX_COMMIT_PARENT = "3f70c9c^"


def _load_module_from_path(mod_path: Path, mod_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, str(mod_path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_prefix_source_to(dst: Path) -> None:
    src = subprocess.check_output(
        ["git", "show", f"{PRE_FIX_COMMIT_PARENT}:benchtop_audit_log.py"],
        cwd=str(REPO_ROOT),
        text=True,
        encoding="utf-8",
    )
    dst.write_text(src, encoding="utf-8")


def _worker(
    mod_path_str: str,
    audit_dir: str,
    barrier,
    worker_id: int,
    n_appends: int,
    round_id: int,
) -> None:
    mod = _load_module_from_path(Path(mod_path_str), "audit_mod_worker")
    writer = mod.AuditLogWriter(audit_dir)
    barrier.wait()
    for i in range(n_appends):
        writer.append(
            actor=f"w{worker_id}",
            action="concurrent_test",
            target=f"r{round_id}-w{worker_id}-s{i}",
            result="success",
            detail={"round": round_id, "worker": worker_id, "seq": i},
        )


def _run_round(mod_path: Path, audit_dir: str, round_id: int) -> None:
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(N_WORKERS + 1)
    procs = [
        ctx.Process(
            target=_worker,
            args=(str(mod_path), audit_dir, barrier, w, N_APPENDS_EACH_ROUND, round_id),
        )
        for w in range(N_WORKERS)
    ]
    for p in procs:
        p.start()
    barrier.wait()
    hung = []
    for p in procs:
        p.join(timeout=JOIN_TIMEOUT_SEC)
        if p.is_alive():
            hung.append(p.pid)
            p.terminate()
    if hung:
        raise RuntimeError(f"worker(s) hung past {JOIN_TIMEOUT_SEC}s: {hung}")
    bad = [(p.pid, p.exitcode) for p in procs if p.exitcode != 0]
    if bad:
        raise RuntimeError(f"worker exit failures: {bad}")


def _check_line_integrity(audit_dir: str) -> dict[str, Any]:
    p = Path(audit_dir) / "audit.jsonl"
    raw = p.read_bytes()
    ends_with_newline = raw.endswith(b"\n")
    text = raw.decode("utf-8")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    triples: set[tuple[Any, Any, Any]] = set()
    dupes: list[tuple[Any, Any, Any]] = []
    parse_errors: list[tuple[int, str]] = []
    for i, ln in enumerate(lines):
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError as e:
            parse_errors.append((i, str(e)))
            continue
        d = obj.get("detail", {}) or {}
        t = (d.get("round"), d.get("worker"), d.get("seq"))
        if t in triples:
            dupes.append(t)
        triples.add(t)
    expected_triples = {
        (r, w, s)
        for r in range(N_ROUNDS)
        for w in range(N_WORKERS)
        for s in range(N_APPENDS_EACH_ROUND)
    }
    missing = sorted(expected_triples - triples)
    return {
        "n_lines": len(lines),
        "ends_with_newline": ends_with_newline,
        "n_parse_errors": len(parse_errors),
        "n_duplicates": len(dupes),
        "n_missing": len(missing),
        "sample_missing": missing[:5],
        "sample_duplicates": dupes[:5],
    }


def _run_against(source_path: Path) -> dict[str, Any]:
    outcome: dict[str, Any] = {"error": None, "verify": None, "integrity": None}
    with tempfile.TemporaryDirectory() as tmp:
        try:
            for r in range(N_ROUNDS):
                _run_round(source_path, tmp, r)
        except RuntimeError as e:
            outcome["error"] = str(e)
        mod = _load_module_from_path(source_path, "audit_mod_check")
        outcome["verify"] = mod.AuditLogWriter.verify_chain(tmp)
        outcome["integrity"] = _check_line_integrity(tmp)
    return outcome


def main() -> int:
    print(f"config: N={N_WORKERS} workers, M={N_APPENDS_EACH_ROUND} appends/round, "
          f"R={N_ROUNDS} rounds -> {N_WORKERS * N_APPENDS_EACH_ROUND * N_ROUNDS} appends total")
    print()
    print("=== negative control (pre-fix, must FAIL) ===")
    with tempfile.TemporaryDirectory() as ctrl_tmp:
        prefix_src = Path(ctrl_tmp) / "benchtop_audit_log_prefix.py"
        _write_prefix_source_to(prefix_src)
        neg = _run_against(prefix_src)
        print(f"  error:     {neg['error']}")
        print(f"  verify:    {neg['verify']}")
        print(f"  integrity: {neg['integrity']}")
    print()
    print("=== positive test (patched, must PASS) ===")
    patched_src = REPO_ROOT / "benchtop_audit_log.py"
    pos = _run_against(patched_src)
    print(f"  error:     {pos['error']}")
    print(f"  verify:    {pos['verify']}")
    print(f"  integrity: {pos['integrity']}")

    expected_total = N_WORKERS * N_APPENDS_EACH_ROUND * N_ROUNDS
    fails: list[str] = []

    if neg["error"] is not None:
        fails.append(f"NEGATIVE CONTROL: unexpected error while running pre-fix: {neg['error']}")
    if neg["verify"].get("valid") is True:
        fails.append("NEGATIVE CONTROL PASSED (chain valid on pre-fix) — test is invalid; "
                     "pre-fix code did not reproduce the break at this size")

    if pos["error"] is not None:
        fails.append(f"POSITIVE TEST: worker error / hang: {pos['error']}")
    if pos["verify"].get("valid") is not True:
        fails.append(f"POSITIVE TEST: chain invalid on patched: {pos['verify']}")
    if pos["verify"].get("total") != expected_total:
        fails.append(f"POSITIVE TEST: expected total={expected_total}, "
                     f"got {pos['verify'].get('total')}")
    pi = pos["integrity"]
    if pi["n_lines"] != expected_total:
        fails.append(f"POSITIVE TEST: file has {pi['n_lines']} lines, expected {expected_total}")
    if pi["n_parse_errors"]:
        fails.append(f"POSITIVE TEST: {pi['n_parse_errors']} unparseable line(s)")
    if pi["n_duplicates"]:
        fails.append(f"POSITIVE TEST: {pi['n_duplicates']} duplicate (round,worker,seq): "
                     f"{pi['sample_duplicates']}")
    if pi["n_missing"]:
        fails.append(f"POSITIVE TEST: {pi['n_missing']} missing (round,worker,seq): "
                     f"{pi['sample_missing']}")
    if not pi["ends_with_newline"]:
        fails.append("POSITIVE TEST: audit.jsonl does not end with a newline")

    print()
    print("=== summary ===")
    if fails:
        for f in fails:
            print(f"  FAIL: {f}")
        return 1
    print("  PASS: pre-fix reproduced the break (negative control fires),")
    print("        patched source held the chain, line count matched,")
    print("        no missing or duplicate (round,worker,seq), file ends with newline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
