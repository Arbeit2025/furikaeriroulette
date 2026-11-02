"""ふりかえりルーレット furikaeriroulette

学習や一日の「ふりかえり」のテーマをルーレット（ランダム抽選）で決め、
そのテーマで短いふりかえりメモを残せる小さなツール。
自己調整学習のふりかえり習慣を軽く回すための小物。
テーマ（ふりかえりの質問）とメモは SQLite に保存する。
単一ファイル Flask + SQLite。
"""
import os
import random
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, g, jsonify, redirect, render_template_string, request, url_for

app = Flask(__name__)
JST = ZoneInfo("Asia/Tokyo")
DB_PATH = os.environ.get("FURIKAERI_DB", os.path.join(os.path.dirname(__file__), "furikaeri.db"))

DEFAULT_THEMES = [
    "今日いちばん集中できたのはいつ？",
    "つまずいたところと、その理由は？",
    "明日ひとつだけ変えるなら何を変える？",
    "今日の自分に点数をつけるなら何点？",
    "新しく分かったことは？",
    "今日の学びを誰かに教えるならどう言う？",
    "予想と違ったことは？",
    "次に同じことをするならどうする？",
    "今日うまくいったことと、そのコツは？",
]


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS themes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            theme_text TEXT NOT NULL,
            memo TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    # 初回だけデフォルトテーマを投入する（全削除後に復活しないよう印を残す）
    row = db.execute("SELECT value FROM meta WHERE key = 'seeded'").fetchone()
    if row is None:
        ts = now_str()
        db.executemany(
            "INSERT INTO themes(text, created_at) VALUES(?, ?)",
            [(t, ts) for t in DEFAULT_THEMES],
        )
        db.execute("INSERT INTO meta(key, value) VALUES('seeded', '1')")
    db.commit()
    db.close()


def now_str():
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M")


INDEX = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ふりかえりルーレット</title>
<style>body{font-family:sans-serif;max-width:760px;margin:2em auto;padding:0 1em}
table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:.3em .5em}
.note{background:#f4f4f4;border:1px solid #ccc;padding:.8em;border-radius:6px}
.result{background:#fff7e6;border:2px solid #e0a800;padding:1em;border-radius:8px}
.result .theme{font-size:1.6em;font-weight:bold;line-height:1.4}
textarea{width:100%;max-width:560px}</style>
</head><body>
<h1>ふりかえりルーレット</h1>
<p>学習や一日のふりかえりのテーマを、ルーレットで1つ決めるための小さな道具です。「回す」ボタンを押すと登録テーマからランダムに1件が選ばれるので、そのテーマで短いメモを残せます。</p>
<p class="note">データはこのアプリの SQLite に保存されます。Render 無料プランでは再デプロイ等でデータが消える場合があります。</p>

<h2>ルーレットを回す</h2>
<form method="post" action="{{ url_for('spin') }}">
  <button type="submit" style="font-size:1.1em;padding:.4em 1.2em">🎲 回す</button>
</form>

{% if spin_message %}
<p class="note">{{ spin_message }}</p>
{% endif %}

{% if result_theme %}
<div class="result">
  <p>今日のふりかえりテーマは…</p>
  <p class="theme">{{ result_theme }}</p>
  <form method="post" action="{{ url_for('add_entry') }}">
    <input type="hidden" name="theme_text" value="{{ result_theme }}">
    <label>ふりかえりメモ<br>
    <textarea name="memo" rows="4" required placeholder="このテーマで思いついたことを短く書いてみてください"></textarea></label><br>
    <button type="submit">メモを保存する</button>
  </form>
</div>
{% endif %}

<h2>ふりかえりメモ履歴（{{ entries|length }}件）</h2>
<table>
<tr><th>日時</th><th>テーマ</th><th>メモ</th><th>操作</th></tr>
{% for e in entries %}
<tr>
  <td>{{ e.created_at }}</td>
  <td>{{ e.theme_text }}</td>
  <td>{{ e.memo }}</td>
  <td><form method="post" action="{{ url_for('delete_entry', eid=e.id) }}" style="display:inline" onsubmit="return confirm('このメモを削除しますか？')"><button>削除</button></form></td>
</tr>
{% else %}
<tr><td colspan="4">まだメモがありません。ルーレットを回して最初のふりかえりを残しましょう。</td></tr>
{% endfor %}
</table>

<h2>テーマ一覧（{{ themes|length }}件）</h2>
<table>
<tr><th>テーマ</th><th>操作</th></tr>
{% for t in themes %}
<tr>
  <td>{{ t.text }}</td>
  <td><form method="post" action="{{ url_for('delete_theme', tid=t.id) }}" style="display:inline" onsubmit="return confirm('このテーマを削除しますか？')"><button>削除</button></form></td>
</tr>
{% else %}
<tr><td colspan="2">登録されたテーマはまだありません。下のフォームから追加してください。</td></tr>
{% endfor %}
</table>

<h2>テーマを追加</h2>
<form method="post" action="{{ url_for('add_theme') }}">
  <label>ふりかえりの質問 <input type="text" name="text" size="50" required placeholder="例：今日いちばん集中できたのはいつ？"></label>
  <button type="submit">追加する</button>
</form>
</body></html>"""


def render_index(result_theme=None, spin_message=None):
    db = get_db()
    themes = db.execute("SELECT * FROM themes ORDER BY id").fetchall()
    entries = db.execute("SELECT * FROM entries ORDER BY id DESC").fetchall()
    return render_template_string(
        INDEX,
        themes=themes,
        entries=entries,
        result_theme=result_theme,
        spin_message=spin_message,
    )


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/")
def index():
    return render_index()


@app.route("/spin", methods=["POST"])
def spin():
    db = get_db()
    themes = db.execute("SELECT * FROM themes ORDER BY id").fetchall()
    if not themes:
        return render_index(
            spin_message="テーマが登録されていないため、ルーレットを回せませんでした。まず下のフォームからテーマを追加してください。"
        )
    chosen = random.choice(themes)
    return render_index(result_theme=chosen["text"])


@app.route("/themes", methods=["POST"])
def add_theme():
    text = (request.form.get("text") or "").strip()
    if text:
        db = get_db()
        db.execute(
            "INSERT INTO themes(text, created_at) VALUES(?, ?)",
            (text, now_str()),
        )
        db.commit()
    return redirect(url_for("index"))


@app.route("/themes/<int:tid>/delete", methods=["POST"])
def delete_theme(tid):
    db = get_db()
    db.execute("DELETE FROM themes WHERE id = ?", (tid,))
    db.commit()
    return redirect(url_for("index"))


@app.route("/entries", methods=["POST"])
def add_entry():
    theme_text = (request.form.get("theme_text") or "").strip()
    memo = (request.form.get("memo") or "").strip()
    if theme_text and memo:
        db = get_db()
        db.execute(
            "INSERT INTO entries(theme_text, memo, created_at) VALUES(?, ?, ?)",
            (theme_text, memo, now_str()),
        )
        db.commit()
    return redirect(url_for("index"))


@app.route("/entries/<int:eid>/delete", methods=["POST"])
def delete_entry(eid):
    db = get_db()
    db.execute("DELETE FROM entries WHERE id = ?", (eid,))
    db.commit()
    return redirect(url_for("index"))


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
