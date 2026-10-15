# B(監視詰め)受け入れ検証 — commit 8eb1698

**監査日**: 2026-10-15 **方法**: テスト実行(pytest/素の両モード)+実コード精読+ゴールドキャッシュからの基準分布再計算+Sonnet単独障害の再現(全て API 不使用・$0)。

## 0. 判定: **合格(条件1つ=B-1 を小コミットで修正)**

## 1. 受け入れ条件 §4 の照合

| # | 条件 | 結果 | 確認方法 |
|---|---|---|---|
| 1 | `_JUDGED` 1本から導出・`_HASH_WINDOW` は `(client, hash)` | ✅ | `gateway.py` L65-66, L165-170, L241-262。`/metrics` は snapshot→計算のみ、状態更新なし |
| 2 | `/metrics` 8フィールド | ✅ | `window_size` / `escalation_rate_window` / `escalation_alerting` / `escalated_verdict_dist` / `per_client_recent`(top20) / `judge_error_rate_window` / `judge_error_alerting` / `input_hash_dup_rate` 全て存在 |
| 3 | 4イベント行(ヒステリシス) | ✅ | `_eval_alerts` 35/25%・10/5%・最小30件。既存 degraded_enter/exit と同形式 |
| 4 | C-1〜C-3 | ✅ | `rescued` 分離(L105-106)/降格遷移が `_MLOCK` 下(L140)/生長さが normalize 前(L191) |
| 5 | README 基準分布・client_id 方針・リセット注記 | ✅ | **基準分布を監査側で再計算**: gold100 のキャッシュで帯域エスカレ20件の Sonnet 最終判定 = none 5 / low 3 / medium 9 / high 3。README と一致 |
| 6 | テスト16本・ESTIMATES 事前記録 | ✅ | 16/16(pytest 0.58s・素モードも同結果)。疎通2件 $0.004135(見積 $0.005・上限 $0.01 内) |

## 2. 見つかった穴(1件・小)

### B-1. Sonnet 単独障害が**見えない**(再現済み)

Haiku=low/medium で帯域エスカレ → Sonnet がエラー → Haiku の判定を採用(設計どおり)。このとき:

```
{"decision":"block","layer":"cascade","reason":"haiku low","risk":"low","escalated":true,"rescued":false, ...}
metrics: judge_error_rate_window=0.0  escalated_verdict_dist={"low":1}
```

- ログに **Sonnet が失敗した痕跡が無い**(`reason` は Haiku の理由、`error` 旗は「両方失敗」専用)。
- `judge_error_rate_window` は 0 のまま → **Sonnet だけの429嵐ではアラートが出ない**。その間カスケードの精度は Haiku 単体(誤検知 3.1%→9.4%)に**黙って**落ちる。これは B1 監査1-1 と同じ種類の「静かな劣化」の最後の1片。
- さらに `escalated_verdict_dist` に **Haiku の判定が Sonnet の最終判定として混入**する。README の基準分布(Sonnet 判定)と比べる前提が崩れる。

**直し方(同じ機構・小)**:
1. `_cascade_live` の戻りに `sonnet_error` を追加(Haiku 採用かつ Sonnet 失敗で True)。レコード/ログ/`_JUDGED` に乗せる。
2. `judge_error_rate_window` と `judge_error_alert` の分子を **`error or sonnet_error`**(どのモデルでも失敗)にする。`METRICS["judge_error"]`(判定不能の件数)は従来どおり。
3. `escalated_verdict_dist` は `sonnet_error` のレコードを**除外**(Sonnet の判定だけを数える)。`/metrics` に `sonnet_error_rate_window` を1つ追加。
4. テスト1本: Haiku low + Sonnet エラーで `sonnet_error=True`・dist に乗らない・35件で `judge_error_alert` が1回。

## 3. 変更不要と判断したもの
- `MIN_SAMPLES=30` が env 化されていない: 不要(変える根拠が出てから)。
- 累積 `escalation_rate` を残していること: 可(窓と並記で意味が明確)。
- 生長さ超過時の `input_hash` が生テキストのハッシュ: 可(正規化できないので当然)。

## 4. B 完了後の次(監査の見解・ユーザ判断)
B-1 修正で「ゲートウェイの静かな劣化」は全て可視化される。ここで**エンジニアリングを一度止めて**、`CASE_STUDY.md` に「デプロイ化で学んだこと」の節を書くのを推奨する(予算DoS→降格・フェイルオープンを監査で発見→正直なラベル・ソフトキャップの数字・監視は診断でなく合図)。この作品の価値はケーススタディであり、増分D(レート制限)は読者が居るときに作ればよい。
