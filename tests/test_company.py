"""会社の土台部分の自動テスト。

外部ライブラリも、APIキーも、ネットワークも要らない。
Pythonの標準機能(unittest)だけで動く。

手元で動かす:
    python -m unittest discover -s tests -v

GitHub上で動かす:
    Actions タブ → test → Run workflow(手動実行のみ。自動では走らない)

**ここで確かめているのは、AIの賢さではない。**
AIの返答は毎回変わるので、テストで固定できない。
かわりに、**返答がどう転んでも会社が壊れないこと**を確かめている。
"""

import concurrent.futures
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

os.environ.setdefault("GEMINI_API_KEY", "dummy")
os.environ.setdefault("GITHUB_TOKEN", "dummy")
os.environ.setdefault("GITHUB_REPOSITORY", "example/repo")

from lib import gemini, store  # noqa: E402
import employee  # noqa: E402


class TempRepo(unittest.TestCase):
    """テストごとに、使い捨てのリポジトリを1つ作る。"""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ai_company_test_")
        store.ROOT = self.dir

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class TestExtractJson(TempRepo):
    """モデルの返答からJSONを取り出せるか(第3章)。"""

    def test_plain(self):
        self.assertEqual(gemini.extract_json('{"a": 1}'), {"a": 1})

    def test_surrounded_by_text(self):
        text = '承知しました。\n```json\n{"a": {"b": 2}}\n```\nご確認ください。'
        self.assertEqual(gemini.extract_json(text), {"a": {"b": 2}})

    def test_brace_inside_string(self):
        # 文字列の中の } を閉じ括弧と数えてはいけない
        self.assertEqual(gemini.extract_json('{"r": "記号 } も使えます"}'),
                         {"r": "記号 } も使えます"})

    def test_escaped_quote(self):
        self.assertEqual(gemini.extract_json(r'{"r": "引用 \" つき"}'),
                         {"r": '引用 " つき'})

    def test_no_json(self):
        self.assertIsNone(gemini.extract_json("JSONはありません"))

    def test_broken_json_is_none(self):
        self.assertIsNone(gemini.extract_json('{"a": }'))


class TestSafeName(TempRepo):
    """モデルが返したファイル名を、そのまま使わない(第4章)。"""

    def test_path_traversal_is_stripped(self):
        got = employee.safe_name("../../.github/workflows/company.yml")
        self.assertNotIn("/", got)
        self.assertNotIn("..", got)

    def test_japanese_is_kept(self):
        self.assertEqual(employee.safe_name("調査レポート.md"), "調査レポート.md")

    def test_empty_is_none(self):
        self.assertIsNone(employee.safe_name(""))
        self.assertIsNone(employee.safe_name(None))

    def test_too_long_is_cut(self):
        self.assertLessEqual(len(employee.safe_name("あ" * 200)), 80)


class TestMemory(TempRepo):
    """記憶は育ち続けない(第5章)。"""

    def test_append_keeps_only_recent_lines(self):
        for i in range(300):
            store.append("memory/E01.md", "- 行%d\n" % i, keep_lines=200)
        kept = store.read("memory/E01.md").strip().split("\n")
        self.assertEqual(len(kept), 200)
        self.assertIn("行299", kept[-1])   # 新しい行が残る
        self.assertNotIn("行0", kept[0])   # 古い行は落ちる

    def test_read_missing_file_returns_default(self):
        self.assertEqual(store.read("memory/none.md", "(まだありません)"),
                         "(まだありません)")


class TestRoster(TempRepo):
    """名簿の読み取り(第3章・第7章)。"""

    def setUp(self):
        super().setUp()
        store.write_json(store.ROSTER, {"members": [
            {"id": "E01", "name": "かなで", "label": "担当:かなで", "role": "調査"},
        ]})

    def test_member_found(self):
        self.assertEqual(store.member("E01")["name"], "かなで")

    def test_unknown_member_is_none(self):
        self.assertIsNone(store.member("E99"))
        self.assertIsNone(store.member(""))

    def test_broken_roster_does_not_crash(self):
        store.write(store.ROSTER, "{壊れたJSON")
        self.assertEqual(store.members(), [])


class TestLimit(TempRepo):
    """上限の読み取り。壊れていても危険側に倒さない(第6章)。"""

    def test_missing_file_uses_default(self):
        limit, warning = store.limit_of()
        self.assertEqual(limit, store.DEFAULT_LIMIT)
        self.assertEqual(warning, "")

    def test_valid_file_is_respected(self):
        store.write(store.BUDGET, json.dumps({"limit": 100}))
        limit, warning = store.limit_of()
        self.assertEqual(limit, 100)
        self.assertEqual(warning, "")

    def test_broken_file_falls_back_to_safe_value(self):
        # 上限を 100 に下げていた人のファイルが壊れたとき、
        # 既定の 1500 に戻してしまうと、危険な側へ倒れる。
        store.write(store.BUDGET, "{壊れた")
        limit, warning = store.limit_of()
        self.assertEqual(limit, store.SAFE_LIMIT)
        self.assertLess(limit, store.DEFAULT_LIMIT)
        self.assertTrue(warning)

    def test_missing_key_falls_back_to_safe_value(self):
        store.write(store.BUDGET, json.dumps({"limit_typo": 100}))
        limit, warning = store.limit_of()
        self.assertEqual(limit, store.SAFE_LIMIT)
        self.assertTrue(warning)


class TestCharge(TempRepo):
    """出社の計上。同時に動いても消えない(第6章)。"""

    def _charge(self, i):
        os.environ["GITHUB_RUN_ID"] = str(10000 + i)
        return store.charge(number=i, model_name="models/test")

    def test_one_run_leaves_one_mark(self):
        self._charge(1)
        self.assertEqual(store.used_in(store.month_key()), 1)

    def test_mark_records_issue_and_model(self):
        self._charge(7)
        month = store.month_key()
        folder = store.path("%s/%s" % (store.USAGE, month))
        with open(os.path.join(folder, os.listdir(folder)[0]), encoding="utf-8") as f:
            body = f.read()
        self.assertIn("issue=7", body)
        self.assertIn("models/test", body)

    def test_concurrent_runs_are_not_lost(self):
        # 共有カウンタを読んで書き戻す方式だと、ここで計上が消える。
        n = 20
        with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
            list(pool.map(self._charge, range(n)))
        self.assertEqual(store.used_in(store.month_key()), n)

    def test_stops_when_over_limit(self):
        store.write(store.BUDGET, json.dumps({"limit": 2}))
        self.assertIsNotNone(self._charge(1)[0])
        self.assertIsNotNone(self._charge(2)[0])
        self.assertIsNone(self._charge(3)[0])   # 3回目で停止

    def test_months_are_counted_separately(self):
        self._charge(1)
        self.assertEqual(store.used_in("1999-01"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
