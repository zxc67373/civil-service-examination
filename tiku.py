#!/usr/bin/env python3
"""公务员行测真题 · 命令行刷题

用法:
  python3 tiku.py               # 交互菜单
  python3 tiku.py --module 判断推理 --year 2024
  python3 tiku.py --random 10
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

DB = Path("/root/civil-service-examination/bank/tiku.db")
IMG_ROOT = Path("/root/civil-service-examination/xingcezhenti/90-图片")
IMG_INDEX = Path("/root/civil-service-examination/bank/image_index.json")
CHECK = "✅"
_img_idx: dict[str, str] | None = None

# ── 终端能力 ──────────────────────────────────────────
def supports_color() -> bool:
    return sys.stdout.isatty()


def c(text: str, code: str) -> str:
    if not supports_color():
        return text
    return f"\033[{code}m{text}\033[0m"


def bold(t: str) -> str:
    return c(t, "1")


def green(t: str) -> str:
    return c(t, "32")


def red(t: str) -> str:
    return c(t, "31")


def yellow(t: str) -> str:
    return c(t, "33")


def cyan(t: str) -> str:
    return c(t, "36")


def dim(t: str) -> str:
    return c(t, "2")


# ── 图片 → 文本（二值化 ASCII） ──────────────────────
def _load_img_index() -> dict[str, str]:
    global _img_idx
    if _img_idx is None:
        if IMG_INDEX.is_file():
            try:
                _img_idx = json.loads(IMG_INDEX.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                _img_idx = {}
        else:
            _img_idx = {}
    return _img_idx


def refresh_image_index() -> int:
    """扫描 90-图片 重建索引。"""
    global _img_idx
    idx: dict[str, str] = {}
    if IMG_ROOT.is_dir():
        for p in IMG_ROOT.rglob("*"):
            if p.is_file() and not p.name.endswith(".part"):
                idx[p.name] = str(p)
    IMG_INDEX.parent.mkdir(parents=True, exist_ok=True)
    IMG_INDEX.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    _img_idx = idx
    return len(idx)


def find_image(fname: str) -> Path | None:
    """按文件名在 90-图片 下查找（优先索引）。"""
    if not fname:
        return None
    p = Path(fname)
    if p.is_file():
        return p
    idx = _load_img_index()
    hit = idx.get(fname)
    if hit and Path(hit).is_file():
        return Path(hit)
    # 索引未命中时兜底扫盘（可能刚下载）
    if IMG_ROOT.is_dir():
        for sub in IMG_ROOT.rglob(fname):
            if sub.is_file():
                idx[fname] = str(sub)
                return sub
    return None


# Braille 点阵位序（Unicode U+2800）：每字符 2 列 × 4 行 = 8 点
#  (0,0)->bit0  (1,0)->bit3
#  (0,1)->bit1  (1,1)->bit4
#  (0,2)->bit2  (1,2)->bit5
#  (0,3)->bit6  (1,3)->bit7
_BRAILLE_BITS = (
    (0x01, 0x08),
    (0x02, 0x10),
    (0x04, 0x20),
    (0x40, 0x80),
)


def _otsu_threshold(im) -> int:
    hist = im.histogram()
    total = sum(hist) or 1
    sum_all = sum(i * h for i, h in enumerate(hist))
    sum_b = 0.0
    w_b = 0
    best_t, best_var = 128, -1.0
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b = sum_b / w_b
        m_f = (sum_all - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > best_var:
            best_var, best_t = var, t
    if best_t < 10 or best_t > 245:
        best_t = 128
    return best_t


def _flatten_to_rgb(path: Path):
    """透明底铺白，返回 RGB。"""
    from PIL import Image
    im = Image.open(path)
    if im.mode == "P":
        im = im.convert("RGBA")
    if im.mode in ("RGBA", "LA"):
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im.convert("RGBA"))
    return im.convert("RGB")


def _chafa_available() -> bool:
    import shutil
    return shutil.which("chafa") is not None


def _render_chafa(path: Path, max_width: int, max_height: int) -> str | None:
    """用 chafa 渲染（真彩终端最佳）。失败返回 None 走盲文。"""
    import shutil
    import subprocess
    import tempfile
    from PIL import Image

    if not _chafa_available():
        return None
    try:
        im = _flatten_to_rgb(path)
        # 小图先放大，笔画更清楚
        w, h = im.size
        if w < 80 or h < 40:
            factor = max(2, min(6, int(160 / max(w, 1)) or 2))
            from PIL import Image as _Image
            im = im.resize((w * factor, h * factor), _Image.Resampling.NEAREST)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            tmp = Path(tf.name)
        try:
            im.save(tmp)
            # 终端深色/浅色：让 chafa 自己猜；限制尺寸
            cmd = [
                "chafa",
                "--size", f"{max_width}x{max_height}",
                "--symbols", "block",
                "--animate", "off",
                "--relative", "off",
                "--polite", "on",
                str(tmp),
            ]
            r = subprocess.run(cmd, capture_output=True, timeout=8)
            if r.returncode != 0 or not r.stdout:
                return None
            out = r.stdout.decode("utf-8", errors="replace")
            # 去掉光标显隐等控制序列，保留颜色码
            out = re.sub(r"\x1b\[\?[0-9;]*[a-zA-Z]", "", out)
            out = out.rstrip()
            if not out.strip():
                return None
            return out
        finally:
            tmp.unlink(missing_ok=True)
    except Exception:
        return None


def _render_braille(path: Path, max_width: int, max_height: int) -> str:
    """盲文点阵降级渲染。"""
    from PIL import Image

    im = Image.open(path)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    im = im.convert("L")

    w0, h0 = im.size
    if w0 < 80 or h0 < 40:
        factor = max(2, min(6, int(120 / max(w0, 1)) or 2))
        im = im.resize((w0 * factor, h0 * factor), Image.Resampling.NEAREST)
        w0, h0 = im.size

    cap_w = max_width * 2
    cap_h = max_height * 4
    if w0 > cap_w or h0 > cap_h:
        scale = min(cap_w / w0, cap_h / h0)
        nw = max(2, int(w0 * scale))
        nh = max(4, int(h0 * scale))
        im = im.resize((nw * 2, nh * 2), Image.Resampling.LANCZOS)
        im = im.resize((nw, nh), Image.Resampling.BOX)
    else:
        nw, nh = w0, h0

    th = _otsu_threshold(im)
    px = im.load()
    fg = [[px[x, y] < th for x in range(nw)] for y in range(nh)]
    ratio = sum(sum(row) for row in fg) / max(nw * nh, 1)
    if ratio < 0.005:
        return dim(f"[图片近乎全白: {path.name}]")
    if ratio > 0.93:
        fg = [[not v for v in row] for row in fg]

    pad_w = (2 - nw % 2) % 2
    pad_h = (4 - nh % 4) % 4
    if pad_w:
        for row in fg:
            row.extend([False] * pad_w)
        nw += pad_w
    if pad_h:
        for _ in range(pad_h):
            fg.append([False] * nw)
        nh += pad_h

    lines_out = []
    for by in range(0, nh, 4):
        row_chars = []
        for bx in range(0, nw, 2):
            bits = 0
            for dy in range(4):
                b0, b1 = _BRAILLE_BITS[dy]
                if fg[by + dy][bx]:
                    bits |= b0
                if bx + 1 < nw and fg[by + dy][bx + 1]:
                    bits |= b1
            row_chars.append(chr(0x2800 + bits) if bits else " ")
        line = "".join(row_chars).rstrip()
        if line:
            lines_out.append(line)
    if not lines_out:
        return dim("[图片无可见前景]")
    header = dim(f"┌─ {path.name} ({w0}x{h0})")
    body = "\n".join("│ " + ln for ln in lines_out)
    footer = dim("└" + "─" * 40)
    return f"{header}\n{body}\n{footer}"


def image_to_text(path: Path, max_width: int = 72, max_height: int = 24) -> str:
    """终端图片渲染（图表类）：chafa block 真彩，失败回退盲文。"""
    if not path.is_file():
        return dim(f"[图片未下载: {path.name}]")
    try:
        rendered = _render_chafa(path, max_width, max_height)
        if rendered is not None:
            header = dim(f"┌─ {path.name}")
            footer = dim("└" + "─" * 40)
            return f"{header}\n{rendered}\n{footer}"
        return _render_braille(path, max_width, max_height)
    except Exception as e:  # noqa: BLE001
        return dim(f"[图片渲染失败: {e}]")


# ── 公式图 → 文本 ─────────────────────────────────────
FORMULA_TEXT = Path("/root/civil-service-examination/bank/formula_text.json")
_formula_text: dict[str, str] | None = None


def _load_formula_text() -> dict[str, str]:
    global _formula_text
    if _formula_text is None:
        if FORMULA_TEXT.is_file():
            try:
                _formula_text = json.loads(FORMULA_TEXT.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                _formula_text = {}
        else:
            _formula_text = {}
    return _formula_text


def formula_to_text(fname: str) -> str | None:
    """公式图文件名 → 可读文本；无映射返回 None。"""
    text = _load_formula_text().get(fname, "").strip()
    if not text or text in ("-", "--", ":", "|"):
        return None
    return text


def render_markup(text: str, show_images: bool = True) -> str:
    """渲染占位符：
    - {{tex:xx}} 公式图 → 优先转真文本（OCR 映射），无则小图渲染
    - {{img:xx}} 图表/题图 → chafa 大图渲染（结构图需要分辨率）
    """
    if not text:
        return ""

    def repl_tex(m: re.Match) -> str:
        fname = m.group(1)
        # 1) 有文本映射 → 直接内联文字，最清晰
        t = formula_to_text(fname)
        if t is not None:
            return cyan(t) if supports_color() else t
        if not show_images:
            return dim(f"[式:{fname}]")
        # 2) 无映射 → 小尺寸渲染兜底
        p = find_image(fname)
        if p is None:
            return dim(f"[式未下载:{fname}]")
        return "\n" + image_to_text(p, max_width=56, max_height=12) + "\n"

    def repl_img(m: re.Match) -> str:
        fname = m.group(1)
        if not show_images:
            return dim(f"[图:{fname}]")
        p = find_image(fname)
        if p is None:
            return dim(f"[图未下载:{fname}]")
        # 图表/照片：需要更高分辨率看清结构
        return "\n" + image_to_text(p, max_width=72, max_height=24) + "\n"

    out = re.sub(r"\{\{tex:([^}]+)\}\}", repl_tex, text)
    out = re.sub(r"\{\{img:([^}]+)\}\}", repl_img, out)
    return out


def strip_checks(opt_text: str) -> str:
    return opt_text.replace(CHECK, "").strip()


# ── 数据访问 ──────────────────────────────────────────
def connect() -> sqlite3.Connection:
    if not DB.exists():
        sys.exit(f"题库不存在: {DB}，请先运行 parse_bank.py")
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def list_modules(conn) -> list[tuple[str, int]]:
    return conn.execute(
        "SELECT module, COUNT(*) n FROM questions WHERE answer!='' GROUP BY module ORDER BY module"
    ).fetchall()


def list_years(conn, module: str | None = None) -> list[tuple[str, int]]:
    if module:
        return conn.execute(
            "SELECT year, COUNT(*) n FROM questions WHERE answer!='' AND module=? "
            "GROUP BY year ORDER BY year",
            (module,),
        ).fetchall()
    return conn.execute(
        "SELECT year, COUNT(*) n FROM questions WHERE answer!='' AND year!='' "
        "GROUP BY year ORDER BY year"
    ).fetchall()


def list_papers(conn, module: str, year: str) -> list[tuple[str, int]]:
    return conn.execute(
        "SELECT paper, COUNT(*) n FROM questions WHERE answer!='' AND module=? AND year=? "
        "GROUP BY paper ORDER BY paper",
        (module, year),
    ).fetchall()


def fetch_questions(
    conn,
    module: str | None = None,
    year: str | None = None,
    paper: str | None = None,
    limit: int | None = None,
    shuffle: bool = True,
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM questions WHERE answer!=''"
    args: list = []
    if module:
        sql += " AND module=?"
        args.append(module)
    if year:
        sql += " AND year=?"
        args.append(year)
    if paper:
        sql += " AND paper=?"
        args.append(paper)
    sql += " ORDER BY paper, idx_in_paper"
    rows = conn.execute(sql, args).fetchall()
    rows = list(rows)
    if shuffle:
        random.shuffle(rows)
    if limit:
        rows = rows[:limit]
    return rows


# ── 交互 ──────────────────────────────────────────────
def prompt(msg: str) -> str:
    try:
        return input(msg).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return "q"


def choose(title: str, options: list[tuple[str, object]]) -> object | None:
    """返回所选 value；返回 None 表示返回/退出。"""
    print()
    print(bold(f"══ {title} ══"))
    for i, (label, _v) in enumerate(options, 1):
        print(f"  {cyan(str(i))}. {label}")
    print(f"  {cyan('b')}. 返回上一级")
    print(f"  {cyan('q')}. 退出")
    while True:
        raw = prompt("请选择: ")
        if raw.lower() == "q":
            return "QUIT"
        if raw.lower() == "b":
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][1]
        print(red("输入无效，请重试"))


def show_question(q: sqlite3.Row, no: int, total: int, show_img: bool) -> str | None:
    """出题并收答案。返回 'QUIT' / 答案字母 / None(跳过)。"""
    print()
    print(bold(f"┌── 第 {no}/{total} 题 ──"))
    meta = []
    if q["year"]:
        meta.append(str(q["year"]))
    if q["region"]:
        meta.append(str(q["region"]))
    if q["module"]:
        meta.append(str(q["module"]))
    if q["qtype"]:
        meta.append(str(q["qtype"]))
    if meta:
        print(dim("│ " + " · ".join(meta)))
    if q["paper"]:
        print(dim("│ " + str(q["paper"])))

    material = q["material"] or ""
    if material.strip():
        print(cyan("│ 【材料】"))
        print(render_markup(material, show_img))
        print()

    stem = render_markup(q["stem"] or "", show_img)
    print(bold("│ 题干:"))
    for line in stem.splitlines():
        print("│ " + line)

    opts = json.loads(q["options_json"] or "{}")
    print()
    for k in sorted(opts):
        body = render_markup(strip_checks(opts[k]), show_img)
        # 多行选项缩进
        lines = body.splitlines() or [""]
        print(f"│ {cyan(k)}. {lines[0]}")
        for ln in lines[1:]:
            print(f"│    {ln}")

    print(dim("└" + "─" * 40))
    valid = sorted(opts.keys()) or ["A", "B", "C", "D"]
    print(dim(f"输入 {'/'.join(valid)} 作答 · s 跳过 · ? 看答案 · q 退出"))

    while True:
        raw = prompt("答案> ").strip().lower()
        if raw == "q":
            return "QUIT"
        if raw == "s":
            return None
        if raw in ("?", "show", "ans", "answer"):
            return "SHOW"
        if raw.upper() in valid:
            return raw.upper()
        print(red(f"请输入 {'/'.join(valid)} / s / ? / q"))


def reveal(q: sqlite3.Row, show_img: bool) -> None:
    ans = q["answer"]
    opts = json.loads(q["options_json"] or "{}")
    print()
    print(green(f"✔ 正确答案: {ans}"))
    if ans in opts:
        print(f"   {ans}. {strip_checks(opts[ans])}")
    analysis = q["analysis"] or ""
    if analysis:
        print(cyan("【解析】"))
        print(render_markup(analysis, show_img))
    print()


def quiz_loop(
    conn,
    rows: list[sqlite3.Row],
    show_img: bool = True,
) -> dict:
    total = len(rows)
    correct = wrong = skipped = 0
    wrong_list: list[sqlite3.Row] = []

    for i, q in enumerate(rows, 1):
        r = show_question(q, i, total, show_img)
        if r == "QUIT":
            break
        if r is None:
            skipped += 1
            print(dim("已跳过"))
            continue
        if r == "SHOW":
            reveal(q, show_img)
            valid = sorted(json.loads(q["options_json"] or "{}").keys()) or list("ABCD")
            while True:
                raw = prompt("你的答案> ").strip().lower()
                if raw == "q":
                    r = "QUIT"
                    break
                if raw.upper() in valid:
                    r = raw.upper()
                    break
                if raw == "s":
                    r = None
                    break
                print(red(f"请输入 {'/'.join(valid)} / s / q"))
            if r == "QUIT":
                break
            if r is None:
                skipped += 1
                continue

        ans = q["answer"]
        if r == ans:
            correct += 1
            print(green(f"✔ 正确（{r}）"))
        else:
            wrong += 1
            wrong_list.append(q)
            print(red(f"✘ 错误 · 你的 {r} · 正确 {ans}"))
            reveal(q, show_img)

    # 小结
    done = correct + wrong
    print()
    print(bold("══ 本组成绩 ══"))
    print(f"  正确 {green(str(correct))} · 错误 {red(str(wrong))} · 跳过 {dim(str(skipped))}")
    if done:
        print(f"  正确率 {bold(f'{100*correct/done:.1f}%')}  （{correct}/{done}）")
    if wrong_list:
        print(yellow(f"  错题 {len(wrong_list)} 道已记录，可进入错题重练"))
    print()
    return {"correct": correct, "wrong": wrong, "skipped": skipped, "wrong_ids": [q["id"] for q in wrong_list]}


# ── 菜单 ──────────────────────────────────────────────
def menu_main(conn) -> None:
    while True:
        print()
        print(bold("════════ 公务员行测 · 真题刷题 ══════"))
        print(f"  题库: {DB}")
        n = conn.execute("SELECT COUNT(*) FROM questions WHERE answer!=''").fetchone()[0]
        print(f"  可刷题目: {bold(str(n))} 道")
        print()
        print(f"  {cyan('1')}. 按模块 + 年份刷真题")
        print(f"  {cyan('2')}. 按模块随机刷题")
        print(f"  {cyan('3')}. 全库随机刷题")
        print(f"  {cyan('4')}. 指定试卷逐题刷")
        print(f"  {cyan('5')}. 错题重练（本次会话）")
        print(f"  {cyan('6')}. 查看题库统计")
        print(f"  {cyan('7')}. 刷新图片索引（下载完成后）")
        print(f"  {cyan('q')}. 退出")
        raw = prompt("选择> ")
        if raw == "q":
            print("再见，刷题愉快！")
            return
        if raw == "1":
            if menu_module_year(conn) == "QUIT":
                return
        elif raw == "2":
            if menu_random_module(conn) == "QUIT":
                return
        elif raw == "3":
            n_in = prompt("随机抽几题? [10] ")
            k = int(n_in) if n_in.isdigit() else 10
            rows = fetch_questions(conn, limit=k, shuffle=True)
            if rows and quiz_loop(conn, rows) == "QUIT":
                return
        elif raw == "4":
            if menu_paper(conn) == "QUIT":
                return
        elif raw == "5":
            if wrong_pool and menu_wrong(conn, wrong_pool) == "QUIT":
                return
            if not wrong_pool:
                print(yellow("本次会话还没有错题"))
        elif raw == "6":
            menu_stats(conn)
        elif raw == "7":
            n = refresh_image_index()
            print(green(f"已索引 {n} 张图片"))
        else:
            print(red("无效选择"))


wrong_pool: list[int] = []


def menu_module_year(conn) -> str | None:
    mods = list_modules(conn)
    if not mods:
        print(red("无数据"))
        return None
    mv = choose(
        "选择模块（刷题类型）",
        [(f"{m}  ({n} 题)", m) for m, n in mods],
    )
    if mv == "QUIT":
        return "QUIT"
    if mv is None:
        return None
    module = mv

    years = list_years(conn, module)
    if not years:
        print(red("该模块无年份数据"))
        return None
    yv = choose(
        f"{module} · 选择年份（真题）",
        [(f"{y} 年  ({n} 题)", y) for y, n in years],
    )
    if yv == "QUIT":
        return "QUIT"
    if yv is None:
        return None
    year = yv

    # 可选：整年随机 or 指定试卷
    av = choose(
        f"{module} {year} · 出题方式",
        [
            ("整年随机抽题", "rand"),
            ("按试卷顺序刷（选试卷）", "paper"),
        ],
    )
    if av == "QUIT":
        return "QUIT"
    if av is None:
        return None

    if av == "paper":
        papers = list_papers(conn, module, year)
        if not papers:
            print(red("无试卷"))
            return None
        pv = choose(
            f"{module} {year} · 选择试卷",
            [(f"{p}  ({n} 题)", p) for p, n in papers],
        )
        if pv == "QUIT":
            return "QUIT"
        if pv is None:
            return None
        rows = fetch_questions(conn, module=module, year=year, paper=pv, shuffle=False)
    else:
        kn = prompt("抽几题? [全部] ")
        limit = int(kn) if kn.isdigit() else None
        rows = fetch_questions(conn, module=module, year=year, limit=limit, shuffle=True)

    if not rows:
        print(yellow("没有匹配的题目"))
        return None
    print(bold(f"\n开始: {module} · {year} · {len(rows)} 题"))
    result = quiz_loop(conn, rows)
    wrong_pool.extend(result.get("wrong_ids", []))
    if result == "QUIT":
        return "QUIT"
    return None


def menu_random_module(conn) -> str | None:
    mods = list_modules(conn)
    mv = choose("选择模块", [(f"{m}  ({n} 题)", m) for m, n in mods])
    if mv == "QUIT":
        return "QUIT"
    if mv is None:
        return None
    kn = prompt("抽几题? [10] ")
    k = int(kn) if kn.isdigit() else 10
    rows = fetch_questions(conn, module=mv, limit=k, shuffle=True)
    if rows:
        result = quiz_loop(conn, rows)
        wrong_pool.extend(result.get("wrong_ids", []))
        if result == "QUIT":
            return "QUIT"
    return None


def menu_paper(conn) -> str | None:
    mods = list_modules(conn)
    mv = choose("选择模块", [(f"{m}", m) for m, n in mods])
    if mv == "QUIT":
        return "QUIT"
    if mv is None:
        return None
    years = list_years(conn, mv)
    yv = choose("选择年份", [(y, y) for y, n in years])
    if yv == "QUIT":
        return "QUIT"
    if yv is None:
        return None
    papers = list_papers(conn, mv, yv)
    pv = choose("选择试卷", [(f"{p} ({n}题)", p) for p, n in papers])
    if pv == "QUIT":
        return "QUIT"
    if pv is None:
        return None
    rows = fetch_questions(conn, module=mv, year=yv, paper=pv, shuffle=False)
    if rows:
        result = quiz_loop(conn, rows)
        wrong_pool.extend(result.get("wrong_ids", []))
        if result == "QUIT":
            return "QUIT"
    return None


def menu_wrong(conn, ids: list[int]) -> str | None:
    if not ids:
        print(yellow("无错题"))
        return None
    uniq = list(dict.fromkeys(ids))
    kn = prompt(f"错题 {len(uniq)} 道，重练几题? [全部] ")
    k = int(kn) if kn.isdigit() else len(uniq)
    placeholders = ",".join("?" * len(uniq))
    rows = conn.execute(
        f"SELECT * FROM questions WHERE id IN ({placeholders})", uniq
    ).fetchall()
    rows = list(rows)
    random.shuffle(rows)
    rows = rows[:k]
    result = quiz_loop(conn, rows)
    # 更新池：去掉做对的
    if result.get("wrong_ids"):
        wrong_pool.extend(result["wrong_ids"])
    return "QUIT" if result == "QUIT" else None


def menu_stats(conn) -> None:
    print()
    print(bold("══ 题库统计 ══"))
    print(f"{'模块':<16}{'题量':>8}")
    for row in conn.execute(
        "SELECT module, COUNT(*) n FROM questions GROUP BY module ORDER BY n DESC"
    ):
        print(f"  {row['module']:<14}{row['n']:>8}")
    total = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    print(f"  {'合计':<14}{total:>8}")
    print()
    print(f"{'年份':<8}{'题量':>8}")
    for row in conn.execute(
        "SELECT year, COUNT(*) n FROM questions WHERE year!='' GROUP BY year ORDER BY year"
    ):
        print(f"  {row['year']:<6}{row['n']:>8}")
    papers = conn.execute("SELECT COUNT(DISTINCT paper) FROM questions").fetchone()[0]
    print(f"\n  试卷数: {papers}")
    no_ans = conn.execute("SELECT COUNT(*) FROM questions WHERE answer=''").fetchone()[0]
    if no_ans:
        print(f"  缺答案: {no_ans}")


def main() -> int:
    ap = argparse.ArgumentParser(description="公务员行测真题刷题 CLI")
    ap.add_argument("--module", help="模块名，如 判断推理")
    ap.add_argument("--year", help="年份，如 2024")
    ap.add_argument("--paper", help="试卷名")
    ap.add_argument("--random", type=int, metavar="N", help="随机抽 N 题")
    ap.add_argument("--no-image", action="store_true", help="不渲染图片预览")
    ap.add_argument("--list", action="store_true", help="仅列出模块/年份")
    ap.add_argument("--refresh-index", action="store_true", help="重建图片索引后退出")
    args = ap.parse_args()

    if args.refresh_index:
        n = refresh_image_index()
        print(f"已索引 {n} 张图片 → {IMG_INDEX}")
        return 0

    conn = connect()
    show_img = not args.no_image

    if args.list:
        print("模块:")
        for m, n in list_modules(conn):
            print(f"  {m}: {n}")
        print("年份:")
        for y, n in list_years(conn):
            print(f"  {y}: {n}")
        return 0

    # 直接指定参数 → 单组刷题
    if args.module or args.year or args.random:
        if args.random:
            rows = fetch_questions(
                conn, module=args.module, year=args.year, limit=args.random, shuffle=True
            )
        else:
            rows = fetch_questions(
                conn,
                module=args.module,
                year=args.year,
                paper=args.paper,
                shuffle=bool(args.random),
            )
        if not rows:
            print("没有匹配的题目")
            return 1
        print(bold(f"共 {len(rows)} 题"))
        quiz_loop(conn, rows, show_img=show_img)
        return 0

    # 交互菜单
    try:
        menu_main(conn)
    except KeyboardInterrupt:
        print("\n再见！")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
