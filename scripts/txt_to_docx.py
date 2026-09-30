# -*- coding: utf-8 -*-
r"""转写稿(raw txt) -> Word 文字稿（docx）。一条命令跑完：建文档 / 分片插入 / 补标题层级 / 保存。

用法:
    <通用 python> txt_to_docx.py config.json

config.json 字段:
{
  "src":      "raw_0920.txt",                   # transcribe.py --timestamps 的输出（必填）
  "out":      "D:\\...\\xxx.docx",               # 目标 docx 全路径（必填）
  "title":    "9月20日 AI 训练师课程 录音 · 转写文字稿",
  "subtitle": "AI 训练师课程（第二天）· 全程逐段文字稿",
  "source_note": "9月20 ai训练师课程.m4a（234 MB）",
  "outline":  [["00:00 - 10:00", "开场……"]],    # 辅助归纳的段落索引，可为 []
  "parts_dir": "docparts_0920",                 # 可选，放 HTML 分片，默认 docparts
  "chunk": 120                                  # 可选，每片段落数
}
相对路径（src / parts_dir）按 config.json 所在目录解析。

依赖 editor_sdk（tencent-local-office-edit 技能），路径由 EDS_SKILL 环境变量指定；
未设时会尝试从常见位置自动探测，换机器/换盘符时设 EDS_SKILL 指向该技能目录即可。

踩过的坑（已在代码里处理）：
1. 时间戳分钟数可能 3 位（录音 >100 分钟），正则必须 \d{2,3}，否则段落结构解析错。
2. create_doc 返回后文档不是马上可写，立刻调 doc_get_last_operable_pos 会报
   「document is not open」——必须轮询等就绪（wait_ready）。
3. doc_insert_html_content 的参数名是 html_text；回包里 position / last_edit_index 同级同值，
   用它当下一次插入的 idx 顺序追加。
4. doc_insert_html_content 的 <h1> 不会自动套 Heading 样式，要事后用
   doc_find(拿 begin/end) + doc_apply_named_style(ranges=..., named_style_type="HEADING_1") 补，
   否则 Word 导航窗格里看不到层级。
5. editor_sdk 各工具回包格式不统一（纯文本 / JSON 混用），统一用正则取字段最稳。
"""
import io
import json
import os
import re
import sys
import html as htmlmod

def _find_eds():
    env = os.environ.get("EDS_SKILL")
    if env and os.path.isdir(env):
        return env
    home = os.path.expanduser("~")
    # 常见 WorkBuddy 内置技能目录，跨平台自动探测（不含任何写死的用户名）
    cands = []
    for base in (
        os.path.join(home, ".workbuddy", "skills", "tencent-local-office-edit"),
        os.path.join(home, ".workbuddy", "plugins", "cache"),
    ):
        cands.append(base)
    # 递归找 tencent-local-office-edit（限制深度，避免全盘扫描）
    def _walk(root, depth):
        if depth < 0:
            return None
        try:
            for name in os.listdir(root):
                if name == "tencent-local-office-edit":
                    p = os.path.join(root, name)
                    if os.path.isdir(p):
                        return p
            for name in os.listdir(root):
                sub = os.path.join(root, name)
                if os.path.isdir(sub) and ("workbuddy" in name.lower() or "plugin" in name.lower()
                                           or "skill" in name.lower()):
                    r = _walk(sub, depth - 1)
                    if r:
                        return r
        except Exception:
            return None
        return None
    for c in cands:
        if os.path.isdir(c):
            return c
        r = _walk(c, 4)
        if r:
            return r
    return None


EDS_SKILL = _find_eds()
if not EDS_SKILL:
    raise SystemExit(
        "找不到 tencent-local-office-edit 技能目录。请设环境变量 EDS_SKILL 指向它，"
        "或确认该技能已安装。")
sys.path.insert(0, EDS_SKILL)
import edsdk  # noqa: E402

TS = re.compile(r"^\[(\d{2,3}:\d\d\.\d\d) - (\d{2,3}:\d\d\.\d\d)\]\s*(.*)$")
NOTICE_PREFIX = (
    "Notice: ffmpeg", "If you want to use ffmpeg", "sudo apt install ffmpeg",
    "# brew install ffmpeg", "funasr version:", "Check update of funasr",
    "New version is available", 'Please use the command "pip install -U funasr"',
    "[1/2] ffmpeg", "[2/2] FunASR",
)
HEADINGS = ["一、文档信息", "二、内容脉络（辅助归纳，非原文）", "三、全文文字稿（带时间戳）"]


def call(name, args):
    res = edsdk._rpc("tools/call", {"name": name, "arguments": args})
    texts = [c.get("text", "") for c in (res.get("content") or [])
             if isinstance(c, dict) and c.get("type") == "text"]
    return "\n".join(texts)


def safe_call(name, args, retries=12, wait=1.0):
    """edsdk._die 会 sys.exit(1)，这里兜住 SystemExit 做重试。"""
    import time
    for i in range(retries):
        try:
            return call(name, args)
        except SystemExit:
            if i == retries - 1:
                raise
            time.sleep(wait)


def first(pattern, s, default=None):
    m = re.search(pattern, s or "")
    return m.group(1) if m else default


def wait_ready(fid):
    """create_doc 后文档需要一点时间才就绪，轮询到能取到 position 为止。"""
    import time
    last = ""
    for _ in range(40):
        try:
            raw = call("doc_get_last_operable_pos", {"file_id": fid})
        except SystemExit:
            time.sleep(1.0)
            continue
        m = re.search(r'"position"\s*:\s*(\d+)', raw or "")
        if m:
            return int(m.group(1))
        last = raw or ""
        time.sleep(1.0)
    raise SystemExit("文档迟迟未就绪: " + last)


def parse_segments(path):
    segs = []
    for ln in io.open(path, encoding="utf-8").read().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith(NOTICE_PREFIX):
            continue
        m = TS.match(ln)
        segs.append((m.group(1), m.group(2), m.group(3).strip()) if m
                    else ("", "", ln))
    return segs


def build_parts(cfg, segs, parts_dir):
    body_chars = sum(len(re.sub(r"\s", "", t)) for _, _, t in segs)
    total = segs[-1][1] if segs and segs[-1][1] else ""
    src_note = cfg.get("source_note") or os.path.basename(cfg["src"])

    head = ['<p style="text-align:center"><span style="font-size:20pt;font-weight:bold">'
            + htmlmod.escape(cfg["title"]) + "</span></p>"]
    if cfg.get("subtitle"):
        head.append('<p style="text-align:center"><span style="font-size:10pt;color:#808080">'
                    + htmlmod.escape(cfg["subtitle"]) + "</span></p>")
    head.append("<h1>一、文档信息</h1>")
    head.append(f"<p><b>来源文件</b>：{htmlmod.escape(src_note)}</p>"
                f"<p><b>音频时长</b>：约 {total}　<b>文字稿规模</b>：{len(segs)} 个语音段落，"
                f"正文约 {body_chars} 字</p>"
                "<p><b>转写方式</b>：本地 FunASR / SenseVoiceSmall 引擎识别（中文，CPU，含标点与数字规整），"
                "<b>未经人工逐句校对</b></p>"
                "<p><b>保真说明</b>：正文为引擎原始输出，保留口语、重复、语气词与原有断句；"
                "人名、专业术语及方言口音处可能存在同音误识，正式引用请以录音原声为准。</p>")
    head.append("<h1>二、内容脉络（辅助归纳，非原文）</h1>")
    if cfg.get("outline"):
        head.append("<p>下表为便于检索的段落级索引，时间点为该话题在录音中的大致起点。</p>")
        head.append("<table border='1' cellspacing='0' cellpadding='4' "
                    "style='border-collapse:collapse;width:100%'>"
                    "<tr><th style='width:120px'>时间</th><th>内容</th></tr>"
                    + "".join(f"<tr><td>{htmlmod.escape(t)}</td><td>{htmlmod.escape(d)}</td></tr>"
                              for t, d in cfg["outline"])
                    + "</table>")
    else:
        head.append("<p>（本次未做归纳，全文见下。）</p>")
    head.append("<h1>三、全文文字稿（带时间戳）</h1>")
    head.append("<p>每段前缀为该段在录音中的起止时间（分:秒）；语音连续无静音处会合并为较长段落。</p>")

    os.makedirs(parts_dir, exist_ok=True)
    for f in os.listdir(parts_dir):
        os.remove(os.path.join(parts_dir, f))

    def write(n, s):
        io.open(os.path.join(parts_dir, f"part_{n:02d}.html"), "w", encoding="utf-8").write(s)

    write(0, "".join(head))
    n, buf, chunk = 0, [], cfg.get("chunk", 120)
    for a, b, t in segs:
        buf.append(f"<p>{htmlmod.escape((f'[{a} - {b}] ' if a else '') + t)}</p>")
        if len(buf) >= chunk:
            n += 1
            write(n, "".join(buf))
            buf = []
    if buf:
        n += 1
        write(n, "".join(buf))
    return body_chars, total


def main():
    cfg_path = os.path.abspath(sys.argv[1])
    base = os.path.dirname(cfg_path)
    cfg = json.loads(io.open(cfg_path, encoding="utf-8").read())
    src = cfg["src"] if os.path.isabs(cfg["src"]) else os.path.join(base, cfg["src"])
    parts_dir = cfg.get("parts_dir", "docparts")
    if not os.path.isabs(parts_dir):
        parts_dir = os.path.join(base, parts_dir)

    segs = parse_segments(src)
    body_chars, total = build_parts(cfg, segs, parts_dir)
    print(f"segments={len(segs)} chars={body_chars} duration={total}")

    raw = call("create_doc", {})
    fid = first(r"file_id=([^\s,]+)", raw)
    if not fid:
        raise SystemExit("create_doc 未返回 file_id:\n" + raw)
    print("file_id =", fid)

    idx = wait_ready(fid)
    print("start position =", idx)
    for fn in sorted(f for f in os.listdir(parts_dir) if f.endswith(".html")):
        html_text = io.open(os.path.join(parts_dir, fn), encoding="utf-8").read()
        raw = safe_call("doc_insert_html_content",
                        {"file_id": fid, "idx": idx, "html_text": html_text})
        p = first(r'"position"\s*:\s*(\d+)', raw)
        print(f"  {fn}: {idx} -> {p}")
        idx = int(p) if p else idx

    for h in HEADINGS:
        raw = safe_call("doc_find", {"file_id": fid, "text": h})
        m = re.search(r'"begin"\s*:\s*(\d+)\s*,\s*"end"\s*:\s*(\d+)', raw or "")
        if not m:
            print("  heading MISS:", h)
            continue
        safe_call("doc_apply_named_style",
                  {"file_id": fid, "ranges": [{"begin": int(m.group(1)), "end": int(m.group(2))}],
                   "named_style_type": "HEADING_1"})
        print("  heading OK:", h)

    raw = safe_call("save_file", {"file_id": fid, "file_path": cfg["out"]})
    print("save:", (raw or "")[:200].replace("\n", " "))


if __name__ == "__main__":
    main()
