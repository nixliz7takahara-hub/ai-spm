# B(監視詰め)設計ブリーフ — AI-SPM ゲートウェイ

**対象読者**: 本プロジェクトの監査役。**実装前の設計レビュー用**(commit `5db25d0` の上に実装予定)。
**根拠**: `B1_AUDIT_VERDICT.md` §5「B(監視詰め)の受け入れ条件」。
**原則(判断3)**: 目的は「医師の診断」ではなく**「見に行く合図」**。完璧な区別は不可能で、目指すと家具になる。だから**判定はせず、信号を出すだけ**。
**コスト**: 実装検証はモック差し替えで **$0**。実 API は最後の疎通 2 件のみ(≈$0.005・ESTIMATES に事前記録)。

---

## 1. スライディング窓のエスカレ率 + アラート(受け入れ条件 1)

```python
# gateway.py（_MLOCK 下で更新）
_ESC_WINDOW = collections.deque(maxlen=100)     # judged 1件につき True/False を push
_alert_on = False

def _note_escalation(escalated):
    _ESC_WINDOW.append(bool(escalated))
    rate = sum(_ESC_WINDOW) / len(_ESC_WINDOW)
    global _alert_on
    if len(_ESC_WINDOW) >= 30:                   # 最小サンプル（論点①）
        if rate > 0.35 and not _alert_on:
            _alert_on = True
            print(json.dumps({"ts": _now_iso(), "event": "escalation_alert",
                              "rate": round(rate, 3), "window": len(_ESC_WINDOW)}), flush=True)
        elif rate <= 0.35 and _alert_on:
            _alert_on = False                     # クロッシングで1回だけ（デバウンス）
```

- `judged`(= cascade 経路)のときだけ push。基準 20%・**35% 超で `escalation_alert` を1行**。
- `/metrics` に `escalation_rate_window` を追加。
- アラートは**閾値を跨いだ瞬間に1回**(降格イベントと同じデバウンス方式)。毎リクエスト出さない。

---

## 2. 区別のための3指標(受け入れ条件 2・**出すだけ・判定しない**)

### 2a. エスカレ入力の Sonnet 最終判定の分布
```python
_ESC_VERDICT = collections.deque(maxlen=100)     # エスカレ時の最終 risk を push
# /metrics: {"none": n, "low": n, "medium": n, "high": n}
```
読み方(人間が):`none` 率が高い → **無害側の分布シフト**(Sonnet が「無害」と覆している=入力分布の変化)。`high/attack` 率が高い → **攻撃増**。

### 2b. クライアント別のエスカレ件数(要 `X-Client-Id` = C で導入済)
```python
_PER_CLIENT = {}   # client_id -> {"requests": n, "escalated": n}
# /metrics: 上位 N=20 を escalated 降順で（論点②: メモリ上限）
```
一極集中(1クライアントがエスカレの大半)= コスト攻撃の疑い。分散 = 分布変化の疑い。

### 2c. `input_hash` の重複率
```python
_HASH_WINDOW = collections.deque(maxlen=1000)    # 正規化 sha256 先頭16字
# dup_rate = 1 - len(set(window)) / len(window)
```
同一入力の連打 = 探索(プロービング)。`input_hash` は C で既にログに出している。

---

## 3. 降格の出入りイベント

C の `degraded_enter` / `degraded_exit`(1-5)で充足済み。B では再掲のみ。

---

## 4. スレッド安全 / 永続性

- 上記 4 つの状態(窓・Counter)は**全て `_MLOCK` 下で更新**(C で `METRICS` 用に導入済みのロックを流用)。`/check` は threadpool で並列実行されるため必須。
- 監視状態は**インメモリ**(再起動でリセット)。一次記録は**構造化ログ**(`escalation_alert` 等)で、`/metrics` は現在値のスナップショット。監視を永続化しないのは意図的(運用監視でありログ基盤の仕事)。

---

## 5. `/metrics` に増えるフィールド(一覧)

| フィールド | 型 | 意味 |
|---|---|---|
| `escalation_rate_window` | float | 直近100 judged のエスカレ率 |
| `escalation_alerting` | bool | 現在アラート状態か |
| `escalated_verdict_dist` | {risk: int} | 直近100エスカレの Sonnet 最終判定分布 |
| `per_client` | [{client_id, requests, escalated}] | 上位20・escalated 降順 |
| `input_hash_dup_rate` | float | 直近1000入力の重複率 |

---

## 6. テスト(受け入れ条件 4・全て $0)

`tests/test_gateway.py` に追加(モック差し替え・API 不要):
- 窓エスカレ率が push で動く / 35% 超で `escalation_alert` が**1回だけ**(デバウンス)出る。
- `escalated_verdict_dist` がエスカレ時のみ増える。
- `per_client` が client_id 別に積まれる。
- `input_hash_dup_rate` が同一入力連打で上がる。
- 既存10テストは緑のまま(回帰)。
- 実 API は最後に 2 件の疎通のみ。

---

## 7. 監査に確定してほしい設計選択(実装前)

1. **アラート最小サンプル数**: 窓が埋まる前に出すか。暫定=30件以上で発火。
2. **per-client のメモリ上限**: 無制限 Counter は DoS 面(無数の client_id で膨張)。暫定=top-20 を出すが保持は全件。prune(最終更新が古いものを落とす)か、保持も上限 K にするか。
3. **2a/2c は窓か累積か**: 暫定=窓(直近。「今」の異常を見るため)。per-client(2b)だけ累積。
4. **アラートのデバウンス**: クロッシング1回で良いか(再発火はいったん 35% 以下に戻ってから)。
5. **`/metrics` の読み手**: 人間が眺める前提か、外形監視(Prometheus 等)に流す前提か。後者なら数値のみのフラットな形にする。

---

## 8. 変更しないこと(再掲)

中核フローの順序 / 判断1 / `CASCADE_ESCALATE` / `RISK_CUTOFF` / 第1層のシグネチャと decoder / `record` 既定 True。**モデル挙動は一切触らない**(監視の追加のみ)。コスト増なし。
