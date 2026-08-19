#!/usr/bin/env python3
"""
benchtop-mcp physics-limits pre-flight layer : 単位付き算術で LLM の 弱点を埋める
================================================================================

v0.6.0-alpha (2026-08-20, chat-Claude 2026-08-20 turn 「コネクタの本体は解説ではなく
単位付き算術」 の 5 tool 実装、 藤本さん承認で benchtop v0.6 に統合)。

**目的**:

  LLM が 自信満々に間違える 領域 = 単位換算 + 桁勘定 + 上界計算 を、
  Bekenstein / Landauer / Lloyd / operator space / compression bound の 5 primitives
  として MCP tool に落とし、 実 hardware SCPI 送出 (benchtop measure() 等) の
  pre-flight check として 使えるようにする。 STEP 1345 SafetyGate と同じ scope
  (「実 hardware に送る前の 静的 check layer」) で 相補関係。

**5 tool** (chat-Claude 2026-08-20 提示、 命名は chat-Claude 案を尊重):

  1. bekenstein_bound_bits(radius_m, energy_J) → 球状領域 R,E の 情報上界 bits
  2. landauer_min_energy_j(bits, temperature_K) → N bit erase の 最小 E (可逆計算 除外)
  3. lloyd_computation_ceiling(mass_kg) → Lloyd 2000 究極的 ops/s 上限
  4. operator_space_size(k, n) → k 値 n 変数 演算子空間 (log10 N + LUT + config)
  5. compression_upper_bound(length, method, entropy_bits_per_symbol) → 圧縮長 上界

**★ 命名 discipline** ([[feedback-super-naming-siren-family-pattern]] 適用):

  Kolmogorov 複雑性 K(x) は Turing-uncomputable。 「kolmogorov_complexity」 という
  tool 名は 果たせない約束 = siren。 本 module は 全 tool で 「上界 / 最小 / 上限 /
  空間 size」 という semantic を name に埋め込み、 「厳密値を返す」 と 誤解されない
  ようにする。 return dict にも 明示的に 'is_upper_bound': True 等の flag を含める。

**scope 明示** (v0.6.0-alpha pre-flight scope):

  (1) 全 tool は pure calculation (stdlib のみ、 network / file I/O なし)、 状態なし。
      remote MCP としても そのまま deploy 可能 (依存 lag なし)。
  (2) Bekenstein bound は 球状 (非回転) 領域、 一般化 (Bousso covariant bound) は
      別 tool candidate。
  (3) Landauer は irreversible operation (bit erase) の 熱力学的下限、 reversible
      computation は E=0 下限 の 別 regime = 本 tool の scope 外 (docstring 明示)。
  (4) Lloyd's ultimate limit は 質量-energy rest-mass base、 relativistic 極限で
      speed-of-light constraint も別途、 単純化された上限のみ返す。
  (5) operator_space_size は 演算子個数の 数え上げ (k^(k^n))、 実 FPGA 合成 では
      shared-subexpression + BDD 圧縮で 実効 config bits は 大幅減、 本 tool は
      理論上限のみ。
  (6) compression_upper_bound は Shannon entropy-based typical set 上界、
      Kolmogorov K(x) の 実現値ではない (K は uncomputable、 本 tool は
      「上界の一つ」 を 返す のみ)。
  (7) [[feedback-world-uniqueness-claim-controllable]] 継承 = 「世界初」 主張ゼロ、
      全 tool は 60+ 年前の 教科書 定理 の operational wrap layer のみ。

**related memory**:
  - chat-Claude 2026-08-20 turn (「LLM が 自信満々に間違える 領域 = 単位付き算術」)
  - [[feedback-super-naming-siren-family-pattern]] (kolmogorov_complexity 命名警告)
  - [[project-step1345-benchtop-provenance-spike-2026-08-19]] (v0.5.0-alpha SafetyGate)
  - [[feedback-peace-axiom-hardware-io-extension-2026-08-17]] (Peace Axiom I/O 拡張)
  - [[feedback-one-reproduction-over-ten-unverified]] (順序原則、 内部先行 → 外部化)

**References** (60+ 年前既知、 全 教科書事項):
  - Bekenstein 1981, "Universal upper bound on the entropy-to-energy ratio for
    bounded systems", PRD 23:287
  - Landauer 1961, "Irreversibility and heat generation in the computing process",
    IBM J. Res. Dev. 5:183
  - Lloyd 2000, "Ultimate physical limits to computation", Nature 406:1047
  - Post 1921 / Rosser 1936 (k-valued logic function count formula k^(k^n))
  - Shannon 1948 (compression bound H · N)

License: benchtop-mcp v0.x = MIT (irrevocable per README)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


# ============================================================================
# Physical constants (CODATA 2018 recommended values)
# ============================================================================

_C = 299_792_458.0                    # speed of light in vacuum, m/s (exact)
_H_BAR = 1.054_571_817e-34            # reduced Planck constant, J·s
_K_B = 1.380_649e-23                  # Boltzmann constant, J/K (exact)
_LN2 = 0.693_147_180_559_945_309_4    # ln 2 (dimensionless)


# ============================================================================
# 1. Bekenstein bound
# ============================================================================


def bekenstein_bound_bits(radius_m: float, energy_J: float) -> dict[str, Any]:
    """球状領域 R, E に含みうる 情報量の 上界 (bits)。

    Formula (Bekenstein 1981, PRD 23:287):

        S ≤ 2π R E / (ℏ c ln 2)  bits

    where:
        R = radius of the smallest sphere containing the system (m)
        E = total mass-energy of the system (J)
        ℏ = reduced Planck constant, c = speed of light, ln 2 = base conversion

    Args:
        radius_m: 系を含む 最小球の 半径 (meters)、 must be > 0。
        energy_J: 系の 全質量-エネルギー (Joules)、 must be > 0。 通常 mc² だが
                  熱平衡 系では 内部エネルギー 込みも可。

    Returns:
        {
          "ok": True,
          "bound_bits": <float>,          # 上界 (bits)
          "bound_nats": <float>,          # bits × ln 2 (自然対数版)
          "is_upper_bound": True,
          "assumptions": [...],           # 適用条件
          "citation": "Bekenstein 1981, PRD 23:287",
          "honest_scope": "..."
        }
        On invalid input: {"ok": False, "error": "..."}

    Honest scope:
      - 球状 (非回転) 領域 前提、 一般 covariant bound (Bousso) は別。
      - 弱い重力 regime (Schwarzschild 半径以上) で 実効的、 black hole 内部は
        Bekenstein-Hawking entropy S = A / (4 ℓ_P²) が より tight。
      - 系が 熱平衡 でない場合 は 上界の 上界 (holds but not tight)。
    """
    if not isinstance(radius_m, (int, float)) or radius_m <= 0:
        return {"ok": False, "error": f"radius_m must be positive number, got {radius_m!r}"}
    if not isinstance(energy_J, (int, float)) or energy_J <= 0:
        return {"ok": False, "error": f"energy_J must be positive number, got {energy_J!r}"}

    # S_max (nats) = 2π R E / (ℏ c)
    bound_nats = (2.0 * math.pi * float(radius_m) * float(energy_J)) / (_H_BAR * _C)
    bound_bits = bound_nats / _LN2

    return {
        "ok": True,
        "bound_bits": bound_bits,
        "bound_nats": bound_nats,
        "is_upper_bound": True,
        "inputs": {"radius_m": float(radius_m), "energy_J": float(energy_J)},
        "assumptions": [
            "spherical (non-rotating) region",
            "weak-gravity regime (system radius > Schwarzschild radius 2GM/c²)",
            "thermal equilibrium (bound is looser but still holds otherwise)",
        ],
        "citation": "Bekenstein 1981, PRD 23:287",
        "honest_scope": (
            "Upper bound only. Covariant Bousso bound (1999) is more general. "
            "Inside a black hole, Bekenstein-Hawking S = A / (4 ℓ_P²) is tighter."
        ),
    }


# ============================================================================
# 2. Landauer minimum energy
# ============================================================================


def landauer_min_energy_j(
    bits: float,
    temperature_K: float = 300.0,
) -> dict[str, Any]:
    """N bit を 不可逆的に 消去する 最小エネルギー (Joules)、 温度 T で。

    Formula (Landauer 1961, IBM J. Res. Dev. 5:183):

        E_min = N × k_B × T × ln 2   Joules

    where:
        N = number of bits erased (irreversible operation)
        k_B = 1.380649 × 10⁻²³ J/K (Boltzmann constant)
        T = environment temperature (K)
        ln 2 = base-2 → base-e conversion

    Args:
        bits: 消去される bit 数 (float allowed for partial-erasure amortization)。
              must be >= 0。
        temperature_K: 環境温度 (Kelvin)、 default 300 K (room temperature)。

    Returns:
        {
          "ok": True,
          "min_energy_J": <float>,        # 最小 E (Joules)
          "min_energy_eV": <float>,       # 参考値 (electron-volts)
          "min_energy_kT_ln2": <float>,   # N kT ln 2 の 無次元表現 (= bits)
          "is_lower_bound": True,         # ★ これは 下限 (逆に 実現の最小)
          "assumptions": [...],
          "citation": "Landauer 1961, IBM J. Res. Dev. 5:183",
          "honest_scope": "..."
        }

    Honest scope:
      - **Irreversible operation (bit erase) の 熱力学的下限**。 Reversible
        computation は E=0 下限 の 別 regime = 本 tool の scope 外 (Bennett 1973)。
      - T=300 K で 1 bit erase = 2.87 × 10⁻²¹ J ≈ 0.018 eV (実 CMOS の 10⁹〜10¹²
        倍 上、 現実の semiconductor は Landauer limit よりはるか上で動作)。
      - Multiple simultaneous erasures では correlation を 考慮すれば tighter
        (Sagawa-Ueda 2010、 本 tool は independent-erasure 前提)。
    """
    if not isinstance(bits, (int, float)) or bits < 0:
        return {"ok": False, "error": f"bits must be non-negative number, got {bits!r}"}
    if not isinstance(temperature_K, (int, float)) or temperature_K <= 0:
        return {"ok": False, "error": f"temperature_K must be positive, got {temperature_K!r}"}

    e_min = float(bits) * _K_B * float(temperature_K) * _LN2

    return {
        "ok": True,
        "min_energy_J": e_min,
        "min_energy_eV": e_min / 1.602_176_634e-19,
        "min_energy_kT_ln2": float(bits),  # dimensionless equivalent
        "is_lower_bound": True,
        "inputs": {"bits": float(bits), "temperature_K": float(temperature_K)},
        "assumptions": [
            "irreversible operation (bit erasure), not reversible computation",
            "independent erasures (no correlation savings)",
            "environment at thermal equilibrium at temperature_K",
        ],
        "citation": "Landauer 1961, IBM J. Res. Dev. 5:183",
        "honest_scope": (
            "Lower bound for irreversible erasure only. Reversible computation "
            "(Bennett 1973) has E=0 lower bound and is out of scope. Real CMOS "
            "operates 10⁹-10¹² × above Landauer limit."
        ),
    }


# ============================================================================
# 3. Lloyd ultimate computation ceiling
# ============================================================================


def lloyd_computation_ceiling(mass_kg: float) -> dict[str, Any]:
    """質量 m の 系が 単位時間あたりに 実行可能な 演算数の 究極的上限 (ops/s)。

    Formula (Lloyd 2000, Nature 406:1047, "Ultimate physical limits to computation"):

        rate_max = 2 E / (π ℏ)   with E = m c²   (Margolus-Levitin theorem)
                 = 2 m c² / (π ℏ)   ops/s

    where "operation" means an orthogonal state transition in Hilbert space
    (Margolus-Levitin 1998 lower bound on time per elementary op = π ℏ / (2 E))。

    Args:
        mass_kg: 系の 静止質量 (kilograms)、 must be > 0。 例: 1 kg で
                 Lloyd's "ultimate laptop" thought experiment。

    Returns:
        {
          "ok": True,
          "ops_per_second_ceiling": <float>,      # 上限 ops/s
          "energy_J": <float>,                    # E = m c²
          "min_op_time_s": <float>,               # π ℏ / (2 E)
          "is_upper_bound": True,
          "assumptions": [...],
          "citation": "Lloyd 2000, Nature 406:1047",
          "honest_scope": "..."
        }

    Honest scope:
      - 究極的物理限界 (thermodynamic + relativistic 全 energy を 計算に 完全変換の
        thought experiment)、 実 device 実装は 10⁴⁰+ 倍 下で 動作。
      - Storage capacity は別 limit (Bekenstein bound を 使う)、 本 tool は rate のみ。
      - Serial vs parallel: 上限は 並列度を 上げても 総 rate は変わらない
        (energy が制約)、 単 CPU 換算値ではない。
      - "operation" 定義 = orthogonal state transition (Margolus-Levitin 1998)、
        実 FLOPS などの 応用 metric とは 直接比較不能。
    """
    if not isinstance(mass_kg, (int, float)) or mass_kg <= 0:
        return {"ok": False, "error": f"mass_kg must be positive number, got {mass_kg!r}"}

    energy_J = float(mass_kg) * _C * _C
    rate_max = 2.0 * energy_J / (math.pi * _H_BAR)
    min_op_time = 1.0 / rate_max

    return {
        "ok": True,
        "ops_per_second_ceiling": rate_max,
        "energy_J": energy_J,
        "min_op_time_s": min_op_time,
        "is_upper_bound": True,
        "inputs": {"mass_kg": float(mass_kg)},
        "assumptions": [
            "all rest-mass energy converted to computation (thought-experiment limit)",
            "operation = orthogonal Hilbert-space state transition (Margolus-Levitin)",
            "no consideration of storage capacity (see Bekenstein bound tool)",
        ],
        "citation": "Lloyd 2000, Nature 406:1047",
        "honest_scope": (
            "Ultimate thought-experiment limit. Real devices operate 10⁴⁰+ × below. "
            "Not comparable to FLOPS. Serial vs parallel: total rate is invariant "
            "(energy-constrained)."
        ),
    }


# ============================================================================
# 4. k-valued n-variable operator space
# ============================================================================


def operator_space_size(k: int, n: int) -> dict[str, Any]:
    """k 値 n 変数 演算子の 総数 = k^(k^n)、 及び 実装 metric。

    Formula:
        input_configurations = k^n
        total_functions      = k^(k^n)      (each input → one of k outputs)

    For D-FUMT₈ (k=8):
        n=1: 8^8 = 16,777,216 (1-var)
        n=2: 8^64 ≈ 6.28 × 10⁵⁷ (2-var、 truth table 64 entries)
        n=3: 8^512 ≈ 10⁴⁶² (完全 enumeration 不可能領域)

    Args:
        k: 論理値 の 数 (2=Boolean, 3=Kleene/Belnap-3, 4=Belnap-FDE, 8=D-FUMT₈)。
           must be int >= 2。
        n: 変数の 数、 must be int >= 0。

    Returns:
        {
          "ok": True,
          "input_configurations": <int>,          # k^n
          "total_functions_log10": <float>,       # log10(k^(k^n)) = (k^n) log10(k)
          "total_functions_str": "<str>",         # "10^X" 表記 (exact int は overflow risk)
          "config_bits": <int>,                   # bits to enumerate all functions
          "lut_k_entries": <int>,                 # k^n entry LUT for k-valued output
          "enumeration_seconds_1ns": <float>,     # 1 ns/function 想定の 列挙時間
          "is_theoretical_max": True,             # BDD/shared-subexpression 圧縮前
          "assumptions": [...],
          "citation": "Post 1921 / Rosser 1936 (k-valued logic function count)",
          "honest_scope": "..."
        }

    Honest scope:
      - **理論上限**、 実 FPGA 合成では BDD 圧縮 + shared subexpression で 実効
        config bits は 大幅減 (STEP 1011 D-FUMT₈ ALU が Tang Nano 9K で 37 LUT4
        しか 消費しなかった 実測 evidence)。
      - LUT metric は k^n entry × log2(k) bits/entry (D-FUMT₈ で 3 bits/entry)、
        FPGA 側 LUT6 との 差異は 別 mapping 問題。
      - enumeration_seconds は 1 ns/function 想定、 GPU 並列でも n=3 (8^512)
        は 現物理的に 到達不能 (Lloyd bound 参照)。
    """
    if not isinstance(k, int) or k < 2:
        return {"ok": False, "error": f"k must be int >= 2, got {k!r}"}
    if not isinstance(n, int) or n < 0:
        return {"ok": False, "error": f"n must be int >= 0, got {n!r}"}

    input_configs = k ** n
    # total_functions = k^input_configs — massive int, use log for display
    total_log10 = float(input_configs) * math.log10(k)
    # config_bits = ceil(log2(k^input_configs)) = input_configs × log2(k)
    config_bits = int(math.ceil(input_configs * math.log2(k)))
    lut_entries = input_configs

    # 列挙時間 (1 ns/function 想定)
    # total_functions = 10 ** total_log10、 1e-9 sec/each
    if total_log10 < 300:
        enum_seconds = (10.0 ** total_log10) * 1e-9
    else:
        enum_seconds = float("inf")  # overflow, physically unreachable anyway

    return {
        "ok": True,
        "input_configurations": input_configs,
        "total_functions_log10": total_log10,
        "total_functions_str": f"10^{total_log10:.4f}",
        "config_bits": config_bits,
        "lut_k_entries": lut_entries,
        "enumeration_seconds_1ns": enum_seconds,
        "is_theoretical_max": True,
        "inputs": {"k": k, "n": n},
        "assumptions": [
            "counts every distinct function (no equivalence reduction)",
            "BDD / shared-subexpression compression not applied",
            "1 ns/function baseline for enumeration_seconds (GPU parallel not modeled)",
        ],
        "citation": "Post 1921 / Rosser 1936 (k-valued logic function count formula k^(k^n))",
        "honest_scope": (
            "Theoretical maximum. Real FPGA synthesis compresses via BDD + "
            "shared subexpressions (STEP 1011 D-FUMT₈ ALU: 37 LUT4 on Tang Nano 9K "
            "for k=8, n=2 operator, empirical evidence). enumeration_seconds "
            "reaches infinity for n≥3 (Lloyd ceiling exceeded)."
        ),
    }


# ============================================================================
# 5. Compression length upper bound (Shannon-based, K uncomputable disclaimer)
# ============================================================================


def compression_upper_bound(
    length: int,
    entropy_bits_per_symbol: float = 1.0,
    method: str = "shannon",
) -> dict[str, Any]:
    """長さ N の source の 圧縮後長の 上界 (bits)、 Shannon entropy ベース。

    Formula (Shannon 1948 source coding theorem):

        L_compressed ≥ N × H   bits    (下限、 asymptotic)
        L_compressed ≈ N × H + O(log N)  bits (upper bound with overhead)

    where H = entropy_bits_per_symbol = Σ p_i log2(1/p_i)。

    Args:
        length: source symbol 数 N、 must be int >= 0。
        entropy_bits_per_symbol: H (Shannon entropy per symbol)、 must be in [0,
            log2(alphabet_size)]。 default 1.0 (binary uniform)。
        method: "shannon" (default, N·H + overhead) / "typical_set" (asymptotic
            equipartition) / "arithmetic" (arithmetic coding practical bound)。

    Returns:
        {
          "ok": True,
          "shannon_lower_bound_bits": <float>,    # N × H (下限)
          "practical_upper_bound_bits": <float>,  # N × H + O(log N) 上界
          "compression_ratio_min": <float>,       # H / log2(alphabet_size) 下限
          "is_upper_bound": True,
          "kolmogorov_note": "K(x) is Turing-uncomputable...",
          "assumptions": [...],
          "citation": "Shannon 1948",
          "honest_scope": "..."
        }

    Honest scope (★ CRITICAL — siren-family pattern):
      - **Kolmogorov complexity K(x) は Turing-uncomputable**。 本 tool は Shannon
        entropy H (statistical) に 基づく 圧縮長上界のみ 返し、 K(x) の 実現値
        (algorithmic incompressibility) では ない。
      - K(x) ≤ H(source) × N + O(log N) は 常に 成立 (K は universal な 意味で
        より tight)、 但し K を 直接返す tool は 原理的に 作成不可 = 本 tool は
        「上界の一つ」 の位置付け。
      - method "typical_set" は AEP-based asymptotic、 finite N では overhead 大。
      - source が IID stationary Gaussian でない場合、 H の 定義自体が context 依存。
    """
    if not isinstance(length, int) or length < 0:
        return {"ok": False, "error": f"length must be int >= 0, got {length!r}"}
    if not isinstance(entropy_bits_per_symbol, (int, float)) or entropy_bits_per_symbol < 0:
        return {
            "ok": False,
            "error": f"entropy_bits_per_symbol must be >= 0, got {entropy_bits_per_symbol!r}",
        }
    if method not in ("shannon", "typical_set", "arithmetic"):
        return {
            "ok": False,
            "error": f"method must be 'shannon' | 'typical_set' | 'arithmetic', got {method!r}",
        }

    H = float(entropy_bits_per_symbol)
    N = int(length)
    lower = N * H

    # overhead depends on method
    if method == "shannon":
        overhead = math.ceil(math.log2(N + 1)) if N > 0 else 0
    elif method == "typical_set":
        # AEP-based overhead: O(sqrt(N log N)) for typical set encoding
        overhead = math.ceil(math.sqrt(max(N, 1) * math.log2(max(N, 2))))
    else:  # arithmetic
        # arithmetic coding: ~2 bits overhead
        overhead = 2.0

    upper = lower + overhead

    # compression ratio (H / max_H); assume alphabet_size = 2^ceil(H) minimally
    if H > 0:
        alphabet_bits = max(1.0, math.ceil(H))
        ratio_min = H / alphabet_bits
    else:
        ratio_min = 0.0

    return {
        "ok": True,
        "shannon_lower_bound_bits": lower,
        "practical_upper_bound_bits": upper,
        "compression_ratio_min": ratio_min,
        "is_upper_bound": True,
        "kolmogorov_note": (
            "K(x) is Turing-uncomputable (Chaitin 1975). This tool returns "
            "Shannon-entropy-based statistical upper bound, NOT K(x)."
        ),
        "inputs": {
            "length": N,
            "entropy_bits_per_symbol": H,
            "method": method,
        },
        "assumptions": [
            "source is IID (independent identically distributed) with entropy H",
            f"method '{method}' overhead model applied",
        ],
        "citation": "Shannon 1948, Bell System Technical Journal 27:379",
        "honest_scope": (
            "Kolmogorov complexity K(x) is uncomputable — this tool returns Shannon "
            "statistical upper bound only. K(x) ≤ N·H + O(log N) always holds "
            "(K is tighter in the universal sense) but K itself cannot be a tool."
        ),
    }


# ============================================================================
# Self-test (module-level, runs when invoked directly)
# ============================================================================


def _selftest() -> int:
    """Return 0 on all-pass, non-zero on any failure。"""
    passed = 0
    failed = 0

    def _check(label: str, cond: bool, detail: str = "") -> None:
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"  [PASS] {label}")
        else:
            failed += 1
            print(f"  [FAIL] {label}  {detail}")

    print("=" * 70)
    print("benchtop_physics_limits selftest")
    print("=" * 70)

    # ---- 1. Bekenstein ----
    print("\n[1] bekenstein_bound_bits")
    r = bekenstein_bound_bits(1.0, 1.0)  # 1 m, 1 J
    _check("ok true", r["ok"])
    _check("is_upper_bound flag", r["is_upper_bound"] is True)
    # Expected: 2π × 1 × 1 / (ℏ c ln 2) = 6.283 / (1.055e-34 × 3e8 × 0.693) ≈ 2.87e26 bits
    _check(
        f"bound_bits ~2.87e26 (got {r['bound_bits']:.3e})",
        2.8e26 < r["bound_bits"] < 2.95e26,
    )
    _check("invalid radius rejected", bekenstein_bound_bits(-1, 1)["ok"] is False)
    _check("invalid energy rejected", bekenstein_bound_bits(1, 0)["ok"] is False)

    # ---- 2. Landauer ----
    print("\n[2] landauer_min_energy_j")
    r = landauer_min_energy_j(1, 300.0)  # 1 bit at 300 K
    _check("ok true", r["ok"])
    _check("is_lower_bound flag", r["is_lower_bound"] is True)
    # Expected: k_B × 300 × ln 2 ≈ 2.87e-21 J
    _check(
        f"min_energy_J ~2.87e-21 (got {r['min_energy_J']:.3e})",
        2.8e-21 < r["min_energy_J"] < 2.95e-21,
    )
    _check(
        f"min_energy_eV ~0.018 (got {r['min_energy_eV']:.4f})",
        0.017 < r["min_energy_eV"] < 0.019,
    )
    _check("zero bits → zero energy", landauer_min_energy_j(0, 300)["min_energy_J"] == 0.0)
    _check("invalid T rejected", landauer_min_energy_j(1, -1)["ok"] is False)

    # ---- 3. Lloyd ----
    print("\n[3] lloyd_computation_ceiling")
    r = lloyd_computation_ceiling(1.0)  # 1 kg
    _check("ok true", r["ok"])
    _check("is_upper_bound flag", r["is_upper_bound"] is True)
    # Expected: 2 × (1 × c²) / (π × ℏ) ≈ 5.43e50 ops/s (Lloyd's original 1 kg laptop = 5.4258e50)
    _check(
        f"ops ~5.4e50 (got {r['ops_per_second_ceiling']:.3e})",
        5.3e50 < r["ops_per_second_ceiling"] < 5.5e50,
    )
    _check("invalid mass rejected", lloyd_computation_ceiling(0)["ok"] is False)

    # ---- 4. operator_space_size ----
    print("\n[4] operator_space_size")
    r = operator_space_size(2, 1)  # Boolean 1-var
    _check("ok true (k=2, n=1)", r["ok"])
    _check(
        f"2^(2^1) = 2^2 = 4 functions (log10={r['total_functions_log10']:.6f})",
        r["input_configurations"] == 2
        and abs(r["total_functions_log10"] - math.log10(4)) < 1e-9,
    )
    r = operator_space_size(8, 1)  # D-FUMT₈ 1-var
    _check(f"8^(8^1) = 8^8 = 16.78M (log10={r['total_functions_log10']:.4f})",
           abs(r["total_functions_log10"] - math.log10(16_777_216)) < 1e-6)
    r = operator_space_size(8, 2)  # D-FUMT₈ 2-var
    _check(f"8^64 log10 ~57.8 (got {r['total_functions_log10']:.4f})",
           57.7 < r["total_functions_log10"] < 57.9)
    _check("k=1 rejected", operator_space_size(1, 2)["ok"] is False)
    _check("negative n rejected", operator_space_size(8, -1)["ok"] is False)

    # ---- 5. compression_upper_bound ----
    print("\n[5] compression_upper_bound")
    r = compression_upper_bound(1000, 1.0, "shannon")  # 1000 uniform bits
    _check("ok true", r["ok"])
    _check("kolmogorov_note present", "uncomputable" in r["kolmogorov_note"])
    _check(f"lower ~1000 (got {r['shannon_lower_bound_bits']})", r["shannon_lower_bound_bits"] == 1000.0)
    _check(f"upper ~1010 (got {r['practical_upper_bound_bits']})",
           1000 < r["practical_upper_bound_bits"] < 1020)
    r = compression_upper_bound(1000, 0.5, "arithmetic")
    _check("arithmetic overhead ~2", abs(r["practical_upper_bound_bits"] - 502) < 1)
    _check("invalid method rejected", compression_upper_bound(100, 1, "gzip")["ok"] is False)
    _check("negative length rejected", compression_upper_bound(-1, 1, "shannon")["ok"] is False)

    print()
    print("=" * 70)
    print(f"benchtop_physics_limits selftest : {passed} passed, {failed} failed")
    print("=" * 70)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(_selftest())
