"""data/*.json を index.html のインライン定数へ埋め込む。

正本は data/*.json。index.html の `const xxxData = [...]` 行は再生成物なので手で編集しない。

    python deploy.py           # data/*.json → index.html を再生成
    python deploy.py --check   # 再生成結果と commit 済み index.html を比較（差分があれば exit 2）
    python deploy.py --export  # index.html の埋め込みデータ → data/*.json（移行・復旧用）

公開は main へのマージで GitHub Pages が行う。このスクリプトは git 操作をしない。
"""
import json
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
            bad = [u for u in t["sources"] if not re.fullmatch(r"https://[^\s（）()]+", u)]
            if bad:
                sys.exit(f"ERROR: tools.json {t['name']!r} sources に URL 以外が混入: {bad}")
            if t.get("evidence", "page") not in ("page", "search_excerpt"):
                sys.exit(f"ERROR: tools.json {t['name']!r} evidence は page / search_excerpt のみ")


def render(html):
    for var, fname in TARGETS:
        path = DATA / fname
        items = json.loads(path.read_text(encoding="utf-8"))
        validate(var, items)
        pat = line_pattern(var)
        if len(pat.findall(html)) != 1:
            sys.exit(f"ERROR: index.html に const {var} の1行宣言がちょうど1つ見つからない")
        payload = json.dumps(items, ensure_ascii=False)
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
