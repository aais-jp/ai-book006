"""GitHub REST API の最小クライアント。

外部ライブラリは使わない。Python 標準の urllib だけで組み立てる。
認証は GitHub Actions が自動で用意する GITHUB_TOKEN を使う。
"""

import json
import os
import urllib.error
import urllib.request

API = os.environ.get("GITHUB_API_URL", "https://api.github.com")
REPO = os.environ.get("GITHUB_REPOSITORY", "")
TOKEN = os.environ.get("GITHUB_TOKEN", "")


class GitHubError(RuntimeError):
    """HTTP ステータスを持ったまま投げ直すための例外。"""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _request(method, path, payload=None):
    url = path if path.startswith("http") else API + "/repos/" + REPO + path
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            text = res.read().decode("utf-8")
        return json.loads(text) if text.strip() else {}
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:300]
        raise GitHubError(err.code, "%s %s -> %s %s" % (method, url, err.code, detail))


def issue(number):
    """Issue 本体(タイトル・本文・ラベル)を取得する。"""
    return _request("GET", "/issues/%s" % number)


def comments(number, limit=100):
    """Issue のコメントを古い順に取得する。"""
    return _request("GET", "/issues/%s/comments?per_page=%d" % (number, limit))


def say(number, text):
    """Issue にコメントを書き込む。社員の発言はすべてここを通る。"""
    return _request("POST", "/issues/%s/comments" % number, {"body": text})


def add_labels(number, names):
    """Issue にラベルを付ける。宛先の指定に相当する。"""
    return _request("POST", "/issues/%s/labels" % number, {"labels": names})


def ensure_label(name, color, description=""):
    """ラベルが無ければ作る。既にあれば 422 が返るので、それは無視する。"""
    try:
        _request("POST", "/labels", {
            "name": name,
            "color": color,
            "description": description[:100],
        })
    except GitHubError as err:
        if err.status != 422:
            raise


def close(number):
    """Issue を閉じる。案件の完了に相当する。"""
    return _request("PATCH", "/issues/%s" % number,
                    {"state": "closed", "state_reason": "completed"})


def disable_workflow(filename):
    """ワークフローそのものを無効化する。最後の停止装置。"""
    return _request("PUT", "/actions/workflows/%s/disable" % filename)
