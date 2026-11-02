import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["FURIKAERI_DB"] = _tmp.name

import app as app_module  # noqa: E402


class FurikaeriRouletteTest(unittest.TestCase):
    def setUp(self):
        app_module.init_db()
        self.client = app_module.app.test_client()
        with app_module.app.app_context():
            conn = app_module.get_db()
            conn.execute("DELETE FROM entries")
            conn.execute("DELETE FROM themes")
            conn.commit()

    # ---- helpers ----
    def add_theme(self, text):
        return self.client.post("/themes", data={"text": text})

    def theme_texts(self):
        with app_module.app.app_context():
            rows = app_module.get_db().execute("SELECT text FROM themes ORDER BY id").fetchall()
            return [r["text"] for r in rows]

    def counts(self):
        with app_module.app.app_context():
            db = app_module.get_db()
            t = db.execute("SELECT COUNT(*) AS n FROM themes").fetchone()["n"]
            e = db.execute("SELECT COUNT(*) AS n FROM entries").fetchone()["n"]
            return t, e

    # ---- tests ----
    def test_healthz(self):
        res = self.client.get("/healthz")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "ok")

    def test_index_ok(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("ふりかえりルーレット", res.get_data(as_text=True))

    def test_default_themes_seeded_on_fresh_db(self):
        fresh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        fresh.close()
        original = app_module.DB_PATH
        try:
            app_module.DB_PATH = fresh.name
            app_module.init_db()
            with app_module.app.app_context():
                rows = app_module.get_db().execute("SELECT text FROM themes ORDER BY id").fetchall()
            texts = [r["text"] for r in rows]
            self.assertEqual(texts, app_module.DEFAULT_THEMES)
            self.assertGreaterEqual(len(texts), 8)
            self.assertLessEqual(len(texts), 10)
        finally:
            app_module.DB_PATH = original

    def test_add_theme(self):
        res = self.add_theme("今日の調子はどうだった？")
        self.assertEqual(res.status_code, 302)
        self.assertEqual(self.theme_texts(), ["今日の調子はどうだった？"])
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn("今日の調子はどうだった？", body)

    def test_add_theme_empty_rejected(self):
        self.add_theme("   ")
        self.add_theme("")
        themes, _ = self.counts()
        self.assertEqual(themes, 0)

    def test_delete_theme(self):
        self.add_theme("消すテーマ")
        self.add_theme("残すテーマ")
        with app_module.app.app_context():
            rows = app_module.get_db().execute("SELECT id, text FROM themes ORDER BY id").fetchall()
            target = [r["id"] for r in rows if r["text"] == "消すテーマ"][0]
        res = self.client.post(f"/themes/{target}/delete")
        self.assertEqual(res.status_code, 302)
        self.assertEqual(self.theme_texts(), ["残すテーマ"])

    def test_spin_returns_one_of_themes(self):
        self.add_theme("テーマ甲")
        self.add_theme("テーマ乙")
        res = self.client.post("/spin")
        self.assertEqual(res.status_code, 200)
        body = res.get_data(as_text=True)
        self.assertIn("今日のふりかえりテーマは", body)
        self.assertTrue(
            '<p class="theme">テーマ甲</p>' in body or '<p class="theme">テーマ乙</p>' in body
        )

    def test_spin_with_no_themes_does_not_error(self):
        themes, _ = self.counts()
        self.assertEqual(themes, 0)
        res = self.client.post("/spin")
        self.assertEqual(res.status_code, 200)
        body = res.get_data(as_text=True)
        self.assertIn("回せませんでした", body)
        self.assertNotIn('<p class="theme">', body)

    def test_add_entry_and_shown_in_history(self):
        res = self.client.post(
            "/entries",
            data={"theme_text": "新しく分かったことは？", "memo": "関数の使い方が分かった"},
        )
        self.assertEqual(res.status_code, 302)
        _, entries = self.counts()
        self.assertEqual(entries, 1)
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn("新しく分かったことは？", body)
        self.assertIn("関数の使い方が分かった", body)

    def test_entries_newest_first(self):
        self.client.post("/entries", data={"theme_text": "テーマ1", "memo": "古いメモAAA"})
        self.client.post("/entries", data={"theme_text": "テーマ2", "memo": "新しいメモBBB"})
        body = self.client.get("/").get_data(as_text=True)
        self.assertLess(body.index("新しいメモBBB"), body.index("古いメモAAA"))

    def test_delete_entry(self):
        self.client.post("/entries", data={"theme_text": "テーマ", "memo": "消えるメモ"})
        with app_module.app.app_context():
            eid = app_module.get_db().execute("SELECT id FROM entries").fetchone()["id"]
        res = self.client.post(f"/entries/{eid}/delete")
        self.assertEqual(res.status_code, 302)
        _, entries = self.counts()
        self.assertEqual(entries, 0)
        body = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("消えるメモ", body)

    def test_add_entry_empty_memo_rejected(self):
        self.client.post("/entries", data={"theme_text": "テーマ", "memo": "  "})
        self.client.post("/entries", data={"theme_text": "", "memo": "メモだけ"})
        _, entries = self.counts()
        self.assertEqual(entries, 0)

    def test_page_escapes_user_input(self):
        self.add_theme('<script>alert("x")</script>')
        self.client.post(
            "/entries",
            data={"theme_text": "テーマ", "memo": "<b>太字メモ</b>"},
        )
        body = self.client.get("/").get_data(as_text=True)
        self.assertNotIn('<script>alert("x")</script>', body)
        self.assertIn("&lt;script&gt;", body)
        self.assertNotIn("<b>太字メモ</b>", body)
        self.assertIn("&lt;b&gt;", body)


if __name__ == "__main__":
    unittest.main()
