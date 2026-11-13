#!/usr/bin/env python3
"""完善题库：
1. 判断题（空选项）→ 补 A/B 正确·错误
2. 从解析恢复缺失答案（故正确答案为X）
3. 图片下载完成后：刷新索引、校验图片引用覆盖率
4. 给题目打 has_image / img_count 标记

可反复执行（幂等）。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

DB = Path("/root/civil-service-examination/bank/tiku.db")
IMG_ROOT = Path("/root/civil-service-examination/xingcezhenti/90-图片")
IMG_INDEX = Path("/root/civil-service-examination/bank/image_index.json")

TF_OPTS = {"A": "正确", "B": "错误"}
# 解析里恢复答案
RE_ANS = re.compile(r"故正确答案为\s*([A-Ha-h])")
RE_ANS2 = re.compile(r"正确答案\s*[是为:：]\s*([A-Ha-h])")
RE_IMG = re.compile(r"\{\{(img|tex):([^}]+)\}\}")


def refresh_image_index() -> dict[str, str]:
    idx: dict[str, str] = {}
    if IMG_ROOT.is_dir():
        for p in IMG_ROOT.rglob("*"):
            if p.is_file() and not p.name.endswith(".part"):
                idx[p.name] = str(p)
    IMG_INDEX.parent.mkdir(parents=True, exist_ok=True)
    IMG_INDEX.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    return idx


def fix_tf_options(conn: sqlite3.Connection) -> int:
    """空选项 + 有答案 → 判断题补 A/B。"""
    rows = conn.execute(
        "SELECT id, answer, analysis FROM questions WHERE options_json='{}' AND answer!=''"
    ).fetchall()
    n = 0
    for qid, ans, analysis in rows:
        # 约定 A=正确 B=错误；若答案不是 A/B 跳过
        if ans not in ("A", "B"):
            continue
        # 用解析校验（可选，不强制）
        conn.execute(
            "UPDATE questions SET options_json=? WHERE id=?",
            (json.dumps(TF_OPTS, ensure_ascii=False), qid),
        )
        n += 1
    conn.commit()
    return n


def fix_missing_answers(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT id, analysis FROM questions WHERE answer=''"
    ).fetchall()
    n = 0
    for qid, analysis in rows:
        if not analysis:
            continue
        # 判断题：故表述错误 → B；故表述正确 → A
        tail = analysis.rstrip()
        if "表述错误" in tail or tail.endswith("错误。"):
            conn.execute("UPDATE questions SET answer='B' WHERE id=?", (qid,))
            n += 1
            continue
        if "表述正确" in tail or tail.endswith("正确。"):
            conn.execute("UPDATE questions SET answer='A' WHERE id=?", (qid,))
            n += 1
            continue
        m = RE_ANS.search(analysis) or RE_ANS2.search(analysis)
        if not m:
            continue
        ch = m.group(1).upper()
        if ch not in "ABCDEFGH":
            continue
        conn.execute("UPDATE questions SET answer=? WHERE id=?", (ch, qid))
        n += 1
    conn.commit()
    return n


def add_image_flags(conn: sqlite3.Connection, idx: dict[str, str]) -> dict:
    """计算 has_image / 图片是否已就位。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(questions)")}
    if "has_image" not in cols:
        conn.execute("ALTER TABLE questions ADD COLUMN has_image INTEGER DEFAULT 0")
    if "img_total" not in cols:
        conn.execute("ALTER TABLE questions ADD COLUMN img_total INTEGER DEFAULT 0")
    if "img_ready" not in cols:
        conn.execute("ALTER TABLE questions ADD COLUMN img_ready INTEGER DEFAULT 0")

    total_q = ready_q = 0
    img_refs = ready_refs = 0
    missing_names: set[str] = set()

    rows = conn.execute(
        "SELECT id, stem, options_json, material, analysis FROM questions"
    ).fetchall()
    upd = []
    for qid, stem, opts, mat, an in rows:
        blob = "\n".join(
            [
                stem or "",
                opts or "",
                mat or "",
                an or "",
            ]
        )
        names = RE_IMG.findall(blob)
        # 只统计文件名
        files = [n for _k, n in names]
        ready = sum(1 for f in files if f in idx)
        for f in files:
            if f not in idx:
                missing_names.add(f)
        has = 1 if files else 0
        if has:
            total_q += 1
            img_refs += len(files)
            ready_refs += ready
            if ready == len(files):
                ready_q += 1
        upd.append((has, len(files), ready, qid))

    conn.executemany(
        "UPDATE questions SET has_image=?, img_total=?, img_ready=? WHERE id=?",
        upd,
    )
    conn.commit()
    return {
        "questions_with_image": total_q,
        "questions_all_images_ready": ready_q,
        "image_refs": img_refs,
        "image_refs_ready": ready_refs,
        "missing_unique": len(missing_names),
        "missing_sample": sorted(missing_names)[:20],
    }


def main() -> int:
    if not DB.exists():
        sys.exit("题库不存在")
    conn = sqlite3.connect(DB)

    print("== 1/3 判断题补选项 ==")
    n1 = fix_tf_options(conn)
    print(f"  修复 {n1} 题（A=正确 B=错误）")

    print("== 2/3 从解析恢复答案 ==")
    n2 = fix_missing_answers(conn)
    print(f"  恢复 {n2} 题答案")

    print("== 3/3 图片索引与标记 ==")
    idx = refresh_image_index()
    print(f"  索引图片 {len(idx)} 张 → {IMG_INDEX}")
    stats = add_image_flags(conn, idx)
    print(f"  含图题目: {stats['questions_with_image']}")
    print(f"  图片全部就位的题目: {stats['questions_all_images_ready']}")
    print(f"  图片引用: {stats['image_refs_ready']}/{stats['image_refs']} 就位")
    print(f"  仍缺失图片文件: {stats['missing_unique']}")
    if stats["missing_sample"]:
        print(f"  缺失样例: {stats['missing_sample'][:5]}")

    # 汇总
    print("\n== 汇总 ==")
    print("  可刷题(有答案):", conn.execute(
        "SELECT COUNT(*) FROM questions WHERE answer!=''"
    ).fetchone()[0])
    print("  仍缺答案:", conn.execute(
        "SELECT COUNT(*) FROM questions WHERE answer=''"
    ).fetchone()[0])
    print("  仍空选项:", conn.execute(
        "SELECT COUNT(*) FROM questions WHERE options_json='{}'"
    ).fetchone()[0])
    # 空选项且无答案的判断题：也补上选项但没法给答案
    n3 = conn.execute(
        "SELECT COUNT(*) FROM questions WHERE options_json='{}'"
    ).fetchone()[0]
    if n3:
        rows = conn.execute(
            "SELECT id FROM questions WHERE options_json='{}'"
        ).fetchall()
        conn.executemany(
            "UPDATE questions SET options_json=? WHERE id=?",
            [
                (json.dumps(TF_OPTS, ensure_ascii=False), r[0])
                for r in rows
            ],
        )
        conn.commit()
        print(f"  已为剩余 {n3} 题补判断选项（答案仍可能缺）")

    conn.close()
    # 写一份统计快照
    snap = {
        "fixed_tf_options": n1,
        "recovered_answers": n2,
        "image_index": len(idx),
        **stats,
    }
    Path("/root/civil-service-examination/bank/fix_report.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n报告: bank/fix_report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
