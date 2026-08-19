#!/usr/bin/env python3
"""
benchtop-mcp provenance layer : instrument-agnostic measurement record layer
================================================================================

SPIKE v0.5.0-alpha (2026-08-19, GO 判定後の 半日仕事 spike、 藤本さん judgment 待ち)。

**目的** (chat-Claude 2026-08-18 「MCP コネクタ世界一」 report §3-1〜§3-4):

  下層 (機器制御 SCPI/VISA、 Keysight/rigol-mcp/lecroy-mcp 等 既 10 実装 = 混雑) を捨てて、
  上層 (機器メーカーに関係なく測定記録を保存・比較・改竄検証する層) に座る。
  他社 MCP server の 出力も 受け入れる instrument-agnostic 設計で、
  下層 10 実装 の 全ユーザーを 潜在流入経路化。

**独自 primitive の位置付け** (2026-08-19 verify 後 framing 訂正):

  - hash chain 部分 = benchtop_audit_log.py (v0.3.0) で既存、 primitive として
    **Vouched KYA-OS MCP (RFC 9162 Merkle checkpoint + Ed25519 + JCS + DIF 寄贈)**
    が technically 先行、 別 STEP で kya-os 互換 verify() interface 追加検討。
  - 本 module の 差別化 = **SafetyGate** = SCPI-argument level 物理 hazard 検出
    (chat-Claude report で誰も触れていないと 4 agent verify 済 domain)。
  - Rei stack STEP 1344 Asset ② (Peace Axiom hardware I/O 拡張) の operational form、
    external prior-art benchtop-devicedef (Kikusui PLZ-5W CR mode Siemens hazard 等
    3 vendor cross-reference asset) を SafetyGate rule として 集約。

**scope 明示** (spike level、 「世界初」 主張ゼロ):

  (1) 本 module は SCPI-argument level の 「単位系ミスによる silent 短絡」 系 hazard
      検出 の primitive layer、 全ての hardware safety を cover するものではない。
  (2) Kikusui PLZ-5W CR mode conductance/resistance 混同 の 1 rule のみ built-in、
      他 rule は spike scope 外 (別 STEP で 3 vendor 拡張 candidate)。
  (3) 実 hardware verify 不能 (spike は mock only)、 実機 SCPI 送出前の 静的 check
      layer として 位置付け、 実 hardware feedback loop は 未実装。
  (4) External session import は schema 検証 + safety gate + audit log 記録のみ、
      import 元 MCP server の crypto attestation (kya-os の Ed25519 signature 等) は
      pass-through 保存で verify せず (別 STEP kya-os interop で verify 化 candidate)。
  (5) [[feedback-world-uniqueness-claim-controllable]] 継承 = 「世界初」 主張禁止、
      SafetyGate rule は Kikusui 自マニュアル明記済 hazard (「ジーメンス」 明記) の
      operational check、 novelty は Rei stack 内 集約 layer 位置のみ。

**related memory**:
  - [[project-benchtop-devicedef-external-asset-2026-08-17]] (Kikusui 3 vendor asset)
  - [[feedback-peace-axiom-hardware-io-extension-2026-08-17]] (Peace Axiom I/O template)
  - [[feedback-super-naming-siren-family-pattern]] inverse siren subtype (100=Ω vs 100=S)
  - chat-Claude 2026-08-18 market report (data/external-prior-art/mcp-strategy-*/)
  - 4 agent verify 2026-08-19 (Vouched/EQTY/Anthropic dir/hash-chain audit)

License: benchtop-mcp v0.x = MIT (irrevocable per README).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


# ============================================================================
# Schema : instrument-agnostic measurement record
# ============================================================================


@dataclass
class ProvenanceRecord:
    """Single measurement record, source-agnostic.

    Accepted from benchtop native measure() or from external MCP servers
    (Keysight MCP / rigol-mcp / lecroy-mcp / kya-os-wrapped instrument MCP).

    Fields:
      source        : origin identifier, e.g. 'benchtop', 'external:rigol-mcp',
                      'external:keysight-mcp', 'external:kya-os:<inner-source>'
      ts            : ISO 8601 UTC timestamp of measurement
      channels      : ordered list of channel names, e.g. ['V', 'I', 'T']
      values        : dict {channel_name: numeric value}
      unit_hints    : optional dict {channel_name: unit string}, e.g. {'I': 'A'}
      instrument    : optional dict describing the instrument (vendor / model /
                      scpi_mode / firmware / serial)。 SafetyGate uses this to
                      lookup vendor-specific rules。
      raw           : optional dict for arbitrary source-native payload,
                      preserved verbatim for later re-parsing
      attestation   : optional dict for external crypto attestation
                      (e.g. kya-os JOSE proof, RFC 9162 checkpoint receipt);
                      preserved as-is, verify is out-of-spike-scope
      noise_floor_mW      : optional float, noise floor value captured just
                            before this measurement (unit: mW). Default None.
      noise_floor_taken_at: optional ISO 8601 UTC timestamp when noise_floor_mW
                            was captured. Default None.
      snr_ratio           : optional float, signal-to-noise ratio (Δ / noise_floor).
                            Default None.

    Noise floor / SNR field policy (2026-08-20, order principle):
      Fields are placeholders only. Threshold for snr_ratio is deliberately
      NOT hard-coded in this module. The digit magnitude of noise_floor_mW
      must first be established by an actual NULL burn on real hardware;
      only then may a threshold be written into any downstream check.
      See [[feedback-one-reproduction-over-ten-unverified]]。
    """
    source: str
    ts: str
    channels: list[str] = field(default_factory=list)
    values: dict[str, float] = field(default_factory=dict)
    unit_hints: dict[str, str] | None = None
    instrument: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None
    attestation: dict[str, Any] | None = None
    noise_floor_mW: float | None = None
    noise_floor_taken_at: str | None = None
    snr_ratio: float | None = None


@dataclass
class SafetyVerdict:
    """Output of a SafetyGate check.

    ok = True   : proceed
    ok = False  : reject, do NOT persist / send to hardware / import
    """
    ok: bool
    severity: str  # 'info' | 'warn' | 'dangerous' | 'catastrophic'
    rule_id: str
    reason: str
    suggested_fix: str | None = None
    detail: dict[str, Any] | None = None


# ============================================================================
# Safety gate : SCPI-argument level physical hazard detection
# ============================================================================


# Kikusui PLZ-5W CR mode conductance/resistance confusion rule
# Source: data/external-prior-art/benchtop-devicedef-2026-08-17/devices/kikusui_plz5w.yaml
# quirk id 'cr_mode_is_conductance_not_resistance', severity 'dangerous'
_KIKUSUI_PLZ5W_CR_CONDUCTANCE_PATTERN = re.compile(
    r"^\s*(\[?SOURce\]?:)?CONDuctance(:LEVel)?(:IMMediate)?(:AMPlitude)?\s+(?P<value>[-+]?\d+(\.\d+)?([eE][-+]?\d+)?)\s*$",
    re.IGNORECASE,
)


def _rule_kikusui_plz5w_conductance_hazard(
    vendor: str, model: str, command: str, args: dict[str, Any] | None
) -> SafetyVerdict | None:
    """Reject 'set CONDuctance = <value>' when value is in the range that a naive
    caller likely means as ohms (i.e. anything > ~1 S which corresponds to < 1 Ω).

    Rationale (from Kikusui PLZ-5W device definition YAML, quirk
    'cr_mode_is_conductance_not_resistance'):
      「100Ωにする」つもりで 100 を送ると 100 S = 0.01Ω となり、
      被試験電源をほぼ短絡する。構文エラーにはならず、そのまま実行される。

    Threshold rationale (spike-level heuristic, NOT a specification):
      - Practical CR-mode set-points are typically 0.001 S–1 S (1 Ω–1000 Ω).
      - Values > 1 S mean sub-ohm load, which is *possible* but almost never
        what a caller who wrote "resistance = X ohms" meant.
      - We reject > 1 S with severity='dangerous' and suggest the conductance =
        1/resistance conversion. Caller can override by attaching an explicit
        acknowledgment field to args (spike does not implement override yet).

    False-positive scope (honest):
      A legitimate high-conductance measurement (sub-ohm load bank) triggers
      this rule. Real deployments MUST provide an override mechanism.
    """
    if vendor.upper() != "KIKUSUI":
        return None
    if not re.match(r"^PLZ.*5W", model, re.IGNORECASE):
        return None
    match = _KIKUSUI_PLZ5W_CR_CONDUCTANCE_PATTERN.match(command)
    if match is None:
        return None
    try:
        value = float(match.group("value"))
    except ValueError:
        return None
    # Heuristic threshold: > 1 S ⇒ < 1 Ω, almost certainly ohms-vs-siemens confusion
    if value <= 1.0:
        return SafetyVerdict(
            ok=True,
            severity="info",
            rule_id="kikusui-plz5w-cr-conductance-check",
            reason=f"CONDuctance = {value} S ({1.0 / value:.4g} Ω) within plausible CR-mode range",
        )
    equivalent_ohms = 1.0 / value if value > 0 else float("inf")
    return SafetyVerdict(
        ok=False,
        severity="dangerous",
        rule_id="kikusui-plz5w-cr-conductance-hazard",
        reason=(
            f"Kikusui PLZ-5W CR mode uses CONDuctance in Siemens (S), not Ω. "
            f"Sending {value} would set {equivalent_ohms:.4g} Ω = short-circuit hazard. "
            f"Confirmed against manufacturer manual (unit table 「ジーメンス」 明記)."
        ),
        suggested_fix=(
            f"If you meant {value} Ω, send CONDuctance {1.0 / value:.6g}. "
            f"If you truly want sub-ohm load, override this rule explicitly."
        ),
        detail={
            "vendor": vendor,
            "model": model,
            "command": command,
            "value_sent": value,
            "unit_actual": "S",
            "unit_common_mistake": "ohm",
            "equivalent_ohms": equivalent_ohms,
            "source_yaml": "kikusui_plz5w.yaml quirk cr_mode_is_conductance_not_resistance",
        },
    )


class SafetyGate:
    """Composable, extensible SCPI-argument level safety checker.

    Spike v0.5.0-alpha ships with ONE built-in rule (Kikusui PLZ-5W CR mode
    Siemens vs Ω hazard). Additional rules (Kikusui PLZ-3W RSET Ω, Siglent
    SDL1000X RESistance Ω cross-vendor contrast, PLZ-5W input state activation
    guard) are spike-scope-out and tracked as future STEP candidates.
    """

    def __init__(self, rules: list[Any] | None = None) -> None:
        self.rules = rules if rules is not None else [
            _rule_kikusui_plz5w_conductance_hazard,
        ]

    def check_scpi(
        self,
        vendor: str,
        model: str,
        command: str,
        args: dict[str, Any] | None = None,
    ) -> SafetyVerdict:
        """Run all registered rules against a proposed SCPI command.

        Returns the FIRST non-None verdict from any rule (fail-fast).
        If no rule matches, returns an 'info' verdict indicating unchecked.
        """
        for rule in self.rules:
            verdict = rule(vendor, model, command, args)
            if verdict is not None:
                return verdict
        return SafetyVerdict(
            ok=True,
            severity="info",
            rule_id="no-rule-matched",
            reason=f"No SafetyGate rule matched for {vendor}/{model} command '{command}'",
        )

    def check_record(self, record: ProvenanceRecord) -> SafetyVerdict:
        """Run safety check against a ProvenanceRecord (from external import).

        Currently checks the record's `raw.command` field if the instrument
        info is present. Extension point for import-time validation.
        """
        if record.instrument is None:
            return SafetyVerdict(
                ok=True,
                severity="info",
                rule_id="no-instrument-metadata",
                reason="Record has no instrument metadata; SafetyGate cannot check",
            )
        vendor = str(record.instrument.get("vendor", ""))
        model = str(record.instrument.get("model", ""))
        command = ""
        if record.raw and isinstance(record.raw, dict):
            command = str(record.raw.get("command", ""))
        if not (vendor and model and command):
            return SafetyVerdict(
                ok=True,
                severity="info",
                rule_id="incomplete-metadata",
                reason="Missing vendor/model/command; SafetyGate skipped",
            )
        return self.check_scpi(vendor, model, command)


# ============================================================================
# External session import : accept measurements from other MCP servers
# ============================================================================


@dataclass
class ImportResult:
    """Return value of import_external_session."""
    ok: bool
    session_id: str | None
    records_accepted: int
    records_rejected: int
    rejections: list[dict[str, Any]] = field(default_factory=list)
    warning: str | None = None


def _generate_session_id(source: str) -> str:
    """Generate a session_id for an imported external session.

    Format: 'ext-<source-slug>-<utc-timestamp>'
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", source).strip("-").lower()[:40] or "unknown"
    return f"ext-{slug}-{ts}"


def import_external_session(
    source: str,
    records: list[dict[str, Any]],
    subject: str | None = None,
    mystery_id: str | None = None,
    environment: dict[str, Any] | None = None,
    instrument_config: dict[str, Any] | None = None,
    safety_gate: SafetyGate | None = None,
) -> ImportResult:
    """Ingest measurement records from an external source, returning a
    session-compatible dict on success.

    Args:
      source          : origin identifier (e.g. 'external:rigol-mcp',
                        'external:keysight-mcp', 'external:kya-os:<inner>').
      records         : list of dicts convertible to ProvenanceRecord.
                        Required per-record: 'ts', 'channels', 'values'.
                        Optional: 'unit_hints', 'instrument', 'raw', 'attestation'.
      subject         : passthrough to Session.subject (experiment notebook field)
      mystery_id      : passthrough to Session.mystery_id (rei-aios link)
      environment     : passthrough to Session.environment
      instrument_config: passthrough to Session.instrument_config
      safety_gate     : SafetyGate instance; default = SafetyGate() with built-in rules

    Returns:
      ImportResult with session_id (if any records accepted) and rejection
      details for records blocked by SafetyGate.

    Behavior on rejection:
      - Any dangerous/catastrophic verdict rejects THAT record and adds to
        `rejections`; other records continue.
      - If ALL records are rejected, session_id is None and ok=False.
      - Import log entry is emitted via caller's audit hook (this module does
        not directly write to audit log; caller is responsible for wiring).
    """
    if safety_gate is None:
        safety_gate = SafetyGate()

    accepted: list[ProvenanceRecord] = []
    rejections: list[dict[str, Any]] = []

    for i, raw_rec in enumerate(records):
        # Minimal schema validation
        if not isinstance(raw_rec, dict):
            rejections.append({
                "index": i,
                "reason": "record is not a dict",
                "record_preview": str(raw_rec)[:200],
            })
            continue
        required = {"ts", "channels", "values"}
        missing = required - set(raw_rec.keys())
        if missing:
            rejections.append({
                "index": i,
                "reason": f"missing required fields: {sorted(missing)}",
                "record_preview": {k: raw_rec.get(k) for k in list(raw_rec.keys())[:5]},
            })
            continue

        try:
            _nf = raw_rec.get("noise_floor_mW")
            _snr = raw_rec.get("snr_ratio")
            record = ProvenanceRecord(
                source=source,
                ts=str(raw_rec["ts"]),
                channels=list(raw_rec["channels"]),
                values={str(k): float(v) for k, v in raw_rec["values"].items()},
                unit_hints=raw_rec.get("unit_hints"),
                instrument=raw_rec.get("instrument"),
                raw=raw_rec.get("raw"),
                attestation=raw_rec.get("attestation"),
                noise_floor_mW=None if _nf is None else float(_nf),
                noise_floor_taken_at=(
                    None if raw_rec.get("noise_floor_taken_at") is None
                    else str(raw_rec["noise_floor_taken_at"])
                ),
                snr_ratio=None if _snr is None else float(_snr),
            )
        except (TypeError, ValueError) as e:
            rejections.append({
                "index": i,
                "reason": f"schema parse error: {e}",
                "record_preview": {k: raw_rec.get(k) for k in list(raw_rec.keys())[:5]},
            })
            continue

        verdict = safety_gate.check_record(record)
        if not verdict.ok:
            rejections.append({
                "index": i,
                "rule_id": verdict.rule_id,
                "severity": verdict.severity,
                "reason": verdict.reason,
                "suggested_fix": verdict.suggested_fix,
                "detail": verdict.detail,
            })
            continue

        accepted.append(record)

    if not accepted:
        return ImportResult(
            ok=False,
            session_id=None,
            records_accepted=0,
            records_rejected=len(rejections),
            rejections=rejections,
            warning="No records accepted (all rejected or invalid)",
        )

    session_id = _generate_session_id(source)
    return ImportResult(
        ok=True,
        session_id=session_id,
        records_accepted=len(accepted),
        records_rejected=len(rejections),
        rejections=rejections,
        warning=None if not rejections else f"{len(rejections)} of {len(records)} records rejected",
    )


def build_session_dict_from_import(
    result: ImportResult,
    source: str,
    records: list[dict[str, Any]],
    subject: str | None = None,
    mystery_id: str | None = None,
    environment: dict[str, Any] | None = None,
    instrument_config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Convert an ImportResult + original records into a benchtop Session-compatible
    dict, suitable for persistence via the existing Session.save() flow.

    Returns None if the import was not successful.
    """
    if not result.ok or result.session_id is None:
        return None

    accepted_records = []
    accepted_indices = {i for i in range(len(records))} - {r["index"] for r in result.rejections}
    accepted_records = [records[i] for i in sorted(accepted_indices)]

    all_channels: list[str] = []
    for r in accepted_records:
        for ch in r.get("channels", []):
            if ch not in all_channels:
                all_channels.append(ch)

    rows = []
    for r in accepted_records:
        row = {"ts": r["ts"]}
        for ch, v in r.get("values", {}).items():
            row[ch] = v
        rows.append(row)

    return {
        "id": result.session_id,
        "port": f"external:{source}",
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": f"Imported from {source} ({len(accepted_records)} records)",
        "channels": all_channels,
        "rows": rows,
        "skipped": result.records_rejected,
        "subject": subject,
        "environment": environment,
        "instrument_config": instrument_config,
        "mystery_id": mystery_id,
        # New v0.5.0-alpha field, requires Session.source field addition
        "source": source,
    }


__all__ = [
    "ProvenanceRecord",
    "SafetyVerdict",
    "SafetyGate",
    "ImportResult",
    "import_external_session",
    "build_session_dict_from_import",
]
