"""Gemini API の最小クライアント。

この本のコードにはモデル名を書かない。
起動のたびに ListModels API へ問い合わせ、そのとき使えるモデルの中から選ぶ。
モデルが世代交代しても、コードを書き換えずに動き続けるための設計。
"""

import json
import os
import time
import urllib.error
import urllib.request

BASE = "https://generativelanguage.googleapis.com/v1beta"
KEY = os.environ.get("GEMINI_API_KEY", "")

# 前から順に探す。安くて無料枠の大きいものを先に置く。
PREFER = ("flash-lite", "flash")

# 用途が違って今回は使わないモデルを名前で弾く。
EXCLUDE = ("embedding", "aqa", "vision", "tts", "image", "live", "native-audio")

_picked = []


class SearchUnavailable(RuntimeError):
    """検索だけが使えなかったときの合図。仕事そのものは止めない。"""


def _get(url):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode("utf-8"))


def _post(url, payload):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=120) as res:
        return json.loads(res.read().decode("utf-8"))


def chosen():
    """すでに決まっているモデル名。まだ決めていなければ空文字。

    どのモデルで動いたかを記録に残すために使う。自動選択は寿命を延ばすが、
    「いつ何が選ばれたか」を残さないと、品質が変わった原因を追えなくなる。
    """
    return _picked[0] if _picked else ""


def model():
    """実行時に使えるモデルを解決して返す。1プロセス内では1回だけ問い合わせる。"""
    if _picked:
        return _picked[0]

    forced = os.environ.get("GEMINI_MODEL", "").strip()
    if forced:
        _picked.append(forced if forced.startswith("models/") else "models/" + forced)
        return _picked[0]

    data = _get(BASE + "/models?pageSize=200&key=" + KEY)
    usable = []
    for item in data.get("models", []):
        name = item.get("name", "")
        if "generateContent" not in item.get("supportedGenerationMethods", []):
            continue
        if any(word in name for word in EXCLUDE):
            continue
        usable.append(name)

    for want in PREFER:
        hit = [n for n in usable if want in n]
        if hit:
            # 「-latest」で終わる別名があればそれを最優先で使う。
            alias = [n for n in hit if n.endswith("-latest")]
            _picked.append(sorted(alias or hit)[-1])
            return _picked[0]

    if not usable:
        raise RuntimeError("generateContent に対応したモデルが見つかりませんでした")
    _picked.append(sorted(usable)[-1])
    return _picked[0]


def ask(prompt, system=None, temperature=0.4, max_tokens=4096, retries=3):
    """1回の問い合わせ。混雑時は少し待って数回だけ再試行する。"""
    url = "%s/%s:generateContent?key=%s" % (BASE, model(), KEY)
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}

    wait = 5
    for attempt in range(retries):
        try:
            data = _post(url, payload)
        except urllib.error.HTTPError as err:
            retryable = err.code in (429, 500, 502, 503)
            if retryable and attempt < retries - 1:
                time.sleep(wait)
                wait *= 2
                continue
            detail = err.read().decode("utf-8", "replace")[:300]
            raise RuntimeError("Gemini API -> %s %s" % (err.code, detail))
        cand = (data.get("candidates") or [{}])[0]
        parts = cand.get("content", {}).get("parts", [])
        if cand.get("finishReason") == "MAX_TOKENS":
            # 途中で切れた返答は、たいてい JSON として読めない。
            # 黙って捨てず、ログに残して原因を追えるようにする。
            print("警告: 返答が長さの上限で切れました(maxOutputTokens=%d)。" % max_tokens)
        return "".join(p.get("text", "") for p in parts).strip()
    return ""


def search(query, system=None, temperature=0.2, max_tokens=4096, retries=2):
    """Google検索で裏を取ってから答えさせる。

    返り値は (本文, 出典リスト, 実際に検索された語のリスト)。
    出典はモデルに書かせない。APIが返した groundingMetadata から機械的に取り出す。
    モデルに書かせると、それらしいが存在しないURLが混ざる。
    """
    url = "%s/%s:generateContent?key=%s" % (BASE, model(), KEY)
    payload = {
        "contents": [{"role": "user", "parts": [{"text": query}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}

    wait = 5
    for attempt in range(retries):
        try:
            data = _post(url, payload)
        except urllib.error.HTTPError as err:
            if err.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(wait)
                wait *= 2
                continue
            detail = err.read().decode("utf-8", "replace")[:300]
            raise SearchUnavailable("%s %s" % (err.code, detail))

        cand = (data.get("candidates") or [{}])[0]
        parts = cand.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts).strip()

        meta = cand.get("groundingMetadata") or {}
        sources = []
        seen = set()
        for chunk in meta.get("groundingChunks") or []:
            web = chunk.get("web") or {}
            uri = web.get("uri")
            if uri and uri not in seen:
                seen.add(uri)
                sources.append((web.get("title") or uri, uri))
        return text, sources, meta.get("webSearchQueries") or []
    return "", [], []


def ask_json(prompt, system=None, temperature=0.3, max_tokens=4096, retries=2):
    """返答から JSON オブジェクトを1つ取り出す。失敗したら言い直させる。"""
    for _ in range(retries):
        text = ask(prompt, system=system, temperature=temperature, max_tokens=max_tokens)
        found = extract_json(text)
        if found is not None:
            return found
        # 読めない原因の多くは「長すぎて途中で切れた」なので、短くするよう頼む。
        prompt += ("\n\n※前回の返答は JSON として読めませんでした。"
                   "説明を付けず、JSON オブジェクトだけを返してください。"
                   "途中で切れた可能性があるので、成果物は短めにまとめてください。")
    raise RuntimeError("JSON を取り出せませんでした")


def extract_json(text):
    """文章の中に混ざった最初の JSON オブジェクトを、括弧の対応を数えて切り出す。"""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    return None
