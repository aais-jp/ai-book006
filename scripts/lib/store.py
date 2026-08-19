"""リポジトリの中を「会社の書庫」として読み書きする。

データベースは使わない。すべてリポジトリ内のファイルで持つ。
YAML ではなく JSON を選んだのは、標準ライブラリだけで読み書きできるから。
"""

import datetime
import json
import os

ROOT = os.environ.get("GITHUB_WORKSPACE", ".")

ROSTER = "company/roster.json"
BUDGET = "company/budget.json"
POLICY = "company/policy.md"
# 出社の印を置く場所。1実行につき1ファイル。書き込む先を重ねないための置き場。
USAGE = "company/usage"

# 上限の既定値と、設定が読めなかったときに使う安全値。
DEFAULT_LIMIT = 1500
SAFE_LIMIT = 50


def path(rel):
    return os.path.join(ROOT, rel)


def read(rel, default=""):
    try:
        with open(path(rel), encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return default


def write(rel, text):
    full = path(rel)
    folder = os.path.dirname(full)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def append(rel, text, keep_lines=200):
    """追記する。ただし古い行から捨てて、一定量以上には育てない。"""
    lines = (read(rel) + text).splitlines()
    write(rel, "\n".join(lines[-keep_lines:]) + "\n")


def read_json(rel, default):
    raw = read(rel).strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except ValueError:
        return default


def write_json(rel, obj):
    write(rel, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def roster():
    return read_json(ROSTER, {"company": "", "members": []})


def members():
    return roster().get("members", [])


def member(member_id):
    for m in members():
        if m.get("id") == member_id:
            return m
    return None


def member_by_label(label):
    for m in members():
        if m.get("label") == label:
            return m
    return None


def month_key(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m")


def limit_of():
    """今月の上限と、警告文の組を返す。

    **設定が壊れていても既定値には戻さない。**
    上限を 100 に下げていた人のファイルが壊れたとき、既定の 1500 に戻すのは
    「安全側」ではなく「危険側」に倒すことになる。読めないときは、
    ぐっと小さい SAFE_LIMIT を使い、警告文を添えて呼び出し側に伝える。
    """
    raw = read(BUDGET).strip()
    if not raw:
        # ファイルが無い・空 → まだ設定していないだけ。既定値でよい。
        return DEFAULT_LIMIT, ""
    try:
        data = json.loads(raw)
        return int(data["limit"]), ""
    except (ValueError, TypeError, KeyError) as err:
        return SAFE_LIMIT, (
            "`company/budget.json` を読めませんでした(%s)。\n"
            "安全のため、今月の上限を %d 回として動いています。\n"
            "ファイルを直すまで、この状態が続きます。" % (err, SAFE_LIMIT))


def used_in(month):
    """その月の出社回数。印の数をそのまま数える。"""
    folder = path("%s/%s" % (USAGE, month))
    if not os.path.isdir(folder):
        return 0
    return len([f for f in os.listdir(folder) if f.endswith(".txt")])


def charge(number=None, model_name=""):
    """出社1回ぶんの印を置き、(今月の残り回数, 警告文)を返す。

    残り回数は概算。使い切っていたら None を返す。
    警告文は、設定ファイルが読めなかったときだけ中身が入る。

    **共有カウンタを読んで書き戻す方式は使わない。**
    別々のIssueは同時に動く。両方が同じ値を読み、同じ値を書き戻すと、
    片方の計上が消える。しかも同じファイルを書くのでプッシュも衝突する(第6章)。

    かわりに、実行ごとに自分だけのファイルを1つ置き、その数を数える。
    書く場所が重ならないので、計上が消えることも、衝突することもない。

    ただしこれは分数の実測ではなく、**出社回数の概算**である。
    同時に始まった実行は互いの印を見られないため、上限をわずかに超えることがある。
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    month = month_key(now)
    run_id = "%s-%s" % (os.environ.get("GITHUB_RUN_ID", "local"),
                        os.environ.get("GITHUB_RUN_ATTEMPT", "1"))

    write("%s/%s/%s.txt" % (USAGE, month, run_id),
          "%s\tissue=%s\tmodel=%s\n" % (now.isoformat(timespec="seconds"),
                                         number if number is not None else "-",
                                         model_name or "-"))

    limit, warning = limit_of()
    used = used_in(month)
    if used > limit:
        return None, warning
    return limit - used, warning


def today():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
