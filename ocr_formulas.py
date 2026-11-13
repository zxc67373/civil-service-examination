#!/usr/bin/env python3
"""公式图 → 文本映射 bank/formula_text.json（多策略 OCR + 断点续传）"""
from __future__ import annotations
import json, re, subprocess, sys, os, threading
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from PIL import Image, ImageOps

IDX = Path('/root/civil-service-examination/bank/image_index.json')
OUT = Path('/root/civil-service-examination/bank/formula_text.json')
FREQ = Path('/root/civil-service-examination/bank/formula_freq.json')
TMP = Path('/tmp/ocr_f')
TMP.mkdir(exist_ok=True)

WH = "0123456789.%,+=<>xyna→−-/()°′″"

def prep(path: Path):
    im = Image.open(path)
    if im.mode == 'P':
        im = im.convert('RGBA')
    if im.mode in ('RGBA', 'LA'):
        bg = Image.new('RGBA', im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im.convert('RGBA'))
    g = im.convert('L')
    f = max(2, min(8, 80 // max(g.height, 1) or 2))
    if f != 1:
        g = g.resize((g.width * f, g.height * f), Image.Resampling.LANCZOS)
    return ImageOps.autocontrast(g)

def ocr_one(item):
    name, path = item
    wid = threading.get_ident()
    tmp = TMP / f'w{wid}.png'
    try:
        g = prep(Path(path))
        g.save(tmp)
        # 1) 数字
        r = subprocess.run(['tesseract', str(tmp), 'stdout', '-l', 'eng', '--psm', '7',
                            '-c', f'tessedit_char_whitelist={WH}'],
                           capture_output=True, text=True, timeout=10)
        t = re.sub(r'\s+', '', r.stdout.strip())
        if t and re.search(r'\d', t):
            return name, t
        # 2) 符号
        r = subprocess.run(['tesseract', str(tmp), 'stdout', '-l', 'eng', '--psm', '10',
                            '-c', 'tessedit_char_whitelist=→−+=<>xyna%'],
                           capture_output=True, text=True, timeout=10)
        t2 = re.sub(r'\s+', '', r.stdout.strip())
        if t2 and t2 not in ('', '-', '--'):
            mp = {')>': '→', ')>': '→', '--': '−', '-': '−', '=': '=', '+': '+',
                  'x': 'x', 'y': 'y', 'a': 'a', '>': '>', '<': '<', '%': '%'}
            return name, mp.get(t2, t2)
        # 3) 中文
        r = subprocess.run(['tesseract', str(tmp), 'stdout', '-l', 'chi_sim', '--psm', '6'],
                           capture_output=True, text=True, timeout=10)
        t3 = re.sub(r'\s+', '', r.stdout.strip())
        if t3:
            return name, t3
        # 4) psm8
        r = subprocess.run(['tesseract', str(tmp), 'stdout', '-l', 'eng', '--psm', '8'],
                           capture_output=True, text=True, timeout=10)
        t4 = re.sub(r'\s+', '', r.stdout.strip())
        return name, t4 or t or t2
    except Exception:
        return name, ''
    finally:
        tmp.unlink(missing_ok=True)

def main():
    idx = json.loads(IDX.read_text())
    freq = json.loads(FREQ.read_text()) if FREQ.exists() else {}
    names = sorted((n for n in idx if n.startswith('formula-')),
                   key=lambda n: -freq.get(n, 0))
    done = json.loads(OUT.read_text()) if OUT.exists() else {}
    todo = [(n, idx[n]) for n in names if n not in done]
    print(f'total={len(names)} done={len(done)} todo={len(todo)}', flush=True)
    if not todo:
        return 0
    n = 0
    with ProcessPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(ocr_one, it) for it in todo]
        for fut in as_completed(futs):
            name, text = fut.result()
            if text:
                done[name] = text
            n += 1
            if n % 1000 == 0:
                OUT.write_text(json.dumps(done, ensure_ascii=False), encoding='utf-8')
                print(f'  {n}/{len(todo)} ok={len(done)}', flush=True)
    OUT.write_text(json.dumps(done, ensure_ascii=False), encoding='utf-8')
    print(f'FINISHED {len(done)} -> {OUT}', flush=True)
    return 0

if __name__ == '__main__':
    sys.exit(main())
