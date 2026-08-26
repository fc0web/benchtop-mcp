#!/usr/bin/env python3
"""
benchtop-mcp Akizuki UART chemistry layer : MH-Z19C CO2 UART mock
================================================================================

v0.9.1-alpha (2026-08-27, Rei stack STEP 1419 continuation of STEP 1416、 STEP 1408
excluded_from_v09 の uart_co2 candidate (MH-Z19C Akizuki 116142) を 別 module で
mock 追加、 STEP 1416 akizuki_chem I2C 2 SKU pattern の UART 兄弟実装)。

**目的**:

  STEP 1416 v0.9 の 化学 layer 2 SKU (I2C SCD40/SGP40) の gap fill 続編として、
  STEP 1408 で 明示された excluded_from_v09.uart_co2 candidate の 定番 SKU
  MH-Z19C (Winsen 社製 NDIR CO2、 UART 9600 baud 9-byte packet protocol、
  Akizuki 116142 ¥4,580) を benchtop-mcp mock として 別 module で 追加する。
  hardware 未取得 = 全 tool で hardware_available: False marker 徹底、
  STEP 1416 akizuki_chem pattern を そのまま 継承。

**2 tool** (STEP 1416 の 3 tool と 同 pattern):

  1. list_uart_chem_probes() → 内蔵 mock UART chem probe registry の 一覧 (1 SKU)
  2. measure_co2_uart_ndir(probe_id, condition_tag) → MH-Z19C mock
     (co2_ppm + temperature_c + status_byte + packet 9-byte hex + verdict)

**1 SKU** (STEP 1408 UART 定番、 v0.9.1 pilot):

  MH-Z19C (Akizuki 116142、 UART、 ¥4,580、 Winsen NDIR CO2 sensor、 400-5000 ppm)

**★ 命名 discipline** ([[feedback-super-naming-siren-family-pattern]] 適用):

  「measure_co2_uart_ndir」 は 実 hardware で 実測値を返す tool と 誤解されやすい。
  v0.9.1 spike の scope 内では 全 return dict に is_mock: True + hardware_available:
  False + is_packet_synthetic: True を含め、 mock 値生成 が deterministic
  (probe_id + condition_tag の hashlib.md5 seed 由来、 cross-process 安定) で
  あることを 明示する。 9-byte packet も seed から 決定的合成、 実 sensor UART
  出力は 不使用。 実 hardware wire-up は 別 STEP candidate (UART host MCU +
  serial reader + benchtop 統合 の 4 段 barrier、 STEP 1408 に 記載)。

**★ pool saturation 予防** ([[feedback-projection-self-audit-pattern]] SAC-4 適用):

  「秋月 MH-Z19C UART module wire-up」 は 個人電子工作 + 環境計測 実習 定番 pattern
  で novelty ゼロ ([[feedback-world-uniqueness-claim-controllable]] 継承)、 本
  module は Rei stack 内 benchtop への UART 化学 sublayer 1 SKU 追加のみ、
  「世界初」 主張なし。

**scope 明示** (v0.9.1-alpha spike scope、 8 条):

  (1) 全 tool は pure calculation (stdlib のみ、 network / file I/O / serial なし)、
      状態なし (built-in registry 1 probe のみ、 hardware discovery なし)。
      remote MCP としても そのまま deploy 可能。
  (2) mock 値は deterministic (probe_id + condition_tag の hashlib.md5 由来
      seed で cross-process 再現可能)、 実 sensor physics (NDIR 4.26μm CO2
      吸収線 IR 光量減衰 検出) を模倣していない = 教育 / interface skeleton 用途のみ。
      md5 は cryptographic 用途ではない (単純 seed 用途)。
  (3) MH-Z19C CO2 range: 400〜5000 ppm (datasheet 標準 range、 屋内 CO2 濃度
      envelope に 対応、 UART 上限 range として 5000 ppm 選定、 実 sensor は
      オプション 0-2000/0-5000/0-10000 ppm から user 選択)。
  (4) MH-Z19C 温度: -10〜50°C (datasheet 動作範囲、 内蔵 温度センサ 出力、
      精度 datasheet ±2°C 表記だが mock では range 内 uniform hash 選択)。
  (5) UART 9-byte packet 合成: `[0xFF 0x86 CO2_HIGH CO2_LOW TEMP U1 U2 U3 CHECKSUM]`
      = Winsen datasheet Command 0x86 (Read CO2 concentration) response format、
      checksum = 0xFF - ((byte1+byte2+..+byte7) & 0xFF) + 1 (Winsen 独自 formula)、
      mock では 実 CO2 数値 + 温度 + zero padding + 正しい checksum を 合成、
      packet 検証 pass を保証。
  (6) status_byte = 0x86 (正常 response)、 command 0x87/0x88 (calibration/range set)
      は mock 未実装 = read-only。
  (7) STEP 1350 d8_verdict_from_measurement primitive を 2 値 subset で 参照
      (TRUE if in-range / NEITHER if out-of-range or hardware not present)。
      BOTH / FALSE / SELF / ∞ / ○ / 〜 は 未使用 (2/8 subset)。
  (8) SafetyGate (STEP 1345 v0.5.0-alpha) との 統合は 未実装 = MH-Z19C は 5V
      UART + 25mA 級 微弱電流 で SafetyGate 対象外。 STEP 1408 で 明示された
      可燃性ガス系 (MQ-2/3B/4 = 内蔵ヒーター 5V/150mA + 発火源) は 別 STEP
      candidate = SafetyGate rule 拡張 と 同時 に 実装予定。

**Rei stack alignment**:

  - STEP 1416 akizuki_chem v0.9 と 相補 (I2C 2 SKU vs UART 1 SKU、 同 化学 layer 別 sublayer)
  - STEP 1408 excluded_from_v09.uart_co2 candidate の pilot 実装
  - STEP 1350 d8_verdict_from_measurement を 2 値 subset で 参照 (verdict field)
  - STEP 1345 SafetyGate (現段階 MH-Z19C は 対象外)
  - STEP 1407 akizuki_wireup v0.8 pattern (structural sibling)
  - benchtop-mcp v0.9 tool 27 → v0.9.1 tool 29 (+2)

**related memory**:

  - [[project-step1416-benchtop-v09-chem-mock-2026-08-26]] (I2C 2 SKU 起点、 UART は本 STEP)
  - [[project-step1408-akizuki-gas-co2-recon-2026-08-26]] (10 SKU recon + UART candidate 明示)
  - [[project-step1407-benchtop-v08-akizuki-wireup-mock-2026-08-26]] (structural sibling pattern)
  - [[project-step1350-d8-verdict-mapping-phase-a-2026-08-20]] (verdict field 原典)
  - [[feedback-super-naming-siren-family-pattern]] (mock でない 誤読 予防)
  - [[feedback-projection-self-audit-pattern]] SAC-4 (pool saturation 予防)
  - [[feedback-world-uniqueness-claim-controllable]] (novelty 主張ゼロ)

**References** (公開文献 + datasheet、 全 外部 evidence):

  - Winsen MH-Z19C datasheet (Infrared CO2 sensor module, UART 9600 baud, 400-5000 ppm)
  - Winsen MH-Z19C user manual (9-byte command/response packet format, checksum formula)
  - Akizuki 通販コード 116142 (2026-08-26 catalog 表記)

License: benchtop-mcp v0.x = MIT (irrevocable per README)。
"""

from __future__ import annotations

import hashlib
from typing import Any

# ---------------------------------------------------------------------------
# Built-in mock UART chem probe registry (stateless, immutable)
# 1 SKU = STEP 1408 UART CO2 定番 (MH-Z19C)
# 全 hardware_available: False marker 徹底。
# ---------------------------------------------------------------------------

_MOCK_UART_CHEM_PROBES: dict[str, dict[str, Any]] = {
    "mhz19c-co2-uart-e1": {
        "layer": "chemistry",
        "sublayer": "co2_uart_ndir",
        "sublayer_number": 3,
        "part_number": "MH-Z19C",
        "akizuki_code": "116142",
        "akizuki_price_jpy": 4580,
        "interface": "UART",
        "uart_baudrate": 9600,
        "uart_frame": "8N1",
        "vendor": "Winsen",
        "measures": ["co2_ppm", "temperature_c"],
        "range_co2_ppm": [400.0, 5000.0],
        "range_temp_c": [-10.0, 50.0],
        "resolution": "1 ppm CO2 / 1°C (datasheet 表記、 内蔵温度センサは 参考値)",
        "principle": "ndir_ir_absorption",
        "packet_length_bytes": 9,
        "command_read_co2": "0x86",
        "hardware_available": False,
        "notes": "NDIR CO2 UART 9-byte packet、 教育 + HVAC 実習 定番、 Warm-up 3 分 datasheet",
    },
}


# ---------------------------------------------------------------------------
# list_uart_chem_probes : 内蔵 mock UART chem registry の 一覧
# ---------------------------------------------------------------------------

def list_uart_chem_probes() -> dict[str, Any]:
    """内蔵 mock UART chem probe registry (Akizuki UART 化学 layer 1 SKU) の 一覧を返す。
    全 probe は hardware_available: False。

    Returns:
        dict with:
          ok: True
          probes: list of probe descriptor
          probe_count: 1
          hardware_available: False
          is_mock: True
          honest_scope: mock registry のみ、 実 hardware discovery + serial port scan 未実装
          related_step: STEP 1408 (UART CO2 candidate origin) + STEP 1416 (I2C sibling)
    """
    probes = []
    for pid, meta in _MOCK_UART_CHEM_PROBES.items():
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
            "v0.9.1-alpha spike: 内蔵 mock UART chem registry 1 probe (MH-Z19C) のみ、 "
            "実 hardware discovery + serial port scan (pyserial list_ports) 未実装。 全 "
            "probe は hardware_available: False marker で 実測データでないことを 機械的に "
            "判別可能。 STEP 1408 excluded_from_v09.uart_co2 の MH-Z19C を pilot、 兄弟 "
            "MH-Z14B (Akizuki 116388) は v0.9.2+ candidate (同 Winsen protocol、 range 違い)。 "
            "実 wire-up は 別 STEP (UART host MCU or USB-serial adapter + 3 分 warmup + "
            "9-byte packet reader + checksum verify + benchtop 統合 の 5 段 barrier)。"
        ),
        "related_step": (
            "STEP 1408 (Akizuki UART CO2 candidate origin) + STEP 1416 (I2C sibling SCD40/SGP40)"
        ),
        "excluded_from_v091": {
            "uart_co2_variant": ["MH-Z14B (Akizuki 116388、 同 Winsen protocol、 range 違い)"],
            "analog_odor_v092_candidate": ["TGS2450 (100989)", "AE-TGS8100 (115562)"],
            "analog_combustible_needs_safetygate": ["MQ-2 (116141)", "MQ-3B (116269)", "MQ-4 (116270)"],
            "analog_co2_heated": ["MG812 (116496)"],
        },
        "source": "benchtop-akizuki-uart-chem-mock-registry",
    }


# ---------------------------------------------------------------------------
# _hash_seed : deterministic seed generator (cross-process 安定、 STEP 1416 と 同 impl)
# ---------------------------------------------------------------------------

def _hash_seed(*parts: str) -> int:
    """probe_id + tag 等の string 結合を hashlib.md5 で 32-bit seed に。

    hashlib.md5 = cross-process stable (Python built-in hash() は PYTHONHASHSEED で
    process 毎に seed 化されるため cross-process 決定的ではない = spike の 「再現可能」
    claim を 満たすため md5 必要)。 md5 は cryptographic 用途ではない (単純 seed 用途、
    collision resistance は要求せず)。 STEP 1416 akizuki_chem._hash_seed と 同 impl。
    """
    joined = "|".join(parts)
    return int.from_bytes(hashlib.md5(joined.encode("utf-8")).digest()[:4], "big")


# ---------------------------------------------------------------------------
# _mhz19c_checksum : Winsen datasheet 独自 formula
# ---------------------------------------------------------------------------

def _mhz19c_checksum(packet_bytes_1_to_7: list[int]) -> int:
    """Winsen MH-Z19C datasheet checksum formula:
        checksum = 0xFF - ((byte1 + byte2 + ... + byte7) & 0xFF) + 1

    Args:
        packet_bytes_1_to_7: 9-byte packet の byte[1] 〜 byte[7] (byte[0]=0xFF start, byte[8]=checksum)

    Returns:
        checksum byte (0-255)
    """
    total = sum(packet_bytes_1_to_7) & 0xFF
    return (0xFF - total + 1) & 0xFF


# ---------------------------------------------------------------------------
# measure_co2_uart_ndir : MH-Z19C mock (UART 9-byte packet 合成 + CO2 + temp)
# ---------------------------------------------------------------------------

def measure_co2_uart_ndir(
    probe_id: str,
    condition_tag: str = "indoor-typical",
) -> dict[str, Any]:
    """mock CO2 測定 (MH-Z19C style: NDIR UART 9-byte packet、 CO2 ppm + 内蔵 温度)。
    probe_id + condition_tag から deterministic な 2 値 + 9-byte packet を合成、
    MH-Z19C datasheet range 内 か verdict (STEP 1350 mapping) を返す。

    Args:
        probe_id: list_uart_chem_probes() の 'probe_id' (現状 'mhz19c-co2-uart-e1' のみ)。
        condition_tag: 想定 環境 tag (例: 'indoor-typical' / 'crowded-classroom' /
            'poorly-ventilated' / 'outdoor-fresh')、 mock stimulus。 実 NDIR 4.26μm
            IR 吸収 光量減衰 は 不使用、 tag hash で 値決定。

    Returns dict with:
        ok, probe_id, probe_layer, probe_sublayer, part_number, condition_tag,
        co2_ppm, temperature_c,
        packet_hex_9byte (Winsen 0xFF 0x86 ... checksum), packet_checksum_valid,
        status_byte (0x86 = normal response),
        in_range_all, verdict_d8 ('TRUE' or 'NEITHER'), verdict_d8_symbol, verdict_reason,
        is_mock: True, is_packet_synthetic: True, hardware_available: False,
        honest_scope, d8_mapping_source, principle, source。
    """
    if probe_id not in _MOCK_UART_CHEM_PROBES:
        return {
            "ok": False,
            "error": f"unknown probe_id: {probe_id!r}",
            "known_probes": sorted(_MOCK_UART_CHEM_PROBES.keys()),
            "source": "benchtop-akizuki-uart-chem-co2",
        }
    meta = _MOCK_UART_CHEM_PROBES[probe_id]
    if meta.get("sublayer") != "co2_uart_ndir":
        return {
            "ok": False,
            "error": f"probe_id {probe_id!r} is sublayer={meta.get('sublayer')!r}, not 'co2_uart_ndir'",
            "expected_sublayer": "co2_uart_ndir",
            "source": "benchtop-akizuki-uart-chem-co2",
        }

    seed = _hash_seed(probe_id, condition_tag)
    c_lo, c_hi = meta["range_co2_ppm"]
    t_lo, t_hi = meta["range_temp_c"]
    # deterministic pick within range (uniform hash-derived)
    co2 = c_lo + (seed % 12500) / 12500.0 * (c_hi - c_lo)
    t = t_lo + ((seed >> 8) % 10000) / 10000.0 * (t_hi - t_lo)

    # UART 9-byte packet synthesis: [0xFF 0x86 CO2_HIGH CO2_LOW TEMP U1 U2 U3 CHECKSUM]
    # per Winsen MH-Z19C datasheet Command 0x86 (Read CO2 concentration) response format
    co2_int = int(round(co2))
    co2_high = (co2_int >> 8) & 0xFF
    co2_low = co2_int & 0xFF
    # temperature encoding: MH-Z19C datasheet はやや不明瞭、 mock では 単純に (温度 + 40) を byte 化
    temp_byte = (int(round(t)) + 40) & 0xFF
    # U1/U2/U3: MH-Z19C datasheet で「reserved / undocumented」 field、 mock では zero padding
    u1, u2, u3 = 0x00, 0x00, 0x00
    status_byte = 0x86  # normal response marker
    packet_bytes_1_to_7 = [status_byte, co2_high, co2_low, temp_byte, u1, u2, u3]
    checksum = _mhz19c_checksum(packet_bytes_1_to_7)
    packet_full = [0xFF] + packet_bytes_1_to_7 + [checksum]
    packet_hex = " ".join(f"{b:02X}" for b in packet_full)

    # verify checksum (self-consistency check、 mock で 常に valid)
    checksum_recomputed = _mhz19c_checksum(packet_bytes_1_to_7)
    checksum_valid = (checksum == checksum_recomputed)

    in_range = (c_lo <= co2 <= c_hi) and (t_lo <= t <= t_hi)
    if in_range:
        verdict, symbol, reason = "TRUE", "⊤", "within_mhz19c_range"
    else:
        verdict, symbol, reason = "NEITHER", "〜", "out_of_mhz19c_range"

    return {
        "ok": True,
        "probe_id": probe_id,
        "probe_layer": meta["layer"],
        "probe_sublayer": meta["sublayer"],
        "part_number": meta["part_number"],
        "condition_tag": condition_tag,
        "co2_ppm": co2_int,
        "temperature_c": round(t, 1),
        "packet_hex_9byte": packet_hex,
        "packet_bytes": packet_full,
        "packet_checksum_valid": checksum_valid,
        "status_byte": status_byte,
        "status_byte_hex": f"0x{status_byte:02X}",
        "in_range_all": in_range,
        "verdict_d8": verdict,
        "verdict_d8_symbol": symbol,
        "verdict_reason": reason,
        "is_mock": True,
        "is_packet_synthetic": True,
        "hardware_available": False,
        "honest_scope": (
            "v0.9.1-alpha spike: deterministic mock (probe_id + condition_tag hash seed 由来)、 "
            "実 MH-Z19C physics (NDIR 4.26μm CO2 吸収線 IR 光量減衰 検出) を 模倣していない = "
            "interface skeleton のみ。 9-byte packet も seed から 決定的合成、 実 UART serial "
            "出力 と は byte-identical でも 実測性 は ゼロ (is_packet_synthetic: True marker)。 "
            "実 hardware 統合は 別 STEP candidate (UART host MCU or USB-serial + 3 分 warmup + "
            "packet reader + checksum verify)。"
        ),
        "d8_mapping_source": "STEP 1350 d8_verdict_from_measurement (2-value subset)",
        "principle": meta["principle"],
        "source": "benchtop-akizuki-uart-chem-co2",
    }


# ---------------------------------------------------------------------------
# selftest (module-level) : python -c 'import benchtop_akizuki_uart_chem as m; m.selftest()'
# ---------------------------------------------------------------------------

def selftest() -> int:
    """module-level 単体テスト。 benchtop_mcp.py --selftest からも 統合 test 実行される。"""
    print("--- benchtop_akizuki_uart_chem selftest (v0.9.1-alpha) ---")

    # [1] list_uart_chem_probes: 1 probe registry
    r1 = list_uart_chem_probes()
    assert r1["ok"] is True
    assert r1["probe_count"] == 1
    assert r1["hardware_available"] is False
    assert r1["is_mock"] is True
    ids = {p["probe_id"] for p in r1["probes"]}
    assert ids == {"mhz19c-co2-uart-e1"}
    assert "excluded_from_v091" in r1
    assert "analog_combustible_needs_safetygate" in r1["excluded_from_v091"]
    print(f"[1] list_uart_chem_probes: count={r1['probe_count']} ids={sorted(ids)}")

    # [2] measure_co2_uart_ndir: MH-Z19C mock, in-range verdict + packet 9-byte
    r2 = measure_co2_uart_ndir("mhz19c-co2-uart-e1", "indoor-typical")
    assert r2["ok"] is True
    assert r2["is_mock"] is True
    assert r2["is_packet_synthetic"] is True
    assert 400 <= r2["co2_ppm"] <= 5000
    assert -10.0 <= r2["temperature_c"] <= 50.0
    assert r2["verdict_d8"] == "TRUE"
    assert r2["principle"] == "ndir_ir_absorption"
    # packet: 9 bytes total (0xFF start + 7 middle + 1 checksum)
    packet_bytes = r2["packet_bytes"]
    assert len(packet_bytes) == 9
    assert packet_bytes[0] == 0xFF
    assert packet_bytes[1] == 0x86  # command_read_co2 response marker
    assert r2["packet_checksum_valid"] is True
    print(f"[2] measure_co2_uart_ndir(mhz19c, indoor-typical): co2={r2['co2_ppm']}ppm "
          f"t={r2['temperature_c']}C packet={r2['packet_hex_9byte']} verdict={r2['verdict_d8']}")

    # [3] measure_co2_uart_ndir: checksum formula independent verify
    # Winsen formula: checksum = 0xFF - ((byte1+byte2+..+byte7) & 0xFF) + 1
    checksum_manual = (0xFF - (sum(packet_bytes[1:8]) & 0xFF) + 1) & 0xFF
    assert checksum_manual == packet_bytes[8]
    print(f"[3] checksum formula verify: manual={checksum_manual:#04x} "
          f"packet={packet_bytes[8]:#04x} match={checksum_manual == packet_bytes[8]}")

    # [4] measure_co2_uart_ndir: determinism
    r4a = measure_co2_uart_ndir("mhz19c-co2-uart-e1", "crowded-classroom")
    r4b = measure_co2_uart_ndir("mhz19c-co2-uart-e1", "crowded-classroom")
    assert r4a["co2_ppm"] == r4b["co2_ppm"]
    assert r4a["packet_bytes"] == r4b["packet_bytes"]
    print(f"[4] measure_co2_uart_ndir determinism: co2_equal={r4a['co2_ppm'] == r4b['co2_ppm']} "
          f"packet_equal={r4a['packet_bytes'] == r4b['packet_bytes']}")

    # [5] measure_co2_uart_ndir: different tag → different value + packet
    r5 = measure_co2_uart_ndir("mhz19c-co2-uart-e1", "outdoor-fresh")
    assert r5["co2_ppm"] != r4a["co2_ppm"]
    assert r5["packet_bytes"] != r4a["packet_bytes"]
    print(f"[5] tag-variance: crowded={r4a['co2_ppm']}ppm outdoor={r5['co2_ppm']}ppm "
          f"packet_diff=True")

    # [6] measure_co2_uart_ndir: CO2 packet encoding consistency
    # packet[2] << 8 | packet[3] should equal co2_ppm
    r6 = measure_co2_uart_ndir("mhz19c-co2-uart-e1", "poorly-ventilated")
    packet_co2 = (r6["packet_bytes"][2] << 8) | r6["packet_bytes"][3]
    assert packet_co2 == r6["co2_ppm"]
    print(f"[6] packet CO2 encoding: packet_high_low={packet_co2} co2_ppm={r6['co2_ppm']} match=True")

    # [7] cross-sublayer misuse rejection (unknown probe / wrong sublayer)
    r7a = measure_co2_uart_ndir("scd40-co2-d1", "any")  # I2C SCD40 not in this registry
    r7b = measure_co2_uart_ndir("unknown-probe", "any")
    assert not r7a["ok"] and not r7b["ok"]
    print(f"[7] invalid probe rejected: wrong_registry={not r7a['ok']} unknown={not r7b['ok']}")

    print("\n benchtop_akizuki_uart_chem: all 7 test PASS")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(selftest())
