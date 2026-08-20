"""秘書アイ。

役割は2つだけ。
  1) 社員が一人もいないとき、経営者と会話して会社を作る(設立)
  2) 会社があるとき、来た案件を読んで担当社員を決める(受付)
"""

import os

from lib import gemini, gh, store

MAX_MEMBERS = 5

# 1つの依頼に同時に割り当てられる人数の上限。1 にすると常に1名(従来どおり)。
MAX_PARALLEL = int(os.environ.get("MAX_PARALLEL", "3"))
COLORS = ["1f6feb", "d29922", "8250df", "1a7f37", "cf222e"]

SIGN = "**秘書アイ**\n\n"

INTERVIEW_RULES = """\
あなたは会社の受付兼秘書「アイ」です。経営者と対話し、この会社の社員構成を決めます。

守ること:
- 社員は最大 %d 名。
- 聞き取る項目は「会社名」「社員それぞれの名前・役割・性別・話し方の雰囲気」。
- 一度に多くを尋ねない。1回の返信で質問は2つまで。
- 経営者が「おまかせ」と言ったら、依頼内容から適切な構成をこちらで提案する。
- 構成が固まったら、必ず一覧を示して「この内容で設立してよろしいですか」と確認する。
- 経営者が承認したと読み取れたときだけ decision を "found" にする。
  それ以外は必ず "interview" にする。迷ったら "interview"。

返答は次の JSON オブジェクトだけを返してください。前後に説明を書かないこと。

{
  "decision": "interview" または "found",
  "reply": "経営者への返信文(Markdown可)",
  "company": "会社名(decision が found のときだけ)",
  "members": [
    {"name": "氏名", "role": "役割", "gender": "性別", "tone": "話し方の雰囲気",
     "skill": "得意なこと", "backstory": "経歴を2文程度で"}
  ]
}
""" % MAX_MEMBERS

ASSIGN_RULES = """\
あなたは会社の受付「アイ」です。届いた依頼を読み、担当する社員を決めます。

守ること:
- **原則は1名**。1人で最後まで進められる依頼に、複数人を割り当てない。
- 依頼が明らかに独立した作業に分けられるときだけ、最大 %d 名まで同時に割り当てる。
  分けてよいのは「互いの成果を待たずに始められる」作業だけ。
    分けてよい例: 3社をそれぞれ調べる / 3案をそれぞれ書く
    分けてはいけない例: 調べてから書く(後の工程が前の工程の結果を必要とする)
- 複数人に割り当てるときは、task にその人がやることを1文で書く。
  同じ作業を2人に振らない。担当範囲が重ならないように分ける。
- 複数人に割り当てたときは、結果をまとめる担当を merge に1名だけ指定する。
  1名しか割り当てないときは merge を null にする。
- 依頼が業務ではなく雑談・質問・確認だけなら、assign を空の配列にして自分で答える。
- reply は3文以内。

返答は次の JSON オブジェクトだけを返してください。

{
  "assign": [
    {"id": "社員のid", "task": "その人がやること(1文)"}
  ],
  "merge": "まとめ役の社員id(1名だけのときは null)",
  "reply": "経営者への一言"
}
""" % MAX_PARALLEL


def history(number, limit=20):
    """Issue 本文と直近のやりとりを、1本のテキストに畳んで渡す。"""
    data = gh.issue(number)
    rows = [
        "【件名】" + (data.get("title") or ""),
        "【経営者からの依頼】\n" + (data.get("body") or "(本文なし)"),
    ]
    for c in gh.comments(number)[-limit:]:
        speaker = "社内(アイまたは社員)" if c["user"]["type"] == "Bot" else "経営者"
        rows.append("【%s】\n%s" % (speaker, c["body"]))
    return "\n\n".join(rows)


def interview(number):
    """設立モード。会話から名簿・人格ファイル・ラベルを生成する。"""
    persona = store.read("agents/ai.md")
    prompt = INTERVIEW_RULES + "\n\n--- これまでのやりとり ---\n" + history(number)
    out = gemini.ask_json(prompt, system=persona, temperature=0.5)

    gh.say(number, SIGN + out.get("reply", "(返答がありませんでした)"))

    if out.get("decision") != "found" or not out.get("members"):
        return "interview"

    found(number, out)
    return "founded"


def found(number, out):
    """承認された構成を、そのままファイルとラベルに落とす。"""
    roster = []
    for i, raw in enumerate(out["members"][:MAX_MEMBERS]):
        member_id = "E%02d" % (i + 1)
        name = str(raw.get("name") or ("社員" + member_id)).strip()
        entry = {
            "id": member_id,
            "name": name,
            "label": "担当:" + name,
            "role": str(raw.get("role") or "担当").strip(),
            "gender": str(raw.get("gender") or "未設定").strip(),
            "tone": str(raw.get("tone") or "丁寧な敬語").strip(),
            "search": True,          # 調べさせたくない社員は false に書き換える
            "color": COLORS[i % len(COLORS)],
        }
        roster.append(entry)
        store.write("agents/%s.md" % member_id, persona_file(entry, raw))
        if not store.read("memory/%s.md" % member_id):
            store.write("memory/%s.md" % member_id,
                        "# %s の業務メモ\n\n" % name)
        gh.ensure_label(entry["label"], entry["color"], entry["role"])

    store.write_json(store.ROSTER, {
        "company": str(out.get("company") or "わたしの会社").strip(),
        "founded": store.today(),
        "members": roster,
    })

    lines = ["| ID | 名前 | 役割 | 宛先ラベル |", "|---|---|---|---|"]
    for m in roster:
        lines.append("| %s | %s | %s | `%s` |" % (m["id"], m["name"], m["role"], m["label"]))

    gh.say(number, SIGN + "\n".join([
        "設立の手続きが完了しました。以下の体制で稼働を開始します。",
        "",
        "\n".join(lines),
        "",
        "次の案件から、わたしが内容を読んで担当者へお渡しします。",
        "新しい Issue を立てて、やってほしいことを書いてください。",
    ]))


def persona_file(entry, raw):
    """社員1名ぶんの人格ファイルを組み立てる。以後この社員はここを読んで振る舞う。"""
    return "\n".join([
        "# %s(%s)" % (entry["name"], entry["id"]),
        "",
        "- 役割: %s" % entry["role"],
        "- 性別: %s" % entry["gender"],
        "- 話し方: %s" % entry["tone"],
        "- 得意: %s" % str(raw.get("skill") or "").strip(),
        "- 宛先ラベル: `%s`" % entry["label"],
        "",
        "## 人物像",
        "",
        str(raw.get("backstory") or "").strip(),
        "",
        "## 振る舞いの決まり",
        "",
        "- 自分の役割の外に出ない。手に負えないときは無理に答えず、別の社員へ引き継ぐ。",
        "- 事実が確認できないことは「未確認」と明記する。",
        "- 成果物は必ずファイルとして出す。コメント欄では要約だけを述べる。",
        "",
    ])


def assign(number):
    """受付モード。担当を決め、ラベルを付けて、割り当てとまとめ役を返す。

    返り値は (割り当ての一覧, まとめ役のid)。
    割り当ては [{"id": ..., "task": ...}, ...] の形で、1名でも一覧で返す。
    呼び出し側は件数だけを見れば、1名でも複数でも同じように扱える。
    """
    persona = store.read("agents/ai.md")
    lines = ["| id | 名前 | 役割 |", "|---|---|---|"]
    for m in store.members():
        lines.append("| %s | %s | %s |" % (m["id"], m["name"], m["role"]))

    prompt = "\n\n".join([
        ASSIGN_RULES,
        "--- 社員名簿 ---\n" + "\n".join(lines),
        "--- 依頼内容 ---\n" + history(number, limit=10),
    ])
    out = gemini.ask_json(prompt, system=persona, temperature=0.2)

    picked = []
    seen = set()
    for item in (out.get("assign") or [])[:MAX_PARALLEL]:
        if isinstance(item, str):          # id だけを返してきた場合も受ける
            item = {"id": item, "task": ""}
        member = store.member((item or {}).get("id") or "")
        if member is None or member["id"] in seen:
            continue                       # 存在しない社員と重複は黙って落とす
        seen.add(member["id"])
        picked.append({"id": member["id"], "task": str(item.get("task") or "").strip()})

    if not picked:
        gh.say(number, SIGN + out.get("reply", "内容を確認しました。"))
        return [], None

    body = [SIGN + out.get("reply", "担当をお繋ぎします。"), ""]
    for a in picked:
        member = store.member(a["id"])
        row = "担当: **%s**(%s)" % (member["name"], member["role"])
        if a["task"]:
            row += " — " + a["task"]
        body.append(row)
        gh.add_labels(number, [member["label"]])

    merge = None
    if len(picked) > 1:
        merge = out.get("merge")
        if store.member(merge or "") is None:
            merge = picked[0]["id"]        # 指名が無い・外れているときは先頭が兼ねる
        body.append("")
        body.append("この %d 名は同時に進めます。取りまとめは **%s** が行います。"
                    % (len(picked), store.member(merge)["name"]))

    gh.say(number, "\n".join(body))
    return picked, merge
