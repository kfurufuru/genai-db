"""data/*.json を index.html のインライン定数へ埋め込む。

正本は data/*.json。index.html の `const xxxData = [...]` 行は再生成物なので手で編集しない。

    python deploy.py           # data/*.json → index.html を再生成
    python deploy.py --check   # 再生成結果と commit 済み index.html を比較（差分があれば exit 2）
    python deploy.py --export  # index.html の埋め込みデータ → data/*.json（移行・復旧用）

公開は main へのマージで GitHub Pages が行う。このスクリプトは git 操作をしない。

公開前の禁止語チェック（実名・勤務先等）:
  生成結果を secretary-portal（非公開）の scripts/sanitize_public_html.py で検査し、
  1件でも残れば index.html を書かずに止める。禁止語リストはこのリポジトリに書かない
  （公開リポジトリに書けば、リスト自体が漏洩になる。短い語はハッシュ化しても総当たりで戻る）。
  サニタイザの場所: 環境変数 GENAI_DB_SANITIZER、無ければ ../secretary-portal/scripts/。
  見つからなければ検査不能として停止する（黙って素通りさせない）。
"""
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HTML = ROOT / "index.html"
DATA = ROOT / "data"

# (JS 定数名, JSON ファイル名)。index.html 上の宣言順と揃える。
TARGETS = [
    ("roadmapData", "roadmap.json"),
    ("termsData", "terms.json"),
    ("toolsData", "tools.json"),
    ("casesData", "cases.json"),
    ("conceptsData", "concepts.json"),
    ("ideasData", "ideas.json"),
]

# 各ツールに必須のキー。欠けると描画が "$undefined/月" 等で崩れる。
TOOL_REQUIRED = [
    "name", "provider", "color", "icon_label", "japanese_quality", "paid_plan",
    "main_models", "context_window", "free_tier", "strengths", "weaknesses",
    "best_for", "checked_at", "sources",
]


def line_pattern(var):
    # 1 行 1 定数で埋め込まれている前提。複数行化されたら fail-closed で止める。
    return re.compile(r"^(const " + var + r"\s*=\s*)(\[.*\]);(\r?)$", re.M)


def validate(var, items):
    if not isinstance(items, list) or not items:
        sys.exit(f"ERROR: {var} が空、または配列ではない")
    if var == "toolsData":
        for t in items:
            missing = [k for k in TOOL_REQUIRED if k not in t]
            if missing:
                sys.exit(f"ERROR: tools.json {t.get('name')!r} に必須キー欠落: {missing}")
            if not isinstance(t["paid_plan"], (int, float)):
                sys.exit(f"ERROR: tools.json {t['name']!r} paid_plan は数値（無料は 0）")
            if not t["sources"]:
                sys.exit(f"ERROR: tools.json {t['name']!r} sources が空（出典なしの記述は載せない）")
            # href 属性に入るため、HTML で意味を持つ文字（" ' < > ` と空白・括弧）は URL として認めない
            bad = [u for u in t["sources"]
                   if not re.fullmatch(r"https://[A-Za-z0-9._~:/?#\[\]@!$&*+,;=%-]+", u)]
            if bad:
                sys.exit(f"ERROR: tools.json {t['name']!r} sources に URL 以外が混入: {bad}")
            if t.get("evidence", "page") not in ("page", "search_excerpt"):
                sys.exit(f"ERROR: tools.json {t['name']!r} evidence は page / search_excerpt のみ")


SANITIZER = Path(os.environ.get(
    "GENAI_DB_SANITIZER",
    ROOT.parent / "secretary-portal" / "scripts" / "sanitize_public_html.py"))


def pii_check(text):
    """禁止語が残っていれば停止する。検査器が無い・壊れている場合も停止（fail-closed）。"""
    if not SANITIZER.is_file():
        sys.exit(f"ERROR: 禁止語チェッカーが見つからない: {SANITIZER}\n"
                 "  secretary-portal を隣に clone するか、GENAI_DB_SANITIZER にパスを指定すること")
    spec = importlib.util.spec_from_file_location("sanitize_public_html", SANITIZER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # 正対照: 検出器が生きていなければ「0件」は信用できない
    if mod.self_test() != 0:
        sys.exit("ERROR: 禁止語チェッカーの self-test 失敗（検出器故障）")
    hits = mod.scan_with_shadow(text)
    if hits:
        for pat, label, ln, ctx in hits:
            print(f"[FAIL] {label}: L{ln} …{ctx}…")
        sys.exit(f"ERROR: 公開前の禁止語チェックで {len(hits)} 件検出。index.html は書き込んでいない")


def render(html):
    for var, fname in TARGETS:
        path = DATA / fname
        items = json.loads(path.read_text(encoding="utf-8"))
        validate(var, items)
        pat = line_pattern(var)
        if len(pat.findall(html)) != 1:
            sys.exit(f"ERROR: index.html に const {var} の1行宣言がちょうど1つ見つからない")
        # インライン <script> 内に置くため、</script> による脱出と JS の行終端文字を無害化する（JSON の値は不変）
        payload = (json.dumps(items, ensure_ascii=False)
                   .replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
        html = pat.sub(lambda m: m.group(1) + payload + ";" + m.group(3), html)
    return html


def export(html):
    for var, fname in TARGETS:
        m = line_pattern(var).search(html)
        if not m:
            sys.exit(f"ERROR: const {var} が見つからない")
        items = json.loads(m.group(2))
        (DATA / fname).write_text(
            json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"exported {var}: {len(items)} -> data/{fname}")


def main():
    # index.html は CRLF。newline="" で改行を変換せずに読み書きする。
    with open(HTML, encoding="utf-8", newline="") as f:
        html = f.read()
    args = sys.argv[1:]
    if args == ["--export"]:
        export(html)
        return
    out = render(html)
    pii_check(out)
    if args == ["--check"]:
        if out != html:
            print("DRIFT: data/*.json と index.html が一致しない。python deploy.py を実行して commit すること")
            sys.exit(2)
        print("OK: index.html は data/*.json と一致")
        return
    if args:
        sys.exit(__doc__)
    if out == html:
        print("変更なし")
        return
    with open(HTML, "w", encoding="utf-8", newline="") as f:
        f.write(out)
    print("index.html を再生成した")


if __name__ == "__main__":
    main()
