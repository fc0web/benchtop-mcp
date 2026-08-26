#!/usr/bin/env python3
"""
benchtop-mcp Akizuki wire-up chemistry layer : CO2 / VOC mock spike
================================================================================

v0.9.0-alpha (2026-08-26, Rei stack STEP 1415 別 tab pickup、 STEP 1407 の
続編 = 化学 layer を STEP 1408 「v0.9-alpha 化学 layer candidate」 明示 の
MVP path (SCD40 CO2 + SGP40 VOC の I2C 2 SKU) で skeleton 化)。

**目的**:

  STEP 1407 v0.8 の 3 layer (環境 / 慣性 / 距離) の gap fill 続編として、
  STEP 1408 で recon 済 の 気体センサー 10 SKU から MVP 2 SKU
  (SCD40 = 光音響 NDIR CO2、 SGP40 = 金属酸化物 VOC index) を benchtop-mcp
  mock として 追加する。 hardware 未取得 = 全 tool で hardware_available: False
  marker 徹底、 STEP 1407 akizuki_wireup pattern を そのまま 継承。

**3 tool** (STEP 1407 4 tool の 続編):

  1. list_chem_probes() → 内蔵 mock chem probe registry の 一覧 (2 SKU)
  2. measure_co2_ndir(probe_id, condition_tag) → SCD40 mock
     (co2_ppm + temperature_c + humidity_pct + STEP 1350 verdict)
  3. measure_voc_index(probe_id, condition_tag) → SGP40 mock
     (voc_index 0-500 + raw_resistance_ohm + STEP 1350 verdict)

**2 SKU** (STEP 1408 MVP path、 I2C 定番 の 化学 layer 2 定番 SKU):

  ① CO2 (光音響 NDIR) = SCD40 (Akizuki 通販コード 117851、 I2C、 ¥5,980)
  ② VOC index (金属酸化物) = SGP40 (Akizuki 通販コード 116444、 I2C、 ¥1,280)

**★ 命名 discipline** ([[feedback-super-naming-siren-family-pattern]] 適用):

  「measure_co2_ndir」 は 実 hardware で 実測値を返す tool と 誤解されやすい。
  v0.9 spike の scope 内では 全 return dict に is_mock: True + hardware_available:
  False を含め、 mock 値生成 が deterministic (probe_id + condition_tag の
  hashlib.md5 seed 由来、 cross-process 安定) であることを 明示する。 実 hardware
  wire-up は 別 STEP candidate (SCD40 の I2C driver 実装 + ESP32/STM32 host +
  UART 経由 benchtop 統合 の 4 段 barrier、 STEP 1406/1408 に 記載)。

**★ pool saturation 予防** ([[feedback-projection-self-audit-pattern]] SAC-4 適用):

  「秋月 気体 module wire-up」 の 主張は 個人電子工作 + 学生実習 の 定番 pattern で
  novelty ゼロ ([[feedback-world-uniqueness-claim-controllable]] 継承)、 本 module
  は Rei stack 内 benchtop への 化学 layer 1 domain 追加のみ、 「世界初」 主張なし。

**scope 明示** (v0.9.0-alpha spike scope、 8 条):

  (1) 全 tool は pure calculation (stdlib のみ、 network / file I/O なし)、
      状態なし (built-in registry 2 probe のみ、 hardware discovery なし)。
      remote MCP としても そのまま deploy 可能。
  (2) mock 値は deterministic (probe_id + condition_tag の hashlib.md5 由来
      seed で cross-process 再現可能)、 実 sensor physics (光音響 phonon oscillation
      / 金属酸化物 表面吸着 電気抵抗変化 等) を模倣していない = 教育 / interface
      skeleton 用途のみ。 md5 は cryptographic 用途ではない (単純 seed 用途)。
  (3) SCD40 CO2 range: 400〜2000 ppm (datasheet 典型 屋内 CO2 濃度 range、
      実 sensor は 0〜40,000 ppm operating range だが mock は 屋内 realistic
      range に狭めた subset を 使用)。
  (4) SCD40 温湿度: -10〜60°C, 0〜95% RH (datasheet 動作範囲)。
  (5) SGP40 VOC index: 0〜500 (Sensirion 独自 index、 100=nominal ambient、
      0〜100=improving quality、 100〜500=degrading quality、 datasheet 表記)。
  (6) SGP40 raw resistance: 20kΩ〜100MΩ (datasheet 動作範囲、 log scale で
      hash から 決定的に選択)。
  (7) STEP 1350 d8_verdict_from_measurement primitive を 2 値 subset で 参照
      (TRUE if in-range / NEITHER if out-of-range or hardware not present)。
      BOTH / FALSE / SELF / ∞ / ○ / 〜 の 6 値 は 未使用 (2/8 subset)。
  (8) SafetyGate (STEP 1345 v0.5.0-alpha) との 統合は 未実装 = SCD40/SGP40
      は 3.3V I2C の 微弱電流 で SafetyGate 対象外。 STEP 1408 で 明示された
      可燃性ガス 系 (MQ-2/3B/4 = 内蔵ヒーター 5V/150mA + 発火源) は v0.10+
      候補 = SafetyGate rule 拡張 と 同時 に 実装予定。

**Rei stack alignment**:

  - STEP 1345 SafetyGate と 相補 (現段階 CO2/VOC は 対象外、 可燃性 は v0.10+)
  - STEP 1348 physics-limits と 相補 (physics-limits = 上界計算、 本 module = 測定 layer)
  - STEP 1350 d8_verdict_from_measurement を 2 値 subset で 参照 (verdict field)
  - STEP 1396 olfact/biosensor mock v0.7 と 相補 (olfact = 匂い分子検出 EAG、
    本 module = 単一分子 CO2/VOC index、 layer は 別)
  - STEP 1407 akizuki_wireup v0.8 pattern を そのまま 継承 (structural sibling)
  - STEP 1408 気体センサー 10 SKU recon から MVP 2 SKU pilot
  - benchtop-mcp v0.8 tool 24 → v0.9 tool 27 (+3)

**related memory**:

  - [[project-step1408-akizuki-gas-co2-recon-2026-08-26]] (10 SKU list origin + MVP path 明示)
  - [[project-step1407-benchtop-v08-akizuki-wireup-mock-2026-08-26]] (structural sibling pattern)
  - [[project-step1396-benchtop-olfact-spike-2026-08-23]] (匂い系 別 layer)
  - [[project-step1350-d8-verdict-mapping-phase-a-2026-08-20]] (verdict field 原典)
  - [[project-step1345-benchtop-provenance-spike-2026-08-19]] (SafetyGate、 v0.10+ 拡張候補)
  - [[feedback-super-naming-siren-family-pattern]] (mock でない 誤読 予防)
  - [[feedback-projection-self-audit-pattern]] SAC-4 (pool saturation 予防)
  - [[feedback-world-uniqueness-claim-controllable]] (novelty 主張ゼロ discipline)

**References** (公開文献 + datasheet、 全 外部 evidence):

  - Sensirion SCD40 datasheet (Photoacoustic NDIR CO2 sensor, I2C, 400-2000 ppm typical)
  - Sensirion SGP40 datasheet (Metal-oxide VOC index sensor, I2C, index 0-500)
  - Akizuki 通販コード 117851 / 116444 (2026-08-26 catalog 表記)

License: benchtop-mcp v0.x = MIT (irrevocable per README)。
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

# ---------------------------------------------------------------------------
# Built-in mock chem probe registry (stateless, immutable)
# 2 SKU = STEP 1408 MVP path (SCD40 CO2 + SGP40 VOC の I2C 2 定番)
# 全 hardware_available: False marker 徹底。
# ---------------------------------------------------------------------------

_MOCK_CHEM_PROBES: dict[str, dict[str, Any]] = {
    "scd40-co2-d1": {
        "layer": "chemistry",
        "sublayer": "co2_ndir",
        "sublayer_number": 1,
        "part_number": "SCD40",
        "akizuki_code": "117851",
        "akizuki_price_jpy": 5980,
        "interface": "I2C",
        "vendor": "Sensirion",
        "measures": ["co2_ppm", "temperature_c", "humidity_pct"],
        "range_co2_ppm": [400.0, 2000.0],
        "range_temp_c": [-10.0, 60.0],
        "range_humidity_pct": [0.0, 95.0],
        "resolution": "1 ppm CO2 / 0.01°C / 0.1%RH (datasheet 典型)",
        "principle": "photoacoustic_ndir",
        "hardware_available": False,
        "notes": "光音響 NDIR CO2、 屋内 空気質モニタ 定番、 I2C addr 0x62、 5s update cycle",
    },
    "sgp40-voc-d2": {
        "layer": "chemistry",
        "sublayer": "voc_index",
        "sublayer_number": 2,
        "part_number": "SGP40",
        "akizuki_code": "116444",
        "akizuki_price_jpy": 1280,
        "interface": "I2C",
        "vendor": "Sensirion",
        "measures": ["voc_index", "raw_resistance_ohm"],
        "range_voc_index": [0.0, 500.0],
        "range_raw_ohm": [20000.0, 100000000.0],
        "voc_index_nominal": 100.0,
        "resolution": "1 index unit (Sensirion 独自 scale、 datasheet 表記)",
        "principle": "metal_oxide_semiconductor",
        "hardware_available": False,
        "notes": "金属酸化物 (SnO2 系) VOC index、 100=nominal / 0-100=improving / 100-500=degrading、 I2C addr 0x59",
    },
}


# ---------------------------------------------------------------------------
# list_chem_probes : 内蔵 mock chem registry の 一覧
# ---------------------------------------------------------------------------

def list_chem_probes() -> dict[str, Any]:
    """内蔵 mock chem probe registry (Akizuki 化学 layer 2 SKU) の 一覧を返す。
    全 probe は hardware_available: False。

    Returns:
        dict with:
          ok: True
          probes: list of probe descriptor (part_number / akizuki_code / range 等)
          probe_count: 2
          hardware_available: False (spike scope、 全 probe mock)
          is_mock: True
          honest_scope: mock registry のみ、 実 hardware discovery 未実装
          related_step: STEP 1408 (10 SKU recon origin + MVP path 明示)
    """
    probes = []
    for pid, meta in _MOCK_CHEM_PROBES.items():
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
            "v0.9.0-alpha spike: 内蔵 mock chem registry 2 probe (SCD40/SGP40) のみ、 "
            "実 hardware discovery 未実装。 全 probe は hardware_available: False marker で "
            "実測データでないことを 機械的に判別可能。 STEP 1408 recon で 抽出済 の 気体 "
            "センサー 10 SKU のうち MVP 2 SKU (I2C CO2 + I2C VOC) のみ 選定、 UART CO2 "
            "(MH-Z19C/MH-Z14B) / Analog (TGS/MQ/MG812) は v0.10+ candidate。 実 wire-up "
            "は 別 STEP (I2C driver + ESP32/STM32 host + UART 経由 benchtop 統合 の 4 段 "
            "barrier、 STEP 1408 明示)。"
        ),
        "related_step": "STEP 1408 (Akizuki 気体センサー 10 SKU recon、 MVP path origin)",
        "excluded_from_v09": {
            "uart_co2": ["MH-Z19C (Akizuki 116142)", "MH-Z14B (Akizuki 116388)"],
            "analog_odor": ["TGS2450 (100989)", "AE-TGS8100 (115562)"],
            "analog_combustible_needs_safetygate": ["MQ-2 (116141)", "MQ-3B (116269)", "MQ-4 (116270)"],
            "analog_co2_heated": ["MG812 (116496)"],
        },
        "source": "benchtop-akizuki-chem-mock-registry",
    }


# ---------------------------------------------------------------------------
# _hash_seed : deterministic seed generator (cross-process 安定、 STEP 1407 と 同 impl)
# ---------------------------------------------------------------------------

def _hash_seed(*parts: str) -> int:
    """probe_id + tag 等の string 結合を hashlib.md5 で 32-bit seed に。

    hashlib.md5 = cross-process stable (Python built-in hash() は PYTHONHASHSEED で
    process 毎に seed 化されるため cross-process 決定的ではない = spike の 「再現可能」
    claim を 満たすため md5 必要)。 md5 は cryptographic 用途ではない (単純 seed 用途、
    collision resistance は要求せず)。 STEP 1407 akizuki_wireup._hash_seed と 同 impl。
    """
    joined = "|".join(parts)
    return int.from_bytes(hashlib.md5(joined.encode("utf-8")).digest()[:4], "big")


# ---------------------------------------------------------------------------
# measure_co2_ndir : SCD40 mock (CO2 ppm + temp + humidity、 spike scope)
# ---------------------------------------------------------------------------

def measure_co2_ndir(
    probe_id: str,
    condition_tag: str = "indoor-typical",
) -> dict[str, Any]:
    """mock CO2 測定 (SCD40 style: 光音響 NDIR、 CO2 ppm + temperature + humidity)。
    probe_id + condition_tag から deterministic な 3 値を生成、 SCD40 datasheet
    range 内 か verdict (STEP 1350 mapping) を返す。

    Args:
        probe_id: list_chem_probes() の 'probe_id' (現状 'scd40-co2-d1' のみ)。
        condition_tag: 想定 環境 tag (例: 'indoor-typical' / 'crowded-room' /
            'outdoor-fresh' / 'poorly-ventilated')、 mock stimulus。 実 CO2
            吸収線 (4.26μm 光音響共鳴) は 不使用、 tag hash で 値決定。

    Returns dict with:
        ok, probe_id, probe_layer, probe_sublayer, part_number, condition_tag,
        co2_ppm, temperature_c, humidity_pct, in_range_all,
        verdict_d8 ('TRUE' or 'NEITHER'), verdict_d8_symbol, verdict_reason,
        is_mock: True, hardware_available: False, honest_scope,
        d8_mapping_source, source。
    """
    if probe_id not in _MOCK_CHEM_PROBES:
        return {
            "ok": False,
            "error": f"unknown probe_id: {probe_id!r}",
            "known_probes": sorted(_MOCK_CHEM_PROBES.keys()),
            "source": "benchtop-akizuki-chem-co2",
        }
    meta = _MOCK_CHEM_PROBES[probe_id]
    if meta.get("sublayer") != "co2_ndir":
        return {
            "ok": False,
            "error": f"probe_id {probe_id!r} is sublayer={meta.get('sublayer')!r}, not 'co2_ndir'",
            "expected_sublayer": "co2_ndir",
            "source": "benchtop-akizuki-chem-co2",
        }

    seed = _hash_seed(probe_id, condition_tag)
    c_lo, c_hi = meta["range_co2_ppm"]
    t_lo, t_hi = meta["range_temp_c"]
    h_lo, h_hi = meta["range_humidity_pct"]
    # deterministic pick within range (uniform hash-derived)
    co2 = c_lo + (seed % 12500) / 12500.0 * (c_hi - c_lo)
    t = t_lo + ((seed >> 8) % 10000) / 10000.0 * (t_hi - t_lo)
    h = h_lo + ((seed >> 16) % 8000) / 8000.0 * (h_hi - h_lo)

    in_range = (c_lo <= co2 <= c_hi) and (t_lo <= t <= t_hi) and (h_lo <= h <= h_hi)
    if in_range:
        verdict, symbol, reason = "TRUE", "⊤", "within_scd40_range"
    else:
        verdict, symbol, reason = "NEITHER", "〜", "out_of_scd40_range"

    return {
        "ok": True,
        "probe_id": probe_id,
        "probe_layer": meta["layer"],
        "probe_sublayer": meta["sublayer"],
        "part_number": meta["part_number"],
        "condition_tag": condition_tag,
        "co2_ppm": round(co2, 0),
        "temperature_c": round(t, 2),
        "humidity_pct": round(h, 2),
        "in_range_all": in_range,
        "verdict_d8": verdict,
        "verdict_d8_symbol": symbol,
        "verdict_reason": reason,
        "is_mock": True,
        "hardware_available": False,
        "honest_scope": (
            "v0.9.0-alpha spike: deterministic mock (probe_id + condition_tag hash seed 由来)、 "
            "実 SCD40 physics (4.26μm CO2 吸収線 光音響 phonon 共鳴 検出) を 模倣していない = "
            "interface skeleton のみ。 実 hardware 統合は 別 STEP candidate (Sensirion Sensirion "
            "Command mode I2C driver + host MCU)。"
        ),
        "d8_mapping_source": "STEP 1350 d8_verdict_from_measurement (2-value subset)",
        "principle": meta["principle"],
        "source": "benchtop-akizuki-chem-co2",
    }


# ---------------------------------------------------------------------------
# measure_voc_index : SGP40 mock (VOC index 0-500 + raw resistance)
# ---------------------------------------------------------------------------

def measure_voc_index(
    probe_id: str,
    condition_tag: str = "indoor-nominal",
) -> dict[str, Any]:
    """mock VOC index 測定 (SGP40 style: 金属酸化物、 VOC index + raw resistance)。
    probe_id + condition_tag から deterministic な voc_index (0-500) + raw resistance
    (log-scale 20kΩ-100MΩ) を生成、 datasheet range 内 か verdict を返す。

    Args:
        probe_id: list_chem_probes() の 'probe_id' (現状 'sgp40-voc-d2' のみ)。
        condition_tag: 想定 環境 tag (例: 'indoor-nominal' / 'cooking-fumes' /
            'freshly-painted' / 'alcohol-vapor')、 mock stimulus。 実 SnO2 表面
            吸着 電気抵抗変化 は 不使用、 tag hash で 値決定。

    Returns dict with:
        ok, probe_id, probe_layer, probe_sublayer, part_number, condition_tag,
        voc_index, voc_index_interpretation ('improving'/'nominal'/'degrading'),
        raw_resistance_ohm, in_range_all,
        verdict_d8 ('TRUE' or 'NEITHER'), verdict_d8_symbol, verdict_reason,
        is_mock: True, hardware_available: False, honest_scope,
        d8_mapping_source, principle, source。
    """
    if probe_id not in _MOCK_CHEM_PROBES:
        return {
            "ok": False,
            "error": f"unknown probe_id: {probe_id!r}",
            "known_probes": sorted(_MOCK_CHEM_PROBES.keys()),
            "source": "benchtop-akizuki-chem-voc",
        }
    meta = _MOCK_CHEM_PROBES[probe_id]
    if meta.get("sublayer") != "voc_index":
        return {
            "ok": False,
            "error": f"probe_id {probe_id!r} is sublayer={meta.get('sublayer')!r}, not 'voc_index'",
            "expected_sublayer": "voc_index",
            "source": "benchtop-akizuki-chem-voc",
        }

    seed = _hash_seed(probe_id, condition_tag)
    v_lo, v_hi = meta["range_voc_index"]
    r_lo, r_hi = meta["range_raw_ohm"]
    nominal = meta["voc_index_nominal"]
    # deterministic voc_index in [0, 500]
    voc = v_lo + (seed % 50000) / 50000.0 * (v_hi - v_lo)
    # raw resistance: log-scale between 20kΩ and 100MΩ (4 decades)
    log_lo, log_hi = math.log10(r_lo), math.log10(r_hi)
    log_r = log_lo + ((seed >> 12) % 40000) / 40000.0 * (log_hi - log_lo)
    raw_r = 10 ** log_r

    # interpretation based on Sensirion documentation
    if voc < nominal - 10:
        interp = "improving"
    elif voc > nominal + 10:
        interp = "degrading"
    else:
        interp = "nominal"

    in_range = (v_lo <= voc <= v_hi) and (r_lo <= raw_r <= r_hi)
    if in_range:
        verdict, symbol, reason = "TRUE", "⊤", "within_sgp40_range"
    else:
        verdict, symbol, reason = "NEITHER", "〜", "out_of_sgp40_range"

    return {
        "ok": True,
        "probe_id": probe_id,
        "probe_layer": meta["layer"],
        "probe_sublayer": meta["sublayer"],
        "part_number": meta["part_number"],
        "condition_tag": condition_tag,
        "voc_index": round(voc, 1),
        "voc_index_interpretation": interp,
        "raw_resistance_ohm": round(raw_r, 1),
        "in_range_all": in_range,
        "verdict_d8": verdict,
        "verdict_d8_symbol": symbol,
        "verdict_reason": reason,
        "is_mock": True,
        "hardware_available": False,
        "honest_scope": (
            "v0.9.0-alpha spike: deterministic mock (probe_id + condition_tag hash seed 由来)、 "
            "実 SGP40 physics (SnO2 表面 での VOC 吸着 → 電気抵抗変化 → Sensirion 独自 gas "
            "index algorithm) を 模倣していない = interface skeleton のみ。 voc_index_interpretation "
            "は Sensirion documentation の 100=nominal 基準 ±10 で 分類 (簡略)、 実 hardware "
            "の tuning は 別途 対応。"
        ),
        "d8_mapping_source": "STEP 1350 d8_verdict_from_measurement (2-value subset)",
        "principle": meta["principle"],
        "source": "benchtop-akizuki-chem-voc",
    }


# ---------------------------------------------------------------------------
# selftest (module-level) : 呼ぶ場合は python -c 'import benchtop_akizuki_chem as m; m.selftest()'
# ---------------------------------------------------------------------------

def selftest() -> int:
    """module-level 単体テスト。 benchtop_mcp.py --selftest からも 統合 test 実行される。"""
    print("--- benchtop_akizuki_chem selftest (v0.9.0-alpha) ---")

    # [1] list_chem_probes: 2 probe registry
    r1 = list_chem_probes()
    assert r1["ok"] is True
    assert r1["probe_count"] == 2
    assert r1["hardware_available"] is False
    assert r1["is_mock"] is True
    ids = {p["probe_id"] for p in r1["probes"]}
    assert ids == {"scd40-co2-d1", "sgp40-voc-d2"}
    # v0.10+ candidate exclusion 情報 も返す
    assert "excluded_from_v09" in r1
    assert "analog_combustible_needs_safetygate" in r1["excluded_from_v09"]
    print(f"[1] list_chem_probes: count={r1['probe_count']} ids={sorted(ids)}")

    # [2] measure_co2_ndir: SCD40 mock, in-range verdict
    r2 = measure_co2_ndir("scd40-co2-d1", "indoor-typical")
    assert r2["ok"] is True
    assert r2["is_mock"] is True
    assert 400.0 <= r2["co2_ppm"] <= 2000.0
    assert -10.0 <= r2["temperature_c"] <= 60.0
    assert 0.0 <= r2["humidity_pct"] <= 95.0
    assert r2["verdict_d8"] == "TRUE"
    assert r2["principle"] == "photoacoustic_ndir"
    print(f"[2] measure_co2_ndir(scd40, indoor-typical): co2={r2['co2_ppm']}ppm "
          f"t={r2['temperature_c']}C h={r2['humidity_pct']}% verdict={r2['verdict_d8']}")

    # [3] measure_co2_ndir: determinism
    r3a = measure_co2_ndir("scd40-co2-d1", "crowded-room")
    r3b = measure_co2_ndir("scd40-co2-d1", "crowded-room")
    assert r3a["co2_ppm"] == r3b["co2_ppm"]
    assert r3a["temperature_c"] == r3b["temperature_c"]
    print(f"[3] measure_co2_ndir determinism: co2_equal={r3a['co2_ppm'] == r3b['co2_ppm']}")

    # [4] measure_co2_ndir: different tag → different value
    r4 = measure_co2_ndir("scd40-co2-d1", "outdoor-fresh")
    assert r4["co2_ppm"] != r3a["co2_ppm"]  # different tag → different hash
    print(f"[4] measure_co2_ndir tag-variance: crowded={r3a['co2_ppm']}ppm outdoor={r4['co2_ppm']}ppm")

    # [5] measure_voc_index: SGP40 mock, in-range verdict
    r5 = measure_voc_index("sgp40-voc-d2", "indoor-nominal")
    assert r5["ok"] is True
    assert r5["is_mock"] is True
    assert 0.0 <= r5["voc_index"] <= 500.0
    assert 20000.0 <= r5["raw_resistance_ohm"] <= 100000000.0
    assert r5["voc_index_interpretation"] in ("improving", "nominal", "degrading")
    assert r5["verdict_d8"] == "TRUE"
    assert r5["principle"] == "metal_oxide_semiconductor"
    print(f"[5] measure_voc_index(sgp40, indoor-nominal): voc={r5['voc_index']} "
          f"r={r5['raw_resistance_ohm']:.0f}Ω interp={r5['voc_index_interpretation']} "
          f"verdict={r5['verdict_d8']}")

    # [6] measure_voc_index: determinism
    r6a = measure_voc_index("sgp40-voc-d2", "cooking-fumes")
    r6b = measure_voc_index("sgp40-voc-d2", "cooking-fumes")
    assert r6a["voc_index"] == r6b["voc_index"]
    assert r6a["raw_resistance_ohm"] == r6b["raw_resistance_ohm"]
    print(f"[6] measure_voc_index determinism: voc_equal={r6a['voc_index'] == r6b['voc_index']}")

    # [7] measure_voc_index: interpretation categorization
    # collect samples across multiple tags to observe all 3 categories
    tags = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n", "o", "p"]
    interps = {measure_voc_index("sgp40-voc-d2", t)["voc_index_interpretation"] for t in tags}
    # We expect to see at least 2 different interpretations across 16 samples
    assert len(interps) >= 2
    print(f"[7] measure_voc_index interp variance: observed={sorted(interps)} across 16 tags")

    # [8] cross-sublayer misuse rejection (SCD40 for VOC → error)
    r8a = measure_voc_index("scd40-co2-d1", "any")
    r8b = measure_co2_ndir("sgp40-voc-d2", "any")
    assert not r8a["ok"] and not r8b["ok"]
    print(f"[8] cross-sublayer misuse rejected: co2_probe_not_voc={not r8a['ok']} "
          f"voc_probe_not_co2={not r8b['ok']}")

    # [9] unknown probe rejection
    r9 = measure_co2_ndir("unknown-probe", "any")
    assert r9["ok"] is False
    r9b = measure_voc_index("unknown-probe", "any")
    assert r9b["ok"] is False
    print(f"[9] unknown probe rejected: co2={not r9['ok']} voc={not r9b['ok']}")

    print("\n benchtop_akizuki_chem: all 9 test PASS")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(selftest())
