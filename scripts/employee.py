"""社員。

就業規則・自分の人格・自分の記憶・案件の履歴を読み、
返答、成果物、業務メモ、引き継ぎ先を1回の呼び出しで決める。
"""

import concurrent.futures
import os
import re

from lib import gemini, gh, store
import receptionist

WORK_RULES = """\
あなたはこの会社の社員です。届いた案件を自分の役割の範囲で処理してください。

出力は次の JSON オブジェクトだけです。前後に説明を書かないこと。

{
  "reply": "経営者への報告(200字程度。何をしたか、どこを見てほしいか)",
  "deliverable": {
    "filename": "成果物のファイル名(拡張子つき。不要なら null)",
    "content": "成果物の中身(Markdown。不要なら null)"
  },
  "memo": "次に同じ案件を触るときの自分向けメモ(1〜2行。不要なら null)",
  "handoff": {
    "to": "引き継ぎ先の社員id(不要なら null)",
    "reason": "引き継ぐ理由"
  },
  "done": true または false
}

守ること:
- 自分の役割の外の作業は自分でやらず、handoff に適切な社員 id を入れる。
- 引き継ぐ相手がいない、または自分で完了できるなら handoff.to は null。
- 成果物は原則ファイルとして出す。reply には要約だけを書く。
- **依頼の中心に答えられないなら、成果物を作らない。** 空欄や「※要確認」で埋めた
  文書を出すくらいなら、何も作らず reply で理由を伝えるほうがよい。
- 「※要確認」は、**答えの裏取りが甘い箇所に添える印**であって、
  答えそのものを省くための言葉ではない。依頼の中心には使わない。
- 経営者に追加で聞きたいことがあるときは done を false にして reply で尋ねる。
"""


RESEARCH_RULES = """\
これから受ける依頼に答えるため、Google検索で事実を確認してください。

守ること:
- 調べるのは、数字・日付・料金・仕様・固有名詞など、記憶に頼ると危ういものだけ。
- 分かったことを箇条書きで10項目以内にまとめる。意見・提案・文章案は書かない。
- 調べても確認できなかったことは「未確認」と明記する。
- 出典URLは書かないこと。こちらで機械的に付けるので、あなたが書く必要はない。
"""


def research(number, member):
    """仕事に入る前に、事実を調べる。

    返り値は (調べた事実, 出典リスト)。
    既定では全員が調べる。名簿で "search": false にした社員だけが調べない。
    検索が無効・非対応・枠切れのときは ("", []) を返し、素の知識のまま仕事に入る。
    調べものができないことを、仕事ができない理由にはしない。
    """
    switch = os.environ.get("ENABLE_SEARCH", "true").strip().lower()
    if switch in ("0", "false", "no", "off"):
        return "", []
    # 名簿に "search" が無ければ調べる。調べさせたくない社員にだけ false を書く。
    if member.get("search", True) is False:
        return "", []

    query = "\n\n".join([
        RESEARCH_RULES,
        "--- あなたの役割 ---\n%s(%s)" % (member["name"], member["role"]),
        "--- 依頼 ---\n" + receptionist.history(number, limit=6),
    ])
    try:
        facts, sources, queries = gemini.search(query)
    except gemini.SearchUnavailable as err:
        print("検索を利用できませんでした。素の知識で続けます: %s" % err)
        return "", []

    print("検索語: %s / 出典 %d 件" % (", ".join(queries) or "(なし)", len(sources)))
    return facts, sources


def brief(number, member, facts="", task=""):
    """社員1名に渡す資料一式を組み立てる。"""
    others = [m for m in store.members() if m["id"] != member["id"]]
    lines = ["| id | 名前 | 役割 |", "|---|---|---|"]
    for m in others:
        lines.append("| %s | %s | %s |" % (m["id"], m["name"], m["role"]))

    blocks = [
        WORK_RULES,
        "--- 就業規則 ---\n" + store.read(store.POLICY, "(未設定)"),
        "--- あなたの人格 ---\n" + store.read("agents/%s.md" % member["id"], "(未設定)"),
        "--- あなたの業務メモ ---\n" + store.read("memory/%s.md" % member["id"], "(まだありません)"),
        "--- 同僚 ---\n" + "\n".join(lines),
    ]
    if task:
        # 分担しているときは、自分の持ち分を最初に念押しする。
        blocks.append("--- 今回のあなたの持ち分 ---\n" + task
                      + "\n\nほかの担当が並行して別の部分を進めています。持ち分の外には手を出さないでください。")
    if facts:
        # 調べた事実は案件より前に置く。後ろに置くと、目に入る前に書き始める。
        blocks.append("--- 調べた事実(Google検索で確認済み) ---\n" + facts)
    else:
        # **調べられないことを、社員に隠さない。**
        # 黙って渡すと、社員は「知らない」と「調べられない」を区別できず、
        # 中身の無い成果物を「※要確認」で埋めて出してしまう。
        blocks.append(
            "--- 調べもの ---\n"
            "今回は外部を調べていません。学習済みの知識だけで答えてください。\n"
            "最新の順位・件数・価格・日付など、調べないと分からないことを"
            "求められている場合は、推測で書かないこと。\n"
            "そのときは成果物を作らず、reply に「調べる機能が有効でないため"
            "この依頼には答えられない」と書き、done を false にしてください。")
    blocks.append("--- 案件 ---\n" + receptionist.history(number, limit=12))
    return "\n\n".join(blocks)


def think(number, member_id, task=""):
    """モデルに問い合わせるところまで。

    **この関数は副作用を持たない。** ファイルにも Issue にも書かない。
    だから複数人ぶんを同時に走らせても安全になる。
    """
    member = store.member(member_id)
    if member is None:
        return None, {}, []

    facts, sources = research(number, member)
    out = gemini.ask_json(
        brief(number, member, facts, task),
        system="あなたは「%s」。役割は %s。話し方は %s。"
               % (member["name"], member["role"], member["tone"]),
        temperature=0.5,
    )
    return member, out, sources


def deliver(number, member, out, sources, claimed=None):
    """考えた結果を、リポジトリと Issue に反映する。

    **この関数は必ず1件ずつ順に呼ぶ。** 同時に呼ぶと、コメントの順序が
    実行の速さで決まってしまい、読み手が経過を追えなくなる。
    """
    body = ["**%s**(%s)\n" % (member["name"], member["role"]),
            out.get("reply", "(報告がありませんでした)")]

    deliverable = out.get("deliverable") or {}
    filename = safe_name(deliverable.get("filename"))
    content = deliverable.get("content")
    if filename and content:
        if claimed is not None:
            # 同時に働くと、別々の担当が同じファイル名を選ぶことがある。
            # 空いている名前が見つかるまで、担当者名を足してずらす。
            stem, dot, ext = filename.rpartition(".")
            if not dot:
                stem, ext = filename, ""
            n = 0
            while filename in claimed:
                n += 1
                tail = member["name"] if n == 1 else "%s%d" % (member["name"], n)
                filename = "%s_%s%s%s" % (stem, tail, dot, ext)
            claimed.add(filename)
        rel = "deliverables/%s/%s" % (number, filename)
        text = str(content).rstrip() + "\n"
        if sources:
            # 出典はモデルの文章からではなく、検索APIが返した一覧から貼る。
            text += "\n## 出典\n\n" + "\n".join(
                "- [%s](%s)" % (title, uri) for title, uri in sources) + "\n"
        store.write(rel, text)
        body.append("\n納品: `%s`" % rel)
        if sources:
            body.append("(出典 %d 件を末尾に付けました)" % len(sources))

    memo = (out.get("memo") or "").strip()
    if memo:
        store.append("memory/%s.md" % member["id"],
                     "- %s #%s %s\n" % (store.today(), number, memo.replace("\n", " ")))

    gh.say(number, "\n".join(body))
    return out


def run_once(number, member_id, task="", claimed=None):
    """1名ぶんの仕事を、考えて反映するところまで通しで行う。"""
    member, out, sources = think(number, member_id, task)
    if member is None:
        return {}
    return deliver(number, member, out, sources, claimed)


def work(number, member_id, task="", claimed=None):
    """引き継ぎを追いかける。ただし回数には天井を設ける。"""
    max_hops = int(os.environ.get("MAX_HOPS", "3"))
    visited = []
    hop = 0

    while member_id:
        visited.append(member_id)
        out = run_once(number, member_id, task, claimed)
        task = ""                      # 持ち分の指定は最初の1人にだけ効かせる
        nxt = (out.get("handoff") or {}).get("to")

        if not nxt or store.member(nxt) is None or nxt in visited:
            break
        if hop >= max_hops:
            gh.say(number, receptionist.SIGN
                   + "引き継ぎが %d 回に達したため、ここで一度止めます。"
                     "続きが必要でしたら、このIssueにコメントで指示してください。" % max_hops)
            break

        hop += 1
        member_id = nxt

    return visited


def work_together(number, assignments, merge_id=None):
    """複数の社員を同時に走らせ、最後に1人がまとめる。

    時間がかかるのはモデルへの問い合わせだけなので、そこだけを同時に走らせる。
    ジョブは1つのままなので、**Actions の分数は増えない**。
    """
    limit = max(1, int(os.environ.get("MAX_PARALLEL", "3")))
    assignments = assignments[:limit]
    if len(assignments) == 1:
        return work(number, assignments[0]["id"], assignments[0].get("task", ""))

    # モデルの解決を先に済ませておく。各スレッドから同時に問い合わせないため。
    gemini.model()

    print("%d 名を同時に動かします。" % len(assignments))
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(assignments)) as pool:
        futures = [pool.submit(think, number, a["id"], a.get("task", ""))
                   for a in assignments]
        results = []
        for a, future in zip(assignments, futures):
            try:
                results.append(future.result())
            except Exception as err:
                # 1人がこけても、他の担当の成果は捨てない。
                print("%s の処理に失敗しました: %s" % (a["id"], err))
                results.append((None, {}, []))

    # 反映は割り当てた順に、1件ずつ。出力の順序を実行の速さに任せない。
    claimed = set()
    done = []
    for member, out, sources in results:
        if member is None:
            continue
        deliver(number, member, out, sources, claimed)
        done.append(member["id"])

    if not done:
        gh.say(number, receptionist.SIGN
               + "全員の処理に失敗しました。Actions のログをご確認ください。")
        return []

    # 並行で走った担当の引き継ぎ指示は見ない。ここで枝分かれさせると止まらなくなる。
    if merge_id and store.member(merge_id) and len(done) > 1:
        # まとめ役は1回だけ動かす。ここで引き継ぎを追うと、終わりが見えなくなる。
        # claimed を渡して、担当者の納品物を上書きしないようにする。
        run_once(number, merge_id,
                 "同時に進んだ %d 名の報告が、この Issue のコメントに出そろっています。"
                 "それらを1つの成果物にまとめてください。"
                 "重複を削り、食い違いがあれば「食い違いあり」と明記すること。" % len(done),
                 claimed)

    return done

def safe_name(name):
    """モデルが返したファイル名から、パスを遡る文字などを取り除く。"""
    if not name:
        return None
    name = os.path.basename(str(name).strip())
    name = re.sub(r"[^0-9A-Za-z぀-ヿ一-鿿._\- ]", "_", name)
    return name[:80] or None
