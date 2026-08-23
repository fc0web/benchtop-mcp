#!/usr/bin/env python3
"""
benchtop-mcp olfact / biosensor layer : 生体嗅覚センサ mock spike
================================================================================

v0.7.0-alpha (2026-08-23, 藤本さん directive (a) 「benchtop-mcp v0.7 olfact connector
v0.1 spike」 実装、 対話 arc 「虫の触覚センサー / 動物のセンサー / 植物のセンサー」
「AI に役立つか」 3 turn 経由)。

**目的**:

  現状の benchtop-mcp は SCPI 電気計測 (Kikusui / Rigol 等) の domain のみ。
  本 module は 生体嗅覚センサ (EAG = Electroantennogram、 受容体 FET、 bio-inspired
  e-nose) を benchtop の 新 channel として mock 段階で 追加する。 hardware 未取得
  = 全 tool で hardware_available: False marker 徹底、 実測データではないことを
  return dict で 機械的に判別可能に。

**3 tool** (藤本さん directive 準拠、 chat-Claude 相当 tool 提示なし = 私 (Claude Code)
の 命名):

  1. list_probes() → 内蔵 mock probe registry の 一覧 (3 layer 各 1 probe)
  2. measure_eag(probe_id, odor_name, duration_s, sample_rate_hz) → mock EAG
     waveform + peak amplitude + SNR + D-FUMT₈ verdict (STEP 1350 mapping)
  3. probe_health(probe_id, age_hours, last_calibration_hours_ago) → 生体劣化
     verdict {HEALTHY / DEGRADING / EXPIRED / UNCALIBRATED}

**3 layer** (対話 arc で 整理した 3 分類):

  ① bio-hybrid (生体をそのまま部品)  = silkworm-antenna-a1 (7h hydrogel)
  ② receptor-chip (受容体タンパク質 + FET) = mosquito-receptor-fet-b1 (0.5 ppb)
  ③ bio-inspired (原理模倣、 完全機械)     = sparse-e-nose-c1 (silicon)

**★ 命名 discipline** ([[feedback-super-naming-siren-family-pattern]] 適用):

  「measure_eag」 は実 hardware で 実 EAG 波形を返す tool と 誤解されやすい。
  v0.1 spike の scope 内では 全 return dict に is_mock: True + hardware_available:
  False を含め、 mock signal 生成 が deterministic (probe_id + odor_name の
  hashlib.md5 seed 由来、 cross-process 安定) であることを 明示する。 実 hardware
  統合は 別 STEP candidate、 現段階では 「実 hardware に置換可能な interface
  skeleton」 位置のみ。

**★ pool saturation 予防** ([[feedback-projection-self-audit-pattern]] SAC-4 適用):

  「生体センサ 装置化」 の 主張は 論文レベル既存 (Osmo Principal Odor Map 2023 /
  神奈川産技研 2026-06 / Scentian Bio 等)、 本 module は Rei stack 内 benchtop への
  新 domain 追加のみ、 novelty ゼロ ([[feedback-world-uniqueness-claim-controllable]]
  継承)。 「世界初」 主張なし。

**scope 明示** (v0.7.0-alpha spike scope):

  (1) 全 tool は pure calculation (stdlib のみ、 network / file I/O なし)、 状態なし
      (built-in registry 3 probe のみ、 hardware discovery は 実装しない)。
      remote MCP としても そのまま deploy 可能。
  (2) mock waveform は deterministic (probe_id + odor_name の hashlib.md5 由来
      seed で cross-process 再現可能)、 生体信号の 実 physics (ion channel kinetics
      等) を模倣していない = 教育 / interface skeleton 用途のみ。 md5 は cryptographic
      用途ではない (単純 seed 用途、 collision resistance は要求せず)。
  (3) probe_health degradation model は 対話 arc で 挙げた 論文数値 (7h hydrogel /
      0.5 ppb) を parameter として 使うだけの 単純線形 / exponential model、
      実 hardware feedback loop なし。 校正 hazard 検出 (実 hardware で 必須の
      機能) は 未実装 = v0.2 candidate。
  (4) STEP 1350 d8_verdict_from_measurement primitive を 3 値 subset で 参照
      (TRUE=SNR≥threshold / NEITHER=SNR<threshold or hardware not present)、
      BOTH / FALSE / SELF / ∞ / ○ / 〜 は 未使用 (5/8 → 2/8 subset)。
  (5) SafetyGate (STEP 1345 v0.5.0-alpha) との 統合は 未実装 = 生体センサ hazard
      (probe 感染 / 揮発性有機物 exposure 等) rule は v0.2 candidate。
  (6) 実 EAG 実験には 別途: フロントエンドアンプ (差動 GΩ入力) + シールド box +
      恒温恒湿 + オルファクトメータ + シリアル DAQ が必要、 本 module は 全部
      置換可能な interface のみ、 実物調達 は 藤本さん judgment 待ち。

**Rei stack alignment**:

  - STEP 1345 SafetyGate と 相補 (SafetyGate = SCPI-arg hazard、 olfact = 生体劣化)
  - STEP 1348 physics-limits と 相補 (physics-limits = 上界計算、 olfact = 測定 layer)
  - STEP 1350 d8_verdict_from_measurement を 3 値 subset で 参照 (verdict field)
  - benchtop-mcp v0.6 の 拡張 (systems 数 8 不変、 v0.6 tool 17 → v0.7 tool 20)

**related memory**:

  - 対話 arc 2026-08-23 (「虫の触覚センサー、 動物のセンサー、 植物のセンサー」)
  - [[feedback-super-naming-siren-family-pattern]] (mock でない 誤読 予防)
  - [[feedback-projection-self-audit-pattern]] SAC-4 (pool saturation 予防)
  - [[feedback-world-uniqueness-claim-controllable]] (novelty 主張ゼロ discipline)
  - [[feedback-peace-axiom-hardware-io-extension-2026-08-17]] (Peace Axiom I/O 拡張)
  - [[project-step1345-benchtop-provenance-spike-2026-08-19]] (v0.5.0-alpha SafetyGate)
  - [[project-step1348-benchtop-physics-limits-v06-2026-08-20]] (v0.6.0-alpha physics-limits)
  - [[project-step1350-d8-verdict-mapping-phase-a-2026-08-20]] (SNR<3 → NEITHER 原典)

**References** (公開文献、 全 外部 evidence):

  - Silkworm-moth EAG hydrogel electrode 7h stability (2026, npj Robotics 等)
  - Mosquito odorant receptor + CNT-FET 0.5 ppb (東大生研 / ACS AMI 2026)
  - 神奈川県立産業技術総合研究所 + 東大生研 尿匂い成分 がん関連 VOC 検出 (JST 2026-06)
  - Scentian Bio 昆虫嗅覚受容体 startup (NZ, funding)
  - MIT plant nanobionics (CNT + 近赤外蛍光、 water stress 検出)
  - Osmo Principal Odor Map (Science 2023、 AI + 匂い埋め込みベクトル空間)
  - Insect-inspired sparse-coding e-nose chip (2026-07)

License: benchtop-mcp v0.x = MIT (irrevocable per README)。
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

# ---------------------------------------------------------------------------
# Built-in mock probe registry (stateless, immutable)
# 3 layer 各 1 probe = 対話 arc で整理した 3 分類の 代表 mock。
# 実 hardware は 全て hardware_available: False。
# ---------------------------------------------------------------------------

_MOCK_PROBES: dict[str, dict[str, Any]] = {
    "silkworm-antenna-a1": {
        "layer": "bio-hybrid",
        "layer_number": 1,
        "type": "silkworm-moth-antenna-EAG",
        "reference": "npj Robotics 2026 (hydrogel electrode, 7h stability)",
        "expected_lifetime_hours": 7.0,
        "sensitivity_ppb": 1.0,
        "channels": 1,
        "hardware_available": False,
        "degradation_model": "linear-hydrogel-dehydration",
        "notes": "生体触角を hydrogel 電極で保水、 EAG 差動アンプ (GΩ 入力) 必須",
    },
    "mosquito-receptor-fet-b1": {
        "layer": "receptor-chip",
        "layer_number": 2,
        "type": "odorant-receptor-nanodisc-CNT-FET",
        "reference": "ACS Appl Mater Interfaces 2026 (0.5 ppb detection)",
        "expected_lifetime_hours": 168.0,  # ~1 week
        "sensitivity_ppb": 0.5,
        "channels": 4,
        "hardware_available": False,
        "degradation_model": "exponential-protein-denaturation",
        "notes": "受容体タンパク質を nanodisc に埋込 CNT-FET チャネル、 実運用は 4℃ 保管",
    },
    "sparse-e-nose-c1": {
        "layer": "bio-inspired",
        "layer_number": 3,
        "type": "insect-olfactory-sparse-coding-chip",
        "reference": "2026-07 semiconductor insect-inspired e-nose",
        "expected_lifetime_hours": 8760.0,  # ~1 year
        "sensitivity_ppb": 100.0,
        "channels": 32,
        "hardware_available": False,
        "degradation_model": "calibration-only-silicon",
        "notes": "完全 silicon、 生体成分ゼロ、 sparse coding で 少素子から匂い分類",
    },
}


# ---------------------------------------------------------------------------
# list_probes : 内蔵 mock registry の 一覧
# ---------------------------------------------------------------------------

def list_probes() -> dict[str, Any]:
    """内蔵 mock probe registry の 一覧を返す。 全 probe は hardware_available: False。

    Returns:
        dict with:
          ok: True
          probes: list of probe descriptor (id + layer + type + reference + ...)
          probe_count: 3
          hardware_available: False (spike scope、 全 probe mock)
          honest_scope: mock registry のみ、 実 hardware discovery 未実装
          related_step: STEP 番号 未予約 (write-time gate)
    """
    probes = []
    for pid, meta in _MOCK_PROBES.items():
        entry = {"probe_id": pid}
        entry.update(meta)
        probes.append(entry)
    return {
        "ok": True,
        "probes": probes,
        "probe_count": len(probes),
        "hardware_available": False,
        "is_mock": True,
        "honest_scope": (
            "v0.7.0-alpha spike: 内蔵 mock registry 3 probe のみ、 実 hardware "
            "discovery 未実装。 全 probe は hardware_available: False marker で "
            "実測データでないことを 機械的に判別可能。"
        ),
        "related_step": "STEP 番号 未予約 (帰宅時 git log で 割当)",
        "source": "benchtop-olfact-mock-registry",
    }


# ---------------------------------------------------------------------------
# _mock_eag_waveform : deterministic mock EAG signal
# probe_id + odor_name の hashlib.md5 由来 seed (cross-process 安定) で 再現可能な mock 波形。
# 実 physics (ion channel kinetics) を模倣していない = interface skeleton のみ。
# ---------------------------------------------------------------------------

def _mock_eag_waveform(
    probe_id: str, odor_name: str, duration_s: float, sample_rate_hz: float
) -> tuple[list[float], float, float, float]:
    """deterministic mock EAG waveform。 返り値: (waveform_mv, peak_mv, amp_mv, noise_mv)。

    envelope: rise 0.5s → exp decay τ=2s (典型 EAG 応答 envelope の 単純化)。
    amplitude: probe_id + odor_name hash から 0.1〜2.0 mV の deterministic 値。
    noise floor: 0.05 mV (AgCl 電極 典型 noise、 spike では固定)。
    """
    n = max(1, int(duration_s * sample_rate_hz))
    # hashlib.md5 = cross-process stable (Python built-in hash() は PYTHONHASHSEED で
    # process 毎に seed 化されるため cross-process 決定的ではない = spike の 「再現可能」
    # claim を 満たすため md5 必要)。 md5 は cryptographic 用途ではない = 単純 seed 用途。
    md5_bytes = hashlib.md5(f"{probe_id}|{odor_name}".encode("utf-8")).digest()
    seed_int = int.from_bytes(md5_bytes[:4], "big")
    amp_mv = 0.1 + (seed_int % 1900) / 1000.0  # 0.1 .. 2.0 mV
    noise_mv = 0.05
    waveform = []
    for i in range(n):
        t = i / sample_rate_hz
        if t < 0.5:
            env = t / 0.5
        else:
            env = math.exp(-(t - 0.5) / 2.0)
        # deterministic noise from linear congruential seed advance
        noise = ((seed_int + i * 7919) % 1000 - 500) / 500.0 * noise_mv
        waveform.append(amp_mv * env + noise)
    peak_mv = max(waveform) if waveform else 0.0
    return waveform, peak_mv, amp_mv, noise_mv


# ---------------------------------------------------------------------------
# measure_eag : mock EAG measurement (spike scope、 hardware 不在で 決定的)
# ---------------------------------------------------------------------------

def measure_eag(
    probe_id: str,
    odor_name: str,
    duration_s: float = 3.0,
    sample_rate_hz: float = 100.0,
    snr_threshold: float = 3.0,
) -> dict[str, Any]:
    """mock EAG 測定。 probe_id + odor_name から deterministic 波形を生成、 SNR と
    D-FUMT₈ verdict (STEP 1350 mapping subset) を返す。

    Args:
        probe_id: list_probes() の 'probe_id' field (silkworm-antenna-a1 等)。
        odor_name: 提示する 匂い名 (mock、 実 stimulus 装置 制御なし)。
        duration_s: 測定継続時間 (秒)、 must be > 0。
        sample_rate_hz: サンプリング周波数 (Hz)、 must be > 0。
        snr_threshold: D-FUMT₈ verdict の TRUE / NEITHER 境界 (default 3.0、
            STEP 1350 primitive と 同 default)。

    Returns dict with:
        ok, probe_id, odor_name, duration_s, sample_rate_hz, sample_count,
        waveform_mv (list[float]), peak_mv, amp_estimated_mv, noise_floor_mv,
        snr_ratio, snr_threshold, verdict_d8, verdict_d8_symbol,
        is_mock: True, hardware_available: False, honest_scope, source。
    """
    if probe_id not in _MOCK_PROBES:
        return {
            "ok": False,
            "error": f"unknown probe_id: {probe_id!r}",
            "known_probes": sorted(_MOCK_PROBES.keys()),
            "source": "benchtop-olfact-measure",
        }
    if duration_s <= 0:
        return {"ok": False, "error": "duration_s must be > 0", "source": "benchtop-olfact-measure"}
    if sample_rate_hz <= 0:
        return {"ok": False, "error": "sample_rate_hz must be > 0", "source": "benchtop-olfact-measure"}
    if snr_threshold <= 0:
        return {"ok": False, "error": "snr_threshold must be > 0", "source": "benchtop-olfact-measure"}

    waveform, peak_mv, amp_mv, noise_mv = _mock_eag_waveform(
        probe_id, odor_name, duration_s, sample_rate_hz
    )
    snr = amp_mv / noise_mv if noise_mv > 0 else float("inf")
    if snr >= snr_threshold:
        verdict = "TRUE"
        symbol = "⊤"
        reason = "signal_above_noise"
    else:
        verdict = "NEITHER"
        symbol = "〜"
        reason = "snr_below_threshold"

    return {
        "ok": True,
        "probe_id": probe_id,
        "probe_layer": _MOCK_PROBES[probe_id]["layer"],
        "odor_name": odor_name,
        "duration_s": duration_s,
        "sample_rate_hz": sample_rate_hz,
        "sample_count": len(waveform),
        "waveform_mv": waveform,
        "peak_mv": peak_mv,
        "amp_estimated_mv": amp_mv,
        "noise_floor_mv": noise_mv,
        "snr_ratio": snr,
        "snr_threshold": snr_threshold,
        "verdict_d8": verdict,
        "verdict_d8_symbol": symbol,
        "verdict_reason": reason,
        "is_mock": True,
        "hardware_available": False,
        "honest_scope": (
            "v0.7.0-alpha spike: deterministic mock waveform (probe_id + odor_name "
            "hash seed 由来)、 実 EAG physics (ion channel kinetics 等) を模倣して "
            "いない = interface skeleton のみ。 実 hardware 統合は 別 STEP candidate。"
        ),
        "d8_mapping_source": "STEP 1350 d8_verdict_from_measurement (3-value subset)",
        "source": "benchtop-olfact-measure",
    }


# ---------------------------------------------------------------------------
# probe_health : 生体劣化 verdict (mock、 spike scope)
# 3 layer 別 degradation model:
#   ① bio-hybrid       = linear (hydrogel dehydration)
#   ② receptor-chip    = exponential (protein denaturation)
#   ③ bio-inspired     = calibration-only (silicon、 生体劣化なし)
# ---------------------------------------------------------------------------

def probe_health(
    probe_id: str,
    age_hours: float,
    last_calibration_hours_ago: float = 0.0,
    calibration_max_interval_hours: float = 24.0,
) -> dict[str, Any]:
    """probe 劣化 verdict。 age_hours (probe 開梱後経過時間) と last_calibration_hours_ago
    (最後の校正からの経過時間) から HEALTHY / DEGRADING / EXPIRED / UNCALIBRATED を返す。

    Args:
        probe_id: list_probes() の 'probe_id' field。
        age_hours: probe を "開梱" (bio-hybrid: 電極接続、 receptor-chip: 4℃ 取り出し、
            bio-inspired: 電源投入) してからの 経過時間 (時間)、 must be >= 0。
        last_calibration_hours_ago: 最後の 校正からの 経過時間 (時間)、 default 0
            (直前校正)、 must be >= 0。
        calibration_max_interval_hours: 校正有効期間 (時間)、 default 24
            (実 lab 標準的 daily calibration)。

    Returns dict with:
        ok, probe_id, layer, age_hours, expected_lifetime_hours, age_ratio,
        health_score (0.0-1.0), verdict {HEALTHY / DEGRADING / EXPIRED / UNCALIBRATED},
        degradation_model, is_calibrated, last_calibration_hours_ago,
        is_mock: True, hardware_available: False, honest_scope, source。
    """
    if probe_id not in _MOCK_PROBES:
        return {
            "ok": False,
            "error": f"unknown probe_id: {probe_id!r}",
            "known_probes": sorted(_MOCK_PROBES.keys()),
            "source": "benchtop-olfact-health",
        }
    if age_hours < 0:
        return {"ok": False, "error": "age_hours must be >= 0", "source": "benchtop-olfact-health"}
    if last_calibration_hours_ago < 0:
        return {
            "ok": False,
            "error": "last_calibration_hours_ago must be >= 0",
            "source": "benchtop-olfact-health",
        }
    if calibration_max_interval_hours <= 0:
        return {
            "ok": False,
            "error": "calibration_max_interval_hours must be > 0",
            "source": "benchtop-olfact-health",
        }

    meta = _MOCK_PROBES[probe_id]
    expected_lifetime = meta["expected_lifetime_hours"]
    model = meta["degradation_model"]
    age_ratio = age_hours / expected_lifetime if expected_lifetime > 0 else 0.0

    if model == "linear-hydrogel-dehydration":
        # bio-hybrid: linear decay, 100% at age=0, 0% at expected_lifetime
        health = max(0.0, 1.0 - age_ratio)
    elif model == "exponential-protein-denaturation":
        # receptor-chip: exponential decay, health = exp(-age/lifetime)
        health = math.exp(-age_ratio)
    elif model == "calibration-only-silicon":
        # bio-inspired: no biological aging, only calibration-dependent
        health = 1.0
    else:
        health = 0.0  # unknown model fallback

    is_calibrated = last_calibration_hours_ago <= calibration_max_interval_hours

    # verdict decision tree
    if not is_calibrated:
        verdict = "UNCALIBRATED"
        verdict_reason = "last_calibration_expired"
    elif age_ratio > 1.5:
        verdict = "EXPIRED"
        verdict_reason = "age_exceeded_150pct_lifetime"
    elif health <= 0.3:
        verdict = "EXPIRED"
        verdict_reason = "health_score_below_threshold"
    elif health <= 0.7:
        verdict = "DEGRADING"
        verdict_reason = "health_score_in_warning_range"
    else:
        verdict = "HEALTHY"
        verdict_reason = "health_score_above_threshold"

    return {
        "ok": True,
        "probe_id": probe_id,
        "layer": meta["layer"],
        "layer_number": meta["layer_number"],
        "age_hours": age_hours,
        "expected_lifetime_hours": expected_lifetime,
        "age_ratio": age_ratio,
        "health_score": health,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "degradation_model": model,
        "is_calibrated": is_calibrated,
        "last_calibration_hours_ago": last_calibration_hours_ago,
        "calibration_max_interval_hours": calibration_max_interval_hours,
        "is_mock": True,
        "hardware_available": False,
        "honest_scope": (
            "v0.7.0-alpha spike: 単純 degradation model (linear / exponential / "
            "calibration-only)、 実 hardware feedback loop なし、 実測 lifetime との "
            "cross-check なし。 校正 hazard 検出 (実 lab で 必須) は v0.2 candidate。"
        ),
        "reference": meta["reference"],
        "source": "benchtop-olfact-health",
    }


# ---------------------------------------------------------------------------
# _selftest : 本 module 単体 self-verify
# ---------------------------------------------------------------------------

def _selftest() -> int:
    """本 module 単体の selftest。 実行: python benchtop_olfact.py --selftest"""
    # Windows cp932 対応: UTF-8 に reconfigure (D-FUMT₈ 8 値記号 ⊤ 〜 出力用)
    import sys as _sys
    try:
        _sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    print("=== benchtop_olfact v0.7.0-alpha selftest ===")
    passed, failed = 0, 0

    def check(cond: bool, msg: str) -> None:
        nonlocal passed, failed
        if cond:
            passed += 1
        else:
            failed += 1
            print(f"  FAIL: {msg}")

    # [1] list_probes: 3 probe 全て hardware_available=False
    r1 = list_probes()
    check(r1["ok"] is True, "list_probes ok")
    check(r1["probe_count"] == 3, "list_probes count=3")
    check(r1["hardware_available"] is False, "list_probes hardware_available=False")
    check(r1["is_mock"] is True, "list_probes is_mock=True")
    check(all(not p["hardware_available"] for p in r1["probes"]), "all probes hw=False")
    ids = {p["probe_id"] for p in r1["probes"]}
    check(ids == {"silkworm-antenna-a1", "mosquito-receptor-fet-b1", "sparse-e-nose-c1"},
          "3 probe id match")
    print(f"[1] list_probes: count={r1['probe_count']} ids={sorted(ids)}")

    # [2] measure_eag: valid probe, deterministic waveform
    r2 = measure_eag("silkworm-antenna-a1", "cis-3-hexenol", duration_s=3.0, sample_rate_hz=100.0)
    check(r2["ok"] is True, "measure_eag ok")
    check(r2["sample_count"] == 300, "measure_eag sample_count=300")
    check(r2["is_mock"] is True, "measure_eag is_mock=True")
    check(r2["hardware_available"] is False, "measure_eag hw=False")
    check(r2["verdict_d8"] in ("TRUE", "NEITHER"), "measure_eag verdict in TRUE/NEITHER")
    print(f"[2] measure_eag: amp={r2['amp_estimated_mv']:.3f} mV noise={r2['noise_floor_mv']:.3f} "
          f"snr={r2['snr_ratio']:.1f} verdict={r2['verdict_d8']}/{r2['verdict_d8_symbol']}")

    # [3] measure_eag: determinism (same input → same output)
    r3a = measure_eag("silkworm-antenna-a1", "cis-3-hexenol", 1.0, 100.0)
    r3b = measure_eag("silkworm-antenna-a1", "cis-3-hexenol", 1.0, 100.0)
    check(r3a["waveform_mv"] == r3b["waveform_mv"], "measure_eag deterministic")
    check(r3a["amp_estimated_mv"] == r3b["amp_estimated_mv"], "measure_eag amp deterministic")
    print(f"[3] measure_eag determinism: waveform equal={r3a['waveform_mv'] == r3b['waveform_mv']}")

    # [4] measure_eag: different odor → different waveform (usually)
    r4a = measure_eag("silkworm-antenna-a1", "odor-A", 1.0, 100.0)
    r4b = measure_eag("silkworm-antenna-a1", "odor-B", 1.0, 100.0)
    check(r4a["waveform_mv"] != r4b["waveform_mv"], "different odor → different waveform")
    print(f"[4] different odor: amp_A={r4a['amp_estimated_mv']:.3f} amp_B={r4b['amp_estimated_mv']:.3f}")

    # [5] measure_eag: unknown probe rejection
    r5 = measure_eag("unknown-probe", "odor", 1.0, 100.0)
    check(r5["ok"] is False, "unknown probe rejected")
    check("known_probes" in r5, "known_probes listed on error")
    print(f"[5] unknown probe rejected: known={len(r5['known_probes'])}")

    # [6] measure_eag: invalid args
    r6a = measure_eag("silkworm-antenna-a1", "odor", duration_s=-1, sample_rate_hz=100)
    r6b = measure_eag("silkworm-antenna-a1", "odor", duration_s=1, sample_rate_hz=0)
    r6c = measure_eag("silkworm-antenna-a1", "odor", 1, 100, snr_threshold=-1)
    check(not r6a["ok"] and not r6b["ok"] and not r6c["ok"], "invalid args all rejected")
    print(f"[6] invalid args rejected: 3/3")

    # [7] probe_health: bio-hybrid at age=0 → HEALTHY
    r7 = probe_health("silkworm-antenna-a1", age_hours=0.0, last_calibration_hours_ago=0.0)
    check(r7["ok"] is True, "probe_health ok")
    check(r7["verdict"] == "HEALTHY", f"age=0 → HEALTHY (got {r7['verdict']})")
    check(r7["health_score"] == 1.0, "age=0 → health=1.0")
    check(r7["is_calibrated"] is True, "calibration=0h → calibrated")
    print(f"[7] silkworm age=0: verdict={r7['verdict']} health={r7['health_score']:.3f}")

    # [8] probe_health: bio-hybrid at age=3.5h (half lifetime) → DEGRADING or HEALTHY border
    r8 = probe_health("silkworm-antenna-a1", age_hours=3.5, last_calibration_hours_ago=1.0)
    check(r8["ok"] is True, "probe_health mid-life ok")
    check(r8["health_score"] == 0.5, f"linear at age=3.5/7=0.5 (got {r8['health_score']})")
    # verdict at health=0.5 → DEGRADING (0.3 < 0.5 <= 0.7)
    check(r8["verdict"] == "DEGRADING", f"health=0.5 → DEGRADING (got {r8['verdict']})")
    print(f"[8] silkworm age=3.5h: verdict={r8['verdict']} health={r8['health_score']:.3f}")

    # [9] probe_health: bio-hybrid at age=10h (150% lifetime) → EXPIRED
    r9 = probe_health("silkworm-antenna-a1", age_hours=10.5, last_calibration_hours_ago=1.0)
    check(r9["verdict"] == "EXPIRED", f"age=10.5h (150%) → EXPIRED (got {r9['verdict']})")
    print(f"[9] silkworm age=10.5h: verdict={r9['verdict']} age_ratio={r9['age_ratio']:.2f}")

    # [10] probe_health: uncalibrated overrides age
    r10 = probe_health("silkworm-antenna-a1", age_hours=0.0, last_calibration_hours_ago=48.0)
    check(r10["verdict"] == "UNCALIBRATED", f"48h cal ago → UNCALIBRATED (got {r10['verdict']})")
    check(r10["is_calibrated"] is False, "48h > 24h max → not calibrated")
    print(f"[10] uncalibrated overrides age: verdict={r10['verdict']}")

    # [11] probe_health: bio-inspired (silicon) at age=1000h → still HEALTHY (calibration-only)
    r11 = probe_health("sparse-e-nose-c1", age_hours=1000.0, last_calibration_hours_ago=1.0)
    check(r11["verdict"] == "HEALTHY", f"silicon age=1000h + calibrated → HEALTHY (got {r11['verdict']})")
    check(r11["health_score"] == 1.0, "silicon no biological aging")
    print(f"[11] sparse-e-nose age=1000h: verdict={r11['verdict']} model={r11['degradation_model']}")

    # [12] probe_health: receptor-chip exponential at age=lifetime → health ≈ 1/e ≈ 0.368
    r12 = probe_health("mosquito-receptor-fet-b1", age_hours=168.0, last_calibration_hours_ago=1.0)
    check(abs(r12["health_score"] - math.exp(-1.0)) < 0.001,
          f"exponential at age=lifetime → 1/e (got {r12['health_score']})")
    # health ≈ 0.368 → DEGRADING (0.3 < 0.368 <= 0.7)
    check(r12["verdict"] == "DEGRADING", f"health=1/e → DEGRADING (got {r12['verdict']})")
    print(f"[12] mosquito age=168h: verdict={r12['verdict']} health={r12['health_score']:.3f}")

    # [13] probe_health: invalid args
    r13a = probe_health("silkworm-antenna-a1", age_hours=-1)
    r13b = probe_health("silkworm-antenna-a1", age_hours=1, last_calibration_hours_ago=-1)
    r13c = probe_health("unknown", age_hours=1)
    check(not r13a["ok"] and not r13b["ok"] and not r13c["ok"], "invalid args rejected")
    print(f"[13] invalid args rejected: 3/3")

    # [14] source markers: 全 tool で source field present
    check(r1["source"] == "benchtop-olfact-mock-registry", "list_probes source")
    check(r2["source"] == "benchtop-olfact-measure", "measure_eag source")
    check(r7["source"] == "benchtop-olfact-health", "probe_health source")
    print(f"[14] source markers: 3/3 present")

    print(f"\n=== selftest result: {passed} passed, {failed} failed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print("This module is a library. Run with --selftest to verify.")
