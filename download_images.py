#!/usr/bin/env python3
"""后台并行下载 xingcezhenti 仓库图片（断点续传 + 进度日志）。

用法:
  python3 download_images.py            # 默认 8 并发
  python3 download_images.py -j 12      # 自定义并发
  python3 download_images.py --once     # 单轮跑完即退出（默认循环直到全部完成）
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

REPO_RAW = "https://raw.githubusercontent.com/ERRRC/xingcezhenti/main/"
PROXY_PREFIX = "https://gh-proxy.com/"
ROOT = Path("/root/civil-service-examination/xingcezhenti")
LIST_FILE = Path("/tmp/image_list.txt")
LOG_FILE = Path("/root/civil-service-examination/download_images.log")
STATE_FILE = Path("/root/civil-service-examination/download_images.state")

# 直连与镜像都试，取先成功者
MIRRORS = [
    PROXY_PREFIX + REPO_RAW,
    REPO_RAW,
]

_lock = threading.Lock()
_done = 0
_failed = 0
_skipped = 0
_bytes = 0
_start = time.time()
_stop = False


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    with _lock:
        print(line, flush=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def load_list() -> list[str]:
    if not LIST_FILE.exists():
        sys.exit(f"缺少清单: {LIST_FILE}")
    paths = []
    for line in LIST_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            paths.append(line)
    return paths


def local_path(rel: str) -> Path:
    # rel 形如 90-图片/题目图/xxx.png
    return ROOT / rel


def already_done(p: Path) -> bool:
    return p.exists() and p.stat().st_size > 0


def fetch_one(rel: str) -> tuple[str, str, int]:
    """返回 (rel, status, bytes_downloaded)。status: ok|skip|fail"""
    global _bytes
    if _stop:
        return rel, "skip", 0
    dest = local_path(rel)
    if already_done(dest):
        return rel, "skip", 0

    dest.parent.mkdir(parents=True, exist_ok=True)
    # 中文路径需编码，但保留 /
    quoted = "/".join(urllib.parse.quote(seg) for seg in rel.split("/"))
    tmp = dest.with_suffix(dest.suffix + ".part")

    last_err = ""
    for base in MIRRORS:
        url = base + quoted
        try:
            with requests.get(url, stream=True, timeout=(15, 60)) as r:
                if r.status_code != 200:
                    last_err = f"HTTP {r.status_code}"
                    continue
                size = 0
                with tmp.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=64 * 1024):
                        if _stop:
                            f.close()
                            tmp.unlink(missing_ok=True)
                            return rel, "skip", 0
                        if chunk:
                            f.write(chunk)
                            size += len(chunk)
                if size == 0:
                    last_err = "empty body"
                    tmp.unlink(missing_ok=True)
                    continue
                tmp.replace(dest)
                with _lock:
                    _bytes += size
                return rel, "ok", size
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            tmp.unlink(missing_ok=True)
            continue
    return rel, "fail", 0


def progress_loop(total: int) -> None:
    while not _stop:
        time.sleep(30)
        with _lock:
            d, f, s, b = _done, _failed, _skipped, _bytes
        finished = d + f + s
        elapsed = max(time.time() - _start, 1)
        speed = b / elapsed
        remain = total - finished
        eta = remain / (finished / elapsed) if finished else 0
        log(
            f"进度 {finished}/{total} ({100*finished/total:.1f}%) "
            f"成功={d} 跳过={s} 失败={f} "
            f"已下={b/1048576:.1f}MB 速度={speed/1048576:.2f}MB/s "
            f"ETA={eta/60:.0f}min"
        )
        if finished >= total:
            return


def main() -> int:
    global _done, _failed, _skipped, _stop

    ap = argparse.ArgumentParser()
    ap.add_argument("-j", "--jobs", type=int, default=8)
    ap.add_argument("--once", action="store_true", help="单轮结束不循环")
    ap.add_argument("--max-rounds", type=int, default=5, help="失败重试轮数")
    args = ap.parse_args()

    paths = load_list()
    total = len(paths)
    log(f"开始下载图片 total={total} jobs={args.jobs}")

    # 已完成统计
    done0 = sum(1 for p in paths if already_done(local_path(p)))
    if done0:
        log(f"已有 {done0} 张，跳过")

    def handle_sig(*_a):
        global _stop
        _stop = True
        log("收到停止信号，收尾中…")

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    threading.Thread(target=progress_loop, args=(total,), daemon=True).start()

    pending = paths
    rounds = 0
    while pending and not _stop:
        rounds += 1
        if rounds > 1:
            log(f"第 {rounds} 轮重试剩余 {len(pending)} 张")
            if rounds > args.max_rounds:
                break
        next_pending: list[str] = []
        with ThreadPoolExecutor(max_workers=args.jobs) as ex:
            futs = {ex.submit(fetch_one, rel): rel for rel in pending}
            for fut in as_completed(futs):
                rel, status, sz = fut.result()
                with _lock:
                    if status == "ok":
                        _done += 1
                    elif status == "skip":
                        _skipped += 1
                    else:
                        _failed += 1
                        next_pending.append(rel)
        pending = next_pending
        if args.once:
            break

    # 终态统计
    ok = sum(1 for p in paths if already_done(local_path(p)))
    with _lock:
        b = _bytes
    log(f"结束: 磁盘上 {ok}/{total} 张, 本轮新下 {_done} 张, 仍失败 {len(pending)} 张, 流量 {b/1048576:.1f}MB")
    if pending:
        fail_list = Path("/root/civil-service-examination/download_images.failed")
        fail_list.write_text("\n".join(pending) + "\n", encoding="utf-8")
        log(f"失败清单: {fail_list}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
