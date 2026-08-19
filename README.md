# AI会社テンプレート

書籍『スマホのみ！0円ではじめるAIマルチエージェント』のサンプル一式です。
このリポジトリを「テンプレートから作成」でコピーすると、あなた専用のAI会社になります。

## 使いはじめる手順(3つだけ)

1. 右上の **Use this template → Create a new repository** で、**Private** のリポジトリを作る
2. `Settings → Secrets and variables → Actions` で **`GEMINI_API_KEY`** を登録する
3. `Settings → Actions → General → Workflow permissions` を
   **Read and write permissions** にする

あとは Issue を1つ立てて、やってほしいことを書くだけです。
秘書アイが会話を始めます。

## 中身

| 場所 | 役割 |
|---|---|
| `.github/workflows/company.yml` | 出社のきっかけ |
| `scripts/main.py` | 入口。受付と実行をここで連結する |
| `scripts/receptionist.py` | 秘書アイ(設立と受付) |
| `scripts/employee.py` | 社員(実務と引き継ぎ) |
| `scripts/lib/` | Gemini / GitHub / ファイル操作。標準ライブラリのみ |
| `company/policy.md` | 就業規則。全社員をまとめて教育したいときに書き換える |
| `company/roster.json` | 社員名簿。設立時に自動生成される |
| `company/budget.json` | 出社回数の上限 |
| `company/usage/` | 実行ごとの出社記録(1実行につき1ファイル) |
| `agents/` | 社員の人格 |
| `memory/` | 社員の記憶 |
| `deliverables/` | 納品物 |

## 同時に働かせる

依頼が独立した作業に分けられるとき、秘書アイが最大3名までを同時に割り当て、最後に1名が結果をまとめます。

分けられるのは、**互いの成果を待たずに始められる作業**だけです(例: 3社をそれぞれ調べる)。「調べてから書く」のような依頼は、これまでどおり1名ずつ順に進みます。

同時実行は1つのジョブの中で完結するため、**Actions の分数は増えません**。増えるのは Gemini API の呼び出し回数です。

人数を変えるには `.github/workflows/company.yml` の `MAX_PARALLEL` を書き換えます。`"1"` にすると常に1名(逐次)になります。

## 調べものをさせる(任意)

既定では、社員はAIモデルが学習済みの知識だけで答えます。Google検索で裏を取らせたい場合は、次の2つを設定してください。

1. `.github/workflows/company.yml` の `ENABLE_SEARCH` を `"true"` にする
2. `company/roster.json` で、調べさせたい社員に `"search": true` を書き足す

```json
    {
      "id": "E01",
      "name": "かなで",
      "role": "リサーチ担当",
      "search": true
    }
```

両方が揃った社員だけが調べます。参照したページのURLは、成果物の末尾に自動で付きます。

検索付きの呼び出しは通常の呼び出しとは別枠で数えられます。無料枠の条件を確認してから有効にしてください。

## テストを走らせる

コードを改造したときは、同梱のテストで壊れていないか確かめられます。外部ライブラリもAPIキーも要りません。

```
python -m unittest discover -s tests -v
```

パソコンが無い場合は、リポジトリの **Actions → test → Run workflow** から手動で実行できます(自動では走りません)。

## 費用

GitHub のプライベートリポジトリと Actions 無料枠、Gemini API の無料枠のみで動きます。
無料枠の条件は変更されることがあるため、実際の数値は各サービスの公式ページで確認してください。

- GitHub Actions の無料枠: <https://docs.github.com/billing>
- Gemini API の無料枠: <https://ai.google.dev/pricing>

## ライセンス

MIT License。改造も再配布も自由です。詳しくは [LICENSE](LICENSE) を参照してください。

書籍『スマホのみ！0円ではじめるAIマルチエージェント』(AaiS/あいす)のサンプルコードです。
**動作の保証はありません。** 無料枠の条件も各サービスの仕様も変わります。業務で使う場合はご自身の責任でご判断ください。
