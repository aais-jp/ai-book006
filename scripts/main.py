"""出社の入口。

GitHub Actions から呼ばれるのはこのファイルだけ。
「受付で振り分けて、そのまま社員が働く」までを1つのプロセスで完結させる。
振り分けと実行をワークフローとして分けない理由は本文(第4章)を参照。
"""

import os
import sys

from lib import gemini, gh, store
import employee
import receptionist

WORKFLOW_FILE = "company.yml"


def main():
    number = os.environ.get("ISSUE_NUMBER", "").strip()
    if not number:
        print("ISSUE_NUMBER が渡されていません。")
        return 0
    number = int(number)

    # 停止装置その1: 出社の印を置き、上限を超えていたら全社停止。
    # どのモデルで動いたかも印に残す。あとから品質の変化を追えるようにするため。
    try:
        model_name = gemini.model()
    except Exception as err:
        model_name = "(解決できず: %s)" % err
    remain, warning = store.charge(number, model_name)
    if warning:
        # 設定が読めないことは、黙って既定値で進めずに必ず知らせる。
        gh.say(number, receptionist.SIGN + warning)
    if remain is None:
        gh.say(number, receptionist.SIGN + "\n".join([
            "今月ぶんの稼働枠(概算)を使い切りました。全社の稼働を停止します。",
            "",
            "**翌月になっても、自動では再開しません。**",
            "ワークフローそのものを無効にしたため、戻す操作が必要です。",
            "",
            "再開のしかた:",
            "1. リポジトリの Actions 画面で `company` を選び、Enable workflow を押す",
            "2. 今月中に再開する場合は、その前に `company/usage/` の当月フォルダを空にする",
            "",
            "翌月まで待つ場合は、フォルダを空にする必要はありません。",
            "月ごとにフォルダが分かれているため、新しい月は自動的に0から数え直します。",
        ]))
        try:
            gh.disable_workflow(WORKFLOW_FILE)
        except Exception as err:  # 停止できなくても処理は終える
            print("ワークフローの無効化に失敗しました: %s" % err)
        return 0

    # 停止装置その2: 1案件あたりの自動応答の回数。
    limit = int(os.environ.get("MAX_BOT_COMMENTS", "20"))
    said = sum(1 for c in gh.comments(number) if c["user"]["type"] == "Bot")
    if said >= limit:
        print("この案件の自動応答が上限(%d 件)に達しました。" % limit)
        return 0

    print("使用モデル: %s" % model_name)
    print("今月の残り出社: 約 %d 回(概算)" % remain)

    # 社員が一人もいなければ、まず会社を作る。
    if not store.members():
        receptionist.interview(number)
        return 0

    # 受付が担当を決め、そのまま同じプロセスで働かせる。
    assignments, merge_id = receptionist.assign(number)
    if not assignments:
        return 0

    employee.work_together(number, assignments, merge_id)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as err:
        # 失敗しても Issue 側に必ず痕跡を残す。黙って落ちるのが一番困る。
        print("ERROR: %s" % err)
        target = os.environ.get("ISSUE_NUMBER", "").strip()
        if target:
            try:
                gh.say(int(target), receptionist.SIGN
                       + "処理中に問題が発生しました。\n\n```\n%s\n```\n\n"
                         "Actions のログをご確認ください。" % str(err)[:800])
            except Exception:
                pass
        sys.exit(1)
