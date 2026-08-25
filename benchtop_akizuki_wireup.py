#!/usr/bin/env python3
"""
benchtop-mcp Akizuki wire-up layer : 環境 / 慣性 / 距離 mock spike
================================================================================

v0.8.0-alpha (2026-08-26, 藤本さん directive 「(1)(2)(3) を 順番に」 実装、
Rei stack STEP 1406 秋月 I2C/SPI/UART wire-up 候補 list から 3 SKU pilot
(BME280 環境 / BNO055 慣性 / VL53L1X ToF 距離) を benchtop-mcp mock として
skeleton 化)。

**目的**:

  STEP 1406 で 明示された benchtop-mcp v0.7 の 5+ layer gap のうち、
  「環境 (温湿度気圧) / 慣性 (IMU) / 距離 (ToF)」 の 3 layer を 秋月 で
  即 入手可能な 定番 I2C module (BME280 / BNO055 / VL53L1X) を 想定 SKU
  として mock 実装で 追加する。 hardware 未取得 = 全 tool で
  hardware_available: False marker 徹底、 STEP 1396 olfact/biosensor
  spike の pattern を そのまま 継承。

**4 tool** (STEP 1396 の 3 tool と 同 pattern):

  1. list_akizuki_probes() → 内蔵 mock probe registry の 一覧 (3 layer 各 1 SKU)
  2. measure_environment(probe_id, condition_tag) → BME280 mock
     (temp_c / humidity_pct / pressure_hpa + STEP 1350 verdict)
  3. measure_orientation(probe_id, motion_tag) → BNO055 mock
     (quaternion + euler_deg + linear_acc_m_s2 + calibration_status)
  4. measure_distance(probe_id, target_tag, timing_budget_ms) → VL53L1X mock
     (distance_mm + range_status + STEP 1350 verdict)

**3 layer** (STEP 1406 wire-up 候補 list から 各 layer 代表 SKU 選定):

  ① environment (温湿度気圧) = BME280 (Akizuki 通販コード 109421、 I2C、 ¥1,180)
  ② inertial   (9軸 IMU)    = BNO055 (Akizuki 通販コード 116996、 I2C、 ¥3,850)
  ③ distance   (ToF 長距離) = VL53L1X (Akizuki 通販コード 114249、 I2C、 ¥1,780)

**★ 命名 discipline** ([[feedback-super-naming-siren-family-pattern]] 適用):

  「measure_environment」 等 は 実 hardware で 実測値を返す tool と 誤解されやすい。
  v0.8 spike の scope 内では 全 return dict に is_mock: True + hardware_available:
  False を含め、 mock 値生成 が deterministic (probe_id + condition_tag の
  hashlib.md5 seed 由来、 cross-process 安定) であることを 明示する。 実 hardware
  wire-up は 別 STEP candidate (BME280 の I2C driver 実装 + ESP32/STM32 host +
  UART 経由 benchtop 統合 の 4 段 barrier、 STEP 1406 に 記載)。

**★ pool saturation 予防** ([[feedback-projection-self-audit-pattern]] SAC-4 適用):

  「秋月 module wire-up」 の 主張は 個人電子工作の 定番 pattern で novelty ゼロ
  ([[feedback-world-uniqueness-claim-controllable]] 継承)、 本 module は
  Rei stack 内 benchtop への 3 新 domain 追加のみ、 「世界初」 主張なし。

**scope 明示** (v0.8.0-alpha spike scope):

  (1) 全 tool は pure calculation (stdlib のみ、 network / file I/O なし)、
      状態なし (built-in registry 3 probe のみ、 hardware discovery なし)。
      remote MCP としても そのまま deploy 可能。
  (2) mock 値は deterministic (probe_id + condition_tag の hashlib.md5 由来
      seed で cross-process 再現可能)、 実 sensor physics (ISFET / MEMS / SPAD 等)
      を模倣していない = 教育 / interface skeleton 用途のみ。 md5 は cryptographic
      用途ではない (単純 seed 用途、 collision resistance は要求せず)。
  (3) 温湿度気圧 の 範囲は BME280 datasheet 典型値 (-40〜85°C, 0〜100%RH, 300〜1100hPa)
      を parameter として 使うだけの 単純線形 model、 実 sensor calibration curve は 不使用。
  (4) IMU quaternion は unit-norm 保証のみ、 実 fusion algorithm (Madgwick / Mahony /
      Kalman) は 実装しない、 mock quaternion は deterministic 軸傾き のみ 表現。
  (5) ToF distance は VL53L1X datasheet 有効範囲 (30〜4000mm) 内 に clamp、
      target_tag hash から deterministic 距離、 実 SPAD photon counting は 不使用。
  (6) STEP 1350 d8_verdict_from_measurement primitive を 3 値 subset で 参照
      (TRUE if in-range / NEITHER if out-of-range or hardware not present)、
      BOTH / FALSE / SELF / ∞ / ○ / 〜 は 未使用 (5/8 → 2/8 subset)。
  (7) SafetyGate (STEP 1345 v0.5.0-alpha) との 統合は 未実装 = STEP 1406 で
      「本 3 layer は SafetyGate 追加要否 なし (3.3V < 5mA)」 と判定済、 v0.9+
      で 通信 layer (Wi-Fi TELEC 認証) 追加時 に SafetyGate rule 拡張予定。

**Rei stack alignment**:

  - STEP 1345 SafetyGate と 相補 (現段階 本 3 layer は SafetyGate 対象外)
  - STEP 1348 physics-limits と 相補 (physics-limits = 上界計算、 本 module = 測定 layer)
  - STEP 1350 d8_verdict_from_measurement を 3 値 subset で 参照 (verdict field)
  - STEP 1396 olfact/biosensor mock v0.7 の pattern 継承 (structural sibling)
  - STEP 1406 秋月 wire-up 候補 list から 3 SKU pilot (env/IMU/ToF)
  - benchtop-mcp v0.7 tool 20 → v0.8 tool 24 (+4)

**related memory**:

  - [[project-step1406-akizuki-i2c-spi-uart-wireup-candidates-2026-08-26]] (25 SKU list origin)
  - [[project-step1396-benchtop-olfact-spike-2026-08-23]] (structural sibling pattern)
  - [[project-step1350-d8-verdict-mapping-phase-a-2026-08-20]] (verdict field 原典)
  - [[project-step1345-benchtop-provenance-spike-2026-08-19]] (SafetyGate、 現 v0.8 対象外)
  - [[feedback-super-naming-siren-family-pattern]] (mock でない 誤読 予防)
  - [[feedback-projection-self-audit-pattern]] SAC-4 (pool saturation 予防)
  - [[feedback-world-uniqueness-claim-controllable]] (novelty 主張ゼロ discipline)

**References** (公開文献 + datasheet、 全 外部 evidence):

  - Bosch BME280 datasheet (Combined humidity/pressure/temperature sensor, I2C/SPI)
  - Bosch/Sensortec BNO055 datasheet (9-axis absolute orientation sensor, I2C)
  - STMicroelectronics VL53L1X datasheet (Time-of-Flight ranging sensor, I2C)
  - Akizuki 通販コード 109421 / 116996 / 114249 (2026-08-26 catalog 表記)

License: benchtop-mcp v0.x = MIT (irrevocable per README)。
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

# ---------------------------------------------------------------------------
# Built-in mock probe registry (stateless, immutable)
# 3 layer 各 1 probe = STEP 1406 wire-up 候補 list から 定番 3 SKU 選定。
# 実 hardware は 全て hardware_available: False。
# ---------------------------------------------------------------------------

_MOCK_PROBES: dict[str, dict[str, Any]] = {
    "bme280-env-a1": {
        "layer": "environment",
        "layer_number": 1,
        "part_number": "BME280",
        "akizuki_code": "109421",
        "akizuki_price_jpy": 1180,
        "interface": "I2C",
        "vendor": "Bosch Sensortec",
        "measures": ["temperature_c", "humidity_pct", "pressure_hpa"],
        "range_temp_c": [-40.0, 85.0],
        "range_humidity_pct": [0.0, 100.0],
        "range_pressure_hpa": [300.0, 1100.0],
        "resolution": "0.01°C / 0.008%RH / 0.18Pa (datasheet 典型)",
        "hardware_available": False,
        "notes": "気圧/湿度/温度 3-in-1、 個人電子工作の 環境測定 定番、 I2C addr 0x76/0x77",
    },
    "bno055-imu-b1": {
        "layer": "inertial",
        "layer_number": 2,
        "part_number": "BNO055",
        "akizuki_code": "116996",
        "akizuki_price_jpy": 3850,
        "interface": "I2C",
        "vendor": "Bosch Sensortec",
        "measures": ["quaternion", "euler_deg", "linear_acc_m_s2", "magnetic_uT"],
        "range_acc_g": [-16.0, 16.0],
        "range_gyro_dps": [-2000.0, 2000.0],
        "range_mag_uT": [-1300.0, 1300.0],
        "resolution": "on-chip fusion (Cortex-M0+ で quaternion 計算)、 100 Hz output",
        "hardware_available": False,
        "notes": "9軸 fusion (加速度+ジャイロ+磁気)、 quaternion 直接出力、 I2C addr 0x28/0x29",
    },
    "vl53l1x-tof-c1": {
        "layer": "distance",
        "layer_number": 3,
        "part_number": "VL53L1X",
        "akizuki_code": "114249",
        "akizuki_price_jpy": 1780,
        "interface": "I2C",
        "vendor": "STMicroelectronics",
        "measures": ["distance_mm"],
        "range_distance_mm": [30, 4000],
        "timing_budget_ms_range": [20, 500],
        "resolution": "1 mm (datasheet 表記、 実精度 は timing_budget と 対象反射率 依存)",
        "hardware_available": False,
        "notes": "940nm レーザー ToF、 laser class 1 eye-safe、 I2C addr 0x29",
    },
}


# ---------------------------------------------------------------------------
# list_akizuki_probes : 内蔵 mock registry の 一覧
# ---------------------------------------------------------------------------

def list_akizuki_probes() -> dict[str, Any]:
    """内蔵 mock probe registry (Akizuki wire-up 3 SKU) の 一覧を返す。
    全 probe は hardware_available: False。

    Returns:
        dict with:
          ok: True
          probes: list of probe descriptor
          probe_count: 3
          hardware_available: False (spike scope、 全 probe mock)
          honest_scope: mock registry のみ、 実 hardware discovery 未実装
          related_step: STEP 1406 (wire-up 候補 list origin)
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
            "v0.8.0-alpha spike: 内蔵 mock registry 3 probe (BME280/BNO055/VL53L1X) のみ、 "
            "実 hardware discovery 未実装。 全 probe は hardware_available: False marker で "
            "実測データでないことを 機械的に判別可能。 実 wire-up は 別 STEP (BME280 の I2C "
            "driver + ESP32/STM32 host + UART 経由 benchtop 統合 の 4 段 barrier)。"
        ),
        "related_step": "STEP 1406 (Akizuki I2C/SPI/UART wire-up 候補 list、 25 SKU origin)",
        "source": "benchtop-akizuki-mock-registry",
    }


# ---------------------------------------------------------------------------
# _hash_seed : deterministic seed generator (cross-process 安定)
# ---------------------------------------------------------------------------

def _hash_seed(*parts: str) -> int:
    """probe_id + tag 等の string 結合を hashlib.md5 で 32-bit seed に。

    hashlib.md5 = cross-process stable (Python built-in hash() は PYTHONHASHSEED で
    process 毎に seed 化されるため cross-process 決定的ではない = spike の 「再現可能」
    claim を 満たすため md5 必要)。 md5 は cryptographic 用途ではない (単純 seed 用途、
    collision resistance は要求せず)。
    """
    joined = "|".join(parts)
    return int.from_bytes(hashlib.md5(joined.encode("utf-8")).digest()[:4], "big")


# ---------------------------------------------------------------------------
# measure_environment : BME280 mock (温湿度気圧、 spike scope、 hardware 不在で 決定的)
# ---------------------------------------------------------------------------

def measure_environment(
    probe_id: str,
    condition_tag: str = "room-default",
) -> dict[str, Any]:
    """mock 環境測定 (BME280 style: 温度 / 湿度 / 気圧)。 probe_id + condition_tag から
    deterministic な 3 値を生成、 datasheet range 内 か verdict (STEP 1350 mapping) を返す。

    Args:
        probe_id: list_akizuki_probes() の 'probe_id' (現状 'bme280-env-a1' のみ)。
        condition_tag: 想定 環境 tag (例: 'room-default' / 'outdoor-summer' / 'freezer')、
            mock stimulus。 実 sensor calibration curve は 不使用、 tag hash で 値決定。

    Returns dict with:
        ok, probe_id, probe_layer, condition_tag,
        temperature_c, humidity_pct, pressure_hpa,
        in_range_all, verdict_d8, verdict_d8_symbol, verdict_reason,
        is_mock: True, hardware_available: False, honest_scope, source。
    """
    if probe_id not in _MOCK_PROBES:
        return {
            "ok": False,
            "error": f"unknown probe_id: {probe_id!r}",
            "known_probes": sorted(_MOCK_PROBES.keys()),
            "source": "benchtop-akizuki-env",
        }
    meta = _MOCK_PROBES[probe_id]
    if meta["layer"] != "environment":
        return {
            "ok": False,
            "error": f"probe_id {probe_id!r} is layer={meta['layer']!r}, not 'environment'",
            "expected_layer": "environment",
            "source": "benchtop-akizuki-env",
        }

    seed = _hash_seed(probe_id, condition_tag)
    t_lo, t_hi = meta["range_temp_c"]
    h_lo, h_hi = meta["range_humidity_pct"]
    p_lo, p_hi = meta["range_pressure_hpa"]
    # deterministic pick within range (uniform hash-derived)
    t = t_lo + (seed % 12500) / 12500.0 * (t_hi - t_lo)
    h = h_lo + ((seed >> 8) % 10000) / 10000.0 * (h_hi - h_lo)
    p = p_lo + ((seed >> 16) % 8000) / 8000.0 * (p_hi - p_lo)

    in_range = (t_lo <= t <= t_hi) and (h_lo <= h <= h_hi) and (p_lo <= p <= p_hi)
    if in_range:
        verdict, symbol, reason = "TRUE", "⊤", "within_datasheet_range"
    else:
        verdict, symbol, reason = "NEITHER", "〜", "out_of_datasheet_range"

    return {
        "ok": True,
        "probe_id": probe_id,
        "probe_layer": meta["layer"],
        "part_number": meta["part_number"],
        "condition_tag": condition_tag,
        "temperature_c": round(t, 2),
        "humidity_pct": round(h, 2),
        "pressure_hpa": round(p, 2),
        "in_range_all": in_range,
        "verdict_d8": verdict,
        "verdict_d8_symbol": symbol,
        "verdict_reason": reason,
        "is_mock": True,
        "hardware_available": False,
        "honest_scope": (
            "v0.8.0-alpha spike: deterministic mock (probe_id + condition_tag hash seed 由来)、 "
            "実 BME280 physics (Bosch calibration curve 等) を 模倣していない = interface "
            "skeleton のみ。 実 hardware 統合は 別 STEP candidate。"
        ),
        "d8_mapping_source": "STEP 1350 d8_verdict_from_measurement (2-value subset)",
        "source": "benchtop-akizuki-env",
    }


# ---------------------------------------------------------------------------
# measure_orientation : BNO055 mock (9軸 IMU、 quaternion + euler + linear_acc)
# ---------------------------------------------------------------------------

def measure_orientation(
    probe_id: str,
    motion_tag: str = "static-level",
) -> dict[str, Any]:
    """mock 慣性測定 (BNO055 style: quaternion + euler + linear_acc)。 probe_id +
    motion_tag から deterministic な orientation を生成。 実 fusion algorithm
    (Madgwick / Mahony / Kalman) は 不使用、 mock は 軸傾き のみ 表現。

    Args:
        probe_id: list_akizuki_probes() の 'probe_id' (現状 'bno055-imu-b1' のみ)。
        motion_tag: 想定 動作 tag (例: 'static-level' / 'tilt-30deg-x' / 'shake')。

    Returns dict with:
        ok, probe_id, probe_layer, motion_tag,
        quaternion {w, x, y, z}, euler_deg {roll, pitch, yaw},
        linear_acc_m_s2 {x, y, z}, magnetic_uT {x, y, z},
        calibration_status {sys, gyro, acc, mag} (0-3 each, mock),
        quaternion_norm, is_unit_quat,
        is_mock: True, hardware_available: False, honest_scope, source。
    """
    if probe_id not in _MOCK_PROBES:
        return {
            "ok": False,
            "error": f"unknown probe_id: {probe_id!r}",
            "known_probes": sorted(_MOCK_PROBES.keys()),
            "source": "benchtop-akizuki-imu",
        }
    meta = _MOCK_PROBES[probe_id]
    if meta["layer"] != "inertial":
        return {
            "ok": False,
            "error": f"probe_id {probe_id!r} is layer={meta['layer']!r}, not 'inertial'",
            "expected_layer": "inertial",
            "source": "benchtop-akizuki-imu",
        }

    seed = _hash_seed(probe_id, motion_tag)
    # deterministic euler angles in [-180, 180] for yaw, [-90, 90] for pitch, [-180, 180] for roll
    roll = -180.0 + (seed % 36000) / 100.0
    pitch = -90.0 + ((seed >> 8) % 18000) / 100.0
    yaw = -180.0 + ((seed >> 16) % 36000) / 100.0

    # euler → quaternion (ZYX intrinsic convention、 standard aerospace)
    cr, cp, cy = math.cos(math.radians(roll) / 2), math.cos(math.radians(pitch) / 2), math.cos(math.radians(yaw) / 2)
    sr, sp, sy = math.sin(math.radians(roll) / 2), math.sin(math.radians(pitch) / 2), math.sin(math.radians(yaw) / 2)
    qw = cr * cp * cy + sr * sp * sy
    qx = sr * cp * cy - cr * sp * sy
    qy = cr * sp * cy + sr * cp * sy
    qz = cr * cp * sy - sr * sp * cy
    q_norm = math.sqrt(qw * qw + qx * qx + qy * qy + qz * qz)
    # normalize (should already be ~1.0 from euler-derived construction)
    qw, qx, qy, qz = qw / q_norm, qx / q_norm, qy / q_norm, qz / q_norm

    # linear_acc: gravity subtracted, mock in ±1 g range for static/tilt tags
    acc_range_g = 1.0 if motion_tag.startswith(("static", "tilt")) else 4.0
    ax = -acc_range_g + ((seed >> 4) % 20000) / 10000.0 * acc_range_g
    ay = -acc_range_g + ((seed >> 12) % 20000) / 10000.0 * acc_range_g
    az = -acc_range_g + ((seed >> 20) % 20000) / 10000.0 * acc_range_g
    # convert g → m/s²
    g_to_mps2 = 9.80665
    ax, ay, az = ax * g_to_mps2, ay * g_to_mps2, az * g_to_mps2

    # magnetic: mock in ±60 uT range (typical geomagnetic)
    mx = -60.0 + ((seed >> 6) % 12000) / 100.0
    my = -60.0 + ((seed >> 14) % 12000) / 100.0
    mz = -60.0 + ((seed >> 22) % 12000) / 100.0

    # calibration status: BNO055 returns 0-3 per subsystem (0=uncalibrated, 3=fully calibrated)
    # mock: derive from seed, biased toward 3 (assume calibrated in mock)
    cal_sys = 2 + ((seed >> 2) % 2)
    cal_gyro = 3
    cal_acc = 2 + ((seed >> 10) % 2)
    cal_mag = 1 + ((seed >> 18) % 3)

    return {
        "ok": True,
        "probe_id": probe_id,
        "probe_layer": meta["layer"],
        "part_number": meta["part_number"],
        "motion_tag": motion_tag,
        "quaternion": {"w": round(qw, 6), "x": round(qx, 6), "y": round(qy, 6), "z": round(qz, 6)},
        "euler_deg": {"roll": round(roll, 2), "pitch": round(pitch, 2), "yaw": round(yaw, 2)},
        "linear_acc_m_s2": {"x": round(ax, 4), "y": round(ay, 4), "z": round(az, 4)},
        "magnetic_uT": {"x": round(mx, 2), "y": round(my, 2), "z": round(mz, 2)},
        "calibration_status": {"sys": cal_sys, "gyro": cal_gyro, "acc": cal_acc, "mag": cal_mag},
        "quaternion_norm": round(math.sqrt(qw * qw + qx * qx + qy * qy + qz * qz), 6),
        "is_unit_quat": True,
        "is_mock": True,
        "hardware_available": False,
        "honest_scope": (
            "v0.8.0-alpha spike: deterministic mock quaternion (euler → ZYX 変換で 単位化)、 "
            "実 BNO055 on-chip fusion (Cortex-M0+ で Madgwick/Mahony 相当) を 模倣していない "
            "= interface skeleton のみ。 calibration_status も mock (実 hardware は 0-3 で "
            "動的更新)、 実 hardware 統合は 別 STEP candidate。"
        ),
        "d8_mapping_source": "STEP 1350 (verdict field 未使用、 quaternion norm で 代替 verify)",
        "source": "benchtop-akizuki-imu",
    }


# ---------------------------------------------------------------------------
# measure_distance : VL53L1X mock (ToF distance、 range check + verdict)
# ---------------------------------------------------------------------------

def measure_distance(
    probe_id: str,
    target_tag: str = "wall-2m",
    timing_budget_ms: float = 100.0,
) -> dict[str, Any]:
    """mock ToF 距離測定 (VL53L1X style)。 probe_id + target_tag から deterministic
    距離 (mm) を生成、 VL53L1X datasheet 有効範囲 (30〜4000mm) 内 か verdict を返す。

    Args:
        probe_id: list_akizuki_probes() の 'probe_id' (現状 'vl53l1x-tof-c1' のみ)。
        target_tag: 想定 対象 tag (例: 'wall-2m' / 'ceiling-3m' / 'obstacle-close-50cm')。
        timing_budget_ms: VL53L1X の 測定 budget (20-500 ms)、 default 100 ms。
            長いほど 精度上昇 (実 hardware の trade-off)、 mock では 値には影響なし。

    Returns dict with:
        ok, probe_id, probe_layer, target_tag,
        distance_mm, timing_budget_ms, range_status,
        in_range, verdict_d8, verdict_d8_symbol, verdict_reason,
        is_mock: True, hardware_available: False, honest_scope, source。
    """
    if probe_id not in _MOCK_PROBES:
        return {
            "ok": False,
            "error": f"unknown probe_id: {probe_id!r}",
            "known_probes": sorted(_MOCK_PROBES.keys()),
            "source": "benchtop-akizuki-tof",
        }
    meta = _MOCK_PROBES[probe_id]
    if meta["layer"] != "distance":
        return {
            "ok": False,
            "error": f"probe_id {probe_id!r} is layer={meta['layer']!r}, not 'distance'",
            "expected_layer": "distance",
            "source": "benchtop-akizuki-tof",
        }
    tb_lo, tb_hi = meta["timing_budget_ms_range"]
    if timing_budget_ms < tb_lo or timing_budget_ms > tb_hi:
        return {
            "ok": False,
            "error": f"timing_budget_ms must be in [{tb_lo}, {tb_hi}], got {timing_budget_ms}",
            "source": "benchtop-akizuki-tof",
        }

    seed = _hash_seed(probe_id, target_tag)
    d_lo, d_hi = meta["range_distance_mm"]
    # deterministic distance in [d_lo - margin, d_hi + margin] to allow out-of-range verdict
    margin = 500  # allow up to 500mm beyond nominal for verdict testing
    span = (d_hi - d_lo) + 2 * margin
    distance = (d_lo - margin) + (seed % (span * 100)) / 100.0

    if distance < d_lo:
        range_status = "TOO_CLOSE"
        in_range = False
    elif distance > d_hi:
        range_status = "TOO_FAR"
        in_range = False
    else:
        range_status = "VALID"
        in_range = True

    if in_range:
        verdict, symbol, reason = "TRUE", "⊤", "within_vl53l1x_range"
    else:
        verdict, symbol, reason = "NEITHER", "〜", f"out_of_range_{range_status.lower()}"

    return {
        "ok": True,
        "probe_id": probe_id,
        "probe_layer": meta["layer"],
        "part_number": meta["part_number"],
        "target_tag": target_tag,
        "distance_mm": round(distance, 1),
        "timing_budget_ms": timing_budget_ms,
        "range_status": range_status,
        "in_range": in_range,
        "verdict_d8": verdict,
        "verdict_d8_symbol": symbol,
        "verdict_reason": reason,
        "is_mock": True,
        "hardware_available": False,
        "honest_scope": (
            "v0.8.0-alpha spike: deterministic mock distance (target_tag hash 由来)、 "
            "実 VL53L1X physics (940nm laser SPAD photon counting) を 模倣していない = "
            "interface skeleton のみ。 timing_budget は 実 hardware では 精度 trade-off "
            "だが、 本 mock では 値には影響なし。 実 hardware 統合は 別 STEP candidate。"
        ),
        "d8_mapping_source": "STEP 1350 d8_verdict_from_measurement (2-value subset)",
        "source": "benchtop-akizuki-tof",
    }


# ---------------------------------------------------------------------------
# selftest (module-level) : 呼ぶ場合は python -c 'import benchtop_akizuki_wireup as m; m.selftest()'
# ---------------------------------------------------------------------------

def selftest() -> int:
    """module-level 単体テスト。 benchtop_mcp.py --selftest からも 統合 test 実行される。"""
    print("--- benchtop_akizuki_wireup selftest (v0.8.0-alpha) ---")

    # [1] list_akizuki_probes: 3 probe registry
    r1 = list_akizuki_probes()
    assert r1["ok"] is True
    assert r1["probe_count"] == 3
    assert r1["hardware_available"] is False
    assert r1["is_mock"] is True
    ids = {p["probe_id"] for p in r1["probes"]}
    assert ids == {"bme280-env-a1", "bno055-imu-b1", "vl53l1x-tof-c1"}
    print(f"[1] list_akizuki_probes: count={r1['probe_count']} ids={sorted(ids)}")

    # [2] measure_environment: BME280 mock, in-range verdict
    r2 = measure_environment("bme280-env-a1", "room-default")
    assert r2["ok"] is True
    assert r2["is_mock"] is True
    assert -40.0 <= r2["temperature_c"] <= 85.0
    assert 0.0 <= r2["humidity_pct"] <= 100.0
    assert 300.0 <= r2["pressure_hpa"] <= 1100.0
    assert r2["verdict_d8"] == "TRUE"
    print(f"[2] measure_environment(bme280, room-default): t={r2['temperature_c']}C "
          f"h={r2['humidity_pct']}% p={r2['pressure_hpa']}hPa verdict={r2['verdict_d8']}")

    # [3] measure_environment: determinism
    r3a = measure_environment("bme280-env-a1", "outdoor-summer")
    r3b = measure_environment("bme280-env-a1", "outdoor-summer")
    assert r3a["temperature_c"] == r3b["temperature_c"]
    assert r3a["pressure_hpa"] == r3b["pressure_hpa"]
    print(f"[3] measure_environment determinism: t_equal={r3a['temperature_c'] == r3b['temperature_c']}")

    # [4] measure_orientation: BNO055 mock, unit quaternion
    r4 = measure_orientation("bno055-imu-b1", "static-level")
    assert r4["ok"] is True
    assert r4["is_mock"] is True
    q = r4["quaternion"]
    q_norm = math.sqrt(q["w"] ** 2 + q["x"] ** 2 + q["y"] ** 2 + q["z"] ** 2)
    assert abs(q_norm - 1.0) < 1e-4
    assert r4["is_unit_quat"] is True
    print(f"[4] measure_orientation(bno055, static-level): q_norm={q_norm:.6f} "
          f"euler=({r4['euler_deg']['roll']}, {r4['euler_deg']['pitch']}, {r4['euler_deg']['yaw']})")

    # [5] measure_orientation: determinism
    r5a = measure_orientation("bno055-imu-b1", "tilt-30deg-x")
    r5b = measure_orientation("bno055-imu-b1", "tilt-30deg-x")
    assert r5a["quaternion"] == r5b["quaternion"]
    print(f"[5] measure_orientation determinism: q_equal={r5a['quaternion'] == r5b['quaternion']}")

    # [6] measure_distance: VL53L1X mock, range check
    r6 = measure_distance("vl53l1x-tof-c1", "wall-2m", timing_budget_ms=100.0)
    assert r6["ok"] is True
    assert r6["is_mock"] is True
    assert r6["range_status"] in ("VALID", "TOO_CLOSE", "TOO_FAR")
    assert r6["verdict_d8"] in ("TRUE", "NEITHER")
    print(f"[6] measure_distance(vl53l1x, wall-2m): d={r6['distance_mm']}mm "
          f"status={r6['range_status']} verdict={r6['verdict_d8']}")

    # [7] measure_distance: timing_budget_ms out-of-range rejection
    r7 = measure_distance("vl53l1x-tof-c1", "wall", timing_budget_ms=1000.0)
    assert r7["ok"] is False
    print(f"[7] measure_distance timing_budget out-of-range: rejected={not r7['ok']}")

    # [8] cross-layer misuse rejection (env probe for orientation → error)
    r8a = measure_orientation("bme280-env-a1", "any")
    r8b = measure_environment("bno055-imu-b1", "any")
    r8c = measure_distance("bme280-env-a1", "any")
    assert not r8a["ok"] and not r8b["ok"] and not r8c["ok"]
    print(f"[8] cross-layer misuse rejected: env_not_orient={not r8a['ok']} "
          f"imu_not_env={not r8b['ok']} env_not_tof={not r8c['ok']}")

    # [9] unknown probe rejection
    r9 = measure_environment("unknown-probe", "any")
    assert r9["ok"] is False
    print(f"[9] unknown probe rejected: {not r9['ok']}")

    print("\n benchtop_akizuki_wireup: all 9 test PASS")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(selftest())
