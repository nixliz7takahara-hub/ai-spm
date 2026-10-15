# B(監視詰め)設計レビュー判定 — 実装前

**監査日**: 2026-10-15 **対象**: `reports/B_MONITORING_BRIEF.md`(commit e2d45bc)+増分C(commit 5db25d0)の完了検証
**コスト影響**: なし。

---

## 0. 増分Cの完了検証(実物)

- `tests/test_gateway.py` を監査側で実行 → **10/10 通過**(pytest・API不使用)。
- 監査1-1〜1-9 はコード上で全て確認。判定エラー→`judge-error`/verdict=None、正規化後スコープ、Lock+Semaphore、クライアント再利用、`/health` degraded、X-Client-Id、input_hash、prune、HTTP max_length。
- レイテンシ再測定(Haiku ≈2.4s + Sonnet ≈3.5s・直列)で「6秒=モデル2回分」が確定。**async 保留の判断は正しかった**(クライアント生成は原因ではなかったが、測って確定したことに価値がある)。

**Cで残った小さな穴(Bの中で直す・別増分にしない)**:

| # | 場所 | 内容 | 直し方 |
|---|---|---|---|
| C-1 | `gateway._cascade_live` | **Haikuエラー→Sonnet救済を `escalated=True` で返している**。帯域エスカレと救済が同じ旗。Bの窓エスカレ率に429嵐が混ざり、分布変化とコスト攻撃の区別に第3の原因(API障害)が紛れる | 戻り値に `rescued` を追加。`escalated` は帯域エスカレのみ。METRICS に `rescued` を別カウント |
| C-2 | `gateway._log_degraded_transition` | `_last_degraded` の読み書きがロック外。並列で enter が2回出うる | `_MLOCK` 下に入れる |
| C-3 | `gateway.check` | 生の長さ判定の**前に** `layer1.normalize` を走らせている。HTTP層の max_length が守るが、`check()` 直呼び(テスト・将来の別入口)では巨大入力を正規化してから捨てる | `len(text) > MAX_INPUT_CHARS` を normalize の前に1行 |

---

## 1. 設計の総評

方針(「見に行く合図」・判定しない・$0・インメモリ)は**正しい**。構造を1点だけ変える: **4つの状態を別々に持たず、「直近100判定のレコード1本の deque」から全部を導出する**。

```python
_JUDGED = collections.deque(maxlen=100)   # 1判定=1レコード(dict)
# {"client": id, "escalated": bool, "rescued": bool, "error": bool, "final_risk": str}
```

- §1 の窓エスカレ率 = `sum(r.escalated)/len`
- §2a の最終判定分布 = `Counter(r.final_risk for r if r.escalated)`
- §2b の**直近**クライアント別 = `Counter(r.client for r if r.escalated)`
- 追加(下記 §3)のエラー率 = `sum(r.error)/len`

利点: ロックが1つ・整合が保証(同じ100件を見ている)・テストが1本の deque を覗くだけ・`/metrics` は計算して返すだけで状態更新が無い。2c のハッシュ窓だけ別(母数が違う=全リクエスト)。

---

## 2. §7 の5点の確定

| # | 論点 | 確定 | 根拠 |
|---|---|---|---|
| 1 | 最小サンプル | **30件で発火・窓100** | 基準20%で30件中11件超(>35%)が偶然起きる確率≈2.6%、満窓100件なら36件超≈0.01%。スライディング窓は毎push評価なので30件直後は誤報が多めだが「見に行く合図」としては許容 |
| 2 | per-client メモリ | **累積は持たない**。直近は §1 の deque から導出(自然に上限100)。累積の `requests` を出したければ **LRU・上限 K=1,000**(`OrderedDict`・touch で `move_to_end`・超過で `popitem(last=False)`) | 無制限 Counter は client_id を無数に投げるだけで膨らむ(DoS面)。累積値は再起動で消えるので価値が薄い。「今、誰がエスカレを占めているか」は直近100で十分 |
| 3 | 窓か累積か | **全部窓**(2b も) | ブリーフの「per-client だけ累積」を却下。累積だと先週活発だった client が再起動まで上位を占め続け、「今の異常」を見る目的に反する |
| 4 | デバウンス | クロッシング1回で可。ただし**ヒステリシス**: 発火 >35%・解除 <25%。解除時に `escalation_alert_clear` を1行 | 35%付近で揺れると enter/clear が連打される。clear イベントが無いとログから継続時間が読めない |
| 5 | `/metrics` の読み手 | **人間+jq/スクリプト。JSONのまま**。Prometheus 形式は作らない | 消費者が居ないものを作ると家具になる。`per_client` の配列だけ非フラットだが、必要になったら `/metrics/prom` を足せばよい(JSONは据え置き) |

---

## 3. ブリーフへの追加・修正

### 3-1. エラー率の窓とアラートを**同じ機構で**追加(必須)
B1監査の最重要項目(判定エラーのフェイルオープン)はCで「正直に記録する」までは直ったが、**起きていることを知らせる**仕組みがまだ無い。§1 の deque に `error` が乗るので、`judge_error_rate_window` と `judge_error_alert`(発火 >10%・解除 <5%・最小30件)は**ほぼ無料**で足せる。429嵐(攻撃者が無料で起こせる)を見に行く合図はこれ。

### 3-2. 2a の読み方に**基準値**を付ける(必須・$0)
「`none` 率が高い=無害側の分布変化」は**基準が無いと読めない**。カスケードは設計上、エスカレした入力の多くを Sonnet が `none` に覆す(Haiku の過検知を消すのが目的)。つまり平常時から none 率は高い。
→ `reports/eval_cascade.py` の gold100 キャッシュ(無料)から、**エスカレ20件の Sonnet 最終判定分布**を1回計算し、README に「基準分布」として載せる。アラートにはしない(20件では無理)。読み手が比べる物差しを置くだけ。

### 3-3. 2c の母数と単位
- 母数は**全リクエスト**(scope reject・layer1 block を含む)。プロービングは第1層で弾かれている段階から始まる。ブリーフの「直近1000入力」はこの意味で確定。
- 窓の要素は `(client_id, hash)` の組にする。別クライアントが同じ挨拶を送るのは重複ではない。`dup_rate` は組で計算。

### 3-4. client_id の扱い
`/metrics` の `per_client` は client_id を生で出す。**client_id は不透明トークン前提**(メール等のPIIを入れない)を app.py のdocstringと README に1行。ログには既に出ているので、方針を明文化するだけ。

### 3-5. テストへの追加(ブリーフ §6 に加える)
- Haiku エラー→Sonnet 救済が **`escalation_rate_window` に乗らない**(C-1 の検証)。
- `judge_error_alert` が30件以上・>10%で1回出る。
- ヒステリシス: 35%超で発火→30%に下がっても clear が出ない→25%未満で clear が1回出る。
- アラート行の検証は stdout をキャプチャ(pytest なら `capsys`、素のモードなら `contextlib.redirect_stdout`)。既存のデュアルモード(素/pytest)を維持。

### 3-6. 変更しないこと(ブリーフ §8 に同意)
中核フロー・判断1・帯域・閾値・第1層・record既定。**レート制限はBに入れない**(次の増分Dの候補として記録のみ)。

---

## 4. 受け入れ条件(B完了の定義)

1. `_JUDGED` deque 1本から §1/2a/2b/エラー率を導出。`_HASH_WINDOW` は `(client, hash)` で別。
2. `/metrics` 追加フィールド: `escalation_rate_window` / `escalation_alerting` / `escalated_verdict_dist` / `per_client_recent`(直近・escalated降順 top20) / `judge_error_rate_window` / `judge_error_alerting` / `input_hash_dup_rate` / `window_size`。
3. イベント行: `escalation_alert` / `escalation_alert_clear` / `judge_error_alert` / `judge_error_alert_clear`(既存 degraded_enter/exit と同形式)。
4. C-1〜C-3 を同コミットで修正。
5. README に基準分布(3-2)と client_id 方針(3-4)と「監視状態は再起動でリセット・一次記録はログ」を記載。
6. テスト: 既存10 + 追加6以上、全緑・API不使用。実 API は最後の疎通2件のみ(ESTIMATES 事前記録)。
