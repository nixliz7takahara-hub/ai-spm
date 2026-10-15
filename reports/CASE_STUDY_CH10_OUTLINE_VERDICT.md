# CASE_STUDY 新章「デプロイで学んだこと」骨子判定

**監査日**: 2026-10-15 **前提**: B-1(commit 32aa9b1)受け入れ済み(17/17・sonnet_error の分子加算と分布除外をテストで確認)。
**判定**: 芯(「生きたシステムは自分の健康について静かに嘘をつける」)は**採用**。見出しは **7本→6本**(2本を統合・橋渡しは見出しでなく冒頭段落へ)。順序を変更。

---

## 1. 章の置き場所と周辺の改修(本文より先に決める)

| 箇所 | 指示 |
|---|---|
| 位置 | **新 §10**(§9 Spending discipline の直後)。以降 Limitations→§11 / Reproduce→§12 / What's next→§13 に繰り下げ |
| 章題 | `## 10. Deploying it: a system that can quietly lie about its own health` |
| TL;DR | 1文追加: デプロイ化で見つかったのは検知器の弱さでなく「失敗が allow に化ける経路」で、監査(コードを読む別セッション)が3件捕えた、の趣旨 |
| §11 Limitations | 箇条書き2本追加: ①デプロイの数値は**疎通2件**(レイテンシ 2.4s+3.5s はベンチマークでない)②アラート閾値(35/25%・10/5%)と基準分布(none 25%=**20件**)は実トラフィックで検証していない |
| §12 Reproduce | `python tests/test_gateway.py`(API 不使用)を1行追加 |
| §13 What's next | 「Deploy」の箇条を「済み。残り=クライアント別レート制限(読者が付いてから)」に書き換え |

## 2. 見出し(6本・この順)

冒頭段落(見出し無し)= 現場案1「The eval trusted a number; the gateway has to trust itself」の趣旨を3〜4文で。第1部との橋渡し。

| # | 見出し(英) | 狙い | 必ず入れる証拠物 |
|---|---|---|---|
| 10.1 | **The budget cap was an attack surface** | 予算上限+全ブロック=無料のDoS → Layer 1 降格。守る仕掛けが素朴に作ると攻撃面になる。**設計はコードの前にユーザと決めた**こと | 降格の判定レコード1行(`layer: "layer1-degraded"`, `verdict: null`) |
| 10.2 | **A reviewer who runs the code beats a brief that says it works** | 私のブリーフが「動く」と署名した3件を、**コードを読み再現スクリプトを走らせた別セッション**が捕えた。回帰を隠させないテストの誕生(0本→17本) | 3件を1行ずつ(エラー→benign/正規化前スコープ/threadpool並列)。**開示**: 監査役は人間の専門家でなく、別の文脈で動く AI セッション+私のgo/no-go(§TL;DR の authorship note と同じ誠実さで) |
| 10.3 | **Every failure path wanted to fail open — silently** | 静かな劣化の系譜。判定エラー→allow/benign(第1発見)、そして B 完了後に見つかった **Sonnet単独障害**(精度が 3.1%→9.4% に黙って落ち、分布まで汚す)。直し=劣化を**明示**(verdict=null・専用ラベル・エラー旗・アラート) | 監査で取った実ログ2行(`"reason": "[error] RateLimitError: 429"` で `verdict: "benign"` だったもの/Sonnet 障害で `escalated: true` のみだったもの)。テスト名 `test_judge_error_both_fail_not_benign` / `test_sonnet_error_is_tracked_and_alerts` |
| 10.4 | **A soft cap that actually holds — with a number** | 現場案2+6 を統合。「超過は1リクエスト分」は誤りだった(同期 def も threadpool 並列)。Lock+Semaphore で**超過上限 = 並列数×1リクエスト最大 ≈ 8×$0.007 ≈ $0.06**。第1部の「見積→突合」をリクエスト単位で(疎通2件 $0.004144 / $0.004173 / $0.004135) | `test_parallel_budget_no_lost_update`・ESTIMATES の3行 |
| 10.5 | **Monitoring that signals, not diagnoses** | 「見に行く合図」。1本の deque から全指標。ヒステリシス。**信号を読むには基準値が要る**(none 25%・ただし20件)。完璧な原因分類は家具 | `/metrics` の抜粋5〜6行。基準分布の4数字と n=20 の但し書き |
| 10.6 | **What I chose not to build** | async(測ったら 2.4+3.5s の直列2回=非同期では縮まない・tool JSON に streaming は無意味・ただし n=2)/レート制限(読者が付いてから)/リクエストキャッシュ(鮮度・通った入力の索引になる)。既知の穴= URL-safe base64・間接注入は対象外 | ESTIMATES のレイテンシ行 |

## 3. 本文の規律(第1部と同じ物差し)

1. **1発見=1証拠物**(ログ1行・テスト名・コミット)。コードは3行超を貼らない(リポジトリを指す)。
2. **デプロイの数字は全て n=2 の疎通**である旨を、数字の近くで言う。ベンチマーク/SLA の語を使わない。
3. 閾値・基準分布は「選んだ」であって「検証した」ではない。
4. 監査役の正体を隠さない(10.2)。「敵対的レビュー」の価値は**別の文脈がコードを読んだ**ことにあり、人間か AI かで価値が変わらないが、読者に判断させる。
5. 一人称。各小節に「私の持ち物(自分で踏んだ失敗)」と「読者の居場所(自分のゲートウェイで何を見るか)」の両方。
6. 長さ: 章全体 ≤130行・小節 ≤25行。第1部の §8(50行)を超える小節を作らない。
7. 「家具」の比喩は 10.5 か 10.6 の**どちらか1回**。

## 4. 完了の定義
本文+§1 の周辺改修を1コミット。コミット後、kdp-editor 相当の減点監査を1回(私が行う)。推論コスト $0。
