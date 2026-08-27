# benchtop-mcp

シリアル接続された計測装置・回路を、AI エージェント（Claude など）から直接操作・記録・解析するための MCP サーバーです。

**実機がなくても動きます。** 内蔵の仮想装置（`port="mock"`）があるので、ハードを繋ぐ前に全機能を試せます。

**Version**: 0.10.0-alpha (2026-08-27) — **★ 宣言的 alert rule engine**: 新 tool 1 個 `check_alert_rules` (既存 session に user 定義閾値ルールを 適用、 校正・保守基準の 静的 gate)。 4 per-row op (`gt`/`lt`/`abs_gt`/`sigma`) + 3 session-level op (`drift_abs`/`stdev_gt`/`mean_abs_gt`) + 3 severity (info/warn/critical) + 5 guard (`channel_not_found`/`unknown_op`/`missing_required_field`/`zero_variance`/`insufficient_samples`)。 `analyze_session` の 3σ 固定則の 補完で、 「T が 30 度超えたら」 「stdev が 0.1 mV 超えたら」 のような 校正・保守閾値を declarative rule で 積む。 hardware 依存なし = 「pure calc」 = **SPIKE ではない** (mock skeleton の格上げではなく 新層追加)。 matched_rows は最大 100 (hoard 防止)、 判定 severity は目安で 実 escalation は caller 責任 ([[feedback-world-uniqueness-claim-controllable]] 継承)。 selftest phase [25a-25f] 全 PASS (per-row gt + session stdev_gt + 4 guard + severity fallback + structured error)。 STEP 1471。

**★ v1.0 threshold は defer 継続** (2026-08-27 判断、 藤本さん directive 経由): SPIKE 4 段 (v0.7 olfact / v0.8 wireup / v0.9.0 chem / v0.9.1 uart-chem) が **mock skeleton のまま** = semver 「1.0 = stable API + verified」 慣習に対して overclaim risk。 [[feedback-no-rush-publication]] discipline + [[feedback-world-uniqueness-claim-controllable]] 継承。 v1.0 移行条件は今後の別 STEP で判断: (i) SPIKE 各段の hardware verified evidence 添付 (Phase C silicon narrative の水平展開)、 (ii) Product Transition Judgment Framework v0.1 で 5 checklist 中 3+ 該当、 (iii) 藤本さん explicit go。 いずれも 2026-08-27 現時点 未達 = v0.10.0-alpha として feature 追加のみ (license MIT 継続、 v0.x 分は 永久 MIT irrevocable、 v1.0+ 分のみ 将来 AGPL flip 検討余地)。

**Version**: 0.7.0-alpha (2026-08-23, SPIKE) — **★ olfact / biosensor mock layer**: 生体嗅覚センサ (bio-hybrid / receptor-chip / bio-inspired 3 layer) の interface skeleton を benchtop に 追加。 新 tool 3 個: `list_probes` (内蔵 mock probe registry 3 probe) + `measure_eag` (deterministic mock EAG waveform、 probe_id + odor_name の hashlib.md5 seed で cross-process 再現可能、 D-FUMT₈ verdict subset for STEP 1350 mapping) + `probe_health` (3 layer 別 degradation model: linear-hydrogel / exponential-protein-denaturation / calibration-only-silicon)。 藤本さん directive (2026-08-23 対話 arc 「虫の触覚センサー / 動物 / 植物センサー」 + 「AI に役立つか」 経由) 実装。 ★ **hardware 未取得** = 全 tool で `hardware_available: False` + `is_mock: True` marker、 実 EAG physics (ion channel kinetics 等) 模倣なし = interface skeleton のみ。 実 hardware 統合 (フロントエンドアンプ + 恒温恒湿 + オルファクトメータ) は 別 STEP candidate。 selftest phase [21a-21f] 追加、 module 単体 35 assertion + wire 6 phase 全 PASS。 [[feedback-super-naming-siren-family-pattern]] 適用 (mock 誤読予防)、 [[feedback-world-uniqueness-claim-controllable]] 継承 (「世界初」 主張ゼロ、 novelty は Rei stack 内 benchtop 新 domain 追加のみ)。

**Version**: 0.6.0-alpha (2026-08-20, SPIKE) — **★ physics-limits pre-flight layer** (5 tool): `bekenstein_bound_bits` / `landauer_min_energy_j` / `lloyd_computation_ceiling` / `operator_space_size` / `compression_upper_bound`。 LLM が 単位付き算術 + 桁勘定 + 上界計算で 誤りやすい 領域を pure calc (stdlib のみ) の MCP tool に落とし、 実 hardware SCPI 送出の pre-flight check として 使う。 SafetyGate (v0.5) と 相補: 事前規模計算 → SafetyGate。 Kolmogorov K(x) uncomputable は siren-family pattern 回避で明示 disclaimer 付き。 selftest phase [20a-20f]。

**Version**: 0.5.0-alpha (2026-08-19, SPIKE) — **★ provenance layer + SafetyGate**: `import_external_session` で 他社 MCP server (Keysight/rigol/lecroy/kya-os wrapped) の 計測記録を benchtop に 取り込み + SafetyGate で SCPI-argument level の hazard (Kikusui PLZ-5W CR mode Siemens/Ω 混同 = 短絡 hazard 等) を 静的検出。 4 agent verify (2026-08-19) 経由の 「機器層/記録層 分割」 戦略の 記録層 実装。 selftest phase [19a-19f]。

**Version**: 0.4.0 (2026-08-17) — **★ 実験ノート (experiment notebook) 統合**: Session dataclass に `subject` (被測定物 ID) / `environment` (温湿度 dict) / `instrument_config` (装置設定 dict) / `mystery_id` (rei-aios link) 全 optional field 追加。 新 tool 2 個: `find_similar_sessions` (subject / mystery_id / environment key/value + tolerance で 過去 session 絞り込み) + `regression_check` (baseline vs current の mean_delta / stdev_ratio tolerance-based 劣化検出)。 chat-Claude 2026-08-17 arc 「実験ノート MCP」 提案 (benchtop = 手を動かす、 rei-aios = 考える、 その間の 空白) を benchtop 内 拡張として 実装 (新 MCP 追加せず 「深化」 discipline 準拠)。 backward compat: 旧 JSON (v0.3.0 以前) も 読める、 新 field default None。 selftest phase [17] (実験ノート + find_similar_sessions 5 case) + [18a-18c] (regression_check 3 case) 追加、 計 18 phase 全 PASS。

**Version**: 0.3.0 (2026-08-17) — **★ major: audit log hash chain 追加** (Rei-Automator STEP 1340 primitive port)。 全 tool 呼び出しが `~/.benchtop-mcp/audit/audit.jsonl` に append-only JSONL + sha256 prev-hash chain で 記録され、 新 tool `verify_audit_chain` で 改竄検出可能。 chat-Claude 2026-08-17 arc 「証跡が価値になる領域」 (ISO/IEC 17025 校正 / GMP 医薬品製造記録 / 監査対応) 用途。 session store (`~/.benchtop-mcp/session_*.json`) と 別 store で 併存、 audit log は 削除禁止 (append-only)。 `BENCHTOP_AUDIT=0` で 無効化可能、 `BENCHTOP_AUDIT_DIR` で 保存先変更可能。 selftest phase [16a-16d] で genesis chain / continuation / tamper detection / MCP tool level を 各 verify。

**Version**: 0.2.4 (2026-08-13) — v0.2.3 verify 中に発火した実 pain 対応 (initial external-verify-derived fix): `search_sessions` の `since` / `until` が `YYYY-MM-DD` (時刻部分なし) のとき **local midnight として解釈** し UTC 換算後に比較。旧 v0.2.3 では UTC 文字列辞書順比較で 「JST 早朝に測った session を `since='今日'` で 検索すると 0 件」 の 静かな穴があった (session_id は JST 表示 / started_at は UTC で日付が 1 日ずれる)。完全 ISO (T + offset) は従来通り厳密。`BENCHTOP_TZ` env で tz override 可能。副 fix として各 tool の返り値に `started_at_local` を併記。詳細は下記「v0.2 で足したもの」節。

**Compatibility note**: v0.2.3 は `interpretation` field の値を `"threshold_gate_on_welch_standard_error"` (v0.2.2) → `"welch_t_statistic_with_fixed_z_threshold"` に rename しました。この文字列を pattern match していた caller は壊れます。現時点で外部 caller はいない想定なので実害ゼロですが、今後 return dict の field 値を触るときは breaking change 扱いとします (メジャー版 or 明示注記の伴う変更のみ)。

v0.2.4 は `search_sessions(since='YYYY-MM-DD')` の 解釈を **UTC 文字列辞書順比較 → local midnight 換算比較** に変更しています。厳密には behavior change ですが、「UTC 基準の日付のみ指定」を意図して使っていた caller は現実には存在しない想定 (いたとすればそれが今回のバグ) なので breaking 扱いはしません。完全 ISO 指定 (`T` + 時刻 + offset) は従来動作を維持。

**License**: v0.x は MIT。 v1.0+ は AGPL-3.0 + commercial dual への切替 可能性 予告 (LICENSE file 参照)。 v0.x 分は 永久 MIT (irrevocable)。

---

## これは何を解決するのか

計測の現場では、だいたい同じことが繰り返されています。

1. 装置にコマンドを送って値を読む
2. しばらく回してログを取る
3. Excel に貼って平均と σ を出し、おかしい点を探す
4. CSV にして誰かに渡す

一つ一つは簡単ですが、面倒で、毎回手でやっています。このサーバーを入れると、その全部を AI に日本語で頼めるようになります。

> 「mock に繋いで200回測って、電圧のばらつきを見て、外れ値があったら教えて。結果は CSV にして」

地味です。しかし前の会話で確認した「売れるものの条件」——**誰もが必要とし、自作すると面倒で、壊れると静かに高くつく**——に、正確に当てはまります。

---

## 公開しているツール（AI から呼べる機能）

| ツール | 役割 |
|---|---|
| `list_ports` | 利用可能な装置の一覧。実機が無くても `mock` が必ず出る |
| `send_command` | 装置に1行送って応答を読む（`*IDN?` など） |
| `measure` | N 回連続で測定し、セッションとして保存 |
| `list_sessions` | 保存済みセッションの一覧 |
| `analyze_session` | 平均・σ・最小/最大・ドリフト・3σ外れ値を算出 |
| `export_session_csv` | CSV に書き出し |
| `plot_session` *(v0.2)* | ASCII スパークライン (▁▂▃▄▅▆▇█) でチャンネル別に視覚化 |
| `compare_sessions` *(v0.2)* | 2 セッションの mean/stdev/drift 差分と Welch 型 z スコアを返す (v0.2.1: `z_threshold` 明示パラメータ) |
| `search_sessions` *(v0.2)* | 日付範囲・note キーワード・port・channel でセッションを絞り込む |
| `verify_audit_chain` *(v0.3.0)* | audit log の sha256 prev-hash chain 整合性を検証 (改竄検出) |
| `find_similar_sessions` *(v0.4.0)* | subject / mystery_id / environment key/value + tolerance で 過去 session を 絞り込み (「3ヶ月前の 同じ条件と 比べて」 用) |
| `regression_check` *(v0.4.0)* | baseline vs current の mean_delta / stdev_ratio を tolerance-based で 判定 (校正基準からの 劣化検出) |
| `list_probes` *(v0.7.0-alpha)* | 生体嗅覚センサ mock probe registry の 一覧 (3 layer: bio-hybrid / receptor-chip / bio-inspired、 全 `hardware_available: False`) |
| `measure_eag` *(v0.7.0-alpha)* | mock EAG (Electroantennogram) 測定、 deterministic waveform (hashlib.md5 seed 由来)、 SNR + D-FUMT₈ verdict (STEP 1350 mapping subset) |
| `probe_health` *(v0.7.0-alpha)* | 生体劣化 verdict (HEALTHY/DEGRADING/EXPIRED/UNCALIBRATED)、 3 layer 別 degradation model |
| `check_alert_rules` *(v0.10.0-alpha)* | 既存 session に 宣言的 alert rule 群を 適用 (校正・保守閾値の 静的 gate)。 4 per-row op (`gt`/`lt`/`abs_gt`/`sigma`) + 3 session-level op (`drift_abs`/`stdev_gt`/`mean_abs_gt`) + 3 severity + 5 guard、 `analyze_session` の 3σ 固定則の 補完 |

存在しない `session_id` を渡した場合、`plot_session` / `analyze_session` / `compare_sessions` / `export_session_csv` は例外を投げずに `{"error": "session_not_found", "session_id": "...", "hint": "..."}` を返す (v0.2.1)。AI から見て tool 呼び出しが例外で落ちるより、error 情報を含む dict が返る方がリトライ or 別 tool に自然に繋がる。

対応する測定値の形式は3種類を自動判別します。

```
T=25.3,H=48.1     →  {"T": 25.3, "H": 48.1}
25.3,48.1         →  {"ch1": 25.3, "ch2": 48.1}
25.3              →  {"value": 25.3}
```

### v0.2 で足したもの

**「毎回手でやる面倒」 を 1 つずつ引き受ける** ための 3 ツール。有料化予告済みの機能 (連続ロギング / 閾値アラート / 校正記録) とは非競合の、あくまで基本操作の拡張です。

- **`plot_session`** — Excel を開かずに傾向・外れ値の位置がざっくり見える。matplotlib を入れない (依存を増やさない) ため、Unicode ブロック文字 8 段階で描画。サンプル数が多いときは平均でビン化して幅を合わせる。
- **`compare_sessions`** — 「先週と比べて怪しくないか」 を AI が数値で判断できるように、2 セッションの mean/stdev/drift 差分と Welch 型 t 統計量 (`mean_shift_z` として返す) を計算する。**使う式は 1 本だけ**: `z = (mean_A − mean_B) / sqrt(σ_A²/n_A + σ_B²/n_B)`。これは **Welch's t 検定の統計量そのもの** (v0.2.3 訂正: v0.2.2 では 「Welch's t-test ではない」 と書いていたが、 statistic は同一で異なるのは判定則という書き分けが正確)。異なるのは:
  - Welch's t-test は t 分布 critical value (自由度依存) で判定 → p 値
  - この tool は 固定閾値 `z_threshold` (既定 3.0) で単純 gate

  `welch_df` (Welch-Satterthwaite 自由度) を per-channel に返すので、caller は 「今回の n で固定 3.0 が甘い/厳しい」 を自分で判定できる (v0.2.3 追加)。分母は per-sample の SD ではなく **平均の標準誤差 (SE) の Welch 合成** なので、n が大きいほど固定閾値は厳しくなる (n=100 なら 「平均が 0.3σ 分ずれれば z=3」)。**判定は呼び出し側の責任**: `z_threshold` パラメータ (既定 3.0) を明示指定でき、`z_threshold_used` / `z_formula` に採用値と式が反映されるので後から audit 可能。`is_hypothesis_test: false` / `disclaimer` / per-channel `interpretation: "welch_t_statistic_with_fixed_z_threshold"` を機械可読 field として置く。

  **Guard (v0.2.3)**: `n<2` (stdev 未定義) または `σ_A²/n_A + σ_B²/n_B = 0` (定数装置) の場合、gate を評価せずに `gate_evaluable: false` + `gate_skip_reason: "insufficient_samples" or "zero_variance"` を返し、`mean_shift_z` / `welch_df` / `standard_error` / `significant_shift` はすべて `None`。旧実装 (v0.2.2 以前) では 0/0→NaN→`significant_shift=False` に落ちて 「差が無い」 と静かに誤報していた path を明示 guard で分離。`None` は 「差が無い」 ではなく 「gate 未評価」 と読むこと。
- **`search_sessions`** — `list_sessions` は直近 30 件しか返さないので、`~/.benchtop-mcp/` にセッションが溜まってきたらこちら。since/until (ISO 日時) + note キーワード (大文字小文字無視) + port + channel の AND 絞り込み。

**v0.2.1 の追加改善** (v0.2.0 レビュー指摘対応):

- **`measure` 途中失敗の partial 保存** — 装置切断・Ctrl+C・SerialException 等が起きても、そこまでに取れた行はセッションに保存され、返り値の `partial: true` と `abort_reason` で通知される。100 回中 60 で止まっても「60 行取れた + 止まった理由」が残る。全部捨てるより実運用の失敗解析に使える。
- **無効 `session_id` の structured error** — 上の tool 表下の注記の通り、例外ではなく dict で返す。

**v0.2.2 の追加改善** (v0.2.1 レビュー指摘対応):

- **`compare_sessions` の z 式明示 + 検定ではないことの機械可読契約** — 上の compare_sessions 説明参照。docstring は人間 (caller) には届くが LLM の出力語彙までは縛れないので、return dict の `is_hypothesis_test: false` + `disclaimer` + per-channel `interpretation` で field 名として置いている。
- **partial の下流波及** — `Session.aborted_at` が立った session は、`analyze_session` / `plot_session` の top-level に `partial: true` + `abort_reason` を mirror。`compare_sessions` は 2 入力の非対称 n が z を歪めうるので `any_input_aborted: true` + `aborted_inputs: ["a" or "b"]` を top-level に立てる。`search_sessions` / `list_sessions` の各行にも `partial` を出す。中断された session が下流のどの tool を通っても事実が消えない契約。
- **`plot_session` の legend contract** — per-channel dict に `label: str` (= channel 名) を追加、top-level に `channels_order: [str]` で render 順を明示。§3.5-c で 「どの line が どの channel か」 を目視 verify する際の後方支援。単位 (unit) は v0.3 へ defer 継続。

**v0.2.4 の追加改善** (v0.2.3 実 verify 発火の pain fix、 initial **external-verify-derived** 変更):

- **`search_sessions` の date-only 解釈を local midnight 化** — 藤本さん が v0.2.3 verify 中 §3.5-b/c 全 pass 直後 に発見した 実 pain。 session_id は local time (JST) 表示、 started_at は UTC 保存で 日付が 1 日ずれる → `since='2026-08-13', note_contains='seed'` で **0 件** (今日作った session を 「今日以降」 で検索すると 消える)。 v0.2.4 では `YYYY-MM-DD` 形式 (時刻部分なし) を検出し **local midnight として解釈** し UTC 換算 (`since` = 当日 00:00 local、 `until` = 当日 23:59:59.999999 local)。 「今日以降と書いたら 手元の時計で今日 0 時以降が返る」 直感一致。 完全 ISO (`T` + 時刻 [+ offset]) は 従来通り 厳密比較。 tz は `BENCHTOP_TZ` env 優先、 無ければ system local。
- **`filters` に audit trail 併記** — 返り値の `filters` に `since_resolved_utc` / `until_resolved_utc` / `since_date_only` / `until_date_only` / `tz_used` を 追加。 「意図した通り 解釈されたか」 が 機械可読で 確認可能。
- **`started_at_local` 副 field を 各 tool に追加** (副役割、 主 fix と 独立)。 `search_sessions` / `list_sessions` 各 row + `analyze_session` / `plot_session` top-level + `compare_sessions` の a/b 各 input dict。 空振り時は 見えない (副役割の 明確化) が、 検索成功後に 日時を 読む時に 便利。

**v0.2.4 で 明示 defer した もの** (「隠す」 選択の 意味論設計先要): `plot_session` の 外れ値で スケール潰れ (3% 外れ値機構の 1 点が最大値になると 残り 29 点が最下段に潰れる) は sparkline の 数学的性質 (min/max 正規化) の限界。 percentile clip や 外れ値別記号は 「clip した」 事実の どう明示するかの 設計判断が 追加で必要 = v0.2.5+ or 別 tool (`plot_session_clipped`) 候補。 現状は `analyze_session` の `outliers` field で 外れ値 位置 + magnitude は 取れる (併用推奨)。

---

**v0.2.3 の追加改善** (v0.2.2 レビュー指摘対応):

- **compare docstring の自己矛盾撤回** — v0.2.2 は 「これは Welch's t-test ではない」 と書いていたが、上の式が示す通り statistic は Welch t そのもの。訂正: 「statistic は Welch t と同一、異なるのは判定則 (df 依存 critical value vs 固定閾値)」 と書き分け。per-channel `interpretation` string も `"threshold_gate_on_welch_standard_error"` → `"welch_t_statistic_with_fixed_z_threshold"` に更新。
- **Welch-Satterthwaite `welch_df` 露出** — per-channel に `welch_df` field を追加。固定閾値 3.0 は n=5 で df≈8 なら本来 2.8〜4.6 が必要 (甘い側)、n=100 で df≈198 なら α≈0.003 相当 (厳しい側) と n 依存する。df を露出することで caller が 「今回の n でこの gate を信用していい範囲か」 を自分で判断できる。partial session は n が任意に小さくなり得るので、この露出は下流波及と繋がっている。
- **zero_variance / insufficient_samples guard** — 実害寄りの gap: mock device が定数を返す構成 (σ=0) や n=1 の partial session を compare すると、旧実装は `se=0 → z=0/0` (NaN) → `abs(z) > 3.0` は常に `False` に落ちて 「差が無い」 と静かに報告していた。v0.2.3 で明示 guard を導入: `n<2` → `gate_skip_reason: "insufficient_samples"`、`σ_A²/n_A + σ_B²/n_B = 0` → `gate_skip_reason: "zero_variance"`。どちらの場合も `mean_shift_z` / `welch_df` / `significant_shift` はすべて `None` (`False` にすると 「差が無い」 と 誤読されるので `None` = 「未評価」 signal に分離)。selftest phase [14] で `_ConstDevice` と `_FailingDevice(fail_after=1)` の 2 case verify。

呼び出し例:

```
「今日 mock で 5 回、それぞれ 30 秒ずつ測って、最後に一日分をまとめて見せて」
→ measure × 5 → search_sessions(since='2026-08-12') → 各 session plot_session
```

```
「先週の校正データと今の値を比べて、有意に動いていないか教えて」
→ search_sessions(note_contains='calib') で基準を特定
→ measure で今の値
→ compare_sessions(session_id_a=今, session_id_b=基準)
```

---

## 導入手順

### 1. 依存関係を入れる

```bash
pip install "mcp>=2.0.0" pyserial
```

`pyserial` は実機に繋ぐときだけ必要です。無くてもモックは動きます。

### 2. 動作確認（Claude に繋ぐ前に、まずこれ）

```bash
python benchtop_mcp.py --selftest
```

以下のように出れば成功です。

```
== benchtop-mcp セルフテスト ==
[1] ポート一覧: 3件 / pyserial=True
[2] IDN応答: MOCK,BENCHTOP-SIM,0001,1.0.0
[3] パース: 4形式すべてOK
[4] 計測: 60行 / channels=['T', 'H', 'V']
[5] 解析: T平均=25.019967 σ=0.473851 外れ値=2件
[6] CSV書き出し: ... (61行=ヘッダ1+データ60)
[7] plot: width=40 T='▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▂▄▄▄▄▄▆' (len=40, range=5.041)
[8] compare: shared=['T', 'H', 'V'] T delta_mean=0.146467 z=1.573 significant=False
[9] search: note='selftest' で 8 件ヒット (s=True, s2=True)
[10] invalid id → structured error='session_not_found' / 有効 id → Session OK
[11] compare threshold: |z|=0.507 welch_df=89.075 strict(3.0)=False loose(0.5)=True
[12] partial measurement: n_rows=5/20 aborted=True reason='RuntimeError: simulated device failure after 5 reads'
[13] partial downstream: analyze.partial=True/False plot.partial=True/False cmp.any_aborted=True/False cmp.aborted_inputs=['b'] search.partial=True/False
[14a] zero variance guard: evaluable=False reason=zero_variance z=None sig=None df=None
[14b] insufficient n guard: evaluable=False reason=insufficient_samples n_a=1 n_b=60
[14c] guard 独立性: 正常 case (phase [11] 再利用) evaluable=True 対 guard case evaluable=False
[15a] date-only 'since=2026-08-13' → resolved_utc=2026-08-12T15:00:00+00:00 date_only=True tz=Asia/Tokyo
[15b] full ISO 'since=2026-08-13T00:00:00+00:00' → resolved_utc=2026-08-13T00:00:00+00:00 date_only=False
[15c] JST 早朝 session (started=2026-08-12T15:30:00+00:00) が since='2026-08-13' で 拾える → found=True (旧 v0.2.3 では 拾えなかった)
[15d] started_at_local 補助 field: search[0]=2026-08-13T00:30:00+09:00 analyze=2026-08-13T00:30:00+09:00 (JST +09:00 一貫)

全テスト成功。実機が無くてもこのサーバーは動作します。
```

数値はランダム性で毎回変わりますが、行の形と phase 数 (1〜15) が一致し、末尾が「全テスト成功」で終われば正常です。Windows の `cp932` 端末でも Unicode スパークラインが表示できるよう、selftest 内で stdout を UTF-8 に切り替えています。phase [15] は `BENCHTOP_TZ='Asia/Tokyo'` を test 内で 一時的に設定 (finally で復元) して tz 依存を 固定しています。

### 3. Claude Desktop に登録する

設定ファイル（`%APPDATA%\Claude\claude_desktop_config.json`）に追記します。

```json
{
  "mcpServers": {
    "benchtop": {
      "command": "python",
      "args": ["C:\\path\\to\\benchtop_mcp.py"]
    }
  }
}
```

Claude Desktop を再起動すると、ツール一覧に `benchtop` が現れます。あとは普通に日本語で頼めます。

### 3.5. 再起動後の動作確認 (推奨)

いきなり本番の指示に入る前に、下の 3 step を挟むと「MCP server が本当に load されているか」「新 3 tool が Claude 側から見えているか」を確実に切り分けられます。MCP server load に失敗していても Claude は既存 tool で "それらしく" 答えてしまうので、失敗が結果に紛れないようにするための保険です。

**Step 3.5-a: tool load 確認 (最優先)**

```
使える tool を全部挙げて
```

期待値: `benchtop` の 9 tool (`list_ports` / `send_command` / `measure` / `list_sessions` / `analyze_session` / `export_session_csv` / `plot_session` / `compare_sessions` / `search_sessions`) が挙がること。挙がらなければ config が読まれていない → `%APPDATA%\Claude\claude_desktop_config.json` の path を確認。

**Step 3.5-b: seed データを 3 つ作る**

`search_sessions` と `compare_sessions` の verify には、note で区別できる複数セッションが必要です。

```
mock で 30 回、note='seed-A' で測って。終わったら少し待って、同じく note='seed-B' で 30 回、
また少し待って note='seed-C' で 30 回、計 3 セッション作って。
```

期待値: 3 つの `session_id` が返ること。各 `started_at` が数秒〜数十秒ずつずれていること (これが後の「一番古い/新しい」判定の根拠になる)。

**Step 3.5-c: 新 3 tool を verify**

```
1. さっき作った seed-B の T チャンネルを plot で見せて  (→ plot_session)
2. note に 'seed' を含むセッションを全部リストして      (→ search_sessions、started_at で新旧確認)
3. seed-A と seed-C を z_threshold=2.0 で比べて、
   T が有意にシフトしているか教えて                       (→ compare_sessions with explicit threshold)
```

期待値: (1) ▁▂▃▄▅▆▇█ のスパークライン + min/max/mean、(2) `seed-A` `seed-B` `seed-C` の 3 セッションが `started_at` 付きで一覧、(3) `mean_shift_z` の数値 + `z_threshold_used: 2.0` + `significant_shift` の bool。`compare_sessions` の判定閾値は明示指定した値で解釈されること (v0.2.1 の責任分界)。

---

## 実機に繋ぐ

装置が1行1レコードで値を送ってくるなら、それだけで動きます。Arduino 側の最小例:

```cpp
void setup() { Serial.begin(9600); }

void loop() {
  float t = analogRead(A0) * 0.0048828125 * 100.0;
  float v = analogRead(A1) * 0.0048828125;
  Serial.print("T="); Serial.print(t, 3);
  Serial.print(",V="); Serial.println(v, 4);
  delay(100);
}
```

あとは `port` に `COM3`（Windows）や `/dev/ttyUSB0`（Linux/Mac）を指定するだけです。

---

## コードの読みどころ

学習目的で読む場合、この3点が設計の要点です。

**1. コアと MCP 層を分離している**
`Bench` クラスは MCP を一切知りません。MCP 層（`@server.tool()` の部分）は薄い皮です。こうしておくと、コアだけ単体テストできますし、将来 CLI や Web API を生やすときにも書き直しが要りません。

**2. モック装置を最初から入れている**
`Device` という共通インターフェースを挟み、実機（`SerialDevice`）とモック（`MockDevice`）を差し替え可能にしています。ハードが手元に無い日でも開発が止まりません。デモも CI も通せます。ハードウェア絡みのソフトでは、これがあるか無いかで開発速度が何倍も変わります。

**3. docstring が AI への説明書になる**
`@server.tool()` を付けた関数の docstring と型注釈は、そのまま AI に渡されます。ここが雑だと AI は道具を正しく使えません。**普通のコードではコメントは人間向けですが、MCP では機械向けの仕様書です。** ここを丁寧に書くことが、そのまま品質になります。

---

## ライセンス

**v0.x = MIT** (LICENSE file 参照)。 藤本さん 2026-08-12 judgment per 選択。

v1.0+ 以降は AGPL-3.0 + commercial dual への 切替可能性 予告 (LICENSE file 内 「License trajectory notice」 参照)。 但し v0.x code は 永久 MIT (irrevocable) = fork 継続 path は 永久に開く。

背景: [Product Transition Judgment Framework v0.1](https://rei-aios.pages.dev/tools/product-transition-judgment-v01/) の 5 checklist を benchtop-mcp v0.x 段階では 0-1 件該当 = 無料継続 default。

### 参考: 有料化候補 3 点 fit (chat-Claude 2026-08-12 arc 分析)

benchtop-mcp は 「売れる条件 3 点」 全該当 = 有料化 candidate:
- **誰もが必要**: 計測ログ + 統計 + CSV 出力 は 差別化要素でない (全部の 計測現場が やる作業)
- **自作面倒**: シリアル通信 + セッション管理 + AI 説明 docstring は 毎回書きたくない
- **静かに壊れて高い**: 監視ログが 数日 気付かず 溜まる、 品質記録が 消えると 監査で困る

将来 v1.0+ で 有料 tier 検討する場合の 線引き案:

### 推奨する組み合わせ (将来 v1.0+ の 参考、 現時点 v0.x = MIT)

**ソフト部分: AGPL-3.0 + 商用ライセンスのデュアル**

- 個人・研究・社内利用は無料で自由に使える（あなたの「個人にも使ってほしい」という希望を満たす）
- ただし、これを組み込んだ製品を売るなら、ソース公開か商用ライセンス購入かを選ぶことになる
- MIT にすると、この選択を後から追加できません。AGPL なら、後から緩めるのは自由（著作権者はいつでも緩められる）

**貢献者対応: CLA を最初に用意する**

外部から Pull Request を受け取ると、その部分の著作権は相手のものになり、あなた単独でライセンスを変更できなくなります。将来の商用化を残すなら、最初から CLA（貢献者ライセンス同意書）を置いてください。後から遡って集めるのは、ほぼ不可能です。

### 無料／有料の線引き案

| | 無料（AGPL） | 有料 |
|---|---|---|
| 装置操作・計測・解析・CSV | ○ | ○ |
| 同時接続する装置の数 | 1台 | 無制限 |
| 長時間の連続ロギング・自動再接続 | − | ○ |
| 閾値アラート・異常通知 | − | ○ |
| 校正記録・監査ログ（トレーサビリティ） | − | ○ |
| サポート・SLA | − | ○ |

企業が金を払うのは機能ではなく、**「止まったときに誰かに電話できる権利」と「監査に出せる記録」** です。個人が欲しがるのは上段だけなので、この線引きなら両者は競合しません。

### 回路・装置を含める場合の警告 (依然 有効)

**公開する前に特許出願の要否を判断してください。** ソフトと違い、ハードウェアは公開した瞬間に新規性が失われ、特許が取れなくなります。日本には新規性喪失の例外（特許法30条、公開から1年以内の出願）がありますが、国によって扱いが異なり、海外出願で詰むことがあります。

これは**一方通行のドア**です。ユーザーが0人でも損失は確定します。

**本 project の scope**: benchtop-mcp = 純 software (Python + pyserial via generic protocol) = **特許性事実上ゼロ** (シリアル通信 + 統計 + CSV export は 数十年 well-known)。 ハードウェア回路 (Arduino sketch 例は README 参照用のみで 本 repo に含まず) は 依然 上記警告対象。

---

## 次にやるとよいこと

1. `--selftest` を通す（最優先。ここが通れば土台は正しい）
2. Claude Desktop に登録して、実際に日本語で呼んでみる (再起動後は上の Step 3.5 の 3 step verify を先に)
3. 手持ちの装置1台を繋いで、`send_command` で `*IDN?` に応答が返るか確認
4. **自分が毎回手でやっている面倒な作業を1つ、ツールとして足す** — ただし判定基準は AND 2 条件:
   - (i) 1 回の測定で手作業が **3 step 以上** (装置接続 → コマンド送信 → CSV 貼付、のような複数手順)
   - (ii) **週 1 回以上** 発生 (月 1 未満の作業は tool 化コスト > 手作業コスト)

   どちらか外れる作業は tool 化しない。この 2 条件を通ったものだけ 4 tool 目候補として拾う。ここからが本当のオリジナルです。
5. ライセンスを決めて GitHub に公開

Elasticsearch は奥さんのレシピアプリから始まりました。最初から立派である必要はありません。
