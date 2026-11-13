#!/usr/bin/env python3
"""把 xingcezhenti 的 md 真题解析为结构化题库 (SQLite + JSONL)。

输出:
  /root/civil-service-examination/bank/tiku.db
  /root/civil-service-examination/bank/questions.jsonl
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path("/root/civil-service-examination/xingcezhenti")
OUT_DIR = Path("/root/civil-service-examination/bank")
DB_PATH = OUT_DIR / "tiku.db"
JSONL_PATH = OUT_DIR / "questions.jsonl"

# 题目标题: ## 第 1 题　<sub>qid 16593143 · 图形推理</sub>
# 也可能是 ### 第 1 题
Q_HEAD = re.compile(
    r"^(#{2,3})\s*第\s*(\d+)\s*题\s*(?:<sub>(.*?)</sub>)?\s*$"
)
MAT_HEAD = re.compile(r"^(#{2,3})\s*材料\s*(\d+)\s*$")
OPT = re.compile(r"^-\s*\*\*([A-H])\*\*\s*[.．]\s*(.*)$", re.S)
ANS = re.compile(r"^\*\*答案\*\*\s*[：:]\s*([A-H])")
QID = re.compile(r"qid\s+(\d+)")
IMG = re.compile(r'<img\b[^>]*\bsrc="([^"]+)"[^>]*>')
TEX_IMG = re.compile(r'<img\b[^>]*\bflag="tex"[^>]*\bsrc="([^"]+)"[^>]*>')
HTML_TAG = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    """去掉 HTML 标签，保留纯文本；图片先换成占位。"""
    # 公式图 → {{tex:路径}}
    def tex_sub(m: re.Match) -> str:
        return "{{tex:" + m.group(1).split("/")[-1] + "}}"

    # 普通图 → {{img:路径}}
    def img_sub(m: re.Match) -> str:
        return "{{img:" + m.group(1).split("/")[-1] + "}}"

    text = TEX_IMG.sub(tex_sub, text)
    text = IMG.sub(img_sub, text)
    text = HTML_TAG.sub("", text)
    # 实体
    text = (
        text.replace("&nbsp;", " ")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )
    # 空白规整
    text = re.sub(r"[ \t　]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_frontmatter(lines: list[str]) -> dict[str, str]:
    meta: dict[str, str] = {}
    if not lines or lines[0].strip() != "---":
        return meta
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"')
    return meta


def parse_file(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()
    meta = parse_frontmatter(lines)

    # 去掉 frontmatter
    body_start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                body_start = i + 1
                break
    body = lines[body_start:]

    module = meta.get("模块") or path.parent.name.split("-", 1)[-1]
    paper = meta.get("试卷") or ""
    year = meta.get("年份") or ""
    region = meta.get("地区") or ""
    source_file = str(path.relative_to(ROOT))

    questions: list[dict] = []
    material_buf: list[str] = []
    in_material = False
    cur: dict | None = None
    section = None  # stem | options | answer | analysis
    opt_buf: list[str] = []
    ans_buf: list[str] = []
    stem_buf: list[str] = []

    def flush():
        nonlocal cur, stem_buf, opt_buf, ans_buf, section
        if not cur:
            return
        stem = strip_html("\n".join(stem_buf)).strip()
        # 选项
        options = {}
        for b in opt_buf:
            m = OPT.match(b.strip())
            if m:
                options[m.group(1)] = strip_html(m.group(2)).strip()
        answer = cur.get("answer") or ""
        if not answer:
            for b in ans_buf:
                m = ANS.match(b.strip())
                if m:
                    answer = m.group(1)
                    break
        analysis = strip_html("\n".join(ans_buf))
        # 从解析中去掉答案行
        analysis = re.sub(r"^\*\*答案\*\*.*$", "", analysis, flags=re.M).strip()
        analysis = re.sub(r"^\*\*官方解析\*\*\s*", "", analysis).strip()

        cur.update(
            {
                "stem": stem,
                "options": options,
                "answer": answer,
                "analysis": analysis,
                "material": strip_html("\n".join(material_buf)).strip() if material_buf else "",
                "source_file": source_file,
                "paper": paper,
                "year": str(year),
                "region": region,
                "module": module,
            }
        )
        if stem or options:
            questions.append(cur)
        cur = None
        stem_buf, opt_buf, ans_buf = [], [], []
        section = None

    for line in body:
        # 材料块（资料分析）
        mm = MAT_HEAD.match(line)
        if mm:
            # 材料头出现时，若上一题未 flush 且不在材料中，先处理
            if cur and section != "material":
                # 材料通常在题目前，直接切换
                pass
            flush()
            in_material = True
            material_buf = []
            section = "material"
            continue

        mq = Q_HEAD.match(line)
        if mq:
            # 新题开始
            if in_material and material_buf and cur is None:
                # 材料保留给后续题（material_buf 不清）
                in_material = False
            flush()
            head_sub = mq.group(3) or ""
            qid_m = QID.search(head_sub)
            # 类型在 · 后面
            qtype = ""
            if "·" in head_sub:
                qtype = head_sub.split("·", 1)[1].strip()
            elif "·" in head_sub:
                qtype = head_sub.split("·", 1)[1].strip()
            # 也支持中点 ·
            parts = re.split(r"[·・]", head_sub)
            if len(parts) >= 2:
                qtype = parts[-1].strip()
            cur = {
                "qid": int(qid_m.group(1)) if qid_m else None,
                "index": int(mq.group(2)),
                "qtype": qtype,
            }
            stem_buf = []
            opt_buf = []
            ans_buf = []
            section = "stem"
            in_material = False
            continue

        if cur is None:
            # 材料正文
            if section == "material":
                material_buf.append(line)
            continue

        # 答案/解析区
        if line.startswith("**答案**"):
            section = "answer"
            ans_buf.append(line)
            continue
        if line.startswith("**官方解析**") or line.strip() == "**官方解析**":
            section = "analysis"
            ans_buf.append(line)
            continue

        # 选项区
        if OPT.match(line.strip()):
            section = "options"
            opt_buf.append(line)
            continue
        # 选项可能跨行（公式 p 标签）
        if section == "options" and (line.strip().startswith("-") or line.strip().startswith("<p")):
            opt_buf.append(line)
            continue

        if section in ("stem", None):
            stem_buf.append(line)
            section = "stem"
        elif section == "options":
            opt_buf.append(line)
        elif section in ("answer", "analysis"):
            ans_buf.append(line)
        elif section == "material":
            material_buf.append(line)

    flush()
    return questions


def main() -> int:
    md_files = sorted(ROOT.rglob("*.md"))
    md_files = [p for p in md_files if ".git" not in p.parts]
    # 排除根 README 等非试卷（仍可解析，无题则跳过）
    print(f"扫描 {len(md_files)} 个 md …")

    all_q: list[dict] = []
    for i, p in enumerate(md_files, 1):
        try:
            qs = parse_file(p)
        except Exception as e:  # noqa: BLE001
            print(f"  解析失败 {p}: {e}", file=sys.stderr)
            continue
        for q in qs:
            q["source_module"] = p.parent.name if p.parent != ROOT else ""
        all_q.extend(qs)
        if i % 500 == 0:
            print(f"  … {i}/{len(md_files)}, 累计 {len(all_q)} 题")

    # 全局编号
    for idx, q in enumerate(all_q, 1):
        q["id"] = idx

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # JSONL
    with JSONL_PATH.open("w", encoding="utf-8") as f:
        for q in all_q:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    # SQLite
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE questions (
          id INTEGER PRIMARY KEY,
          qid INTEGER,
          paper TEXT,
          year TEXT,
          region TEXT,
          module TEXT,
          qtype TEXT,
          idx_in_paper INTEGER,
          stem TEXT,
          options_json TEXT,
          answer TEXT,
          analysis TEXT,
          material TEXT,
          source_file TEXT
        )
        """
    )
    conn.execute("CREATE INDEX idx_module ON questions(module)")
    conn.execute("CREATE INDEX idx_year ON questions(year)")
    conn.execute("CREATE INDEX idx_qid ON questions(qid)")
    conn.executemany(
        """INSERT INTO questions
        (id,qid,paper,year,region,module,qtype,idx_in_paper,
         stem,options_json,answer,analysis,material,source_file)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                q["id"],
                q.get("qid"),
                q.get("paper", ""),
                q.get("year", ""),
                q.get("region", ""),
                q.get("module", ""),
                q.get("qtype", ""),
                q.get("index"),
                q.get("stem", ""),
                json.dumps(q.get("options", {}), ensure_ascii=False),
                q.get("answer", ""),
                q.get("analysis", ""),
                q.get("material", ""),
                q.get("source_file", ""),
            )
            for q in all_q
        ],
    )
    conn.commit()

    # 统计
    cur = conn.execute(
        "SELECT module, COUNT(*) FROM questions GROUP BY module ORDER BY module"
    )
    print("\n=== 题库统计 ===")
    total = 0
    for mod, n in cur.fetchall():
        print(f"  {mod}: {n}")
        total += n
    print(f"  合计: {total}")
    ans_missing = conn.execute(
        "SELECT COUNT(*) FROM questions WHERE answer=''"
    ).fetchone()[0]
    print(f"  缺答案: {ans_missing}")
    print(f"输出: {DB_PATH}")
    print(f"输出: {JSONL_PATH}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
