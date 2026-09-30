# -*- coding: utf-8 -*-
r"""批量把多份转写稿 txt 转成 Word —— txt_to_docx.py 的批处理包装。

txt_to_docx.py 一次只吃一个 config.json，多份录音就得写多个 config 再逐个调用，
本脚本把这一步合并成一条命令。

用法:
    <通用 python> batch_txt_to_docx.py jobs.json

jobs.json 是数组，每项字段与 txt_to_docx.py 的 config 相同（outline 可为 []）：
[
  { "src": "01_xxx.txt",
    "out": "D:\\...\\01 转录文字稿.docx",
    "title": "9月27日 上午① … · 录音转写文字稿",
    "subtitle": "… · 全程逐段文字稿",
    "source_note": "9.27上午，课程内容.m4a（121 MB，1 小时 19 分 10 秒）",
    "parts_dir": "parts_01",
    "outline": [["00:00 - 10:00", "…"]] }
]
相对路径按 jobs.json 所在目录解析。逐项调用 txt_to_docx.py 并汇总成败。
"""
import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONVERTER = os.path.join(HERE, "txt_to_docx.py")


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    jp = os.path.abspath(sys.argv[1])
    base = os.path.dirname(jp)
    jobs = json.loads(io.open(jp, encoding="utf-8").read())
    py = sys.executable
    ok = bad = 0
    for j in jobs:
        cfg = dict(j)
        for k in ("src", "out"):
            if not os.path.isabs(cfg[k]):
                cfg[k] = os.path.join(base, cfg[k])
        cf = os.path.join(base, "cfg_" + cfg.get("parts_dir", "parts") + ".json")
        io.open(cf, "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False, indent=2))
        r = subprocess.run([py, CONVERTER, cf], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        log = ((r.stdout or "") + (r.stderr or "")).splitlines()
        saved = next((l for l in log if "File saved to:" in l), "")
        missed = [l for l in log if "heading MISS" in l]
        segs = next((l for l in log if "segments=" in l), "")
        name = os.path.basename(cfg["src"])
        if saved and not missed:
            ok += 1
            print(f"[OK]   {name}\n       {segs.strip()}\n       {saved.split('File saved to:')[-1].strip()}")
        else:
            bad += 1
            print(f"[FAIL] {name}\n       {segs.strip()}\n       失败原因: {'标题层级未套上' if missed else (r.stderr or r.stdout or '')[-300:]}")
    print(f"\n完成 {ok} 份，失败 {bad} 份")


if __name__ == "__main__":
    main()
