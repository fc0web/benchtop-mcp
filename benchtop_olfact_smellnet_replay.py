#!/usr/bin/env python3
"""
benchtop-mcp olfact SmellNet replay adapter : real dataset schema wire (SPIKE)
================================================================================

v0.11.0-alpha (2026-08-27, 藤本さん directive 「SmellNet spike で benchtop v0.7 → v0.8
real dataset upgrade」 応答、 rei-aios STEP 1474 candidate arc の implementation 実施、
rei-scout 別 tab 発見 (2026-08-27 report) の Finding A)。

**目的**:

  現状の benchtop_olfact.py (v0.7.0-alpha) は 全 signal deterministic mock
  (hashlib.md5 seed 由来)。 本 module は MIT-MI/SmellNet (★72, MIT License, MOX gas
  sensor, 50 substances + 43 mixtures, 828K timesteps / 68 hours) の schema と
  互換 な real dataset replay の interface を 提供する。 network / HF download
  は 本 spike scope 外 (別 STEP directive 待ち)、 embedded synthetic fixture で
  interface 動作 verify のみ。

**★ 命名 discipline** ([[feedback-super-naming-siren-family-pattern]] 適用):

  「SmellNet replay」 は SmellNet 実 dataset を replay する 誤解 を 招きやすい。
  v0.11 spike scope 内では 全 replay session の 全 return に `data_source` +
  `is_embedded_fixture` marker を 含め、 embedded synthetic data であることを
  機械的に判別可能。 実 SmellNet CSV load path (`load_smellnet_csv`) は
  interface 提供のみ、 実 file 未同梱 (別 STEP で DL + integration)。

**scope 明示** (v0.11.0-alpha spike scope):

  (1) 全 tool は pure calculation (stdlib のみ、 network / file DL なし)。
      embedded fixture のみ 動作可能、 CSV load path は 実 file 与えれば動く
      interface のみ (test は fixture path のみ)。
  (2) SmellNet 互換 schema = {timestamp_s, substance, ch1..chN} time-series CSV。
      本 spike は 3 substance × 3 channel × 100 timestep embedded fixture のみ。
      実 SmellNet (828K timestep / 50 substance) は 別 STEP で DL + subset load。
  (3) replay window は session の time-series から 指定 duration_s / sample_rate_hz
      の window を 抽出 + interpolation (linear)。 duration_s > session length の
      case は 折り返し (wrap around) で 対応、 実 hardware の 「連続 sensing」 を模倣。
  (4) benchtop_olfact.measure_eag() の replay_source param として 使用 (別 spike で
      integration、 本 module 単体 は replay session の generation + query のみ)。
  (5) SmellNet 実 dataset は Hugging Face Hub にあるが、 DL は 本 module scope 外。
      藤本さん explicit go 後 別 STEP で `datasets` library + auth + 選択的 DL 実装。

**Rei stack alignment**:

  - benchtop_olfact.py v0.7.0-alpha の 拡張 (v0.11.0-alpha で replay path 追加)
  - rei-aios STEP 1474 (rei-scout finding site 反映) candidate arc A 実装
  - rei-scout 別 tab report 2026-08-27 Finding A (MIT-MI/SmellNet ★72, MIT License)
  - STEP 1396 benchtop-mcp v0.7 olfact spike の 「mock → real upgrade path」 実現 第 1 段

**related memory**:

  - [[project-step1474-scout-findings-site-reflection-2026-08-27]] (candidate arc A 起点)
  - [[project-step1396-benchtop-olfact-spike-2026-08-23]] (v0.7.0-alpha 起点)
  - [[feedback-super-naming-siren-family-pattern]] (mock でない 誤読 予防)
  - [[feedback-projection-self-audit-pattern]] SAC-4 (pool saturation 予防)
  - [[feedback-world-uniqueness-claim-controllable]] (novelty 主張ゼロ discipline)

**References** (公開文献、 全 外部 evidence):

  - MIT-MI/SmellNet (Hugging Face + GitHub、 MIT License、 MIT Media Lab、
    MOX gas sensor 50 substance + 43 mixture、 828K timestep / 68 hours、
    学習 code + GC-MS pipeline + Arduino firmware 同梱)
  - Hugging Face datasets library (公式 hub、 auth 必要な private dataset は 別途)

**Novelty**: **ゼロ** ([[feedback-world-uniqueness-claim-controllable]] 継承)。
「SmellNet 使用」 は 論文レベル既存、 本 module は Rei stack benchtop-mcp 内 の
adapter 実装のみ、 「世界初」 主張なし。

License: benchtop-mcp v0.x = MIT (irrevocable per README)。
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
from typing import Any

# ---------------------------------------------------------------------------
# Embedded synthetic fixture (SmellNet schema-compatible)
# 3 substance × 3 channel × 100 timestep = 900 sample の 小 fixture、
# 実 SmellNet 実 file 未 DL 状態で interface 動作 verify のみを 目的とする。
# ---------------------------------------------------------------------------

# fixture header
_FIXTURE_CHANNELS = ["ch1_resistance_kohm", "ch2_resistance_kohm", "ch3_resistance_kohm"]
_FIXTURE_SUBSTANCES = ["ethanol", "acetone", "hexanol"]  # SmellNet 頻出 3 種
_FIXTURE_TIMESTEPS = 100  # 各 substance あたり 100 sample
_FIXTURE_SAMPLE_RATE_HZ = 10.0  # 10 Hz = 10 sec 分 の window per substance

def _generate_fixture_csv() -> str:
    """embedded 3 substance × 3 channel × 100 timestep synthetic CSV を string で生成。

    signal model (SmellNet に 似せた MOX 応答 envelope):
        base_resistance (ch 別 + substance 別 hash 決定的) から
        exposure 開始 (t=1s) で 急降下 → 減衰、 各 ch で 異なる時定数。
        全 signal は deterministic (hashlib.md5 seed 由来、 cross-process 安定)。
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["timestamp_s", "substance"] + _FIXTURE_CHANNELS)

    for substance in _FIXTURE_SUBSTANCES:
        # substance 別 hash で base + response 特性を 決定的に
        seed_bytes = hashlib.md5(f"smellnet_fixture|{substance}".encode("utf-8")).digest()
        seed_int = int.from_bytes(seed_bytes[:4], "big")
        # base resistance kΩ (10..50)
        base_r = [10.0 + ((seed_int >> (i * 4)) % 40) for i in range(3)]
        # response amplitude Δkω (5..15)
        delta_r = [5.0 + ((seed_int >> (i * 8)) % 10) for i in range(3)]
        # ch 別 時定数 (0.5..2.0 sec)
        tau = [0.5 + ((seed_int >> (i * 3)) % 15) / 10.0 for i in range(3)]

        for i in range(_FIXTURE_TIMESTEPS):
            t = i / _FIXTURE_SAMPLE_RATE_HZ  # 0..10 sec
            row = [f"{t:.3f}", substance]
            for ch_idx in range(3):
                if t < 1.0:
                    # baseline
                    r = base_r[ch_idx]
                else:
                    # exponential recovery back to baseline after initial drop
                    r = base_r[ch_idx] - delta_r[ch_idx] * math.exp(-(t - 1.0) / tau[ch_idx])
                # ch 別 deterministic noise
                noise = ((seed_int + i * 7919 + ch_idx * 331) % 200 - 100) / 1000.0
                r += noise
                row.append(f"{r:.4f}")
            writer.writerow(row)
    return output.getvalue()


# ---------------------------------------------------------------------------
# load_smellnet_csv : CSV path → session dict
# 実 SmellNet CSV は 別 STEP で DL、 本 module では embedded fixture path の みで 動作。
# ---------------------------------------------------------------------------

def load_smellnet_csv(
    csv_source: str, is_fixture: bool = False
) -> dict[str, Any]:
    """SmellNet 互換 CSV を load。 csv_source は file path or CSV string (is_fixture=True 時)。

    Args:
        csv_source: CSV 文字列 (is_fixture=True) or file path (is_fixture=False)。
        is_fixture: True の 時 csv_source を CSV string として parse、 False で file 読み。

    Returns dict with:
        ok, sessions (dict[substance -> list of rows])、 substance_count、
        total_rows、 channels (list of column names)、 duration_per_substance_s、
        data_source ('embedded_fixture' or 'external_csv')、 is_embedded_fixture、
        honest_scope、 source。
    """
    if is_fixture:
        text = csv_source
    else:
        try:
            with open(csv_source, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            return {
                "ok": False,
                "error": f"cannot read csv_source: {e}",
                "csv_source": csv_source,
                "source": "benchtop-olfact-smellnet-load",
            }

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    if "timestamp_s" not in fieldnames or "substance" not in fieldnames:
        return {
            "ok": False,
            "error": "csv missing required columns (timestamp_s, substance)",
            "fieldnames": fieldnames,
            "source": "benchtop-olfact-smellnet-load",
        }

    channels = [f for f in fieldnames if f not in ("timestamp_s", "substance")]
    sessions: dict[str, list[dict[str, Any]]] = {}
    total_rows = 0
    for row in reader:
        substance = row["substance"]
        try:
            ts = float(row["timestamp_s"])
        except (ValueError, TypeError):
            continue
        ch_values = {}
        for ch in channels:
            try:
                ch_values[ch] = float(row[ch])
            except (ValueError, TypeError):
                ch_values[ch] = 0.0
        sessions.setdefault(substance, []).append(
            {"timestamp_s": ts, **ch_values}
        )
        total_rows += 1

    # duration per substance = last - first timestamp
    duration_per_substance = {}
    for sub, rows in sessions.items():
        if rows:
            duration_per_substance[sub] = rows[-1]["timestamp_s"] - rows[0]["timestamp_s"]

    return {
        "ok": True,
        "sessions": sessions,
        "substance_count": len(sessions),
        "total_rows": total_rows,
        "channels": channels,
        "duration_per_substance_s": duration_per_substance,
        "data_source": "embedded_fixture" if is_fixture else "external_csv",
        "is_embedded_fixture": is_fixture,
        "honest_scope": (
            "v0.11.0-alpha spike: is_embedded_fixture=True は synthetic MOX 応答 "
            "envelope (deterministic hashlib.md5 seed 由来)、 実 SmellNet dataset "
            "ではない。 external_csv path は 実 file を 与えれば 動作するが、 実 SmellNet "
            "DL は 本 spike scope 外 (別 STEP directive 待ち)。"
        ),
        "source": "benchtop-olfact-smellnet-load",
    }


def load_embedded_fixture() -> dict[str, Any]:
    """convenience wrapper for embedded fixture load。"""
    csv_text = _generate_fixture_csv()
    return load_smellnet_csv(csv_text, is_fixture=True)


# ---------------------------------------------------------------------------
# get_replay_window : session から 指定 duration_s / sample_rate_hz の window 抽出
# duration_s > session length の case は wrap around で 対応 (連続 sensing 模倣)。
# ---------------------------------------------------------------------------

def get_replay_window(
    session: dict[str, Any],
    substance: str,
    duration_s: float,
    sample_rate_hz: float,
    channel: str | None = None,
) -> dict[str, Any]:
    """SmellNet session から 指定 substance の 指定 duration の window を抽出。

    Args:
        session: load_smellnet_csv() 返り値 (ok=True の dict)。
        substance: session["sessions"] の key (ethanol / acetone / hexanol)。
        duration_s: 抽出 window の 長さ (秒)、 must be > 0。
        sample_rate_hz: 出力サンプリング周波数 (Hz)、 must be > 0。
        channel: 抽出 channel 名 (None なら session["channels"][0] 使用)。

    Returns dict with:
        ok, substance, channel, duration_s, sample_rate_hz, sample_count,
        waveform (list[float]、 channel 値 の time-series)、 peak, mean, min, max,
        original_duration_s, wrap_around (bool)、
        data_source, is_embedded_fixture, honest_scope, source。
    """
    if not session.get("ok"):
        return {"ok": False, "error": "session dict is not ok", "source": "benchtop-olfact-smellnet-replay"}
    if substance not in session.get("sessions", {}):
        return {
            "ok": False,
            "error": f"substance {substance!r} not in session",
            "available_substances": list(session.get("sessions", {}).keys()),
            "source": "benchtop-olfact-smellnet-replay",
        }
    if duration_s <= 0:
        return {"ok": False, "error": "duration_s must be > 0", "source": "benchtop-olfact-smellnet-replay"}
    if sample_rate_hz <= 0:
        return {"ok": False, "error": "sample_rate_hz must be > 0", "source": "benchtop-olfact-smellnet-replay"}

    rows = session["sessions"][substance]
    if not rows:
        return {
            "ok": False,
            "error": f"no rows for substance {substance!r}",
            "source": "benchtop-olfact-smellnet-replay",
        }

    channels = session.get("channels", [])
    if channel is None:
        if not channels:
            return {
                "ok": False,
                "error": "no channels in session",
                "source": "benchtop-olfact-smellnet-replay",
            }
        channel = channels[0]
    if channel not in channels:
        return {
            "ok": False,
            "error": f"channel {channel!r} not in session",
            "available_channels": channels,
            "source": "benchtop-olfact-smellnet-replay",
        }

    original_start = rows[0]["timestamp_s"]
    original_end = rows[-1]["timestamp_s"]
    original_duration = original_end - original_start
    if original_duration <= 0:
        original_duration = 1.0  # avoid divide-by-zero for degenerate case

    requested_samples = max(1, int(duration_s * sample_rate_hz))
    dt = 1.0 / sample_rate_hz
    wrap_around = duration_s > original_duration

    # source rows converted to (t, value) pairs for interpolation
    src_ts = [r["timestamp_s"] - original_start for r in rows]
    src_values = [r[channel] for r in rows]

    def _interpolate(t: float) -> float:
        # wrap around original session length
        if wrap_around:
            t_mod = t % original_duration
        else:
            t_mod = min(t, original_duration)
        # linear interpolation
        if t_mod <= src_ts[0]:
            return src_values[0]
        if t_mod >= src_ts[-1]:
            return src_values[-1]
        # bisect for insertion point
        lo, hi = 0, len(src_ts) - 1
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if src_ts[mid] <= t_mod:
                lo = mid
            else:
                hi = mid
        t0, t1 = src_ts[lo], src_ts[hi]
        v0, v1 = src_values[lo], src_values[hi]
        if t1 == t0:
            return v0
        return v0 + (v1 - v0) * (t_mod - t0) / (t1 - t0)

    waveform = [_interpolate(i * dt) for i in range(requested_samples)]
    peak = max(waveform)
    trough = min(waveform)
    mean = sum(waveform) / len(waveform)

    return {
        "ok": True,
        "substance": substance,
        "channel": channel,
        "duration_s": duration_s,
        "sample_rate_hz": sample_rate_hz,
        "sample_count": len(waveform),
        "waveform": waveform,
        "peak": peak,
        "mean": mean,
        "min": trough,
        "max": peak,
        "original_duration_s": original_duration,
        "wrap_around": wrap_around,
        "data_source": session.get("data_source", "unknown"),
        "is_embedded_fixture": session.get("is_embedded_fixture", False),
        "honest_scope": (
            "v0.11.0-alpha spike: waveform は SmellNet 互換 CSV row から linear "
            "interpolation で 生成 (duration_s > session length で wrap around)。 "
            "実 SmellNet dataset は 別 STEP で load、 本 spike は fixture のみ 動作。"
        ),
        "source": "benchtop-olfact-smellnet-replay",
    }


# ---------------------------------------------------------------------------
# download_smellnet_stub : documented placeholder for real DL (別 STEP)
# ---------------------------------------------------------------------------

def download_smellnet_stub() -> dict[str, Any]:
    """SmellNet 実 dataset DL の placeholder。 v0.11.0-alpha では未実装、 documentation only。

    実 DL は 藤本さん explicit go 後 別 STEP で 実装:
        1. `pip install datasets huggingface_hub`
        2. HF auth (public dataset なら token 不要)
        3. selective subset DL (全 828K timestep は 数 GB、 validation split から 開始)
        4. schema mapping (SmellNet 実 columns → benchtop 互換 CSV format 変換)
        5. cache path 決定 (~/.cache/benchtop/smellnet/ 等) + gitignore
        6. load_smellnet_csv() を cached CSV に対して 呼び出し
    """
    return {
        "ok": True,
        "implemented": False,
        "message": "v0.11.0-alpha spike scope 外: 実 SmellNet DL は 別 STEP directive 待ち",
        "required_steps": [
            "pip install datasets huggingface_hub",
            "hf auth (public dataset は token 不要)",
            "selective subset DL (validation split から 開始)",
            "schema mapping (SmellNet 実 columns → benchtop CSV format)",
            "cache path 決定 (~/.cache/benchtop/smellnet/、 gitignore)",
            "load_smellnet_csv() を cached CSV に対して 呼び出し",
        ],
        "reference_dataset": "MIT-MI/SmellNet on Hugging Face Hub",
        "reference_paper": "MIT Media Lab (MOX gas sensor, 50 substances + 43 mixtures, 828K timesteps / 68 hours)",
        "license": "MIT (irrevocable)",
        "honest_scope": (
            "v0.11.0-alpha spike は embedded synthetic fixture のみ、 実 SmellNet "
            "network access なし。 実 DL は 別 STEP、 spike scope 内では stub のみ。"
        ),
        "source": "benchtop-olfact-smellnet-download-stub",
    }


# ---------------------------------------------------------------------------
# _selftest : 本 module 単体 self-verify
# ---------------------------------------------------------------------------

def _selftest() -> int:
    """本 module 単体の selftest。 実行: python benchtop_olfact_smellnet_replay.py --selftest"""
    import sys as _sys
    try:
        _sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    print("=== benchtop_olfact_smellnet_replay v0.11.0-alpha selftest ===")
    passed, failed = 0, 0

    def check(cond: bool, msg: str) -> None:
        nonlocal passed, failed
        if cond:
            passed += 1
        else:
            failed += 1
            print(f"  FAIL: {msg}")

    # [1] fixture generation
    csv_text = _generate_fixture_csv()
    check(len(csv_text) > 0, "fixture csv non-empty")
    lines = csv_text.strip().split("\n")
    header = lines[0]
    check("timestamp_s" in header, "fixture header has timestamp_s")
    check("substance" in header, "fixture header has substance")
    check("ch1_resistance_kohm" in header, "fixture header has ch1_resistance_kohm")
    # 3 substance × 100 timestep = 300 data rows + 1 header
    check(len(lines) == 3 * 100 + 1, f"fixture row count = 301 (got {len(lines)})")
    print(f"[1] fixture csv: {len(lines)} lines, header={header[:60]}...")

    # [2] load_embedded_fixture
    session = load_embedded_fixture()
    check(session["ok"] is True, "load_embedded_fixture ok")
    check(session["substance_count"] == 3, f"3 substances (got {session['substance_count']})")
    check(session["total_rows"] == 300, f"300 rows (got {session['total_rows']})")
    check(len(session["channels"]) == 3, f"3 channels (got {len(session['channels'])})")
    check(session["is_embedded_fixture"] is True, "is_embedded_fixture=True")
    check(session["data_source"] == "embedded_fixture", "data_source=embedded_fixture")
    check(set(session["sessions"].keys()) == {"ethanol", "acetone", "hexanol"}, "3 substances match")
    print(f"[2] load_embedded_fixture: {session['substance_count']} substances, "
          f"{session['total_rows']} rows, channels={session['channels']}")

    # [3] load_smellnet_csv: missing columns error
    r3 = load_smellnet_csv("bad,header\n1,2\n", is_fixture=True)
    check(r3["ok"] is False, "missing columns rejected")
    check("required columns" in r3.get("error", ""), "error mentions required columns")
    print(f"[3] missing columns rejected: error={r3['error']}")

    # [4] load_smellnet_csv: nonexistent file error
    r4 = load_smellnet_csv("nonexistent-file-xyz-999.csv", is_fixture=False)
    check(r4["ok"] is False, "nonexistent file rejected")
    print(f"[4] nonexistent file rejected: error={r4['error'][:60]}...")

    # [5] get_replay_window: valid, no wrap
    r5 = get_replay_window(session, "ethanol", duration_s=5.0, sample_rate_hz=20.0)
    check(r5["ok"] is True, "get_replay_window ok")
    check(r5["sample_count"] == 100, f"5s * 20Hz = 100 samples (got {r5['sample_count']})")
    check(r5["substance"] == "ethanol", "substance passthrough")
    check(r5["channel"] == "ch1_resistance_kohm", "default channel = ch1")
    check(r5["wrap_around"] is False, "5s < fixture 10s → no wrap")
    print(f"[5] ethanol 5s@20Hz: peak={r5['peak']:.2f} mean={r5['mean']:.2f} wrap={r5['wrap_around']}")

    # [6] get_replay_window: wrap around
    r6 = get_replay_window(session, "acetone", duration_s=25.0, sample_rate_hz=10.0)
    check(r6["ok"] is True, "wrap window ok")
    check(r6["sample_count"] == 250, "25s * 10Hz = 250 samples")
    check(r6["wrap_around"] is True, "25s > fixture ~10s → wrap")
    print(f"[6] acetone 25s@10Hz: samples={r6['sample_count']} wrap={r6['wrap_around']}")

    # [7] get_replay_window: unknown substance
    r7 = get_replay_window(session, "unknown-substance", 1.0, 10.0)
    check(r7["ok"] is False, "unknown substance rejected")
    check("available_substances" in r7, "available_substances listed")
    print(f"[7] unknown substance rejected: {r7['error']}")

    # [8] get_replay_window: specific channel
    r8 = get_replay_window(session, "hexanol", 2.0, 10.0, channel="ch2_resistance_kohm")
    check(r8["ok"] is True, "specific channel ok")
    check(r8["channel"] == "ch2_resistance_kohm", "specific channel passthrough")
    print(f"[8] hexanol ch2: peak={r8['peak']:.2f} min={r8['min']:.2f}")

    # [9] get_replay_window: unknown channel
    r9 = get_replay_window(session, "ethanol", 1.0, 10.0, channel="ch99_bad")
    check(r9["ok"] is False, "unknown channel rejected")
    check("available_channels" in r9, "available_channels listed")
    print(f"[9] unknown channel rejected: available={r9['available_channels']}")

    # [10] get_replay_window: invalid duration
    r10a = get_replay_window(session, "ethanol", -1.0, 10.0)
    r10b = get_replay_window(session, "ethanol", 1.0, 0.0)
    check(not r10a["ok"] and not r10b["ok"], "invalid duration/rate rejected")
    print(f"[10] invalid args rejected: 2/2")

    # [11] determinism: same session, same query → same waveform
    r11a = get_replay_window(session, "ethanol", 3.0, 20.0)
    r11b = get_replay_window(session, "ethanol", 3.0, 20.0)
    check(r11a["waveform"] == r11b["waveform"], "get_replay_window deterministic")
    print(f"[11] determinism: waveform equal={r11a['waveform'] == r11b['waveform']}")

    # [12] fixture regeneration determinism (cross-process stable)
    csv_text_2 = _generate_fixture_csv()
    check(csv_text == csv_text_2, "fixture csv deterministic")
    session_2 = load_embedded_fixture()
    check(session["sessions"] == session_2["sessions"], "session reload deterministic")
    print(f"[12] fixture regeneration deterministic: csv equal={csv_text == csv_text_2}")

    # [13] download_smellnet_stub: documented, not implemented
    r13 = download_smellnet_stub()
    check(r13["ok"] is True, "download stub ok")
    check(r13["implemented"] is False, "download stub NOT implemented")
    check(len(r13["required_steps"]) >= 4, "download stub has required steps documented")
    print(f"[13] download stub: implemented={r13['implemented']} steps={len(r13['required_steps'])}")

    # [14] source markers
    check(session["source"] == "benchtop-olfact-smellnet-load", "load source marker")
    check(r5["source"] == "benchtop-olfact-smellnet-replay", "replay source marker")
    check(r13["source"] == "benchtop-olfact-smellnet-download-stub", "download-stub source marker")
    print(f"[14] source markers: 3/3 present")

    # [15] honest_scope present on all major returns
    check("honest_scope" in session, "session honest_scope")
    check("honest_scope" in r5, "replay honest_scope")
    check("honest_scope" in r13, "download-stub honest_scope")
    print(f"[15] honest_scope markers: 3/3 present")

    print(f"\n=== selftest result: {passed} passed, {failed} failed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print("This module is a library. Run with --selftest to verify.")
