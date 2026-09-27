# benchtop-mcp CHANGELOG

このファイルは 2026-09-20 に v0.14.0-alpha の 破壊的変更 に伴い 新規作成された。
v0.14.0-alpha 以前 の 版履歴は README.md の Version 節を参照。

書式は [Keep a Changelog](https://keepachangelog.com/) に準拠、 Semantic Versioning に緩く従う (alpha channel で v0.x のうちは 破壊的変更を minor bump で扱う)。

## [Unreleased]

### Fixed — 主張と実装のずれ (audit 記録範囲)

- **`instructions` / README の 「全 tool 呼び出しが 記録され」 という 主張が 事実と 違って いた** のを 訂正。
  - **実測**: v0.3.0〜v0.14.0-alpha のあいだ、 `_write_audit` を 呼んで いたのは **33 tool のうち 7 tool のみ** (`measure` / `find_similar_sessions` / `regression_check` / `import_external_session` / `export_session_csv` / `compare_sessions` / `check_alert_rules`)。
  - **記録されて いなかった 計測 tool**: `measure_eag` / `probe_health` / `measure_eag_replay` / `measure_environment` / `measure_orientation` / `measure_distance` / `measure_co2_ndir` / `measure_voc_index` / `measure_co2_uart_ndir`、 および `analyze_session`。 **つまり EAG 本体の 測定が 一件も 証跡に 残って いなかった**。
  - ISO/IEC 17025 / GMP 用途を 掲げた 機能で 主張が 実態を 超えて いたので、 実装側を 主張に 合わせる のではなく **両方を 実態に 合わせた**。

### Added

- **`AUDITED_TOOLS` (17) / `UNAUDITED_TOOLS` (16)** — 記録する tool と、 記録しない tool＋その理由 を 明示 列挙 (合計 33 = 全 tool)。 「列挙しない除外」 は 穴と 同じ なので、 除外にも 理由を 書く。
  - 方針: **状態を 動かす / 測定値 or verdict を 産む tool は 記録する。 純粋な 読み出し (`list_*` / `plot_session` / `search_sessions` / `verify_audit_chain`) と 純粋な 計算 (物理上限 6 tool) は 記録しない。**
- **計測・判定 tool 10 個に audit 記録を 追加**。 `measure_eag_replay` は 引数検証の 早期 return が 複数 ある ため、 実体を `_measure_eag_replay_impl` に 分け、 **wrapper 一箇所で 全経路を 記録** する (記録漏れの 経路を 作らない)。
- **selftest phase [16e]** — 記録範囲を 強制する 回帰試験。 (1) 全 tool が どちらかの 集合に 分類されて いる、 (2) 集合が 重ならない・除外理由が 空でない、 (3) `AUDITED_TOOLS` の 各 tool が 実際に `_write_audit` を 呼ぶ、 (4) `UNAUDITED_TOOLS` は 逆に 呼ばない、 (3b) 判定法 自身の 試験、 (5) `measure_eag` / `probe_health` が 実際に 1 行ずつ 書き、 chain が valid。
  - **(1) が 要点**: `server._tool_manager.list_tools()` の 実際の 登録一覧と `AUDITED_TOOLS | UNAUDITED_TOOLS` の **集合一致**を assert する (phase [27] と 同じ source)。 未分類の 登録 tool と、 逆に 実在しない 分類 entry の 両方向を 落とす。 **新 tool を 足して 分類を 忘れると selftest が 落ちる**。 陰性対照 実測: `list_ports` を `UNAUDITED_TOOLS` から 外すと `registered=33 / classified=32` で AssertionError、 exit 1。
  - **(3)(4) も 要点**: 宣言と 実装の 両方向 drift を 落とす。
  - **(3)(4) の 判定は source 文字列の grep ではなく AST 走査** (`_calls_write_audit`)。 grep だと docstring 内に literal `_write_audit(` を 書いた tool を 取り違える (AUDITED 側では 見逃し、 UNAUDITED 側では 誤検出)。 `ast.Call` node だけ を 見る ことで 消した。 source が 読めない 場合は 「判定不能」 として **黙って 通さず assert で 落とす**。
  - **(3b) は 判定法 自身の 試験**: docstring に literal だけ 書いた 偽 tool を その場で 定義し、 **grep 判定=True / AST 判定=False** を assert する。 判定器が 退行 したら ここが 落ちる。

### Documentation — 正直な限界の明記

- `_write_audit` の docstring に **記録側が fail-open** である ことを 明記 (append 失敗は stderr warn のみ で tool 実行を 続ける)。 証跡が 必須の 運用では 別の 判断が 必要。
- `benchtop_audit_log.py` の `result` 語彙を **実際に 産出側が 書く 値 のみ** に 訂正 (`success` / `error` / `partial` / `rejected`)。 docstring に あった `aborted` は 一度も 書かれて いなかったので 削除。
- **`result` 語彙に selftest 実測の 行数を 併記**。 `success` 41 / `error` 22 / `rejected` 1 は 実測、 **`partial` は コード上の 産出経路 (`measure` / `analyze_session`) は ある が selftest では 一度も 書かれない (実測 0 行)**。 abort を MCP tool 経由で 起こす phase を 足す まで 未実証 として 扱う。 「docstring に 載って いる」 と 「試験で 踏まれて いる」 を 区別する。
- **`denied` / `timeout_denied` は 意図的に 定義しない** と 明記。 benchtop-mcp には 人が 帯域外で 承認/否認する 経路が そもそも 無く、 語彙だけ 先に 足すと 「承認機構が ある」 と 誤読される。 承認段を 実装する ときに 同時に 足す。 参照: `ceobigg10/askgate` が 時間切れの 否認 (`timeout-deny`) を 人の否認と 別事象に して いる。

### Known gap — 未修正 (意図的に 残す)

- **`send_command` の 到達経路**: MCP tool 面からは v0.14.0-alpha で 除去済 だが、 **本 repo の source から 数えられる 到達経路は 2 本 残る**: (1) `Bench.send_command` class method (`benchtop_mcp.py`)、 (2) CLI `python benchtop_mcp.py send_command <port> <command>`。 selftest phase [27] が 毎回 (2) を `port=mock sent='*IDN?'` で 実際に 踏んで 通る ことを 確認して いる (= 生きた 経路)。
  - **本 repo の source では 数えられない 経路**: 同一機体には `pyvisa` 直結・EPICS 経由・シリアル端末 からも 到達し得る が、 これらは **この repo の 外**に あり、 source からは 存在も 本数も 確定できない。 上の 2 本と 同列に 並べて 「6 経路」 と 数えるのは 誤り。 **実測 2 本 + 配置依存で 不定、 が 正しい 書き方**。
  - **つまり SafetyGate を 通る 経路は 機器に 至る 経路の 一部に すぎない**。 これは 実装の bug ではなく 配置の 問題 なので、 経路の 数え上げ (機器ごとに 何本 あり、 何本が gate を 通るか) を 先に 行う (レポート第30回 ㉓)。 **数え上げは 本 patch の 範囲外で、 patch 単体では 完結して いない**。

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
