# CASE_STUDY §10 減点監査(commit e2c06b3)

**監査日**: 2026-10-15 **方式**: 商業編集の減点法(100点起点・合格80)。骨子判定書 §3 の規律7条と第1部の物差し(数字の出所・一人称・開示)で採点。
**形式要件**: 章112行(≤130)✓・各小節≤25行✓・§繰り下げと相互参照(§11/§13・README §11)✓・「家具」1回✓・テスト名2本は実在✓。

## 判定: **67点・再提出(1回)**。直しは全て言い換えで、$0・1コミット。

骨子は守られており構成は良い。減点は**語り手の破綻1箇所**と、**「3件=同じバグ」という事実の誇張**に集中している。この章の売りが誠実さなので、この2つは致命傷になる。

---

## 減点一覧(重い順)

| # | 箇所 | 指摘 | 減点 | 直し |
|---|---|---|---|---|
| 1 | 10.1 L348 「I had the project owner decide」 | **語り手が割れた**。この文書の「I」はプロジェクト所有者本人(著者注で AI は「under my direction」)。所有者に決めさせる「I」は実装側 AI の視点であり、著者注と矛盾する。読者がここで「誰が書いているのか」を疑えば、第1部の信頼も崩れる | −8 | 「So, before writing any code, I made the exhaustion behaviour an explicit decision: degrade to Layer 1 only, not block.」 |
| 2 | 10.3 L378 「The three bugs were one bug in different clothes: on any failure, the gateway defaulted to allow」+ TL;DR L30-32 「failure paths that quietly turn into allow… caught three of them」 | **事実の誇張**。3件のうち「失敗→allow」は判定エラーの1件だけ。正規化前スコープは**コスト上限の迂回**、threadpool は**予算計上の破れ**で、どちらも allow には倒れない。10.4 自身が後者を「cap didn't hold」と正しく書いているので章内で矛盾している | −8 | 10.3: 「The worst of the three — and a fourth found later — were the same bug in different clothes…」。TL;DR: 「A separate, code-reading audit session caught three bugs my own brief had signed off as working — including the worst kind: a failure path that quietly turned into *allow* (§10).」 |
| 3 | 10.5 L425-428 `/metrics` 抜粋(0.52 / 0.14 / escalated 48)+ L430 「can tell … in seconds」 | 抜粋は**作例**であり観測値ではないが、その旨が無い。第1部の読者は全ての数字を実測と読む。さらに「in seconds で区別できる」は §11 の「閾値は未検証」と矛盾し、10.5 の主題「診断しない」とも矛盾 | −6 | 抜粋の前に「a made-up reading, to show the shape:」。結びは「has something concrete to go and look at — one client and errors up points one way, a spread-out rise in the none-rate points the other. It is a pointer, not a verdict.」 |
| 4 | 10.3 L383 ログ行・10.1 L354 ログ行 | 出所未記載。429 の行は**監査がスタブで注入した再現**であり本番観測ではない。10.1 の行は**抜粋(abridged)**。どちらも真だが、出所を書かないのは第1部の規律(ESTIMATES 突合・n を書く)に反する | −4 | 10.3: 「reproduced in the audit with a stubbed judge error:」。10.1: 「(abridged)」をコードブロック直前に |
| 5 | 10.2 L362-364 「signed off three design decisions as implemented and correct … all three were wrong」 | 設計判断は5つで、間違っていたのは**実装と検証の主張**であって設計判断ではない(降格・台帳分離・帯域は正しかった)。「設計が3つ間違い」は自分を不要に貶め、かつ不正確 | −3 | 「described five design decisions and reported them implemented and verified. A separate review read the code and ran repro scripts, and three of those implementation claims were false: …」 |
| 6 | 10.3 L390 「precision quietly fell from 3.1% to 9.4% false positives」 | 用語違い。3.1→9.4 は**誤検知率(FPR)**であり precision ではない(第1部は precision 94.1/84.6% を別に出している)。読者が第1部の表と突き合わせると合わない | −2 | 「the false-positive rate would quietly revert from the cascade's 3.1% to Haiku-alone's 9.4%」 |
| 7 | 10.4 L403 「The cap wasn't soft; it was absent」 | 修辞の誇張。実際は threadpool の上限(40)で有界=**40 × $0.007 ≈ $0.28**(日次 $1 の約3割)。この数字を書く方が「数字で語る」章の主題に合う | −2 | 「The cap wasn't soft; it was bounded only by the thread pool — 40 × $0.007 ≈ $0.28 on a $1 day. A lock…」 |

合計 −33 → **67点**。

## 減点しなかったが直すと良いもの(任意・各0点)
- 10.4 「$0.007」の出所を括弧で: 「(an 8,000-char input through both models)」。読者が検算できる。
- 10.6 は骨子どおりで良い。最後の一文「it was learning what the number is worth, and writing that down」は第1部の結語(L518-519)と重複気味。削っても章は閉じる(判断は現場)。

## 合格条件(再提出時)
#1〜#7 を反映。追加の文章は不要(全て言い換え)。再提出後、相互参照とテスト名の実在だけ再確認して合格とする。
