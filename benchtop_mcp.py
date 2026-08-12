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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


@dataclass
class Session:
    id: str
    port: str
    started_at: str
    note: str = ""
    channels: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    skipped: int = 0

    def path(self) -> Path:
        return DATA_DIR / f"{self.id}.json"

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.path().write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )


def load_session(session_id: str) -> Session:
    p = DATA_DIR / f"{session_id}.json"
    if not p.exists():
        raise FileNotFoundError(f"セッションが見つかりません: {session_id}")
    return Session(**json.loads(p.read_text(encoding="utf-8")))


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
    ) -> Session:
        if samples < 1 or samples > 10000:
            raise ValueError("samples は 1〜10000 の範囲で指定してください")

        dev = self.open(port, baudrate)
        sid = datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{random.randint(100, 999)}"
        session = Session(id=sid, port=port, started_at=_now(), note=note)

        t_start = time.time()
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

        session.save()
        return session

    # -- 解析 ---------------------------------------------------------------

    @staticmethod
    def analyze(session: Session) -> dict[str, Any]:
        result: dict[str, Any] = {
            "session_id": session.id,
            "port": session.port,
            "started_at": session.started_at,
            "note": session.note,
            "n_rows": len(session.rows),
            "skipped": session.skipped,
            "duration_s": round(session.rows[-1]["t"], 3) if session.rows else 0.0,
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
                out.append(
                    {
                        "session_id": d["id"],
                        "port": d["port"],
                        "started_at": d["started_at"],
                        "n_rows": len(d.get("rows", [])),
                        "channels": d.get("channels", []),
                        "note": d.get("note", ""),
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
        """
        result: dict[str, Any] = {
            "session_id": session.id,
            "port": session.port,
            "started_at": session.started_at,
            "width": width,
            "n_rows": len(session.rows),
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
                "sparkline": spark,
                "n": len(xs),
                "min": round(lo, 6),
                "max": round(hi, 6),
                "mean": round(mean, 6),
                "range": round(hi - lo, 6),
            }
        return result

    @staticmethod
    def compare(sa: Session, sb: Session) -> dict[str, Any]:
        """2 セッションをチャンネル単位で比較する。共通チャンネルについて
        mean・stdev・drift の差分と、Welch 型の z スコア (delta_mean / SE)
        を返す。|z| > 3 のとき significant_shift=True。統計的有意性の代替で
        はなく、AI が 「先週と比べて怪しくないか」 を判断するための粗い目安。
        """
        stats_a = Bench.analyze(sa)["channels"]
        stats_b = Bench.analyze(sb)["channels"]
        result: dict[str, Any] = {
            "a": {"session_id": sa.id, "started_at": sa.started_at, "note": sa.note, "port": sa.port},
            "b": {"session_id": sb.id, "started_at": sb.started_at, "note": sb.note, "port": sb.port},
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
            na, nb = max(a["n"], 1), max(b["n"], 1)
            se = math.sqrt((a["stdev"] ** 2) / na + (b["stdev"] ** 2) / nb)
            z = (delta_mean / se) if se > 0 else 0.0
            result["channels"][ch] = {
                "a": {"mean": a["mean"], "stdev": a["stdev"], "drift": a["drift"], "n": a["n"]},
                "b": {"mean": b["mean"], "stdev": b["stdev"], "drift": b["drift"], "n": b["n"]},
                "delta_mean": round(delta_mean, 6),
                "delta_stdev": round(a["stdev"] - b["stdev"], 6),
                "delta_drift": round(a["drift"] - b["drift"], 6),
                "standard_error": round(se, 6),
                "mean_shift_z": round(z, 3),
                "significant_shift": abs(z) > 3.0,
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
    ) -> list[dict[str, Any]]:
        """条件付きでセッションを絞り込む。list_sessions が直近 N 件しか
        返さないので、セッションが増えたらこちらを使う。全条件 AND、
        started_at は ISO 文字列辞書順で比較 (UTC 保存前提)。
        """
        if not DATA_DIR.exists():
            return []
        needle = note_contains.lower() if note_contains else None
        out: list[dict[str, Any]] = []
        for p in sorted(DATA_DIR.glob("*.json"), reverse=True):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            started = d.get("started_at", "")
            if since and started < since:
                continue
            if until and started > until:
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
                    "n_rows": len(d.get("rows", [])),
                    "channels": d.get("channels", []),
                    "note": d.get("note", ""),
                }
            )
            if len(out) >= limit:
                break
        return out


BENCH = Bench()


# ---------------------------------------------------------------------------
# MCP 層 : ここから下が「AI から呼べる道具」の定義
#   関数の docstring と型注釈が、そのまま AI への説明書になる。
#   ここを丁寧に書くほど AI は正しく使ってくれる。
# ---------------------------------------------------------------------------

from mcp.server import MCPServer  # noqa: E402

server = MCPServer(
    name="benchtop",
    version="0.2.0",
    instructions=(
        "シリアル接続された計測装置・回路を操作し、測定値を記録・解析するツール群です。"
        "実機が無い場合は port='mock' を指定すると内蔵の仮想装置が使えます。"
        "典型的な流れ: list_ports → measure → analyze_session → export_session_csv。"
        "v0.2 追加: plot_session (ASCII 波形) / compare_sessions (2 セッション diff) / "
        "search_sessions (日付・note・port・channel での絞り込み)。"
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
) -> dict[str, Any]:
    """装置から連続して測定値を読み取り、1つのセッションとして保存する。

    'T=25.3,H=48.1' のような key=value 形式、'25.3,48.1' のようなCSV形式、
    単一の数値のいずれも自動で解釈する。

    Args:
        port: 装置のポート名。既定は 'mock'。
        samples: 読み取る回数（1〜10000）。
        interval_ms: 各読み取りの間隔（ミリ秒）。
        baudrate: 通信速度。
        command: 毎回送信するコマンド。省略時は装置が自発的に送る行を読む。
        note: このセッションに付けるメモ。後から探すときの手がかりになる。

    Returns:
        保存されたセッションIDと、その場での簡易サマリー。
    """
    s = BENCH.measure(port, samples, interval_ms, baudrate, command, note)
    return {
        "session_id": s.id,
        "saved_to": str(s.path()),
        "n_rows": len(s.rows),
        "skipped": s.skipped,
        "channels": s.channels,
        "summary": Bench.analyze(s)["channels"],
    }


@server.tool()
def list_sessions(limit: int = 30) -> dict[str, Any]:
    """保存済みの計測セッションを新しい順に一覧する。"""
    return {"data_dir": str(DATA_DIR), "sessions": Bench.list_sessions(limit)}


@server.tool()
def analyze_session(session_id: str) -> dict[str, Any]:
    """保存済みセッションをチャンネルごとに統計解析する。

    件数・平均・標準偏差・最小/最大・ドリフト（最終値-初期値）を返し、
    平均から3σ以上離れた点を外れ値として列挙する。
    装置の異常や測定のばらつきを判断するために使う。
    """
    return Bench.analyze(load_session(session_id))


@server.tool()
def export_session_csv(session_id: str, out_path: str) -> dict[str, Any]:
    """保存済みセッションを CSV ファイルに書き出す。

    Args:
        session_id: 対象のセッションID。
        out_path: 書き出し先のファイルパス。例: '/tmp/run1.csv'
    """
    s = load_session(session_id)
    p = Bench.export_csv(s, out_path)
    return {"session_id": session_id, "path": str(p), "n_rows": len(s.rows), "columns": ["t"] + s.channels}


# ---------------------------------------------------------------------------
# MCP 層 v0.2 追加ツール
# ---------------------------------------------------------------------------


@server.tool()
def plot_session(session_id: str, width: int = 60) -> dict[str, Any]:
    """保存済みセッションを ASCII スパークライン (▁▂▃▄▅▆▇█) で視覚化する。

    各チャンネル別に、値の時系列を Unicode ブロック文字 8 段階で表現し、
    min/max/mean/range も同時に返す。matplotlib 等の依存を増やさず、Excel を
    開かずに傾向・外れ値の位置をざっくり把握したいときに使う。

    Args:
        session_id: 対象のセッションID。
        width: スパークラインの横幅（サンプル数がこれより多ければ平均でビン化）。
               既定は 60。1 以上を指定すること。
    """
    return Bench.plot(load_session(session_id), width)


@server.tool()
def compare_sessions(session_id_a: str, session_id_b: str) -> dict[str, Any]:
    """2 つのセッションをチャンネル単位で比較する。

    共通する各チャンネルについて mean・stdev・drift の差分を計算し、
    Welch 型の z スコア (delta_mean / SE) も返す。|z| > 3 のとき
    significant_shift=True。「先週と比べて質が落ちていないか」 の判断に使う。
    厳密な統計的検定ではなく AI 判断のための粗い目安。

    Args:
        session_id_a: 比較元のセッションID (通常は新しい方)。
        session_id_b: 比較先のセッションID (通常は古い方・基準)。
    """
    return Bench.compare(load_session(session_id_a), load_session(session_id_b))


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
    使う。全条件 AND、started_at は ISO 文字列辞書順で比較 (UTC 保存前提)。

    Args:
        since: この日時以降のみ (ISO 形式、例 '2026-08-01' or '2026-08-01T00:00:00+00:00')。
        until: この日時以前のみ (ISO 形式)。
        note_contains: note に含まれる文字列 (大文字小文字を区別しない)。
        port: このポートで計測したものだけ (完全一致)。
        channel: このチャンネルを含むものだけ (例: 'T', 'V', 'ch1')。
        limit: 返す最大件数。既定は 30。
    """
    return {
        "data_dir": str(DATA_DIR),
        "filters": {
            "since": since,
            "until": until,
            "note_contains": note_contains,
            "port": port,
            "channel": channel,
            "limit": limit,
        },
        "sessions": Bench.search_sessions(since, until, note_contains, port, channel, limit),
    }


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

    print("\n全テスト成功。実機が無くてもこのサーバーは動作します。")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    server.run(transport="stdio")
