# benchtop-mcp

シリアル接続された計測装置・回路を、AI エージェント（Claude など）から直接操作・記録・解析するための MCP サーバーです。

**実機がなくても動きます。** 内蔵の仮想装置（`port="mock"`）があるので、ハードを繋ぐ前に全機能を試せます。

**Version**: 0.2.1 (2026-08-13) — v0.2.0 のレビュー指摘に沿った 3 改善: compare_sessions に z_threshold パラメータ明示 (判定責任の外部化) / 無効 session_id を structured error dict で返す / measure の途中失敗を partial 結果として保存。詳細は下記「v0.2 で足したもの」節。

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
- **`compare_sessions`** — 「先週と比べて怪しくないか」 を AI が数値で判断できるように、2 セッションの mean/stdev/drift 差分と Welch 型 z スコアを返す。**判定は呼び出し側の責任**: `z_threshold` パラメータ (既定 3.0) を明示指定でき、`significant_shift` は `|z| > z_threshold` を評価しただけ、`z_threshold_used` に採用値が反映されるので後から audit 可能。これは Welch's t-test の p 値でも t 分布 CDF による厳密検定でもない、粗い gate。厳密検定が必要なら生の `mean_shift_z` と `n` を取り出して外部で処理する。
- **`search_sessions`** — `list_sessions` は直近 30 件しか返さないので、`~/.benchtop-mcp/` にセッションが溜まってきたらこちら。since/until (ISO 日時) + note キーワード (大文字小文字無視) + port + channel の AND 絞り込み。

**v0.2.1 の追加改善** (v0.2.0 レビュー指摘対応):

- **`measure` 途中失敗の partial 保存** — 装置切断・Ctrl+C・SerialException 等が起きても、そこまでに取れた行はセッションに保存され、返り値の `partial: true` と `abort_reason` で通知される。100 回中 60 で止まっても「60 行取れた + 止まった理由」が残る。全部捨てるより実運用の失敗解析に使える。
- **無効 `session_id` の structured error** — 上の tool 表下の注記の通り、例外ではなく dict で返す。

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
[11] compare threshold: |z|=1.573 strict(3.0)=False loose(0.5)=True
[12] partial measurement: n_rows=5/20 aborted=True reason='RuntimeError: simulated device failure after 5 reads'

全テスト成功。実機が無くてもこのサーバーは動作します。
```

数値はランダム性で毎回変わりますが、行の形と phase 数 (1〜12) が一致し、末尾が「全テスト成功」で終われば正常です。Windows の `cp932` 端末でも Unicode スパークラインが表示できるよう、selftest 内で stdout を UTF-8 に切り替えています。

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
