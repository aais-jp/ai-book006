"""月次の締めと、稼働状況の掲示。

やることは2つだけ。
  1) 当月より前の出社記録(company/usage/<年-月>/)を削除する
  2) 今月の出社回数・残り回数・納品件数を、掲示用の Issue に書く

カウンタを 0 に戻す処理は無い。出社記録は月ごとのフォルダに分かれているので、
月が変われば新しいフォルダで自然に 0 から始まる。
"""

import datetime
import os

from lib import gh, store

BOARD_ISSUE = os.environ.get("BOARD_ISSUE", "").strip()


def prune(keep):
    """当月以外の出社記録を削除し、消した件数を返す。"""
    base = store.path(store.USAGE)
    if not os.path.isdir(base):
        return 0
    gone = 0
    for name in sorted(os.listdir(base)):
        folder = os.path.join(base, name)
        if name == keep or not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            os.remove(os.path.join(folder, f))
            gone += 1
        os.rmdir(folder)
    return gone


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    month = store.month_key(now)
    limit, warning = store.limit_of()
    used = store.used_in(month)

    # 先月より前の印は掃除する。放っておくとフォルダが増え続ける。
    removed = prune(keep=month)

    roster = store.roster()
    delivered = 0
    folder = store.path("deliverables")
    if os.path.isdir(folder):
        for _, _, files in os.walk(folder):
            delivered += len(files)

    lines = [
        "**%s 稼働状況(%s 時点)**" % (roster.get("company") or "当社", store.today()),
        "",
        "| 項目 | 値 |",
        "|---|---|",
        "| 今月(%s)の出社回数 | %d 回 |" % (month, used),
        "| 今月の上限 | %d 回 |" % limit,
        "| 残り | 約 %d 回(概算) |" % max(0, limit - used),
        "| 在籍社員 | %d 名 |" % len(roster.get("members", [])),
        "| 納品ファイル総数 | %d |" % delivered,
        "",
        "※ 出社回数は Actions の実測時間ではなく、**起動回数の概算**です。",
        "　 正確な使用量は GitHub の Billing 画面で確認してください。",
    ]
    if removed:
        lines += ["", "先月までの出社記録 %d 件を整理しました。" % removed]
    if warning:
        lines += ["", "⚠ " + warning]

    text = "\n".join(lines)
    print(text)

    if BOARD_ISSUE:
        gh.say(int(BOARD_ISSUE), text)


if __name__ == "__main__":
    main()
