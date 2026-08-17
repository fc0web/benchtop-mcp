#!/usr/bin/env python3
"""
benchtop-mcp audit log : append-only JSONL + sha256 prev-hash chain

Rei-Automator STEP 1340 (2026-08-17) の `src/aios/security/audit-log.ts` を
Python port したもの。 記録の 説明責任 (accountability) 用途、 debug 用
`~/.benchtop-mcp/*.json` (session store) と 独立 store で 併存。

Cross-pollination pattern (Rei stack Type 1 移送): 同じ hash-chain primitive を
TypeScript (Rei-Automator) と Python (benchtop) に 適用、 substrate は 異なるが
情報構造 は 同一 = 「新しいアイデア = 新しい随伴」 の 具体 instance。

★ Honest scope:
(1) 本 module は benchtop の 「証跡が価値になる領域」 (ISO/IEC 17025 校正、
    GMP 医薬品製造記録、 監査対応) 用途の audit layer、 tool 呼び出し の 全成功/失敗
    を append-only JSONL で 記録 + sha256 prev-hash chain で 改竄検出可能に。
(2) session store (`~/.benchtop-mcp/session_*.json`) と 別 store。 audit log は
    削除禁止 (append-only)、 session store は 従来通り 個別ファイル。
(3) audit append 失敗は 呼び出し側に throw、 tool 実行を kill しない policy は
    caller 側 (benchtop_mcp.py 統合層) で 判断。 本 module は raw layer のみ。
(4) Novelty ゼロ: sha256 prev-hash chain は 既知 primitive (Bitcoin 2008 / Merkle
    1979 origin)、 Rei-Automator と benchtop の 両側で 同一 primitive を 適用した
    のみ、 数学的発見ではない。

License: benchtop-mcp v0.x = MIT (irrevocable per README)。
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GENESIS_HASH = "sha256:" + "0" * 64
DEFAULT_FILENAME = "audit.jsonl"


def _sha256_of(line: str) -> str:
    """Compute sha256 hash of a JSONL line (returns 'sha256:...' format)."""
    return "sha256:" + hashlib.sha256(line.encode("utf-8")).hexdigest()


class AuditLogWriter:
    """
    Append-only JSONL + sha256 prev-hash chain writer.

    Each line contains a JSON entry with `prev` field = sha256 of previous line
    (or GENESIS_HASH for the first entry). Tampering with any line breaks the
    chain and is detectable via `verify_chain()`.

    Fields (per entry):
      ts        : ISO 8601 UTC timestamp
      actor     : who initiated (e.g. 'benchtop-mcp')
      action    : tool name (e.g. 'measure', 'compare_sessions')
      target    : what was operated on (e.g. session_id, port)
      result    : 'success' | 'error' | 'partial' | 'aborted'
      detail    : arbitrary dict for extra context
      prev      : sha256:<hex> of previous line (or GENESIS_HASH for first)
    """

    def __init__(self, audit_dir: str, filename: str = DEFAULT_FILENAME) -> None:
        self.audit_dir = Path(audit_dir)
        self.filename = filename
        self.last_hash = self._load_last_hash()

    def _log_path(self) -> Path:
        return self.audit_dir / self.filename

    def _load_last_hash(self) -> str:
        """Load the sha256 of the last line in the audit log (for chain continuation)."""
        p = self._log_path()
        if not p.exists():
            return GENESIS_HASH
        try:
            with p.open("r", encoding="utf-8") as f:
                lines = [ln for ln in f.read().split("\n") if ln.strip()]
            if not lines:
                return GENESIS_HASH
            return _sha256_of(lines[-1])
        except Exception:
            return GENESIS_HASH

    def append(
        self,
        actor: str,
        action: str,
        target: str,
        result: str = "success",
        detail: dict[str, Any] | None = None,
    ) -> str:
        """
        Append a new entry to the audit log. Returns sha256 of the appended
        line (= prev for the next entry).

        Raises on I/O failure; caller decides whether to kill execution or
        continue with an accountability gap.
        """
        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "actor": actor,
            "action": action,
            "target": target,
            "result": result,
            "prev": self.last_hash,
        }
        if detail is not None:
            entry["detail"] = detail
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        with self._log_path().open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        h = _sha256_of(line)
        self.last_hash = h
        return h

    def read_all(self) -> list[dict[str, Any]]:
        """Snapshot read. Never rewrite the file — audit log is append-only."""
        p = self._log_path()
        if not p.exists():
            return []
        with p.open("r", encoding="utf-8") as f:
            return [json.loads(ln) for ln in f.read().split("\n") if ln.strip()]

    def get_head(self) -> str:
        """Current chain head (last appended line's hash, or GENESIS_HASH if empty)."""
        return self.last_hash

    @staticmethod
    def verify_chain(audit_dir: str, filename: str = DEFAULT_FILENAME) -> dict[str, Any]:
        """
        Verify the hash chain integrity.

        Returns:
          {"valid": True, "total": N} on success
          {"valid": False, "broken_at": i, "total": N} on first mismatched prev-hash
            (i is 0-indexed line number where the chain break was detected)
          {"valid": True, "total": 0} if audit log does not exist
        """
        p = Path(audit_dir) / filename
        if not p.exists():
            return {"valid": True, "total": 0}
        with p.open("r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().split("\n") if ln.strip()]
        expected_prev = GENESIS_HASH
        for i, ln in enumerate(lines):
            try:
                entry = json.loads(ln)
            except json.JSONDecodeError:
                return {"valid": False, "broken_at": i, "total": len(lines)}
            if entry.get("prev") != expected_prev:
                return {"valid": False, "broken_at": i, "total": len(lines)}
            expected_prev = _sha256_of(ln)
        return {"valid": True, "total": len(lines)}


__all__ = ["AuditLogWriter", "GENESIS_HASH"]
