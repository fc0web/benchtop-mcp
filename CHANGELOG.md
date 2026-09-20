# benchtop-mcp CHANGELOG

このファイルは 2026-09-20 に v0.14.0-alpha の 破壊的変更 に伴い 新規作成された。
v0.14.0-alpha 以前 の 版履歴は README.md の Version 節を参照。

書式は [Keep a Changelog](https://keepachangelog.com/) に準拠、 Semantic Versioning に緩く従う (alpha channel で v0.x のうちは 破壊的変更を minor bump で扱う)。

## [Unreleased]

## [0.14.0-alpha] — 2026-09-20

### BREAKING — Removed

- **`send_command` を MCP tool 面から除去** (STEP 2159、 rei-aios chat-Claude 2026-09-20 arc 経由)。 MCP tool 数: **34 → 33**。
  - **理由**: 任意 SCPI 文字列を機器に投げる 汎用口が MCP に露出していると、 モデルが SafetyGate (v0.5) や physics-limits (v0.6) の pre-flight を 経由せずに 任意コマンドを 組み立てられる。 確認の段を後から足すのではなく、 能力そのものを MCP から出さない、 という 判断。
  - **保持**: 実装本体 (`Bench.send_command` class method、 `benchtop_mcp.py:473`) は そのまま。 `_selftest()` 内 phase [2] で `BENCH.send_command(MOCK_PORT, '*IDN?')` として 引き続き 使用。
  - **新規追加 CLI 経路**: `python benchtop_mcp.py send_command <port> <command> [--baudrate N]`
    - 出力 = 旧 MCP wrapper と 同一 shape (JSON: `{"port": ..., "sent": ..., "response": ...}`)。
    - `argparse` ベース、 `--help` で 使用方法。
    - dispatcher は `__main__` block 内、 `_cli_send_command(argv)` として 独立関数化。

### Added

- **selftest phase [27]** — 回帰試験:
  - `server._tool_manager.list_tools()` を query して `"send_command"` が 含まれない ことを assertion。
  - Canary として `"list_ports"` と `"measure"` が 依然 含まれる ことも verify (test infra 自体の meaningfulness 保証)。
  - `Bench.send_command` class method が 保持 されている ことを `hasattr` + `callable` で verify。
  - `_cli_send_command` を `redirect_stdout` 下 で 直接呼び、 argparse (argv → args.port/command/baudrate) と `Bench.send_command` 到達 の **2 chain** を JSON payload parse verify (round 2 で `_cli_send_command_test_helper` からの refactor、 af2a4c2)。 `__main__` block の entry 分岐 (`sys.argv[1] == "send_command"`) は 本 test では 通っておらず、 subprocess 経由 の **[27b] 候補** として 保留 (round 3 で code comment 側 narrowing、 a59cdd6、 但し 本 CHANGELOG 側 は round 1 描写 の まま 残留していた ので STEP 2168 で 訂正)。
  - **失敗時 diagnostic**: 現在 tool 数 と "send" を 名前に含む tool の 一覧を assertion message に 埋込。 うっかり `@server.tool()` で 再登録した 場合、 「どこで 何が 起きたか」 が 即分かる。
- **CHANGELOG.md** (本ファイル)。

### Changed

- README の tool 一覧 で `send_command` の row を strike-through + 除去理由 + CLI 経路の 使い方に 差し替え。
- Version 銘板 top に v0.14.0-alpha 節 を 追加、 v0.13.0-alpha を 「過去 Version」 に 送る。

### Honest Scope (chat-Claude 2026-09-20 明示 note)

**本変更は MCP-only client (Claude Desktop 等) に対して のみ 効く**:

- **効く**: shell を 持たない MCP client。 モデルの 「呼べる 道具の 一覧」 から 消えるので、 うっかり 使われる 経路が 閉じる。
- **効かない**: shell を 持つ agent (Claude Code 等)。 CLI を 直接 叩ける。

これは **事故の経路を 減らす 変更 であって、 セキュリティ境界 ではない**。 後で これを 「歯止め」 として 数えないこと。 shell 持ち agent に対する 歯止め が 必要なら、 実行ユーザの権限 or 機器ファームウェア側の 上限 (別 layer) の 話 に なる。

### Migration

MCP client 側 で `send_command` tool を 直接呼んでいた caller は 壊れる。 shell アクセスがある なら CLI subcommand へ 切替、 shell アクセスが ない なら SCPI 通信 は benchtop の 他 tool (`measure` 等の pre-defined 通信) 経由に 設計変更 が 必要。

### Attribution

`[via 藤本さん / orig: chat-Claude 2026-09-20 paste 5153 (send_command MCP 面 除去 directive) + 藤本さん explicit GO 「(ii) 先に CLI subcommand を 足してから MCP を 外す でお願い致します」]`

rei-aios STEP claim: 2159 (tab rei-aios-04、 worktree `benchtop-mcp-step-remove-send`、 branch `step-remove-send-command-from-mcp`)。
