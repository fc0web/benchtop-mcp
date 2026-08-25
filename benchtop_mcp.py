#!/usr/bin/env python3
"""
benchtop-mcp : 計測ベンチ MCP サーバー

AI エージェント（Claude など）に対して、以下の「できること」を追加します。

  1. 装置操作   : シリアル接続された回路・装置にコマンドを送り、応答を読む
  2. 業務自動化 : 一定間隔で N 回サンプリングし、セッションとして記録する
  3. データ処理 : 記録を統計解析し、CSV に書き出す

設計方針
  - コアロジック（Bench クラス）と MCP 層（@server.tool）を分離している。
    → コアだけを単体テストできる。MCP に依存しない形で再利用もできる。
  - 実機がなくても動くモック装置を内蔵している（port="mock"）。
    → ハードが手元に無い状態でも開発・テスト・デモができる。
  - 依存を最小に保つ。標準ライブラリのみで動作し、pyserial は
    実機を使うときだけ必要（無ければモックのみ利用可能）。

ライセンス: 未定（README の「ライセンスの決め方」を参照してから決めること）
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import statistics
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# pyserial は実機を使うときだけ必要。無ければモック専用モードで動く。
try:
    import serial  # type: ignore
    import serial.tools.list_ports  # type: ignore

    HAS_SERIAL = True
except ImportError:  # pragma: no cover
    HAS_SERIAL = False


# ---------------------------------------------------------------------------
# 保存先
# ---------------------------------------------------------------------------

DATA_DIR = Path(os.environ.get("BENCHTOP_DATA_DIR", Path.home() / ".benchtop-mcp"))
MOCK_PORT = "mock"

# v0.2: plot_session 用スパークライン文字 (8 段階、空白は使わない)
_SPARK_CHARS = "▁▂▃▄▅▆▇█"

# v0.2.4: date-only 検出用 (YYYY-MM-DD、T なし)
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    _HAS_ZONEINFO = True
except ImportError:  # pragma: no cover
    _HAS_ZONEINFO = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _resolve_tz() -> tuple[Any, str]:
    """BENCHTOP_TZ env が指定されていればそれを、無ければ system local を返す。
    戻り値は (tzinfo, name) タプル。zoneinfo が使えない環境や tz name 解決失敗時は
    system local に fallback (name='local')。
    """
    tz_name = os.environ.get("BENCHTOP_TZ", "").strip()
    if tz_name and _HAS_ZONEINFO:
        try:
            return ZoneInfo(tz_name), tz_name
        except Exception:
            pass  # 無効 tz name は fallback
    local = datetime.now().astimezone().tzinfo
    return local, "local"


def _to_local_iso(utc_iso: str | None) -> str | None:
    """UTC ISO 文字列 (started_at 由来) を local ISO 文字列に換算。
    v0.2.4 副 fix: 各 tool の return dict に補助 field として併記するため。
    主 fix (date-only local 解釈) と 独立に働く。
    """
    if not utc_iso:
        return None
    try:
        dt = datetime.fromisoformat(utc_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        tz, _ = _resolve_tz()
        return dt.astimezone(tz).isoformat(timespec="seconds")
    except Exception:
        return None


def _resolve_date_boundary(
    s: str | None, is_since: bool
) -> tuple[str | None, dict[str, Any]]:
    """search_sessions の since/until を解決する。

    v0.2.4 主 fix (藤本さん 2026-08-13 verify で 発火):
      - 日付のみ文字列 (YYYY-MM-DD、時刻部分なし) は **local midnight** として
        解釈し、UTC に換算して返す。since は当日 00:00 local、until は当日
        23:59:59.999999 local (day-end inclusive)。
      - 完全 ISO (T + 時刻 [+ offset]) はそのまま返す (従来通り厳密比較)。
      - 換算失敗時は元文字列にfallback (data 破壊しない)。

    Returns:
        (resolved_utc_iso_or_original, meta_dict) の tuple。
        meta_dict は {input, date_only, resolved_utc, tz_used}。
    """
    meta: dict[str, Any] = {
        "input": s,
        "date_only": False,
        "resolved_utc": s,
        "tz_used": None,
    }
    if s is None:
        return None, meta
    s = s.strip()
    if not s:
        return s, meta
    if not _DATE_ONLY_RE.match(s):
        # 完全 ISO or 未認識形式 → そのまま比較 (従来動作)
        return s, meta
    # 日付のみ path
    try:
        tz, tz_name = _resolve_tz()
        y, m, day = int(s[0:4]), int(s[5:7]), int(s[8:10])
        if is_since:
            local_dt = datetime(y, m, day, 0, 0, 0, 0, tzinfo=tz)
        else:
            local_dt = datetime(y, m, day, 23, 59, 59, 999999, tzinfo=tz)
        utc_iso = local_dt.astimezone(timezone.utc).isoformat()
        meta["date_only"] = True
        meta["resolved_utc"] = utc_iso
        meta["tz_used"] = tz_name
        return utc_iso, meta
    except Exception:
        return s, meta


# ---------------------------------------------------------------------------
# 装置の抽象化
#   実機（SerialDevice）とモック（MockDevice）を同じ形で扱えるようにする。
#   これがあるおかげで、上位のロジックは実機かモックかを気にしなくてよい。
# ---------------------------------------------------------------------------


class Device:
    """装置の共通インターフェース。"""

    def send(self, command: str) -> str:
        raise NotImplementedError

    def read_line(self) -> str:
        raise NotImplementedError

    def close(self) -> None:
        pass


class MockDevice(Device):
    """
    実機の代わりに、それらしい測定値を吐く仮想装置。

    温度・湿度・電圧の3チャンネルを模擬する。ゆっくりしたドリフトと
    ランダムなノイズを持ち、まれに外れ値を出す（解析機能の動作確認用）。
    """

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)
        self._t0 = time.time()
        self._commands: list[str] = []

    def send(self, command: str) -> str:
        self._commands.append(command)
        cmd = command.strip().upper()
        if cmd in ("*IDN?", "ID?", "ID"):
            return "MOCK,BENCHTOP-SIM,0001,1.0.0"
        if cmd in ("READ?", "MEAS?", "READ"):
            return self.read_line()
        return f"OK ({command.strip()})"

    def read_line(self) -> str:
        elapsed = time.time() - self._t0
        drift = math.sin(elapsed / 30.0) * 0.8          # ゆっくりした変動
        temp = 25.0 + drift + self._rng.gauss(0, 0.05)
        humid = 48.0 - drift * 2 + self._rng.gauss(0, 0.3)
        volt = 3.300 + self._rng.gauss(0, 0.004)
        if self._rng.random() < 0.03:                    # 3% の確率で外れ値
            temp += self._rng.choice([-1, 1]) * self._rng.uniform(2.0, 4.0)
        return f"T={temp:.3f},H={humid:.2f},V={volt:.4f}"


class SerialDevice(Device):
    """pyserial でシリアルポートに接続する実機用のクラス。"""

    def __init__(self, port: str, baudrate: int = 9600, timeout: float = 2.0) -> None:
        if not HAS_SERIAL:
            raise RuntimeError(
                "実機に接続するには pyserial が必要です: pip install pyserial"
            )
        self._ser = serial.Serial(port, baudrate=baudrate, timeout=timeout)
        time.sleep(2.0)  # Arduino 系は開いた直後にリセットが走るため待つ

    def send(self, command: str) -> str:
        if not command.endswith("\n"):
            command += "\n"
        self._ser.reset_input_buffer()
        self._ser.write(command.encode())
        self._ser.flush()
        return self.read_line()

    def read_line(self) -> str:
        return self._ser.readline().decode(errors="replace").strip()

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 測定行のパース
#   装置ごとに出力形式がばらばらなので、よくある3形式を受け付ける。
#     "T=25.3,H=48.1"   -> {"T": 25.3, "H": 48.1}
#     "25.3,48.1"       -> {"ch1": 25.3, "ch2": 48.1}
#     "25.3"            -> {"value": 25.3}
# ---------------------------------------------------------------------------

_KV = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*[=:]\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)")


def parse_line(line: str) -> dict[str, float]:
    line = line.strip()
    if not line:
        return {}

    kv = _KV.findall(line)
    if kv:
        return {k: float(v) for k, v in kv}

    parts = [p.strip() for p in re.split(r"[,\t; ]+", line) if p.strip()]
    values: dict[str, float] = {}
    for i, p in enumerate(parts, start=1):
        try:
            values[f"ch{i}" if len(parts) > 1 else "value"] = float(p)
        except ValueError:
            return {}
    return values


# ---------------------------------------------------------------------------
# セッション（1回の計測のまとまり）
# ---------------------------------------------------------------------------


def _parse_ts(value: Any) -> float | None:
    """ISO8601 文字列 / epoch 数値 のどちらでも epoch 秒 (float) に正規化する。
    解釈できない場合は None (呼び出し側で 「不明」 として扱うこと)。
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        try:
            return float(text)
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _session_duration_s(session: "Session") -> float | None:
    """session の経過秒を返す。't' 不在でも KeyError にしない。

    native capture (measure) の row は相対秒 `t` を持つが、v0.5.0-alpha の
    import_external_session 由来の row は絶対時刻 `ts` しか持たない。
    旧実装は `rows[-1]["t"]` を無条件参照していたため、import 由来 session を
    analyze / compare_sessions / regression_check に渡すと KeyError: 't' で
    落ちていた (2026-08-22 観測、2026-08-25 特定)。

    優先順: `t` があればそれ、無ければ `ts` の差分から復元、どちらも無ければ
    None ("計測不能" であって 0.0 ではない)。
    """
    if not session.rows:
        return 0.0
    last = session.rows[-1]
    if "t" in last:
        try:
            return round(float(last["t"]), 3)
        except (TypeError, ValueError):
            pass
    t0 = _parse_ts(session.rows[0].get("ts"))
    t1 = _parse_ts(last.get("ts"))
    if t0 is not None and t1 is not None:
        return round(t1 - t0, 3)
    return None


@dataclass
class Session:
    id: str
    port: str
    started_at: str
    note: str = ""
    channels: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    skipped: int = 0
    # v0.2.1: 途中失敗 (KeyboardInterrupt / SerialException / 装置切断等) 時に
    # 部分結果を保存するためのフィールド。正常完了時は None のまま。
    # 旧 (v0.1/v0.2.0) JSON にはこのキーが無いが、default=None なので
    # Session(**old_dict) は成功する (backward compatible)。
    aborted_at: str | None = None
    abort_reason: str | None = None
    # v0.4.0: 実験ノート (experiment notebook) fields。 全 optional、 旧 JSON も
    # 読める (default None、 空 dict は明示 empty)。 「3ヶ月前の 同じ条件と 比べて」
    # を可能にするため 条件・被測定物・環境・装置設定を session に永続化。
    # rei-aios の mystery / theory に ID linking も 保存。
    subject: str | None = None
    """被測定物の 識別子 (例: 'Arduino Uno #17', '抵抗器 R47', 'ProductX serial 001')。
    同じ subject の 過去 session と 比較すると 個体の 経年劣化 追跡可能。"""
    environment: dict[str, Any] | None = None
    """環境条件 dict (自由 schema)。 例: {'temp_c': 25.3, 'humidity': 48.1, 'altitude_m': 15}。
    後で 同条件 session を find_similar_sessions で 検索可能。"""
    instrument_config: dict[str, Any] | None = None
    """装置設定 dict (自由 schema)。 例: {'baudrate': 9600, 'sampling_hz': 10,
    'calibration_ref': 'NIST-cert-2026-08-01'}。 校正記録 chain の 一部。"""
    mystery_id: str | None = None
    """rei-aios の mystery / theory への link ID。 rei-aios MCP の register_mystery で
    生成される ID を 保存すると、 計測結果が 理論に自動で 積み上がる (chat-Claude
    2026-08-17 「証拠が理論に自動で積み上がる」 提案 の 実現)。"""
    # v0.5.0-alpha (SPIKE): 測定記録の origin identifier。 'benchtop' は 従来 measure() 由来
    # (default 維持で 全 backward compat)、 'external:rigol-mcp' 等 は import_external_session
    # 経由 の 他 MCP server 由来。 chat-Claude 2026-08-18 report §3-1 「機器層/記録層 分割」
    # + 4 agent verify 2026-08-19 の 実装。 藤本さん judgment 待ち で 本 field は spike only。
    source: str = "benchtop"

    def path(self) -> Path:
        return DATA_DIR / f"{self.id}.json"

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.path().write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )


def load_session(session_id: str) -> Session:
    """Load session from disk. Ignores unknown JSON keys for forward compatibility
    (v0.5+ で 新 field 追加された JSON も 旧 code で read できる)。"""
    p = DATA_DIR / f"{session_id}.json"
    if not p.exists():
        raise FileNotFoundError(f"セッションが見つかりません: {session_id}")
    raw = json.loads(p.read_text(encoding="utf-8"))
    # 未知 key を除外 (forward compat)、 __dataclass_fields__ にある key のみ残す
    known_fields = set(Session.__dataclass_fields__.keys())
    filtered = {k: v for k, v in raw.items() if k in known_fields}
    return Session(**filtered)


def _resolve_sid(sid: str, session_id: str) -> str | dict[str, Any]:
    """`sid` / `session_id` のどちらで渡されても セッション ID を取り出す。

    2026-08-25: remote-devices MCP proxy 経由で呼ぶと、`session_id` という名前の
    top-level 引数が proxy 自身の session routing field と衝突して **無音で剥がされ**、
    サーバ側には届かない (同じ呼び出しの `width` は届いていた、で切り分け済み)。
    根本原因は proxy 側だが別 repo・別スコープなので、こちらは正名を `sid` に移し、
    `session_id` を別名として残す (直結 Claude Desktop の既存呼び出しは無変更で動く)。

    どちらも空なら structured error dict を返す (例外は投げない = 既存 contract 維持)。
    """
    target = (sid or session_id or "").strip()
    if not target:
        return {
            "ok": False,
            "error": "session ID is required — pass it as 'sid' (preferred) or 'session_id'",
            "hint": "list_sessions() で ID を確認してください",
        }
    return target


def _load_session_or_error(session_id: str) -> Session | dict[str, Any]:
    """MCP tool 層で使う load_session のラッパ。存在しない ID は例外ではなく
    structured error dict を返す。AI から見て tool 呼び出しが例外で落ちるより、
    「error 情報を含む dict が返る」方が自然にリトライ or 別 tool 呼び出しに繋がる。
    """
    try:
        return load_session(session_id)
    except FileNotFoundError:
        return {
            "error": "session_not_found",
            "session_id": session_id,
            "hint": "list_sessions または search_sessions で存在確認してください",
        }


# ---------------------------------------------------------------------------
# コアロジック
# ---------------------------------------------------------------------------


class Bench:
    """装置の接続を保持し、計測・解析・書き出しを行う。MCP に依存しない。"""

    def __init__(self) -> None:
        self._devices: dict[str, Device] = {}

    # -- 装置 ---------------------------------------------------------------

    def open(self, port: str, baudrate: int = 9600) -> Device:
        key = f"{port}@{baudrate}"
        if key not in self._devices:
            self._devices[key] = (
                MockDevice() if port == MOCK_PORT else SerialDevice(port, baudrate)
            )
        return self._devices[key]

    def close_all(self) -> None:
        for d in self._devices.values():
            d.close()
        self._devices.clear()

    def list_ports(self) -> list[dict[str, str]]:
        ports: list[dict[str, str]] = [
            {
                "port": MOCK_PORT,
                "description": "内蔵モック装置（実機不要・動作確認用）",
                "hwid": "-",
            }
        ]
        if HAS_SERIAL:
            for p in serial.tools.list_ports.comports():
                ports.append(
                    {"port": p.device, "description": p.description or "", "hwid": p.hwid or ""}
                )
        return ports

    def send_command(self, port: str, command: str, baudrate: int = 9600) -> str:
        return self.open(port, baudrate).send(command)

    # -- 計測 ---------------------------------------------------------------

    def measure(
        self,
        port: str = MOCK_PORT,
        samples: int = 20,
        interval_ms: int = 100,
        baudrate: int = 9600,
        command: str | None = None,
        note: str = "",
        subject: str | None = None,
        environment: dict[str, Any] | None = None,
        instrument_config: dict[str, Any] | None = None,
        mystery_id: str | None = None,
    ) -> Session:
        if samples < 1 or samples > 10000:
            raise ValueError("samples は 1〜10000 の範囲で指定してください")

        dev = self.open(port, baudrate)
        sid = datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{random.randint(100, 999)}"
        session = Session(
            id=sid, port=port, started_at=_now(), note=note,
            subject=subject, environment=environment,
            instrument_config=instrument_config, mystery_id=mystery_id,
        )

        # v0.2.1: 途中失敗を捕捉して部分結果を保存する。
        # 100 サンプルの途中 60 で失敗した場合、その 60 行と abort_reason を保存し、
        # 上位 (MCP tool 層 / AI) に partial=True で通知する。全部捨てるより、
        # 「どこで止まったか」 が残った方が実運用の失敗解析に使える。
        t_start = time.time()
        try:
            for _ in range(samples):
                raw = dev.send(command) if command else dev.read_line()
                values = parse_line(raw)
                if not values:
                    session.skipped += 1
                else:
                    for k in values:
                        if k not in session.channels:
                            session.channels.append(k)
                    session.rows.append({"t": round(time.time() - t_start, 4), **values})
                if interval_ms:
                    time.sleep(interval_ms / 1000.0)
        except KeyboardInterrupt:
            session.aborted_at = _now()
            session.abort_reason = "KeyboardInterrupt"
        except Exception as e:
            session.aborted_at = _now()
            session.abort_reason = f"{type(e).__name__}: {e}"

        session.save()
        return session

    # -- 解析 ---------------------------------------------------------------

    @staticmethod
    def analyze(session: Session) -> dict[str, Any]:
        result: dict[str, Any] = {
            "session_id": session.id,
            "port": session.port,
            "started_at": session.started_at,
            # v0.2.4 副 fix: local tz 補助
            "started_at_local": _to_local_iso(session.started_at),
            "note": session.note,
            "n_rows": len(session.rows),
            "skipped": session.skipped,
            "duration_s": _session_duration_s(session),
            "partial": session.aborted_at is not None,
            "abort_reason": session.abort_reason,
            "channels": {},
        }

        for ch in session.channels:
            xs = [r[ch] for r in session.rows if ch in r]
            if not xs:
                continue
            mean = statistics.fmean(xs)
            sd = statistics.stdev(xs) if len(xs) > 1 else 0.0
            outliers = (
                [
                    {"index": i, "value": x, "sigma": round((x - mean) / sd, 2)}
                    for i, x in enumerate(xs)
                    if abs(x - mean) > 3 * sd
                ]
                if sd > 0
                else []
            )
            result["channels"][ch] = {
                "n": len(xs),
                "mean": round(mean, 6),
                "stdev": round(sd, 6),
                "min": round(min(xs), 6),
                "max": round(max(xs), 6),
                "first": round(xs[0], 6),
                "last": round(xs[-1], 6),
                "drift": round(xs[-1] - xs[0], 6),
                "outliers": outliers[:20],
                "n_outliers": len(outliers),
            }
        return result

    # -- 書き出し -----------------------------------------------------------

    @staticmethod
    def export_csv(session: Session, out_path: str | Path) -> Path:
        out = Path(out_path).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        header = ["t"] + session.channels
        lines = [",".join(header)]
        for r in session.rows:
            lines.append(",".join(str(r.get(c, "")) for c in header))
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out

    @staticmethod
    def list_sessions(limit: int = 30) -> list[dict[str, Any]]:
        if not DATA_DIR.exists():
            return []
        out = []
        for p in sorted(DATA_DIR.glob("*.json"), reverse=True)[:limit]:
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                started = d["started_at"]
                out.append(
                    {
                        "session_id": d["id"],
                        "port": d["port"],
                        "started_at": started,
                        # v0.2.4 副 fix: local tz 補助表示 (system local or BENCHTOP_TZ)
                        "started_at_local": _to_local_iso(started),
                        "n_rows": len(d.get("rows", [])),
                        "channels": d.get("channels", []),
                        "note": d.get("note", ""),
                        # v0.2.2: partial 情報を search/list 結果に mirror。
                        # 旧 JSON (aborted_at key 不在) は None → false。
                        "partial": d.get("aborted_at") is not None,
                        "abort_reason": d.get("abort_reason"),
                    }
                )
            except Exception:
                continue
        return out

    # -- v0.2 追加: 視覚化 / 比較 / 検索 --------------------------------------

    @staticmethod
    def plot(session: Session, width: int = 60) -> dict[str, Any]:
        """各チャンネルを Unicode ブロック文字 (▁▂▃▄▅▆▇█) の 8 段階で
        描画する。サンプル数が width より多いときは平均でビン化する。
        matplotlib 等の依存を増やさず、Excel を開かずに傾向・外れ値の位置を
        ざっくり把握するための最小道具。

        v0.2.2: legend が必要なので per-channel dict に `label`、top-level に
        `channels_order` (render 順の contract) を明示。中断 session の場合は
        `partial` + `abort_reason` も top-level に出す。
        """
        rendered_order: list[str] = []
        result: dict[str, Any] = {
            "session_id": session.id,
            "port": session.port,
            "started_at": session.started_at,
            # v0.2.4 副 fix: local tz 補助
            "started_at_local": _to_local_iso(session.started_at),
            "width": width,
            "n_rows": len(session.rows),
            "partial": session.aborted_at is not None,
            "abort_reason": session.abort_reason,
            "channels_order": rendered_order,
            "channels": {},
        }
        for ch in session.channels:
            xs = [r[ch] for r in session.rows if ch in r]
            if not xs:
                continue
            lo, hi = min(xs), max(xs)
            span = hi - lo if hi > lo else 1.0
            if len(xs) > width and width > 0:
                bin_size = len(xs) / width
                display = []
                for i in range(width):
                    a = int(i * bin_size)
                    b = int((i + 1) * bin_size)
                    chunk = xs[a:b] if b > a else [xs[a]]
                    display.append(sum(chunk) / len(chunk))
            else:
                display = xs
            spark = "".join(
                _SPARK_CHARS[min(7, max(0, int((v - lo) / span * 7.99)))]
                for v in display
            )
            mean = sum(xs) / len(xs)
            result["channels"][ch] = {
                "label": ch,
                "sparkline": spark,
                "n": len(xs),
                "min": round(lo, 6),
                "max": round(hi, 6),
                "mean": round(mean, 6),
                "range": round(hi - lo, 6),
            }
            rendered_order.append(ch)
        return result

    @staticmethod
    def compare(sa: Session, sb: Session, z_threshold: float = 3.0) -> dict[str, Any]:
        """2 セッションをチャンネル単位で比較する。共通チャンネルについて
        mean・stdev・drift の差分と、Welch 型の t 統計量 (z として扱う) を返す。

        使う式は 1 本だけ:

            z = (mean_A - mean_B) / sqrt(σ_A²/n_A + σ_B²/n_B)

        これは **Welch's t 検定の統計量そのもの**である。異なるのは判定則で
        あって統計量ではない:
          - Welch's t-test: t 分布の critical value (自由度依存) で判定 → p 値
          - この tool: 固定閾値 `z_threshold` (既定 3.0) で単純 gate

        `welch_df` (Welch-Satterthwaite 自由度) を per-channel に返すので、
        caller は 「今回の n で固定閾値 3.0 が甘いか厳しいか」 を自分で判定
        できる (n=5 で df≈8 なら本来 2.8〜4.6 が必要、n=100 で df≈198 なら
        z=3 は α≈0.003 相当、など)。

        分母は per-sample SD ではなく **平均の標準誤差 (SE) の Welch 合成**
        なので、n が大きいほど固定閾値は厳しくなる (n=100 だと 「平均が 0.3σ
        分ずれれば z=3」 に相当)。この非対称性は仕様。

        判定は呼び出し側の責任:
          - `mean_shift_z` は生の統計量 (guard 時は None)
          - `welch_df` は自由度 (guard 時は None)
          - `significant_shift` は |z| > z_threshold の真偽値 (guard 時は None)
          - `gate_evaluable` / `gate_skip_reason` で 「gate が評価できたか」 を明示
          - `z_threshold_used` / `z_formula` に採用値と式を反映
          - top-level `is_hypothesis_test: false` + `disclaimer` で
            「これは検定 (p 値/棄却域) ではない」を機械可読 field として提示
          - per-channel `interpretation: "welch_t_statistic_with_fixed_z_threshold"`

        **Guard (v0.2.3)**: 以下の case では gate を評価せず理由を返す:
          - `n_A < 2` or `n_B < 2` → `gate_skip_reason: "insufficient_samples"`
            (stdev が定義されない、または partial で abort が n=1 で起きた場合)
          - `σ_A²/n_A + σ_B²/n_B == 0` → `gate_skip_reason: "zero_variance"`
            (定数装置 / 極端な同値列。旧実装では 0/0 → NaN → False で
            「差が無い」 と静かに誤報していた path)
        いずれの場合も `mean_shift_z / welch_df / standard_error /
        significant_shift` はすべて `None`。 caller は `None` を 「差が無い」
        と読まないこと。「gate 未評価」 を意味する。

        v0.2.2: 入力セッションのどちらかが aborted (partial) の場合、
        n の非対称が z を歪めるので top-level の `any_input_aborted` +
        `aborted_inputs` で明示的に flag する (下流の判断責任に流す)。
        """
        if z_threshold <= 0:
            raise ValueError("z_threshold は正の実数を指定してください")
        stats_a = Bench.analyze(sa)["channels"]
        stats_b = Bench.analyze(sb)["channels"]
        aborted_inputs: list[str] = []
        if sa.aborted_at is not None:
            aborted_inputs.append("a")
        if sb.aborted_at is not None:
            aborted_inputs.append("b")
        result: dict[str, Any] = {
            "a": {
                "session_id": sa.id,
                "started_at": sa.started_at,
                # v0.2.4 副 fix: local tz 補助
                "started_at_local": _to_local_iso(sa.started_at),
                "note": sa.note,
                "port": sa.port,
                "partial": sa.aborted_at is not None,
                "abort_reason": sa.abort_reason,
            },
            "b": {
                "session_id": sb.id,
                "started_at": sb.started_at,
                # v0.2.4 副 fix: local tz 補助
                "started_at_local": _to_local_iso(sb.started_at),
                "note": sb.note,
                "port": sb.port,
                "partial": sb.aborted_at is not None,
                "abort_reason": sb.abort_reason,
            },
            "z_threshold_used": z_threshold,
            "z_formula": "z = (mean_A - mean_B) / sqrt(sigma_A^2 / n_A + sigma_B^2 / n_B)",
            "is_hypothesis_test": False,
            "disclaimer": (
                "The 'mean_shift_z' statistic is identical to Welch's t "
                "statistic. What differs from a Welch's t-test is the "
                "decision rule: this gate uses a fixed |z| > z_threshold "
                "instead of the t-distribution's df-dependent critical "
                "value. Check 'welch_df' per channel to judge whether the "
                "fixed threshold is calibrated for the actual sample sizes."
            ),
            "any_input_aborted": len(aborted_inputs) > 0,
            "aborted_inputs": aborted_inputs,
            "shared_channels": [],
            "only_in_a": [ch for ch in sa.channels if ch not in sb.channels],
            "only_in_b": [ch for ch in sb.channels if ch not in sa.channels],
            "channels": {},
        }
        for ch in sa.channels:
            if ch not in sb.channels:
                continue
            result["shared_channels"].append(ch)
            a = stats_a.get(ch)
            b = stats_b.get(ch)
            if a is None or b is None:
                continue
            delta_mean = a["mean"] - b["mean"]
            na, nb = a["n"], b["n"]

            # v0.2.3 guard: n<2 (stdev 未定義) と σ 合成 0 (0/0 → NaN → 誤 False) を
            # 明示的に別 path に分離。significant_shift を None にすることで
            # 「差が無い」 との誤読を防ぐ (False は 「差が無い」 と読まれ得る)。
            z: float | None
            se: float | None
            welch_df: float | None
            gate_skip_reason: str | None
            significant: bool | None

            if na < 2 or nb < 2:
                z = None
                se = None
                welch_df = None
                gate_skip_reason = "insufficient_samples"
                significant = None
            else:
                se_sq_a = (a["stdev"] ** 2) / na
                se_sq_b = (b["stdev"] ** 2) / nb
                se_sq_total = se_sq_a + se_sq_b
                if se_sq_total <= 0:
                    z = None
                    se = None
                    welch_df = None
                    gate_skip_reason = "zero_variance"
                    significant = None
                else:
                    se = math.sqrt(se_sq_total)
                    z = delta_mean / se
                    # Welch-Satterthwaite:
                    # df = (se_sq_a + se_sq_b)^2 / (se_sq_a^2/(n_A-1) + se_sq_b^2/(n_B-1))
                    df_den = (se_sq_a ** 2) / (na - 1) + (se_sq_b ** 2) / (nb - 1)
                    welch_df = (se_sq_total ** 2) / df_den if df_den > 0 else None
                    gate_skip_reason = None
                    significant = abs(z) > z_threshold

            result["channels"][ch] = {
                "a": {"mean": a["mean"], "stdev": a["stdev"], "drift": a["drift"], "n": a["n"]},
                "b": {"mean": b["mean"], "stdev": b["stdev"], "drift": b["drift"], "n": b["n"]},
                "delta_mean": round(delta_mean, 6),
                "delta_stdev": round(a["stdev"] - b["stdev"], 6),
                "delta_drift": round(a["drift"] - b["drift"], 6),
                "standard_error": round(se, 6) if se is not None else None,
                "mean_shift_z": round(z, 3) if z is not None else None,
                "welch_df": round(welch_df, 3) if welch_df is not None else None,
                "z_threshold_used": z_threshold,
                "gate_evaluable": gate_skip_reason is None,
                "gate_skip_reason": gate_skip_reason,
                "significant_shift": significant,
                "interpretation": "welch_t_statistic_with_fixed_z_threshold",
            }
        return result

    @staticmethod
    def search_sessions(
        since: str | None = None,
        until: str | None = None,
        note_contains: str | None = None,
        port: str | None = None,
        channel: str | None = None,
        limit: int = 30,
        _meta_out: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """条件付きでセッションを絞り込む。list_sessions が直近 N 件しか
        返さないので、セッションが増えたらこちらを使う。全条件 AND。

        v0.2.4 主 fix (藤本さん 2026-08-13 verify 発火 pain fix):
          - `since` / `until` が **日付のみ文字列** (`YYYY-MM-DD`) のときは
            **local midnight として解釈** し UTC 換算後に started_at と比較。
            since=当日 00:00 local、until=当日 23:59:59.999999 local。
          - 完全 ISO (T + 時刻 [+ offset]) はそのまま辞書順比較 (従来動作)。
          - tz は `BENCHTOP_TZ` env 優先、無ければ system local。
          - `_meta_out` (optional dict) に resolve 結果を書き戻すので、
            MCP tool 層で audit trail (`since_resolved_utc` 等) を返せる。
            渡さない caller (旧 selftest phase [9] 等) は backward compat。
        """
        if not DATA_DIR.exists():
            if _meta_out is not None:
                _meta_out["since"] = since
                _meta_out["until"] = until
                _meta_out["since_resolved_utc"] = since
                _meta_out["until_resolved_utc"] = until
                _meta_out["since_date_only"] = False
                _meta_out["until_date_only"] = False
                _meta_out["tz_used"] = None
            return []

        # v0.2.4: since/until を resolve
        resolved_since, meta_since = _resolve_date_boundary(since, True)
        resolved_until, meta_until = _resolve_date_boundary(until, False)
        if _meta_out is not None:
            _meta_out["since"] = since
            _meta_out["until"] = until
            _meta_out["since_resolved_utc"] = meta_since["resolved_utc"]
            _meta_out["until_resolved_utc"] = meta_until["resolved_utc"]
            _meta_out["since_date_only"] = meta_since["date_only"]
            _meta_out["until_date_only"] = meta_until["date_only"]
            _meta_out["tz_used"] = meta_since["tz_used"] or meta_until["tz_used"]

        needle = note_contains.lower() if note_contains else None
        out: list[dict[str, Any]] = []
        for p in sorted(DATA_DIR.glob("*.json"), reverse=True):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            started = d.get("started_at", "")
            if resolved_since and started < resolved_since:
                continue
            if resolved_until and started > resolved_until:
                continue
            if port and d.get("port") != port:
                continue
            if channel and channel not in d.get("channels", []):
                continue
            if needle and needle not in (d.get("note", "") or "").lower():
                continue
            out.append(
                {
                    "session_id": d["id"],
                    "port": d["port"],
                    "started_at": started,
                    # v0.2.4 副 fix: local tz 補助表示
                    "started_at_local": _to_local_iso(started),
                    "n_rows": len(d.get("rows", [])),
                    "channels": d.get("channels", []),
                    "note": d.get("note", ""),
                    # v0.2.2: partial 情報を search 結果に mirror (list_sessions と同一契約)。
                    "partial": d.get("aborted_at") is not None,
                    "abort_reason": d.get("abort_reason"),
                }
            )
            if len(out) >= limit:
                break
        return out


BENCH = Bench()


# ---------------------------------------------------------------------------
# v0.3.0: audit log hash chain (Rei-Automator STEP 1340 primitive port)
#   session store (~/.benchtop-mcp/session_*.json) と独立の説明責任 store。
#   全 tool 呼び出しを append-only JSONL + sha256 prev-hash chain で記録。
#   証跡が価値になる領域 (ISO/IEC 17025 校正 / GMP 医薬品製造記録 / 監査対応) 用。
# ---------------------------------------------------------------------------

from benchtop_audit_log import AuditLogWriter  # noqa: E402
from benchtop_provenance import (  # noqa: E402 -- v0.5.0-alpha SPIKE
    SafetyGate,
    import_external_session as _provenance_import,
    build_session_dict_from_import,
)
# v0.6.0-alpha (2026-08-20): physics-limits pre-flight layer
# chat-Claude 2026-08-20 「LLM が 単位付き算術で 自信満々に間違える」 対策の 5 tool。
# SafetyGate と 相補 (SafetyGate = SCPI-arg level、 physics-limits = 事前規模計算)。
from benchtop_physics_limits import (  # noqa: E402
    bekenstein_bound_bits as _pl_bekenstein,
    landauer_min_energy_j as _pl_landauer,
    lloyd_computation_ceiling as _pl_lloyd,
    operator_space_size as _pl_operator_space,
    compression_upper_bound as _pl_compression,
)

# v0.7.0-alpha (2026-08-23): olfact / biosensor mock spike
# 藤本さん directive (a) 「benchtop-mcp v0.7 olfact connector v0.1 spike」 実装。
# 対話 arc (虫触角 / 動物 / 植物センサ + AI に役立つか) 経由、 hardware 未取得
# = 全 tool で hardware_available: False marker 徹底。
from benchtop_olfact import (  # noqa: E402
    list_probes as _ol_list_probes,
    measure_eag as _ol_measure_eag,
    probe_health as _ol_probe_health,
)

# v0.8.0-alpha (2026-08-26): Akizuki wire-up 3 layer mock spike
# 藤本さん directive 「(1)(2)(3) を 順番に」 実装、 Rei stack STEP 1406 秋月
# I2C/SPI/UART wire-up 候補 list から 3 SKU pilot (BME280 環境 / BNO055 慣性 /
# VL53L1X ToF 距離) を benchtop mock として 追加。 hardware 未取得 = 全 tool で
# hardware_available: False marker 徹底、 STEP 1396 olfact pattern 継承。
from benchtop_akizuki_wireup import (  # noqa: E402
    list_akizuki_probes as _ak_list_probes,
    measure_environment as _ak_measure_environment,
    measure_orientation as _ak_measure_orientation,
    measure_distance as _ak_measure_distance,
)

AUDIT_DIR = Path(os.environ.get("BENCHTOP_AUDIT_DIR", str(DATA_DIR / "audit")))
_AUDIT_ENABLED = os.environ.get("BENCHTOP_AUDIT", "1").strip() not in ("0", "false", "no", "")
_AUDIT: AuditLogWriter | None = None
if _AUDIT_ENABLED:
    try:
        _AUDIT = AuditLogWriter(str(AUDIT_DIR))
    except Exception as e:
        # audit init 失敗は log のみ、 tool 実行を kill しない
        print(f"[benchtop] audit log init failed: {e}", file=sys.stderr)
        _AUDIT = None


def _write_audit(action: str, target: str, result: str = "success",
                 detail: dict[str, Any] | None = None) -> None:
    """Append audit entry. Failure is swallowed with warn — tool exec must continue."""
    if _AUDIT is None:
        return
    try:
        _AUDIT.append(actor="benchtop-mcp", action=action, target=target,
                      result=result, detail=detail)
    except Exception as e:
        print(f"[benchtop] audit append failed: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# MCP 層 : ここから下が「AI から呼べる道具」の定義
#   関数の docstring と型注釈が、そのまま AI への説明書になる。
#   ここを丁寧に書くほど AI は正しく使ってくれる。
# ---------------------------------------------------------------------------

from mcp.server import MCPServer  # noqa: E402

server = MCPServer(
    name="benchtop",
    version="0.8.0-alpha",
    instructions=(
        "シリアル接続された計測装置・回路を操作し、測定値を記録・解析するツール群です。"
        "実機が無い場合は port='mock' を指定すると内蔵の仮想装置が使えます。"
        "典型的な流れ: list_ports → measure → analyze_session → export_session_csv。"
        "v0.2 追加: plot_session (ASCII 波形) / compare_sessions (2 セッション diff) / "
        "search_sessions (日付・note・port・channel での絞り込み、"
        "v0.2.4 で 'YYYY-MM-DD' の日付のみ指定は local midnight として解釈)。"
        "v0.3.0 追加: audit log hash chain (append-only JSONL + sha256 prev-hash)。"
        "全 tool 呼び出しが 記録され、verify_audit_chain で 改竄検出可能。"
        "証跡が価値になる領域 (ISO/IEC 17025 / GMP / 監査対応) 用。"
        "v0.4.0 追加: 実験ノート (experiment notebook) fields — measure() に subject / "
        "environment / instrument_config / mystery_id 全 optional 追加、 過去 session を "
        "find_similar_sessions で subject/条件別 絞り込み、 regression_check で baseline vs "
        "current の tolerance-based 劣化検出。 rei-aios の mystery/theory と ID linking 可能。"
        "v0.5.0-alpha 追加 (SPIKE): import_external_session で他社 MCP server (Keysight/rigol/"
        "lecroy/kya-os wrapped) の 計測記録を benchtop に取り込み + SafetyGate で SCPI-argument "
        "level の hazard (Kikusui PLZ-5W CR mode Siemens 混同 = 短絡 hazard 等) を静的検出。"
        "v0.6.0-alpha 追加: physics-limits pre-flight 5 tool — bekenstein_bound_bits / "
        "landauer_min_energy_j / lloyd_computation_ceiling / operator_space_size / "
        "compression_upper_bound。 実 hardware 送出前の 単位付き算術 + 桁勘定 + 上界計算を "
        "LLM 単体で 誤りやすい 領域として MCP 化。 Kolmogorov K(x) uncomputable は siren-family "
        "pattern 回避で明示 disclaimer 付き。 全 pure calc (stdlib のみ、 状態なし)。"
        "v0.7.0-alpha 追加 (SPIKE): olfact / biosensor mock 3 tool — list_probes / measure_eag / "
        "probe_health。 生体嗅覚センサ (bio-hybrid / receptor-chip / bio-inspired 3 layer) の "
        "interface skeleton、 hardware 未取得 = 全 tool で hardware_available: False marker、 "
        "measure_eag は deterministic mock waveform (probe_id + odor_name hash seed)、 "
        "probe_health は 3 layer 別 degradation model (linear / exponential / calibration-only)。 "
        "STEP 1350 d8_verdict_from_measurement primitive を 3 値 subset で 参照 (verdict field)。"
        "v0.8.0-alpha 追加 (SPIKE): Akizuki wire-up 3 layer mock 4 tool — list_akizuki_probes / "
        "measure_environment (BME280) / measure_orientation (BNO055) / measure_distance (VL53L1X)。 "
        "Rei stack STEP 1406 秋月 I2C/SPI/UART wire-up 候補 list から 3 SKU pilot、 hardware 未取得 "
        "= 全 tool hardware_available: False、 deterministic mock (probe_id + tag hash seed)、 "
        "実 sensor physics (Bosch calibration / on-chip fusion / SPAD photon counting) は 模倣なし = "
        "interface skeleton のみ。 環境/慣性/距離 3 gap 埋めの STEP 1406 導入 arc。"
    ),
)


@server.tool()
def list_ports() -> dict[str, Any]:
    """利用可能な装置（シリアルポート）の一覧を返す。

    実機が接続されていなくても、必ず 'mock' が含まれる。
    どの装置を使うか決める最初のステップとして呼ぶこと。
    """
    return {"ports": BENCH.list_ports(), "pyserial_available": HAS_SERIAL}


@server.tool()
def send_command(port: str, command: str, baudrate: int = 9600) -> dict[str, Any]:
    """装置に1行のコマンドを送り、返ってきた1行を読む。

    Args:
        port: 装置のポート名。'mock' で内蔵仮想装置。実機は 'COM3' や '/dev/ttyUSB0' など。
        command: 送信する文字列。改行は自動で付与される。例: '*IDN?'
        baudrate: 通信速度。装置の設定に合わせる。既定は 9600。
    """
    return {"port": port, "sent": command, "response": BENCH.send_command(port, command, baudrate)}


@server.tool()
def measure(
    port: str = "mock",
    samples: int = 20,
    interval_ms: int = 100,
    baudrate: int = 9600,
    command: str | None = None,
    note: str = "",
    subject: str | None = None,
    environment: dict[str, Any] | None = None,
    instrument_config: dict[str, Any] | None = None,
    mystery_id: str | None = None,
) -> dict[str, Any]:
    """装置から連続して測定値を読み取り、1つのセッションとして保存する。

    'T=25.3,H=48.1' のような key=value 形式、'25.3,48.1' のようなCSV形式、
    単一の数値のいずれも自動で解釈する。

    途中失敗 (装置切断、Ctrl+C、SerialException 等) が起きた場合でも、
    そこまでに取れた行はセッションに保存され、返り値の `partial` が True
    になる。`abort_reason` に失敗内容が入る。100 回中 60 で止まっても
    「60 行取れた」と「なぜ止まったか」が残るので、失敗解析に使える。

    v0.4.0: 実験ノート fields (subject / environment / instrument_config / mystery_id) 追加。
    全 optional、 「3ヶ月前の同じ条件と 比べて」 を find_similar_sessions で 可能に。

    Args:
        port: 装置のポート名。既定は 'mock'。
        samples: 読み取る回数（1〜10000）。
        interval_ms: 各読み取りの間隔（ミリ秒）。
        baudrate: 通信速度。
        command: 毎回送信するコマンド。省略時は装置が自発的に送る行を読む。
        note: このセッションに付けるメモ。後から探すときの手がかりになる。
        subject: (v0.4) 被測定物の 識別子 (例: 'Arduino Uno #17', '抵抗器 R47')。
                 同じ subject の 過去 session と 比較すると 個体の 経年劣化 追跡可能。
        environment: (v0.4) 環境条件 dict (自由 schema)。 例:
                     {'temp_c': 25.3, 'humidity': 48.1}
        instrument_config: (v0.4) 装置設定 dict (自由 schema)。 例:
                           {'baudrate': 9600, 'sampling_hz': 10, 'calibration_ref': 'NIST-2026-08-01'}
        mystery_id: (v0.4) rei-aios の mystery / theory への link ID。
                    設定すると 計測結果が 理論に自動で 積み上がる。

    Returns:
        保存されたセッションIDと、その場での簡易サマリー。partial が True
        のとき部分結果 (abort_reason に理由)。 v0.4 以降 は subject/environment/
        instrument_config/mystery_id が top-level に mirror される。
    """
    s = BENCH.measure(
        port, samples, interval_ms, baudrate, command, note,
        subject=subject, environment=environment,
        instrument_config=instrument_config, mystery_id=mystery_id,
    )
    result = {
        "session_id": s.id,
        "saved_to": str(s.path()),
        "n_rows": len(s.rows),
        "skipped": s.skipped,
        "channels": s.channels,
        "partial": s.aborted_at is not None,
        "abort_reason": s.abort_reason,
        "summary": Bench.analyze(s)["channels"],
        # v0.4.0: 実験ノート fields mirror
        "subject": s.subject,
        "environment": s.environment,
        "instrument_config": s.instrument_config,
        "mystery_id": s.mystery_id,
    }
    # v0.3.0: audit log (v0.4.0: subject/mystery_id を detail に 追加)
    _write_audit(
        action="measure",
        target=s.id,
        result="partial" if s.aborted_at else "success",
        detail={
            "port": port, "samples_requested": samples, "n_rows": len(s.rows),
            "channels": s.channels, "note": note,
            "abort_reason": s.abort_reason if s.aborted_at else None,
            "subject": subject, "mystery_id": mystery_id,
            "has_environment": environment is not None,
            "has_instrument_config": instrument_config is not None,
        },
    )
    return result


@server.tool()
def find_similar_sessions(
    subject: str | None = None,
    mystery_id: str | None = None,
    environment_key: str | None = None,
    environment_value: Any = None,
    tolerance: float | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    """v0.4.0: 実験ノート fields で 過去 session を 絞り込む。

    「3ヶ月前の 同じ subject の 同じ条件で 測った session」 を 検索する ための tool。
    subject / mystery_id は 完全一致、 environment は 単一 key の 値比較 (tolerance
    指定時は 数値近似)、 since/until は search_sessions と 同じ 日付 filter (v0.2.4
    date-only 解釈 + BENCHTOP_TZ)。 全条件 AND、 いずれも 省略可 (全 session 返却)。

    Args:
        subject: (完全一致) 被測定物 ID。 None なら 条件なし。
        mystery_id: (完全一致) rei-aios mystery ID。 None なら 条件なし。
        environment_key: environment dict の key 名 (例: 'temp_c')。 environment_value と併用。
        environment_value: 上記 key の 期待値。 tolerance 指定時は 数値 |v - value| < tolerance。
        tolerance: environment_value との 許容誤差 (数値時のみ)。 None なら 完全一致比較。
        since: 日付下限。 v0.2.4 date-only 解釈 (YYYY-MM-DD なら local midnight)。
        until: 日付上限。 v0.2.4 date-only 解釈。
        limit: 返す最大件数。 既定 30。

    Returns:
        {"data_dir": ..., "filters": ..., "sessions": [{"session_id": ..., "subject": ...,
         "environment": ..., "mystery_id": ..., "started_at": ..., ...}]}
    """
    from datetime import datetime as _dt

    since_utc, since_meta = _resolve_date_boundary(since, is_since=True)
    until_utc, until_meta = _resolve_date_boundary(until, is_since=False)

    matched: list[dict[str, Any]] = []
    if not DATA_DIR.exists():
        _write_audit(action="find_similar_sessions", target=f"subject={subject},mystery={mystery_id}",
                     result="success", detail={"n_matched": 0, "reason": "data_dir_missing"})
        return {
            "data_dir": str(DATA_DIR),
            "filters": {"subject": subject, "mystery_id": mystery_id,
                        "environment_key": environment_key, "environment_value": environment_value,
                        "tolerance": tolerance, "since": since, "until": until, "limit": limit,
                        "since_resolved_utc": since_meta.get("resolved_utc"),
                        "until_resolved_utc": until_meta.get("resolved_utc")},
            "sessions": matched,
        }

    for p in sorted(DATA_DIR.glob("*.json"), reverse=True):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        # subject / mystery_id 完全一致 filter
        if subject is not None and raw.get("subject") != subject:
            continue
        if mystery_id is not None and raw.get("mystery_id") != mystery_id:
            continue
        # environment key/value filter
        if environment_key is not None:
            env = raw.get("environment") or {}
            if environment_key not in env:
                continue
            actual = env[environment_key]
            if tolerance is not None and isinstance(actual, (int, float)) and isinstance(environment_value, (int, float)):
                if abs(actual - environment_value) > tolerance:
                    continue
            else:
                if actual != environment_value:
                    continue
        # since/until filter (started_at 文字列比較、 UTC ISO)
        started = raw.get("started_at", "")
        if since_utc and started < since_utc:
            continue
        if until_utc and started > until_utc:
            continue
        matched.append({
            "session_id": raw.get("id"),
            "started_at": started,
            "started_at_local": _to_local_iso(started),
            "port": raw.get("port"),
            "note": raw.get("note", ""),
            "subject": raw.get("subject"),
            "environment": raw.get("environment"),
            "instrument_config": raw.get("instrument_config"),
            "mystery_id": raw.get("mystery_id"),
            "channels": raw.get("channels", []),
            "n_rows": len(raw.get("rows", [])),
            "partial": raw.get("aborted_at") is not None,
        })
        if len(matched) >= limit:
            break

    _write_audit(action="find_similar_sessions",
                 target=f"subject={subject},mystery={mystery_id},env={environment_key}",
                 result="success", detail={"n_matched": len(matched), "limit": limit})
    return {
        "data_dir": str(DATA_DIR),
        "filters": {"subject": subject, "mystery_id": mystery_id,
                    "environment_key": environment_key, "environment_value": environment_value,
                    "tolerance": tolerance, "since": since, "until": until, "limit": limit,
                    "since_resolved_utc": since_meta.get("resolved_utc"),
                    "until_resolved_utc": until_meta.get("resolved_utc"),
                    "tz_used": since_meta.get("tz_used") or until_meta.get("tz_used")},
        "sessions": matched,
    }


@server.tool()
def regression_check(
    baseline_session_id: str,
    current_session_id: str,
    tolerance_mean: float = 0.1,
    tolerance_stdev_ratio: float = 0.5,
) -> dict[str, Any]:
    """v0.4.0: baseline session と 現在 session を 比較して 「劣化・回帰」 を 検出する。

    compare_sessions が 「有意差 (Welch t 統計)」 を 返すのに対して、 regression_check は
    「実用的 tolerance を 超えた 変化」 を 返す。 校正基準 (baseline) から どれだけ ズレたら
    「異常」 とみなすかを、 caller が tolerance で 明示指定する。

    共通チャンネル 各々 について:
      - mean_delta = |mean_current - mean_baseline| が tolerance_mean を 超えたら regression=True
      - stdev_ratio = stdev_current / stdev_baseline が (1 - tolerance_stdev_ratio, 1 + tolerance_stdev_ratio)
        の 外なら stdev_regression=True (ノイズ悪化 or 装置固定化)
      - drift_delta = |drift_current - drift_baseline| も 参考値として返す

    存在しない session_id は structured error dict を返す (例外は投げない)。

    Args:
        baseline_session_id: 基準 session ID (通常 = 出荷時校正 or 前月同条件)。
        current_session_id: 現在 session ID (今 測定した もの)。
        tolerance_mean: mean 差 の 許容値 (単位は チャンネルの 単位 と 同じ)。 既定 0.1。
        tolerance_stdev_ratio: stdev 比 の 許容比率 (0.5 なら ±50%)。 既定 0.5。

    Returns:
        {"any_regression": bool, "channels": {ch: {"mean_baseline": ..., "mean_current": ...,
         "mean_delta": ..., "mean_regression": bool, "stdev_baseline": ..., "stdev_current": ...,
         "stdev_ratio": ..., "stdev_regression": bool, "drift_delta": ...}}, "tolerance": {...}}
    """
    a = _load_session_or_error(baseline_session_id)
    if isinstance(a, dict):
        _write_audit(action="regression_check",
                     target=f"{baseline_session_id}|{current_session_id}",
                     result="error", detail={"error": a.get("error"), "which": "baseline"})
        return a
    b = _load_session_or_error(current_session_id)
    if isinstance(b, dict):
        _write_audit(action="regression_check",
                     target=f"{baseline_session_id}|{current_session_id}",
                     result="error", detail={"error": b.get("error"), "which": "current"})
        return b

    analyze_a = Bench.analyze(a)
    analyze_b = Bench.analyze(b)
    ch_a = analyze_a.get("channels", {})
    ch_b = analyze_b.get("channels", {})
    shared = sorted(set(ch_a.keys()) & set(ch_b.keys()))

    per_channel: dict[str, dict[str, Any]] = {}
    any_regression = False
    for ch in shared:
        ma, mb = ch_a[ch]["mean"], ch_b[ch]["mean"]
        sa, sb = ch_a[ch]["stdev"], ch_b[ch]["stdev"]
        da, db = ch_a[ch]["drift"], ch_b[ch]["drift"]
        mean_delta = abs(mb - ma)
        mean_reg = mean_delta > tolerance_mean
        if sa > 0:
            stdev_ratio = sb / sa
            stdev_reg = (stdev_ratio < (1 - tolerance_stdev_ratio)
                         or stdev_ratio > (1 + tolerance_stdev_ratio))
        else:
            stdev_ratio = None
            stdev_reg = None  # baseline stdev=0 → 判定不能 (定数装置)
        drift_delta = abs(db - da)
        if mean_reg or (stdev_reg is True):
            any_regression = True
        per_channel[ch] = {
            "mean_baseline": ma, "mean_current": mb, "mean_delta": mean_delta,
            "mean_regression": mean_reg,
            "stdev_baseline": sa, "stdev_current": sb, "stdev_ratio": stdev_ratio,
            "stdev_regression": stdev_reg,
            "drift_baseline": da, "drift_current": db, "drift_delta": drift_delta,
        }

    result = {
        "any_regression": any_regression,
        "shared_channels": shared,
        "channels": per_channel,
        "tolerance": {"tolerance_mean": tolerance_mean,
                      "tolerance_stdev_ratio": tolerance_stdev_ratio},
        "baseline": {"session_id": baseline_session_id, "subject": a.subject,
                     "started_at": a.started_at, "started_at_local": _to_local_iso(a.started_at),
                     "n_rows": len(a.rows)},
        "current": {"session_id": current_session_id, "subject": b.subject,
                    "started_at": b.started_at, "started_at_local": _to_local_iso(b.started_at),
                    "n_rows": len(b.rows)},
    }
    _write_audit(action="regression_check",
                 target=f"{baseline_session_id}|{current_session_id}",
                 result="success",
                 detail={"any_regression": any_regression, "n_shared_channels": len(shared),
                         "tolerance_mean": tolerance_mean,
                         "tolerance_stdev_ratio": tolerance_stdev_ratio})
    return result


@server.tool()
def import_external_session(
    source: str,
    records: list[dict[str, Any]],
    subject: str | None = None,
    mystery_id: str | None = None,
    environment: dict[str, Any] | None = None,
    instrument_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """他の MCP server (Keysight MCP / rigol-mcp / lecroy-mcp / kya-os wrapped) が
    計測した記録を benchtop に取り込み、 全 tool 呼び出しと同じ audit chain で 記録する。

    v0.5.0-alpha SPIKE (2026-08-19、 藤本さん judgment 待ち)。 chat-Claude 2026-08-18
    「MCP コネクタ世界一」 report §3-1 「機器層 (SCPI) は捨て、 記録層に座る」 の 実装。

    SafetyGate を 全 record に 適用 (default: Kikusui PLZ-5W CR mode Siemens/Ω 混同
    dangerous rule built-in)、 hazard 検出 record は import 時点で reject、
    accepted record のみ Session として persist。 全 import は audit log に 記録。

    Args:
        source: origin identifier。 例: 'external:rigol-mcp', 'external:keysight-mcp',
                'external:kya-os:<inner-source>'
        records: list of measurement records。 各 dict の required key: 'ts', 'channels',
                 'values'。 optional: 'unit_hints', 'instrument' (SafetyGate lookup 用),
                 'raw', 'attestation' (kya-os JOSE proof 等、 pass-through 保存のみ)。
        subject: 被測定物 ID (Session.subject 継承)
        mystery_id: rei-aios mystery / theory link ID (Session.mystery_id 継承)
        environment: 環境条件 dict (Session.environment 継承)
        instrument_config: 装置設定 dict (Session.instrument_config 継承)

    Returns:
        成功時: {"ok": True, "session_id": "ext-...", "records_accepted": N,
                 "records_rejected": M, "rejections": [...]}
        全 reject: {"ok": False, "session_id": None, ...}
        SafetyGate violation の 各 rejection は {"index", "rule_id", "severity",
        "reason", "suggested_fix", "detail"} を含む。
    """
    result = _provenance_import(
        source=source,
        records=records,
        subject=subject,
        mystery_id=mystery_id,
        environment=environment,
        instrument_config=instrument_config,
        safety_gate=SafetyGate(),
    )

    if result.ok and result.session_id is not None:
        # persist as Session (backward-compat via source field default)
        session_dict = build_session_dict_from_import(
            result=result,
            source=source,
            records=records,
            subject=subject,
            mystery_id=mystery_id,
            environment=environment,
            instrument_config=instrument_config,
        )
        if session_dict is not None:
            known_fields = set(Session.__dataclass_fields__.keys())
            filtered = {k: v for k, v in session_dict.items() if k in known_fields}
            sess = Session(**filtered)
            sess.save()

    _write_audit(
        action="import_external_session",
        target=f"{source}|{result.session_id or 'REJECTED'}",
        result="success" if result.ok else "rejected",
        detail={
            "source": source,
            "records_accepted": result.records_accepted,
            "records_rejected": result.records_rejected,
            "rejection_rule_ids": sorted({r.get("rule_id", "?") for r in result.rejections}),
        },
    )

    return {
        "ok": result.ok,
        "session_id": result.session_id,
        "records_accepted": result.records_accepted,
        "records_rejected": result.records_rejected,
        "rejections": result.rejections,
        "warning": result.warning,
    }


# ---------------------------------------------------------------------------
# v0.6.0-alpha (2026-08-20): physics-limits pre-flight layer (5 tools)
# ---------------------------------------------------------------------------
#   chat-Claude 2026-08-20 turn: 「LLM が 単位付き算術で 自信満々に間違える」 領域 =
#   Bekenstein / Landauer / Lloyd / operator space / compression bound の 5 primitive。
#   実 hardware SCPI 送出 (measure() 等) の pre-flight check として 使える。
#   SafetyGate (v0.5.0-alpha、 SCPI-argument level) と 相補: 事前規模計算 → SafetyGate。
#
#   ★ 命名 discipline: 「上界 / 最小 / 上限 / 空間 size」 の semantic を name に埋め込み、
#      Kolmogorov K(x) uncomputable の 果たせない約束を 名乗らない ([[feedback-super-
#      naming-siren-family-pattern]] 遵守)。 return dict にも is_upper_bound / is_lower_bound
#      flag を含める。
#
#   ★ 全 tool は pure calculation (stdlib のみ)、 状態なし、 network I/O なし。
#      remote MCP としても そのまま deploy 可能 (依存 lag なし)。
# ---------------------------------------------------------------------------


@server.tool()
def bekenstein_bound_bits(radius_m: float, energy_J: float) -> dict[str, Any]:
    """球状領域 (半径 R メートル、 総エネルギー E ジュール) に含みうる 情報量の上界を bits で返す。

    Formula: S ≤ 2π R E / (ℏ c ln 2)  bits (Bekenstein 1981, PRD 23:287)。
    上界のみ (is_upper_bound: True)、 球状 (非回転) 領域 + 弱重力 regime 前提。

    Args:
        radius_m: 系を含む 最小球の 半径 (メートル)、 must be > 0。
        energy_J: 系の 全質量-エネルギー (ジュール)、 must be > 0。

    Returns dict with: bound_bits, bound_nats, is_upper_bound, assumptions,
    citation, honest_scope。 詳細は benchtop_physics_limits モジュール docstring。
    """
    return _pl_bekenstein(radius_m, energy_J)


@server.tool()
def landauer_min_energy_j(bits: float, temperature_K: float = 300.0) -> dict[str, Any]:
    """N bit を 不可逆的に 消去する 最小エネルギー (Joules)、 環境温度 T Kelvin で。

    Formula: E_min = N × k_B × T × ln 2  J  (Landauer 1961, IBM J. Res. Dev. 5:183)。
    下限のみ (is_lower_bound: True)、 irreversible (bit erase) 操作専用。
    Reversible computation (Bennett 1973) は E=0 下限 の 別 regime = scope 外。

    T=300 K, N=1 で ≈ 2.87 × 10⁻²¹ J ≈ 0.018 eV (実 CMOS は 10⁹〜10¹² × 上で動作)。

    Args:
        bits: 消去 bit 数 (float 可、 partial-erasure amortization 用)。 must be >= 0。
        temperature_K: 環境温度 Kelvin、 default 300 (室温)。

    Returns dict with: min_energy_J, min_energy_eV, min_energy_kT_ln2 (dimensionless),
    is_lower_bound, assumptions, citation, honest_scope。
    """
    return _pl_landauer(bits, temperature_K)


@server.tool()
def lloyd_computation_ceiling(mass_kg: float) -> dict[str, Any]:
    """質量 m kg の 系が 単位時間あたりに 実行可能な 演算数の 究極的上限 (ops/s)。

    Formula: rate ≤ 2 m c² / (π ℏ)  ops/s  (Lloyd 2000, Nature 406:1047)。
    「operation」 = orthogonal Hilbert-space state transition (Margolus-Levitin 1998)、
    実 FLOPS とは 直接比較 不能。 究極的 thought experiment、 実 device は 10⁴⁰+ × 下。

    m=1 kg で ≈ 5.43 × 10⁵⁰ ops/s (Lloyd's ultimate laptop)。

    Args:
        mass_kg: 系の 静止質量 (kg)、 must be > 0。

    Returns dict with: ops_per_second_ceiling, energy_J, min_op_time_s,
    is_upper_bound, assumptions, citation, honest_scope。
    """
    return _pl_lloyd(mass_kg)


@server.tool()
def operator_space_size(k: int, n: int) -> dict[str, Any]:
    """k 値 n 変数 演算子の 総数 = k^(k^n)、 及び LUT / config bits / 列挙時間。

    Formula: input_configurations = k^n / total_functions = k^(k^n)。
    D-FUMT₈ (k=8) では: n=1→8^8=16.78M / n=2→8^64≈6.28×10⁵⁷ / n=3→8^512≈10⁴⁶² (物理的到達不能)。

    ★ 理論上限 (is_theoretical_max: True)、 実 FPGA 合成では BDD + shared subexpression
    で 実効 config bits は 大幅減 (STEP 1011 D-FUMT₈ ALU が Tang Nano 9K で 37 LUT4 実測)。

    Args:
        k: 論理値の数 (2=Boolean, 4=Belnap-FDE, 8=D-FUMT₈)。 must be int >= 2。
        n: 変数の数。 must be int >= 0。

    Returns dict with: input_configurations, total_functions_log10, total_functions_str,
    config_bits, lut_k_entries, enumeration_seconds_1ns, is_theoretical_max, ...
    """
    return _pl_operator_space(k, n)


@server.tool()
def compression_upper_bound(
    length: int,
    entropy_bits_per_symbol: float = 1.0,
    method: str = "shannon",
) -> dict[str, Any]:
    """長さ N の source (per-symbol entropy H) の 圧縮後長の 上界 (bits)。

    Formula: L ≥ N × H (Shannon 1948 下限) / L ≈ N × H + O(log N) (実用上界)。

    ★★★ CRITICAL disclaimer (siren-family pattern 回避):
      **Kolmogorov complexity K(x) は Turing-uncomputable** (Chaitin 1975)。
      本 tool は Shannon entropy (statistical) 上界のみ、 K(x) の 実現値ではない。
      K(x) ≤ N·H + O(log N) は 常に 成立 (K は universal に tighter)、 但し K を
      直接返す tool は 原理的に 作成不可 = 本 tool は 「上界の一つ」 の位置付け。

    Args:
        length: source symbol 数 N。 must be int >= 0。
        entropy_bits_per_symbol: H (Shannon entropy per symbol)。 default 1.0 (binary uniform)。
        method: "shannon" (default) / "typical_set" (AEP) / "arithmetic" (arithmetic coding)。

    Returns dict with: shannon_lower_bound_bits, practical_upper_bound_bits,
    compression_ratio_min, is_upper_bound, kolmogorov_note, assumptions, ...
    """
    return _pl_compression(length, entropy_bits_per_symbol, method)


# ---------------------------------------------------------------------------
# v0.7.0-alpha (2026-08-23): olfact / biosensor mock spike (3 tools)
# ---------------------------------------------------------------------------
#   藤本さん directive (a) 「benchtop-mcp v0.7 olfact connector v0.1 spike」 実装。
#   対話 arc 2026-08-23 (虫触角 / 動物 / 植物センサ + AI に役立つか) 3 turn 経由。
#
#   3 tool = list_probes / measure_eag / probe_health。
#   3 layer = ① bio-hybrid (silkworm-antenna-a1、 7h 寿命)
#             ② receptor-chip (mosquito-receptor-fet-b1、 0.5 ppb)
#             ③ bio-inspired (sparse-e-nose-c1、 silicon)
#
#   ★ hardware 未取得 = 全 return dict で hardware_available: False + is_mock: True。
#   ★ measure_eag は deterministic mock (probe_id + odor_name hash seed)、 実 physics
#      模倣なし = interface skeleton のみ ([[feedback-super-naming-siren-family-pattern]])。
#   ★ STEP 1350 d8_verdict_from_measurement primitive を 3 値 subset で 参照
#      (TRUE if SNR≥threshold / NEITHER if SNR<threshold)。
# ---------------------------------------------------------------------------


@server.tool()
def list_probes() -> dict[str, Any]:
    """内蔵 mock probe registry の 一覧を返す。 全 probe は hardware_available: False。

    3 probe (対話 arc で整理した 3 layer 各 1):
      - silkworm-antenna-a1 (bio-hybrid、 7h hydrogel EAG)
      - mosquito-receptor-fet-b1 (receptor-chip、 0.5 ppb CNT-FET)
      - sparse-e-nose-c1 (bio-inspired、 silicon sparse coding)

    Returns dict with: ok, probes (list), probe_count, hardware_available: False,
    is_mock: True, honest_scope, related_step, source。
    """
    return _ol_list_probes()


@server.tool()
def measure_eag(
    probe_id: str,
    odor_name: str,
    duration_s: float = 3.0,
    sample_rate_hz: float = 100.0,
    snr_threshold: float = 3.0,
) -> dict[str, Any]:
    """mock EAG (Electroantennogram) 測定。 probe_id + odor_name から deterministic
    波形を生成、 SNR と D-FUMT₈ verdict (STEP 1350 mapping subset) を返す。

    ★ v0.1 spike: 実 hardware 送出なし、 全 return dict で is_mock: True。
    実 EAG physics (ion channel kinetics 等) を模倣していない = interface skeleton のみ。

    Args:
        probe_id: list_probes() の 'probe_id' field (例: 'silkworm-antenna-a1')。
        odor_name: 提示 匂い名 (例: 'cis-3-hexenol')、 mock stimulus。
        duration_s: 測定継続時間 (秒)、 default 3.0、 must be > 0。
        sample_rate_hz: サンプリング周波数 (Hz)、 default 100.0、 must be > 0。
        snr_threshold: D-FUMT₈ verdict 境界 (default 3.0、 STEP 1350 primitive と同)。

    Returns dict with: ok, probe_id, probe_layer, odor_name, duration_s,
    sample_rate_hz, sample_count, waveform_mv (list[float]), peak_mv,
    amp_estimated_mv, noise_floor_mv, snr_ratio, snr_threshold,
    verdict_d8 ('TRUE' or 'NEITHER'), verdict_d8_symbol ('⊤' or '〜'),
    verdict_reason, is_mock: True, hardware_available: False, honest_scope,
    d8_mapping_source, source。
    """
    return _ol_measure_eag(probe_id, odor_name, duration_s, sample_rate_hz, snr_threshold)


@server.tool()
def probe_health(
    probe_id: str,
    age_hours: float,
    last_calibration_hours_ago: float = 0.0,
    calibration_max_interval_hours: float = 24.0,
) -> dict[str, Any]:
    """probe 劣化 verdict。 age_hours + 校正経過時間から HEALTHY / DEGRADING /
    EXPIRED / UNCALIBRATED を返す。

    3 layer 別 degradation model:
      ① bio-hybrid    = linear (hydrogel dehydration)
      ② receptor-chip = exponential (protein denaturation)
      ③ bio-inspired  = calibration-only (silicon、 生体劣化なし)

    Args:
        probe_id: list_probes() の 'probe_id' field。
        age_hours: probe 開梱後経過時間 (時間)、 must be >= 0。
        last_calibration_hours_ago: 最後の校正からの経過時間 (時間)、 default 0。
        calibration_max_interval_hours: 校正有効期間 (時間)、 default 24 (daily calibration)。

    Returns dict with: ok, probe_id, layer, layer_number, age_hours,
    expected_lifetime_hours, age_ratio, health_score (0.0-1.0),
    verdict ('HEALTHY' / 'DEGRADING' / 'EXPIRED' / 'UNCALIBRATED'),
    verdict_reason, degradation_model, is_calibrated, last_calibration_hours_ago,
    calibration_max_interval_hours, is_mock: True, hardware_available: False,
    honest_scope, reference, source。
    """
    return _ol_probe_health(
        probe_id, age_hours, last_calibration_hours_ago, calibration_max_interval_hours
    )


# ---------------------------------------------------------------------------
# v0.8.0-alpha (2026-08-26): Akizuki wire-up 3 layer mock spike (4 tools)
# ---------------------------------------------------------------------------
#   藤本さん directive 「(1)(2)(3) を 順番に」 実装、 Rei stack STEP 1406 秋月
#   I2C/SPI/UART wire-up 候補 list から 3 SKU pilot を benchtop mock として 追加。
#
#   4 tool = list_akizuki_probes / measure_environment / measure_orientation / measure_distance
#   3 layer = ① environment (BME280 温湿度気圧、 Akizuki 109421 ¥1,180)
#             ② inertial   (BNO055 9軸 fusion、 Akizuki 116996 ¥3,850)
#             ③ distance   (VL53L1X ToF、 Akizuki 114249 ¥1,780)
#
#   ★ hardware 未取得 = 全 return dict で hardware_available: False + is_mock: True。
#   ★ mock 値は deterministic (probe_id + tag hash seed 由来)、 実 sensor physics
#      (Bosch calibration / on-chip fusion / SPAD) 模倣なし = interface skeleton のみ
#      ([[feedback-super-naming-siren-family-pattern]])。
#   ★ STEP 1350 d8_verdict_from_measurement primitive を 2 値 subset で 参照。
# ---------------------------------------------------------------------------


@server.tool()
def list_akizuki_probes() -> dict[str, Any]:
    """内蔵 mock probe registry (Akizuki wire-up 3 SKU) の 一覧を返す。
    全 probe は hardware_available: False。

    3 probe (STEP 1406 wire-up 候補 list から 各 layer 代表 SKU 選定):
      - bme280-env-a1 (environment、 BME280 温湿度気圧、 Akizuki 109421)
      - bno055-imu-b1 (inertial、 BNO055 9軸 fusion、 Akizuki 116996)
      - vl53l1x-tof-c1 (distance、 VL53L1X ToF、 Akizuki 114249)

    Returns dict with: ok, probes (list, with akizuki_code + price_jpy + range),
    probe_count, hardware_available: False, is_mock: True, honest_scope,
    related_step, source。
    """
    return _ak_list_probes()


@server.tool()
def measure_environment(
    probe_id: str,
    condition_tag: str = "room-default",
) -> dict[str, Any]:
    """mock 環境測定 (BME280 style: 温度 / 湿度 / 気圧)。 probe_id + condition_tag から
    deterministic な 3 値を生成、 BME280 datasheet range 内 か verdict を返す。

    ★ v0.1 spike: 実 hardware 送出なし、 全 return dict で is_mock: True。
    実 BME280 physics (Bosch calibration curve 等) を 模倣していない = interface skeleton のみ。

    Args:
        probe_id: list_akizuki_probes() の 'probe_id' (現状 'bme280-env-a1' のみ)。
        condition_tag: 想定 環境 tag (例: 'room-default' / 'outdoor-summer' / 'freezer')。

    Returns dict with: ok, probe_id, probe_layer, part_number, condition_tag,
    temperature_c, humidity_pct, pressure_hpa, in_range_all,
    verdict_d8 ('TRUE' or 'NEITHER'), verdict_d8_symbol, verdict_reason,
    is_mock: True, hardware_available: False, honest_scope,
    d8_mapping_source, source。
    """
    return _ak_measure_environment(probe_id, condition_tag)


@server.tool()
def measure_orientation(
    probe_id: str,
    motion_tag: str = "static-level",
) -> dict[str, Any]:
    """mock 慣性測定 (BNO055 style: quaternion + euler + linear_acc + magnetic)。
    probe_id + motion_tag から deterministic な orientation を生成、
    quaternion は unit-norm 保証、 euler → ZYX 変換で 単位化。

    ★ v0.1 spike: 実 hardware 送出なし、 全 return dict で is_mock: True。
    実 BNO055 on-chip fusion (Cortex-M0+ で Madgwick/Mahony 相当) 模倣なし = skeleton のみ。

    Args:
        probe_id: list_akizuki_probes() の 'probe_id' (現状 'bno055-imu-b1' のみ)。
        motion_tag: 想定 動作 tag (例: 'static-level' / 'tilt-30deg-x' / 'shake')。

    Returns dict with: ok, probe_id, probe_layer, part_number, motion_tag,
    quaternion {w, x, y, z}, euler_deg {roll, pitch, yaw},
    linear_acc_m_s2 {x, y, z}, magnetic_uT {x, y, z},
    calibration_status {sys, gyro, acc, mag}, quaternion_norm, is_unit_quat,
    is_mock: True, hardware_available: False, honest_scope,
    d8_mapping_source, source。
    """
    return _ak_measure_orientation(probe_id, motion_tag)


@server.tool()
def measure_distance(
    probe_id: str,
    target_tag: str = "wall-2m",
    timing_budget_ms: float = 100.0,
) -> dict[str, Any]:
    """mock ToF 距離測定 (VL53L1X style)。 probe_id + target_tag から deterministic
    距離 (mm) を生成、 VL53L1X datasheet 有効範囲 (30〜4000mm) 内 か verdict を返す。

    ★ v0.1 spike: 実 hardware 送出なし、 全 return dict で is_mock: True。
    実 VL53L1X physics (940nm laser SPAD photon counting) 模倣なし = skeleton のみ。
    timing_budget は 実 hardware では 精度 trade-off だが、 本 mock では 値に影響なし。

    Args:
        probe_id: list_akizuki_probes() の 'probe_id' (現状 'vl53l1x-tof-c1' のみ)。
        target_tag: 想定 対象 tag (例: 'wall-2m' / 'ceiling-3m' / 'obstacle-close-50cm')。
        timing_budget_ms: VL53L1X の 測定 budget (20-500 ms)、 default 100 ms。

    Returns dict with: ok, probe_id, probe_layer, part_number, target_tag,
    distance_mm, timing_budget_ms, range_status ('VALID'/'TOO_CLOSE'/'TOO_FAR'),
    in_range, verdict_d8 ('TRUE' or 'NEITHER'), verdict_d8_symbol,
    verdict_reason, is_mock: True, hardware_available: False, honest_scope,
    d8_mapping_source, source。
    """
    return _ak_measure_distance(probe_id, target_tag, timing_budget_ms)


@server.tool()
def list_sessions(limit: int = 30) -> dict[str, Any]:
    """保存済みの計測セッションを新しい順に一覧する。"""
    return {"data_dir": str(DATA_DIR), "sessions": Bench.list_sessions(limit)}


@server.tool()
def analyze_session(sid: str = "", session_id: str = "") -> dict[str, Any]:
    """保存済みセッションをチャンネルごとに統計解析する。

    件数・平均・標準偏差・最小/最大・ドリフト（最終値-初期値）を返し、
    平均から3σ以上離れた点を外れ値として列挙する。
    装置の異常や測定のばらつきを判断するために使う。
    存在しない session_id は structured error dict を返す (例外は投げない)。

    引数名について (2026-08-25): セッション ID は **`sid`** で渡すこと。
    `session_id` は後方互換の別名。remote-devices MCP proxy 経由だと
    `session_id` という名前の引数が proxy 側の routing field と衝突して
    無音で剥がされ、サーバに届かない。
    """
    _sid = _resolve_sid(sid, session_id)
    if isinstance(_sid, dict):
        return _sid
    session_id = _sid
    s = _load_session_or_error(session_id)
    if isinstance(s, dict):
        return s
    return Bench.analyze(s)


@server.tool()
def export_session_csv(out_path: str, sid: str = "", session_id: str = "") -> dict[str, Any]:
    """保存済みセッションを CSV ファイルに書き出す。

    存在しない session_id は structured error dict を返す (例外は投げない)。

    Args:
        sid: 対象のセッションID (別名 `session_id` も可)。
        out_path: 書き出し先のファイルパス。例: '/tmp/run1.csv'

    引数名について (2026-08-25): セッション ID は **`sid`** で渡すこと。
    `session_id` は後方互換の別名。remote-devices MCP proxy 経由だと
    `session_id` という名前の引数が proxy 側の routing field と衝突して
    無音で剥がされ、サーバに届かない。
    """
    _sid = _resolve_sid(sid, session_id)
    if isinstance(_sid, dict):
        return _sid
    session_id = _sid
    s = _load_session_or_error(session_id)
    if isinstance(s, dict):
        _write_audit(action="export_session_csv", target=session_id, result="error",
                     detail={"error": s.get("error"), "out_path": out_path})
        return s
    p = Bench.export_csv(s, out_path)
    result = {"session_id": session_id, "path": str(p), "n_rows": len(s.rows), "columns": ["t"] + s.channels}
    _write_audit(action="export_session_csv", target=session_id, result="success",
                 detail={"path": str(p), "n_rows": len(s.rows)})
    return result


# ---------------------------------------------------------------------------
# MCP 層 v0.2 追加ツール
# ---------------------------------------------------------------------------


@server.tool()
def plot_session(width: int = 60, sid: str = "", session_id: str = "") -> dict[str, Any]:
    """保存済みセッションを ASCII スパークライン (▁▂▃▄▅▆▇█) で視覚化する。

    各チャンネル別に、値の時系列を Unicode ブロック文字 8 段階で表現し、
    min/max/mean/range も同時に返す。matplotlib 等の依存を増やさず、Excel を
    開かずに傾向・外れ値の位置をざっくり把握したいときに使う。
    存在しない session_id は structured error dict を返す (例外は投げない)。

    Args:
        sid: 対象のセッションID (別名 `session_id` も可)。
        width: スパークラインの横幅（サンプル数がこれより多ければ平均でビン化）。
               既定は 60。1 以上を指定すること。

    引数名について (2026-08-25): セッション ID は **`sid`** で渡すこと。
    `session_id` は後方互換の別名。remote-devices MCP proxy 経由だと
    `session_id` という名前の引数が proxy 側の routing field と衝突して
    無音で剥がされ、サーバに届かない。
    """
    _sid = _resolve_sid(sid, session_id)
    if isinstance(_sid, dict):
        return _sid
    session_id = _sid
    s = _load_session_or_error(session_id)
    if isinstance(s, dict):
        return s
    return Bench.plot(s, width)


@server.tool()
def compare_sessions(
    session_id_a: str,
    session_id_b: str,
    z_threshold: float = 3.0,
) -> dict[str, Any]:
    """2 つのセッションをチャンネル単位で比較する。

    共通する各チャンネルについて mean・stdev・drift の差分と、Welch 型の
    t 統計量 (z として返す) を計算する。式は 1 本:

        z = (mean_A - mean_B) / sqrt(sigma_A^2 / n_A + sigma_B^2 / n_B)

    これは Welch's t 検定の統計量そのもの。異なるのは判定則:
      - Welch's t-test: t 分布 critical value (df 依存) で判定 → p 値
      - この tool: 固定閾値 z_threshold (既定 3.0) で単純 gate

    per-channel に `welch_df` (Welch-Satterthwaite 自由度) を返すので、
    caller は 「今回の n で固定 3.0 が甘い/厳しい」 を自分で判定できる。

    判定は呼び出し側の責任:
      - `mean_shift_z` は生の t 統計量 (guard 時は None)
      - `welch_df` は自由度 (guard 時は None)
      - `significant_shift` は |z| > z_threshold (guard 時は None)
      - `gate_evaluable` + `gate_skip_reason` で 「gate 未評価」 を明示
      - top-level `is_hypothesis_test: false` + `disclaimer` で
        「これは検定ではない」を機械可読 field として提示

    v0.2.3 guard: n<2 (stdev 未定義) と σ 合成=0 (定数装置) では
    gate 評価不能。z / welch_df / significant_shift はすべて None、
    `gate_skip_reason` に理由 (`"insufficient_samples"` or `"zero_variance"`)。
    None は 「差が無い」 ではなく 「gate 未評価」 と読むこと。

    存在しない session_id は structured error dict を返す (例外は投げない)。
    入力のどちらかが aborted (partial) な場合は top-level の
    `any_input_aborted: true` + `aborted_inputs: ["a"/"b"]` で通知される。

    Args:
        session_id_a: 比較元のセッションID (通常は新しい方)。
        session_id_b: 比較先のセッションID (通常は古い方・基準)。
        z_threshold: |z| がこの値を超えたとき significant_shift=True になる正の実数。
                     既定は 3.0 (df に依らない固定値)。厳密な検定をしたいときは
                     この値と `welch_df` を見て外部で t 分布 CDF に流すこと。
    """
    a = _load_session_or_error(session_id_a)
    if isinstance(a, dict):
        _write_audit(action="compare_sessions", target=f"{session_id_a}|{session_id_b}",
                     result="error", detail={"error": a.get("error"), "which": "a"})
        return a
    b = _load_session_or_error(session_id_b)
    if isinstance(b, dict):
        _write_audit(action="compare_sessions", target=f"{session_id_a}|{session_id_b}",
                     result="error", detail={"error": b.get("error"), "which": "b"})
        return b
    result = Bench.compare(a, b, z_threshold)
    _write_audit(action="compare_sessions", target=f"{session_id_a}|{session_id_b}",
                 result="success",
                 detail={"z_threshold": z_threshold, "n_a": len(a.rows), "n_b": len(b.rows)})
    return result


@server.tool()
def search_sessions(
    since: str | None = None,
    until: str | None = None,
    note_contains: str | None = None,
    port: str | None = None,
    channel: str | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    """保存済みセッションを条件で絞り込む。

    list_sessions は直近 N 件しか返さないので、セッションが増えたらこちらを
    使う。全条件 AND。

    **v0.2.4 date-only 解釈** (藤本さん 2026-08-13 verify 発火 pain fix):
    since / until が `YYYY-MM-DD` 形式 (時刻部分なし) のとき、**local
    midnight として解釈** し UTC 換算後に比較する。since=当日 00:00 local、
    until=当日 23:59:59.999999 local。つまり `since='2026-08-13'` は
    「手元の時計で 8/13 以降」 と直感的に一致する。時刻 + offset まで書いた
    完全 ISO 文字列 (例 `'2026-08-13T00:00:00+09:00'`) は従来通り厳密比較。
    tz は `BENCHTOP_TZ` env 優先、無ければ system local。

    返り値の `filters` に `since_resolved_utc` / `until_resolved_utc` /
    `since_date_only` / `until_date_only` / `tz_used` を併記するので、
    「意図した通り解釈されたか」 は audit trail から確認できる。

    Args:
        since: この日時以降のみ。'YYYY-MM-DD' なら local midnight、完全 ISO なら厳密。
        until: この日時以前のみ。'YYYY-MM-DD' なら local day-end、完全 ISO なら厳密。
        note_contains: note に含まれる文字列 (大文字小文字を区別しない)。
        port: このポートで計測したものだけ (完全一致)。
        channel: このチャンネルを含むものだけ (例: 'T', 'V', 'ch1')。
        limit: 返す最大件数。既定は 30。
    """
    meta: dict[str, Any] = {}
    sessions = Bench.search_sessions(
        since, until, note_contains, port, channel, limit, _meta_out=meta
    )
    return {
        "data_dir": str(DATA_DIR),
        "filters": {
            "since": since,
            "since_resolved_utc": meta.get("since_resolved_utc"),
            "since_date_only": meta.get("since_date_only", False),
            "until": until,
            "until_resolved_utc": meta.get("until_resolved_utc"),
            "until_date_only": meta.get("until_date_only", False),
            "note_contains": note_contains,
            "port": port,
            "channel": channel,
            "limit": limit,
            "tz_used": meta.get("tz_used"),
        },
        "sessions": sessions,
    }


# ---------------------------------------------------------------------------
# v0.3.0: audit log verify tool
# ---------------------------------------------------------------------------


@server.tool()
def verify_audit_chain(audit_dir: str | None = None) -> dict[str, Any]:
    """audit log の sha256 prev-hash chain 整合性を検証する (v0.3.0)。

    audit log は 全 tool 呼び出しの 説明責任 (accountability) 記録で、
    append-only JSONL に sha256 prev-hash を 埋め込む形で改竄検出可能。
    各行は 前行の sha256 を `prev` field に含み、 一行でも 内容を書き換えると
    後続 line の prev と 不一致になる。

    証跡が価値になる領域 (ISO/IEC 17025 校正 / GMP 医薬品製造記録 /
    監査対応) 用途で、 「この時期の 計測結果は 事後改竄されていない」 を
    機械的に verify する 一次手段。

    Args:
        audit_dir: 検証対象の audit log dir。 省略時は BENCHTOP_AUDIT_DIR env
                   or `~/.benchtop-mcp/audit`。

    Returns:
        {"valid": True, "total": N} — chain 完全 (N 件の entry 全て 整合)
        {"valid": False, "broken_at": i, "total": N} — line i (0-indexed) で
          chain 破断検出、 それ以前は 整合、 それ以降は 未検証
        {"valid": True, "total": 0} — audit log 未生成 (integrity としては vacuously true)
    """
    target_dir = audit_dir if audit_dir is not None else str(AUDIT_DIR)
    return AuditLogWriter.verify_chain(target_dir)


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------


def _selftest() -> int:
    """実機も Claude も無い状態で、コアロジックが動くか確認する。"""
    # Windows の CP932 端末では Unicode ブロック文字 (▁▂…█) が出力できないので
    # stdout を UTF-8 に切り替える (Python 3.7+ の reconfigure が使える環境のみ)。
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    print("== benchtop-mcp セルフテスト ==")
    ports = BENCH.list_ports()
    print(f"[1] ポート一覧: {len(ports)}件 / pyserial={HAS_SERIAL}")
    assert any(p["port"] == MOCK_PORT for p in ports)

    print(f"[2] IDN応答: {BENCH.send_command(MOCK_PORT, '*IDN?')}")

    assert parse_line("T=25.3,H=48.1") == {"T": 25.3, "H": 48.1}
    assert parse_line("25.3,48.1") == {"ch1": 25.3, "ch2": 48.1}
    assert parse_line("25.3") == {"value": 25.3}
    assert parse_line("garbage!!") == {}
    print("[3] パース: 4形式すべてOK")

    s = BENCH.measure(port=MOCK_PORT, samples=60, interval_ms=0, note="selftest")
    print(f"[4] 計測: {len(s.rows)}行 / channels={s.channels}")
    assert len(s.rows) == 60 and s.channels == ["T", "H", "V"]

    a = Bench.analyze(load_session(s.id))
    t = a["channels"]["T"]
    print(f"[5] 解析: T平均={t['mean']} σ={t['stdev']} 外れ値={t['n_outliers']}件")
    assert 20 < t["mean"] < 30

    out = Bench.export_csv(load_session(s.id), DATA_DIR / f"{s.id}.csv")
    n = len(out.read_text().strip().splitlines())
    print(f"[6] CSV書き出し: {out} ({n}行=ヘッダ1+データ60)")
    assert n == 61

    # v0.2 追加 phase --------------------------------------------------------

    plot = Bench.plot(load_session(s.id), width=40)
    t_spark = plot["channels"]["T"]["sparkline"]
    print(f"[7] plot: width=40 T='{t_spark}' (len={len(t_spark)}, range={plot['channels']['T']['range']})")
    assert 0 < len(t_spark) <= 40
    assert all(c in _SPARK_CHARS for c in t_spark)
    assert plot["channels"]["T"]["range"] >= 0

    s2 = BENCH.measure(port=MOCK_PORT, samples=60, interval_ms=0, note="selftest-b")
    cmp = Bench.compare(load_session(s.id), load_session(s2.id))
    t_cmp = cmp["channels"]["T"]
    print(
        f"[8] compare: shared={cmp['shared_channels']} "
        f"T delta_mean={t_cmp['delta_mean']} z={t_cmp['mean_shift_z']} "
        f"significant={t_cmp['significant_shift']}"
    )
    assert "T" in cmp["shared_channels"] and "H" in cmp["shared_channels"] and "V" in cmp["shared_channels"]
    assert cmp["only_in_a"] == [] and cmp["only_in_b"] == []
    assert "delta_mean" in t_cmp and "mean_shift_z" in t_cmp

    hits = Bench.search_sessions(note_contains="selftest", limit=100)
    ids = {h["session_id"] for h in hits}
    print(f"[9] search: note='selftest' で {len(hits)} 件ヒット (s={s.id in ids}, s2={s2.id in ids})")
    assert s.id in ids and s2.id in ids
    hits_b = Bench.search_sessions(note_contains="selftest-b", limit=100)
    assert any(h["session_id"] == s2.id for h in hits_b)
    assert all("selftest-b" in (h["note"] or "").lower() for h in hits_b)
    hits_port = Bench.search_sessions(port=MOCK_PORT, note_contains="selftest", limit=100)
    assert s.id in {h["session_id"] for h in hits_port}
    hits_none = Bench.search_sessions(note_contains="__no_such_marker__", limit=10)
    assert hits_none == []

    # v0.2.1 追加 phase --------------------------------------------------------

    err = _load_session_or_error("no-such-session-id-xyz")
    assert isinstance(err, dict) and err.get("error") == "session_not_found"
    ok = _load_session_or_error(s.id)
    assert isinstance(ok, Session)
    print(f"[10] invalid id → structured error='{err['error']}' / 有効 id → Session OK")

    cmp_strict = Bench.compare(load_session(s.id), load_session(s2.id), z_threshold=3.0)
    cmp_loose = Bench.compare(load_session(s.id), load_session(s2.id), z_threshold=0.5)
    z = cmp_strict["channels"]["T"]["mean_shift_z"]
    df_strict = cmp_strict["channels"]["T"]["welch_df"]
    strict_sig = cmp_strict["channels"]["T"]["significant_shift"]
    loose_sig = cmp_loose["channels"]["T"]["significant_shift"]
    print(
        f"[11] compare threshold: |z|={abs(z)} welch_df={df_strict} "
        f"strict(3.0)={strict_sig} loose(0.5)={loose_sig}"
    )
    assert cmp_strict["z_threshold_used"] == 3.0
    assert cmp_loose["z_threshold_used"] == 0.5
    assert cmp_strict["channels"]["T"]["z_threshold_used"] == 3.0
    assert strict_sig == (abs(z) > 3.0)
    assert loose_sig == (abs(z) > 0.5)
    # v0.2.3: 正常 n では welch_df が非 None (df ~ 2n-2 に近づくはず, n=60 で df~118)
    assert df_strict is not None and df_strict > 50
    try:
        Bench.compare(load_session(s.id), load_session(s2.id), z_threshold=0)
        raise AssertionError("z_threshold=0 が ValueError にならなかった")
    except ValueError:
        pass

    class _FailingDevice(Device):
        """selftest 用: N 回読んだ後 RuntimeError を投げる仮想装置。"""

        def __init__(self, fail_after: int) -> None:
            self._n = 0
            self._fail_after = fail_after
            self._real = MockDevice(seed=42)

        def send(self, command: str) -> str:
            return self._real.send(command)

        def read_line(self) -> str:
            self._n += 1
            if self._n > self._fail_after:
                raise RuntimeError(f"simulated device failure after {self._fail_after} reads")
            return self._real.read_line()

    fail_after = 5
    BENCH._devices["fail-selftest@9600"] = _FailingDevice(fail_after=fail_after)
    s3 = BENCH.measure(port="fail-selftest", samples=20, interval_ms=0, note="selftest-partial")
    print(
        f"[12] partial measurement: n_rows={len(s3.rows)}/20 "
        f"aborted={s3.aborted_at is not None} reason='{s3.abort_reason}'"
    )
    assert s3.aborted_at is not None
    assert s3.abort_reason and "RuntimeError" in s3.abort_reason
    # 5 回成功 → 6 回目で失敗、rows は 5 前後 (interval_ms=0 なので誤差極小)。
    assert 1 <= len(s3.rows) <= fail_after + 1
    partial_hit = Bench.search_sessions(note_contains="selftest-partial", limit=10)
    assert any(h["session_id"] == s3.id for h in partial_hit)

    # [13] partial session が下流 (analyze/plot/compare/search) で消えないこと
    ana_partial = Bench.analyze(load_session(s3.id))
    ana_normal = Bench.analyze(load_session(s.id))
    plot_partial = Bench.plot(load_session(s3.id), width=20)
    plot_normal = Bench.plot(load_session(s.id), width=20)
    cmp_asym = Bench.compare(load_session(s.id), load_session(s3.id))
    cmp_clean = Bench.compare(load_session(s.id), load_session(s2.id))
    search_all = Bench.search_sessions(note_contains="selftest", limit=100)
    partial_rows = [h for h in search_all if h["session_id"] == s3.id]
    normal_rows = [h for h in search_all if h["session_id"] == s.id]
    print(
        f"[13] partial downstream: "
        f"analyze.partial={ana_partial['partial']}/{ana_normal['partial']} "
        f"plot.partial={plot_partial['partial']}/{plot_normal['partial']} "
        f"cmp.any_aborted={cmp_asym['any_input_aborted']}/{cmp_clean['any_input_aborted']} "
        f"cmp.aborted_inputs={cmp_asym['aborted_inputs']} "
        f"search.partial={partial_rows[0]['partial'] if partial_rows else '?'}/"
        f"{normal_rows[0]['partial'] if normal_rows else '?'}"
    )
    # analyze / plot: partial 情報が top-level に mirror されている
    assert ana_partial["partial"] is True and ana_normal["partial"] is False
    assert plot_partial["partial"] is True and plot_normal["partial"] is False
    assert "RuntimeError" in (ana_partial["abort_reason"] or "")
    assert "channels_order" in plot_partial and plot_partial["channels_order"]
    for ch, entry in plot_partial["channels"].items():
        assert entry["label"] == ch
    # compare: 非対称入力を top-level で explicit 検出、per-input dict にも partial
    assert cmp_asym["any_input_aborted"] is True
    assert cmp_asym["aborted_inputs"] == ["b"]
    assert cmp_asym["a"]["partial"] is False and cmp_asym["b"]["partial"] is True
    assert cmp_asym["is_hypothesis_test"] is False
    assert "z_formula" in cmp_asym and "disclaimer" in cmp_asym
    for ch_entry in cmp_asym["channels"].values():
        assert ch_entry["interpretation"] == "welch_t_statistic_with_fixed_z_threshold"
        # v0.2.3: 正常 n では welch_df + gate_evaluable が付いていること
        assert ch_entry["welch_df"] is not None and ch_entry["welch_df"] > 0
        assert ch_entry["gate_evaluable"] is True
        assert ch_entry["gate_skip_reason"] is None
    # clean な 2 セッション同士は any_input_aborted=false、aborted_inputs=[]
    assert cmp_clean["any_input_aborted"] is False and cmp_clean["aborted_inputs"] == []
    # search: partial=true/false が各行に立つ
    assert partial_rows and partial_rows[0]["partial"] is True
    assert normal_rows and normal_rows[0]["partial"] is False

    # [15] は下でまとめて置く (guard 系 [14] の後)。 順序: [10]-[13] partial 系 → [14] guard 系 → [15] date-only 系。

    # [14] compare guard: zero_variance と insufficient_samples の 2 case
    # 旧実装 (v0.2.2 以前) では σ=0 で 0/0→NaN→significant_shift=False に落ちる
    # 「静かな bug」 が存在。v0.2.3 で明示 guard に分離。

    class _ConstDevice(Device):
        """selftest 用: 常に同一値を返す仮想装置 (σ=0 を作る)。"""

        def __init__(self, value: float = 3.3) -> None:
            self._v = value

        def send(self, command: str) -> str:
            return self.read_line()

        def read_line(self) -> str:
            return f"V={self._v:.4f}"

    # Case (a): 定数 mock 2 本 → σ=0 → zero_variance guard
    BENCH._devices["const-a@9600"] = _ConstDevice(3.3)
    BENCH._devices["const-b@9600"] = _ConstDevice(3.3)
    sc_a = BENCH.measure(port="const-a", samples=15, interval_ms=0, note="selftest-const-a")
    sc_b = BENCH.measure(port="const-b", samples=15, interval_ms=0, note="selftest-const-b")
    cmp_zv = Bench.compare(load_session(sc_a.id), load_session(sc_b.id))
    v_ch = cmp_zv["channels"]["V"]
    print(
        f"[14a] zero variance guard: evaluable={v_ch['gate_evaluable']} "
        f"reason={v_ch['gate_skip_reason']} z={v_ch['mean_shift_z']} "
        f"sig={v_ch['significant_shift']} df={v_ch['welch_df']}"
    )
    assert v_ch["gate_evaluable"] is False
    assert v_ch["gate_skip_reason"] == "zero_variance"
    assert v_ch["mean_shift_z"] is None
    assert v_ch["significant_shift"] is None
    assert v_ch["welch_df"] is None
    assert v_ch["standard_error"] is None

    # Case (b): n=1 の partial × 正常 → insufficient_samples guard
    BENCH._devices["fail-immediate@9600"] = _FailingDevice(fail_after=1)
    s_tiny = BENCH.measure(port="fail-immediate", samples=10, interval_ms=0, note="selftest-tiny")
    assert len(s_tiny.rows) == 1, f"想定 n=1 だが {len(s_tiny.rows)} 行"
    cmp_tiny = Bench.compare(load_session(s_tiny.id), load_session(s.id))
    t_ch = cmp_tiny["channels"]["T"]
    print(
        f"[14b] insufficient n guard: evaluable={t_ch['gate_evaluable']} "
        f"reason={t_ch['gate_skip_reason']} n_a={t_ch['a']['n']} n_b={t_ch['b']['n']}"
    )
    assert t_ch["gate_evaluable"] is False
    assert t_ch["gate_skip_reason"] == "insufficient_samples"
    assert t_ch["mean_shift_z"] is None
    assert t_ch["significant_shift"] is None
    assert t_ch["welch_df"] is None
    # top-level は依然 partial 情報を露出 (guard と直交)
    assert cmp_tiny["any_input_aborted"] is True
    assert cmp_tiny["aborted_inputs"] == ["a"]

    # Case (c): guard 発火する chunk と発火しない chunk が同 dict で共存できる
    # (V チャンネルの zero_variance 判定は T チャンネルの正常判定に影響しない)
    print(
        f"[14c] guard 独立性: 正常 case (phase [11] 再利用) "
        f"evaluable={cmp_strict['channels']['T']['gate_evaluable']} 対 "
        f"guard case evaluable={cmp_zv['channels']['V']['gate_evaluable']}"
    )
    assert cmp_strict["channels"]["T"]["gate_evaluable"] is True
    assert cmp_zv["channels"]["V"]["gate_evaluable"] is False

    # [15] date-only since/until local 解釈 (v0.2.4 主 fix、 藤本さん 2026-08-13 verify 発火 pain)
    # 「JST 早朝に測った session が since='当日' で 消える」 pain を 再現 + fix verify。
    # test 内 env 変更は 元値保存 + finally 復元 (副作用ゼロ)。
    old_tz = os.environ.get("BENCHTOP_TZ")
    try:
        # JST 固定 (どの環境でも 同じ結果)
        os.environ["BENCHTOP_TZ"] = "Asia/Tokyo"

        # [15a] date-only since は local midnight として解釈される
        meta_a: dict[str, Any] = {}
        Bench.search_sessions(since="2026-08-13", limit=1, _meta_out=meta_a)
        print(
            f"[15a] date-only 'since=2026-08-13' → resolved_utc={meta_a['since_resolved_utc']} "
            f"date_only={meta_a['since_date_only']} tz={meta_a['tz_used']}"
        )
        assert meta_a["since_date_only"] is True
        assert meta_a["tz_used"] == "Asia/Tokyo"
        # JST 8/13 00:00 = UTC 8/12 15:00
        assert meta_a["since_resolved_utc"].startswith("2026-08-12T15:00:00")

        # [15b] 完全 ISO は 従来通り 厳密 (resolve せず そのまま)
        meta_b: dict[str, Any] = {}
        Bench.search_sessions(since="2026-08-13T00:00:00+00:00", limit=1, _meta_out=meta_b)
        print(
            f"[15b] full ISO 'since=2026-08-13T00:00:00+00:00' → "
            f"resolved_utc={meta_b['since_resolved_utc']} date_only={meta_b['since_date_only']}"
        )
        assert meta_b["since_date_only"] is False
        assert meta_b["since_resolved_utc"] == "2026-08-13T00:00:00+00:00"

        # [15c] 藤本さん verify 発火 case 再現: JST 早朝 session が since='当日' で 拾える
        # started_at を JST 8/13 00:30 (= UTC 8/12 15:30) で fake session を作る
        fake_started_utc = "2026-08-12T15:30:00+00:00"
        fake_id = "20260813-003000-999"
        fake_session = Session(
            id=fake_id, port=MOCK_PORT, started_at=fake_started_utc, note="selftest-jst-early",
            channels=["T"], rows=[{"t": 0.0, "T": 25.0}],
        )
        fake_session.save()
        hits = Bench.search_sessions(since="2026-08-13", note_contains="selftest-jst-early", limit=10)
        found = any(h["session_id"] == fake_id for h in hits)
        print(
            f"[15c] JST 早朝 session (started={fake_started_utc}) が "
            f"since='2026-08-13' で 拾える → found={found} (旧 v0.2.3 では 拾えなかった)"
        )
        assert found is True, "v0.2.4 主 fix (date-only local 解釈) が 効いていない"

        # [15d] started_at_local 補助 field 各 tool で 出る
        hits2 = Bench.search_sessions(note_contains="selftest-jst-early", limit=5)
        assert hits2 and "started_at_local" in hits2[0]
        assert hits2[0]["started_at_local"] and "+09:00" in hits2[0]["started_at_local"]
        ana_local = Bench.analyze(load_session(fake_id))
        assert "started_at_local" in ana_local and "+09:00" in ana_local["started_at_local"]
        plot_local = Bench.plot(load_session(fake_id), width=5)
        assert "started_at_local" in plot_local and "+09:00" in plot_local["started_at_local"]
        cmp_local = Bench.compare(load_session(fake_id), load_session(s.id))
        assert "started_at_local" in cmp_local["a"] and "+09:00" in cmp_local["a"]["started_at_local"]
        print(
            f"[15d] started_at_local 補助 field: search[0]={hits2[0]['started_at_local']} "
            f"analyze={ana_local['started_at_local']} (JST +09:00 一貫)"
        )
    finally:
        if old_tz is None:
            os.environ.pop("BENCHTOP_TZ", None)
        else:
            os.environ["BENCHTOP_TZ"] = old_tz

    # [17] v0.4.0 実験ノート: subject / environment / instrument_config / mystery_id 拡張 +
    # find_similar_sessions で cross-session lookup verify (Session backward compat 含む)
    exp_env = {"temp_c": 25.3, "humidity": 48.1}
    exp_cfg = {"baudrate": 9600, "sampling_hz": 10, "calibration_ref": "NIST-selftest"}
    s17a = BENCH.measure(port="mock", samples=5, interval_ms=0,
                          note="selftest-v04-exp-notebook-a",
                          subject="test-device-A", environment=exp_env,
                          instrument_config=exp_cfg, mystery_id="mystery-42")
    s17b = BENCH.measure(port="mock", samples=5, interval_ms=0,
                          note="selftest-v04-exp-notebook-b",
                          subject="test-device-A", environment=exp_env,
                          instrument_config=exp_cfg, mystery_id="mystery-42")
    # Round-trip: 保存 → load → 拡張 fields 保持確認
    ld_a = load_session(s17a.id)
    assert ld_a.subject == "test-device-A", f"subject not persisted: {ld_a.subject}"
    assert ld_a.environment == exp_env, f"environment not persisted: {ld_a.environment}"
    assert ld_a.instrument_config == exp_cfg, f"instrument_config not persisted"
    assert ld_a.mystery_id == "mystery-42", f"mystery_id not persisted: {ld_a.mystery_id}"

    # subject 完全一致 filter
    r17_subj = find_similar_sessions(subject="test-device-A", limit=10)
    n_subj = len(r17_subj["sessions"])
    assert n_subj >= 2, f"subject filter で 2 件以上 期待 だが {n_subj}"
    ids_subj = {row["session_id"] for row in r17_subj["sessions"]}
    assert s17a.id in ids_subj and s17b.id in ids_subj

    # mystery_id 完全一致
    r17_mys = find_similar_sessions(mystery_id="mystery-42", limit=10)
    n_mys = len(r17_mys["sessions"])
    assert n_mys >= 2, f"mystery_id filter で 2 件以上 期待 だが {n_mys}"

    # environment_key tolerance 数値近似
    r17_env = find_similar_sessions(environment_key="temp_c", environment_value=25.0,
                                     tolerance=1.0, limit=10)
    n_env = len(r17_env["sessions"])
    assert n_env >= 2, f"environment tolerance filter で 2 件以上 期待 だが {n_env}"

    # backward compat: 旧 JSON (v0.3.0 以前、 新 field なし) も load できる
    old_style_id = "20260817-000000-000"
    old_style_path = DATA_DIR / f"{old_style_id}.json"
    old_style_dict = {
        "id": old_style_id, "port": "mock",
        "started_at": "2026-08-17T00:00:00+00:00", "note": "selftest-v04-old-style",
        "channels": ["T"], "rows": [{"t": 0.0, "T": 25.0}], "skipped": 0,
        # 新 field なし = 旧 v0.3.0 相当
    }
    old_style_path.write_text(json.dumps(old_style_dict), encoding="utf-8")
    ld_old = load_session(old_style_id)
    assert ld_old.subject is None, "旧 JSON で subject default None 期待"
    assert ld_old.environment is None
    assert ld_old.mystery_id is None
    print(f"[17] v0.4 実験ノート: subject/env/mystery persisted (n_subj={n_subj} n_mys={n_mys} "
          f"n_env_tol={n_env}) + backward compat (old JSON load OK)")

    # [18] v0.4.0 regression_check: baseline vs current の tolerance-based gap detection
    # baseline (小 variance mock) vs current (同 mock 別 seed = 微小差、 tolerance 内)
    s18_base = BENCH.measure(port="mock", samples=30, interval_ms=0,
                              note="selftest-v04-regression-baseline",
                              subject="calibration-A", instrument_config={"cal_ref": "2026-08-17"})
    s18_curr = BENCH.measure(port="mock", samples=30, interval_ms=0,
                              note="selftest-v04-regression-current",
                              subject="calibration-A")
    r18a = regression_check(baseline_session_id=s18_base.id,
                             current_session_id=s18_curr.id,
                             tolerance_mean=5.0, tolerance_stdev_ratio=1.0)
    # 緩い tolerance (5.0) なら 通常 mock は regression=False 期待 (mock は 25 前後 σ<1)
    print(f"[18a] regression_check (緩い tol=5.0): any_regression={r18a['any_regression']} "
          f"shared_channels={r18a['shared_channels']}")
    assert "shared_channels" in r18a
    assert len(r18a["shared_channels"]) > 0

    # 厳しい tolerance (0.001) なら regression=True 期待 (mock noise > 0.001)
    r18b = regression_check(baseline_session_id=s18_base.id,
                             current_session_id=s18_curr.id,
                             tolerance_mean=0.001, tolerance_stdev_ratio=0.001)
    print(f"[18b] regression_check (厳しい tol=0.001): any_regression={r18b['any_regression']} "
          f"expected=True (mock noise)")
    # 厳しい tol で どこかの channel が 引っかかる 期待 (mock は 3 ch 全て noise あり)
    assert r18b["any_regression"] is True, "厳しい tol で 少なくとも 1 ch regression 期待"

    # error path: 存在しない session_id → structured error
    r18c = regression_check(baseline_session_id="nonexistent-xyz",
                             current_session_id=s18_curr.id)
    print(f"[18c] regression_check invalid baseline → error={r18c.get('error')}")
    assert r18c.get("error") == "session_not_found"
    assert r18c.get("session_id") == "nonexistent-xyz"

    # [16] audit log hash chain verify (v0.3.0 主 fix、 Rei-Automator STEP 1340 primitive port)
    # session store と 別 store で 全 tool 呼び出しの 説明責任 記録、 改竄検出可能。
    import tempfile
    from benchtop_audit_log import AuditLogWriter as _AL
    with tempfile.TemporaryDirectory(prefix="benchtop-audit-selftest-") as _tmpdir:
        # [16a] genesis chain: 3 entry 追加 → verify PASS
        w = _AL(_tmpdir)
        h1 = w.append(actor="selftest", action="measure", target="fake-1", result="success",
                      detail={"n": 10})
        h2 = w.append(actor="selftest", action="compare_sessions", target="fake-1|fake-2",
                      result="success", detail={"z_threshold": 3.0})
        h3 = w.append(actor="selftest", action="export_session_csv", target="fake-1",
                      result="success", detail={"path": "/tmp/x.csv"})
        chk1 = _AL.verify_chain(_tmpdir)
        print(f"[16a] genesis chain 3 entries: valid={chk1['valid']} total={chk1['total']} "
              f"head_prefix={h3[:16]}")
        assert chk1["valid"] is True
        assert chk1["total"] == 3

        # [16b] chain continuation: 新 writer instance で 続き append → PASS
        w2 = _AL(_tmpdir)
        assert w2.get_head() == h3, "new instance が 前 head を loadできていない"
        h4 = w2.append(actor="selftest", action="measure", target="fake-2",
                       result="partial", detail={"abort_reason": "test"})
        chk2 = _AL.verify_chain(_tmpdir)
        print(f"[16b] chain continuation: new instance loaded head={h3[:16]}, "
              f"appended → valid={chk2['valid']} total={chk2['total']}")
        assert chk2["valid"] is True
        assert chk2["total"] == 4

        # [16c] tamper detection: 中間 line の target を書き換え → verify で 検出
        audit_path = Path(_tmpdir) / "audit.jsonl"
        raw = audit_path.read_text(encoding="utf-8")
        lines = [ln for ln in raw.split("\n") if ln.strip()]
        entry_0 = json.loads(lines[0])
        entry_0["target"] = "TAMPERED"
        lines[0] = json.dumps(entry_0, ensure_ascii=False, separators=(",", ":"))
        audit_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        chk3 = _AL.verify_chain(_tmpdir)
        print(f"[16c] tamper detection: modified line 0 → valid={chk3['valid']} "
              f"broken_at={chk3.get('broken_at')} total={chk3['total']}")
        assert chk3["valid"] is False
        assert chk3["broken_at"] == 1, f"想定 broken_at=1 (line 0 hash 変化 → line 1 prev mismatch) だが {chk3.get('broken_at')}"

        # [16d] MCP tool level verify_audit_chain (tempdir 対象): 直後 valid (tamper 済 なので false)
        # 上の tamper 状態で MCP tool を 呼び出して 同結果か 確認
        chk4 = verify_audit_chain(audit_dir=_tmpdir)
        print(f"[16d] MCP tool verify_audit_chain(audit_dir={_tmpdir[-30:]}): "
              f"valid={chk4['valid']} broken_at={chk4.get('broken_at')}")
        assert chk4["valid"] is False
        assert chk4.get("broken_at") == 1

    # [19] v0.5.0-alpha SPIKE : import_external_session + SafetyGate + provenance layer
    # chat-Claude 2026-08-18 「MCP コネクタ世界一」 report §3-1 「機器層/記録層 分割」 の
    # 4 agent verify 済 実装。 3 case で 動作確認: valid import / Kikusui hazard reject /
    # audit chain 統合性維持。
    print("\n--- [19] v0.5.0-alpha SPIKE: import_external_session + SafetyGate ---")

    # [19a] valid external import: rigol-mcp mock 由来 record → accept + Session persist
    now_iso = _now()
    r19a = import_external_session(
        source="external:rigol-mcp-mock",
        records=[
            {"ts": now_iso, "channels": ["V", "I"], "values": {"V": 3.30, "I": 0.15}},
            {"ts": now_iso, "channels": ["V", "I"], "values": {"V": 3.31, "I": 0.14}},
            {"ts": now_iso, "channels": ["V", "I"], "values": {"V": 3.30, "I": 0.16}},
        ],
        subject="test-DUT-042",
        mystery_id="mys-spike-19a",
    )
    print(f"[19a] import valid rigol-mock (3 records): ok={r19a['ok']} "
          f"session_id={r19a['session_id']} accepted={r19a['records_accepted']} "
          f"rejected={r19a['records_rejected']}")
    assert r19a["ok"] is True
    assert r19a["records_accepted"] == 3
    assert r19a["records_rejected"] == 0
    assert r19a["session_id"] is not None
    assert r19a["session_id"].startswith("ext-external-rigol-mcp-mock-")
    # verify Session persisted with source field
    sess_a = load_session(r19a["session_id"])
    assert sess_a.source == "external:rigol-mcp-mock", f"source mismatch: {sess_a.source}"
    assert sess_a.subject == "test-DUT-042"
    assert sess_a.mystery_id == "mys-spike-19a"

    # [19b] Kikusui PLZ-5W CR mode Siemens hazard → reject
    # 「100 Ω」 のつもりで 100 (S) を送る → 0.01 Ω 短絡 hazard
    r19b = import_external_session(
        source="external:kikusui-mcp-mock",
        records=[
            # safe: legitimate 0.1 S = 10 Ω
            {"ts": now_iso, "channels": ["V"], "values": {"V": 3.3},
             "instrument": {"vendor": "KIKUSUI", "model": "PLZ1205W"},
             "raw": {"command": "CONDuctance 0.1"}},
            # HAZARD: 100 S = 0.01 Ω, silent short-circuit
            {"ts": now_iso, "channels": ["V"], "values": {"V": 3.3},
             "instrument": {"vendor": "KIKUSUI", "model": "PLZ1205W"},
             "raw": {"command": "CONDuctance 100"}},
            # safe: 0.5 S = 2 Ω
            {"ts": now_iso, "channels": ["V"], "values": {"V": 3.3},
             "instrument": {"vendor": "KIKUSUI", "model": "PLZ1205W"},
             "raw": {"command": "SOURce:CONDuctance:LEVel:IMMediate 0.5"}},
        ],
        subject="test-Kikusui-PLZ5W-safety",
    )
    print(f"[19b] Kikusui PLZ-5W CR hazard: ok={r19b['ok']} "
          f"accepted={r19b['records_accepted']} rejected={r19b['records_rejected']} "
          f"rejection_rule={r19b['rejections'][0]['rule_id'] if r19b['rejections'] else None}")
    assert r19b["ok"] is True  # partial: 2 accepted + 1 rejected
    assert r19b["records_accepted"] == 2
    assert r19b["records_rejected"] == 1
    assert r19b["rejections"][0]["rule_id"] == "kikusui-plz5w-cr-conductance-hazard"
    assert r19b["rejections"][0]["severity"] == "dangerous"
    assert r19b["rejections"][0]["detail"]["equivalent_ohms"] == 0.01

    # [19c] all records reject: ok=False + session_id=None
    r19c = import_external_session(
        source="external:kikusui-mcp-mock",
        records=[
            {"ts": now_iso, "channels": ["V"], "values": {"V": 3.3},
             "instrument": {"vendor": "KIKUSUI", "model": "PLZ405W"},
             "raw": {"command": "CONDuctance 50"}},  # 0.02 Ω hazard
            {"ts": now_iso, "channels": ["V"], "values": {"V": 3.3},
             "instrument": {"vendor": "KIKUSUI", "model": "PLZ405W"},
             "raw": {"command": "CONDuctance 200"}},  # 0.005 Ω hazard
        ],
    )
    print(f"[19c] all-reject batch: ok={r19c['ok']} session_id={r19c['session_id']} "
          f"rejected={r19c['records_rejected']} warning={r19c['warning']}")
    assert r19c["ok"] is False
    assert r19c["session_id"] is None
    assert r19c["records_accepted"] == 0
    assert r19c["records_rejected"] == 2

    # [19d] audit chain integrity after 3 imports: 全 import が audit log に 記録され chain 保持
    chk19 = verify_audit_chain()
    print(f"[19d] audit chain after 3 imports: valid={chk19['valid']} total={chk19['total']} "
          f"(includes 3 import_external_session entries)")
    assert chk19["valid"] is True
    assert chk19["total"] >= 3, f"想定 total ≥ 3 (import 3 件) だが {chk19['total']}"

    # [19e] non-Kikusui vendor bypass: SafetyGate rule は Kikusui 特化、 他 vendor は info verdict
    r19e = import_external_session(
        source="external:siglent-mcp-mock",
        records=[
            {"ts": now_iso, "channels": ["V"], "values": {"V": 3.3},
             "instrument": {"vendor": "SIGLENT", "model": "SDL1000X"},
             "raw": {"command": ":SOURce:RESistance:LEVel:IMMediate 100"}},  # Siglent は Ω 単位 = OK
        ],
    )
    print(f"[19e] non-Kikusui vendor (Siglent SDL1000X): ok={r19e['ok']} "
          f"accepted={r19e['records_accepted']} rejected={r19e['records_rejected']}")
    assert r19e["ok"] is True
    assert r19e["records_accepted"] == 1
    assert r19e["records_rejected"] == 0

    # [19f] backward compat: 旧 v0.4.0 以前の Session JSON (source field なし) を load
    # source field は default 'benchtop' で 補完される (load_session の filter が protect)
    old_style_id = "20260101-000000-legacy-test"
    old_path = DATA_DIR / f"{old_style_id}.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    old_path.write_text(json.dumps({
        "id": old_style_id, "port": "COM3", "started_at": "2026-01-01T00:00:00+00:00",
        "note": "legacy pre-v0.5.0", "channels": ["V"], "rows": [{"ts": now_iso, "V": 3.3}],
        "skipped": 0,
        # NO source field intentionally
    }), encoding="utf-8")
    try:
        sess_old = load_session(old_style_id)
        print(f"[19f] backward compat: legacy JSON (no source field) loaded → "
              f"source='{sess_old.source}' (default 'benchtop' 適用)")
        assert sess_old.source == "benchtop", f"backward compat 破れ: source={sess_old.source}"
    finally:
        # cleanup legacy fixture
        if old_path.exists():
            old_path.unlink()

    # ------------------------------------------------------------------
    # [20] v0.6.0-alpha: physics-limits pre-flight layer (5 tool MCP wrappers)
    # ------------------------------------------------------------------
    #   MCP tool 層の 呼び出しで module 実装との 一致 verify (module 側 selftest 28/28
    #   PASS 済、 ここは wire integrity と 数値 sanity 再確認のみ)。
    print("\n--- [20] v0.6.0-alpha: physics-limits pre-flight (5 MCP tool wire) ---")

    # [20a] bekenstein: 1 m, 1 J → ~2.87e26 bits
    r20a = bekenstein_bound_bits(radius_m=1.0, energy_J=1.0)
    print(f"[20a] bekenstein(1m, 1J): bound_bits={r20a['bound_bits']:.3e} "
          f"is_upper_bound={r20a['is_upper_bound']}")
    assert r20a["ok"] is True
    assert 2.8e26 < r20a["bound_bits"] < 2.95e26
    assert r20a["is_upper_bound"] is True

    # [20b] landauer: 1 bit at 300 K → ~2.87e-21 J
    r20b = landauer_min_energy_j(bits=1, temperature_K=300.0)
    print(f"[20b] landauer(1 bit, 300 K): min_energy_J={r20b['min_energy_J']:.3e} "
          f"eV={r20b['min_energy_eV']:.4f} is_lower_bound={r20b['is_lower_bound']}")
    assert r20b["ok"] is True
    assert 2.8e-21 < r20b["min_energy_J"] < 2.95e-21
    assert r20b["is_lower_bound"] is True

    # [20c] lloyd: 1 kg → ~5.43e50 ops/s
    r20c = lloyd_computation_ceiling(mass_kg=1.0)
    print(f"[20c] lloyd(1 kg): ops_ceiling={r20c['ops_per_second_ceiling']:.3e} "
          f"energy_J={r20c['energy_J']:.3e}")
    assert r20c["ok"] is True
    assert 5.3e50 < r20c["ops_per_second_ceiling"] < 5.5e50

    # [20d] operator_space: k=8, n=2 → log10 ~57.8 (D-FUMT₈ 2-var truth table)
    r20d = operator_space_size(k=8, n=2)
    print(f"[20d] operator_space(k=8, n=2): input_configs={r20d['input_configurations']} "
          f"total_log10={r20d['total_functions_log10']:.4f} "
          f"config_bits={r20d['config_bits']} lut_entries={r20d['lut_k_entries']}")
    assert r20d["ok"] is True
    assert r20d["input_configurations"] == 64
    assert 57.7 < r20d["total_functions_log10"] < 57.9
    assert r20d["is_theoretical_max"] is True

    # [20e] compression: N=1000, H=1.0 (uniform binary) → lower=1000, upper~1010
    r20e = compression_upper_bound(length=1000, entropy_bits_per_symbol=1.0, method="shannon")
    print(f"[20e] compression(N=1000, H=1.0, shannon): "
          f"lower={r20e['shannon_lower_bound_bits']} upper={r20e['practical_upper_bound_bits']} "
          f"K_note='{r20e['kolmogorov_note'][:40]}...'")
    assert r20e["ok"] is True
    assert r20e["shannon_lower_bound_bits"] == 1000.0
    assert 1000 < r20e["practical_upper_bound_bits"] < 1020
    assert "uncomputable" in r20e["kolmogorov_note"]

    # [20f] invalid input rejection (共通 error 経路 sanity)
    r20f1 = bekenstein_bound_bits(-1, 1)
    r20f2 = landauer_min_energy_j(1, -1)
    r20f3 = lloyd_computation_ceiling(0)
    r20f4 = operator_space_size(1, 2)  # k < 2
    r20f5 = compression_upper_bound(-1, 1, "shannon")
    print(f"[20f] invalid input: bekenstein={not r20f1['ok']} landauer={not r20f2['ok']} "
          f"lloyd={not r20f3['ok']} operator={not r20f4['ok']} compression={not r20f5['ok']}")
    assert all(not r["ok"] for r in (r20f1, r20f2, r20f3, r20f4, r20f5))

    # ------------------------------------------------------------------
    # [21] v0.7.0-alpha: olfact / biosensor mock spike (3 MCP tool wire)
    # ------------------------------------------------------------------
    #   MCP tool 層で module 実装との 一致 verify (module 側 selftest 35/35 PASS 済)。
    print("\n--- [21] v0.7.0-alpha: olfact / biosensor mock spike (3 MCP tool wire) ---")

    # [21a] list_probes: 3 probe registry
    r21a = list_probes()
    assert r21a["ok"] is True
    assert r21a["probe_count"] == 3
    assert r21a["hardware_available"] is False
    assert r21a["is_mock"] is True
    ids = {p["probe_id"] for p in r21a["probes"]}
    assert ids == {"silkworm-antenna-a1", "mosquito-receptor-fet-b1", "sparse-e-nose-c1"}
    print(f"[21a] list_probes: count={r21a['probe_count']} hw={r21a['hardware_available']} "
          f"ids={sorted(ids)}")

    # [21b] measure_eag: silkworm probe, valid odor → waveform + verdict
    r21b = measure_eag(probe_id="silkworm-antenna-a1", odor_name="cis-3-hexenol",
                      duration_s=3.0, sample_rate_hz=100.0)
    assert r21b["ok"] is True
    assert r21b["sample_count"] == 300
    assert r21b["is_mock"] is True
    assert r21b["hardware_available"] is False
    assert r21b["verdict_d8"] in ("TRUE", "NEITHER")
    print(f"[21b] measure_eag(silkworm, cis-3-hexenol, 3s@100Hz): "
          f"amp={r21b['amp_estimated_mv']:.3f}mV noise={r21b['noise_floor_mv']:.3f}mV "
          f"snr={r21b['snr_ratio']:.1f} verdict={r21b['verdict_d8']}/{r21b['verdict_d8_symbol']}")

    # [21c] measure_eag: determinism (chat-Claude Osmo Principal Odor Map reproducibility 原理)
    r21c1 = measure_eag("mosquito-receptor-fet-b1", "octenol", 1.0, 100.0)
    r21c2 = measure_eag("mosquito-receptor-fet-b1", "octenol", 1.0, 100.0)
    assert r21c1["waveform_mv"] == r21c2["waveform_mv"]
    print(f"[21c] measure_eag determinism: waveform_equal={r21c1['waveform_mv'] == r21c2['waveform_mv']}")

    # [21d] probe_health: bio-hybrid age progression (0h → 3.5h → 10.5h)
    r21d0 = probe_health("silkworm-antenna-a1", age_hours=0.0)
    r21d1 = probe_health("silkworm-antenna-a1", age_hours=3.5, last_calibration_hours_ago=1.0)
    r21d2 = probe_health("silkworm-antenna-a1", age_hours=10.5, last_calibration_hours_ago=1.0)
    assert r21d0["verdict"] == "HEALTHY"
    assert r21d1["verdict"] == "DEGRADING"
    assert r21d2["verdict"] == "EXPIRED"
    print(f"[21d] probe_health(silkworm): 0h={r21d0['verdict']} 3.5h={r21d1['verdict']} "
          f"10.5h={r21d2['verdict']} (linear-hydrogel model)")

    # [21e] probe_health: bio-inspired silicon (no biological aging)
    r21e = probe_health("sparse-e-nose-c1", age_hours=1000.0, last_calibration_hours_ago=1.0)
    assert r21e["verdict"] == "HEALTHY"
    assert r21e["health_score"] == 1.0
    assert r21e["degradation_model"] == "calibration-only-silicon"
    print(f"[21e] probe_health(sparse-e-nose, 1000h): verdict={r21e['verdict']} "
          f"model={r21e['degradation_model']}")

    # [21f] invalid input rejection (unknown probe / negative args)
    r21f1 = measure_eag("unknown", "odor", 1.0, 100.0)
    r21f2 = measure_eag("silkworm-antenna-a1", "odor", -1, 100)
    r21f3 = probe_health("unknown", 1.0)
    r21f4 = probe_health("silkworm-antenna-a1", -1.0)
    assert all(not r["ok"] for r in (r21f1, r21f2, r21f3, r21f4))
    print(f"[21f] invalid input rejected: unknown_probe={not r21f1['ok']} neg_dur={not r21f2['ok']} "
          f"unknown_probe_health={not r21f3['ok']} neg_age={not r21f4['ok']}")

    # ------------------------------------------------------------------
    # [22] v0.8.0-alpha: Akizuki wire-up 3 layer mock spike (4 MCP tool wire)
    # ------------------------------------------------------------------
    #   MCP tool 層で module 実装との 一致 verify (module 側 selftest 9/9 PASS 済)。
    print("\n--- [22] v0.8.0-alpha: Akizuki wire-up 3 layer mock spike (4 MCP tool wire) ---")

    # [22a] list_akizuki_probes: 3 probe registry
    r22a = list_akizuki_probes()
    assert r22a["ok"] is True
    assert r22a["probe_count"] == 3
    assert r22a["hardware_available"] is False
    assert r22a["is_mock"] is True
    ak_ids = {p["probe_id"] for p in r22a["probes"]}
    assert ak_ids == {"bme280-env-a1", "bno055-imu-b1", "vl53l1x-tof-c1"}
    print(f"[22a] list_akizuki_probes: count={r22a['probe_count']} hw={r22a['hardware_available']} "
          f"ids={sorted(ak_ids)}")

    # [22b] measure_environment: BME280 mock, in-range
    r22b = measure_environment(probe_id="bme280-env-a1", condition_tag="room-default")
    assert r22b["ok"] is True
    assert r22b["is_mock"] is True
    assert r22b["hardware_available"] is False
    assert r22b["verdict_d8"] == "TRUE"
    print(f"[22b] measure_environment(bme280, room-default): t={r22b['temperature_c']}C "
          f"h={r22b['humidity_pct']}% p={r22b['pressure_hpa']}hPa verdict={r22b['verdict_d8']}")

    # [22c] measure_environment: determinism
    r22c1 = measure_environment("bme280-env-a1", "outdoor-summer")
    r22c2 = measure_environment("bme280-env-a1", "outdoor-summer")
    assert r22c1["temperature_c"] == r22c2["temperature_c"]
    assert r22c1["pressure_hpa"] == r22c2["pressure_hpa"]
    print(f"[22c] measure_environment determinism: temp+pressure equal")

    # [22d] measure_orientation: BNO055 mock, unit quaternion
    r22d = measure_orientation(probe_id="bno055-imu-b1", motion_tag="static-level")
    assert r22d["ok"] is True
    assert r22d["is_mock"] is True
    assert r22d["is_unit_quat"] is True
    q22 = r22d["quaternion"]
    q22_norm = math.sqrt(q22["w"]**2 + q22["x"]**2 + q22["y"]**2 + q22["z"]**2)
    assert abs(q22_norm - 1.0) < 1e-4
    print(f"[22d] measure_orientation(bno055, static-level): q_norm={q22_norm:.6f} "
          f"euler_roll={r22d['euler_deg']['roll']}")

    # [22e] measure_distance: VL53L1X mock, range check
    r22e = measure_distance(probe_id="vl53l1x-tof-c1", target_tag="wall-2m", timing_budget_ms=100.0)
    assert r22e["ok"] is True
    assert r22e["is_mock"] is True
    assert r22e["range_status"] in ("VALID", "TOO_CLOSE", "TOO_FAR")
    assert r22e["verdict_d8"] in ("TRUE", "NEITHER")
    print(f"[22e] measure_distance(vl53l1x, wall-2m): d={r22e['distance_mm']}mm "
          f"status={r22e['range_status']} verdict={r22e['verdict_d8']}")

    # [22f] cross-layer misuse rejection
    r22f1 = measure_orientation("bme280-env-a1", "any")
    r22f2 = measure_environment("bno055-imu-b1", "any")
    r22f3 = measure_distance("bme280-env-a1", "any")
    r22f4 = measure_environment("unknown-probe", "any")
    r22f5 = measure_distance("vl53l1x-tof-c1", "wall", timing_budget_ms=1000.0)
    assert all(not r["ok"] for r in (r22f1, r22f2, r22f3, r22f4, r22f5))
    print(f"[22f] invalid input rejected: cross_layer=3/3, unknown_probe={not r22f4['ok']}, "
          f"timing_out_of_range={not r22f5['ok']}")

    print("\n全テスト成功。実機が無くてもこのサーバーは動作します。")
    print("v0.5.0-alpha SPIKE: import_external_session + SafetyGate + source field 追加 動作確認。")
    print("v0.6.0-alpha: physics-limits pre-flight (Bekenstein/Landauer/Lloyd/op-space/compression) 動作確認。")
    print("v0.7.0-alpha SPIKE: olfact / biosensor mock (list_probes / measure_eag / probe_health) 動作確認。")
    print("v0.8.0-alpha SPIKE: Akizuki wire-up 3 layer mock (env/IMU/ToF) 動作確認。")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    server.run(transport="stdio")
