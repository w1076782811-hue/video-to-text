#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
把「视频/音频来源」落到本地文件，打印最终本地路径到 stdout。

支持四类来源：
  1) 本地已存在路径                        -> 直接复用（不复制，省空间）
  2) 直链媒体 http(s) 且路径以媒体后缀结尾 -> urllib 直接下载
  3) 平台页面链接（B站/抖音/小红书/微博/YouTube/快手…）-> 调 yt-dlp 下载完整视频
  4) 飞书 Drive file_token                 -> 用 lark-cli drive +download 下载

注意：飞书【多维表格附件】不能用本脚本，请用专用命令
      `lark-cli base +record-download-attachment`（见 SKILL.md 第1步）。

可发布版：运行环境路径从 <skill>/config.json 读取（环境变量可覆盖），不含个人信息。

用法:
  fetch_media.py <来源> <输出路径> [--max-height 1080] [--audio-only]
                 [--cookies <cookies.txt>] [--cookies-from-browser chrome]
                 [--proxy http://127.0.0.1:7890]

  · 平台链接模式下，<输出路径> 只取其**所在目录**作为下载目录（文件名由 yt-dlp 按视频标题生成），
    stdout 会打印真实的下载文件路径。
  · --max-height   限制最高画质，默认 1080。
  · --audio-only   只下音频（转写用，更省流量更快）。
  · --cookies-from-browser  浏览器名（chrome/edge/firefox…）。抖音必须带，B站通常不用。
  · --proxy  代理地址。YouTube 等境外站点**必须**走代理；
             命中 youtube.com/youtu.be/googlevideo.com 时，若未显式传 --proxy，
             会自动使用 config.json 的 proxy（或环境变量 VTT_PROXY）。
             国内站点（B站/抖音）不要带代理，否则反而变慢或失败。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent


def load_config():
    cfg = {}
    p = SKILL_DIR / "config.json"
    if p.exists():
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    return cfg


CFG = load_config()

# 运行环境：优先 config.json，其次环境变量，最后回退到 PATH 上的同名命令
VENV_PY = os.environ.get("VTT_PYTHON", CFG.get("python", "")) or sys.executable
FFMPEG_DIR = os.environ.get("VTT_BIN_DIR", CFG.get("bin_dir", ""))
LARK_CLI = os.environ.get("LARK_CLI", CFG.get("lark_cli", "lark-cli"))
# 抖音 cookie：命中此文件就自动带上（yt-dlp 的 Douyin 提取器必须要有新鲜 cookie）
DOUYIN_COOKIES = os.environ.get("VTT_DOUYIN_COOKIES", CFG.get("douyin_cookies", ""))
# 境外站点代理：YouTube 等在大陆直连不通，必须走本地代理
YTDLP_PROXY = os.environ.get("VTT_PROXY", CFG.get("proxy", ""))

# 需要走代理的域名（直连一定失败或极慢）
PROXY_HOSTS = ("youtube.com", "youtu.be", "googlevideo.com", "ytimg.com",
               "ggpht.com", "googleusercontent.com")


def host_needs_proxy(url: str) -> bool:
    host = (urllib.parse.urlsplit(url).netloc or "").lower()
    return any(h in host for h in PROXY_HOSTS)


UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

MEDIA_EXTS = {
    ".mp4", ".m4v", ".mov", ".mkv", ".webm", ".flv", ".avi", ".ts", ".wmv", ".mpg", ".mpeg",
    ".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".opus", ".wma", ".amr",
}


class _NeedsYtdlp(Exception):
    """直链下载拿到的是网页而不是媒体文件，需要交给 yt-dlp 解析。"""


def normalize_url(url: str) -> str:
    """把各种「分享页/精选页」链接归一化成提取器认得的规范形式。

    抖音尤其重要：yt-dlp 的 DouyinIE 只认 /video/<数字ID>，
    而 App/网页分享出来的常是 /jingxuan?modal_id=<ID>、/?modal_id=<ID>
    或 v.douyin.com 短链，直接喂会报 Unsupported URL。
    """
    try:
        parts = urllib.parse.urlsplit(url)
    except Exception:
        return url
    host = (parts.netloc or "").lower()
    if "douyin.com" not in host:
        return url

    m = re.search(r"/video/(\d+)", parts.path)
    if m:
        return "https://www.douyin.com/video/" + m.group(1)

    q = urllib.parse.parse_qs(parts.query)
    for key in ("modal_id", "aweme_id", "vid"):
        vals = q.get(key) or []
        if vals and str(vals[0]).isdigit():
            return "https://www.douyin.com/video/" + str(vals[0])

    tail = parts.path.rstrip("/").rsplit("/", 1)[-1]
    if tail.isdigit() and len(tail) >= 15:
        return "https://www.douyin.com/video/" + tail

    return url


def is_url(s: str) -> bool:
    return s.lower().startswith("http://") or s.lower().startswith("https://")


def is_direct_media_url(url: str) -> bool:
    path = urllib.parse.urlsplit(url).path.lower()
    return os.path.splitext(path)[1] in MEDIA_EXTS


def looks_like_token(s: str) -> bool:
    if os.path.exists(s):
        return False
    if os.sep in s or (os.altsep and os.altsep in s):
        return False
    return True


# ---------------------------------------------------------------- 直链下载

def download_url(url: str, out_path: str):
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "html" in ctype or ctype.startswith("text/"):
            raise _NeedsYtdlp("直链返回的是网页(Content-Type: %s)，改由 yt-dlp 解析" % (ctype or "unknown"))
        with open(out_path, "wb") as f:
            shutil.copyfileobj(resp, f)
    print("已下载: %s -> %s" % (url, out_path), file=sys.stderr)


# ---------------------------------------------------------------- yt-dlp 下载

def download_with_ytdlp(url: str, out_dir: str, max_height: str = "1080",
                        audio_only: bool = False,
                        cookies_from_browser: str = None, cookies_file: str = None,
                        proxy: str = None) -> str:
    """用 yt-dlp 下载平台页面上的视频，返回落地文件路径。"""
    os.makedirs(out_dir, exist_ok=True)

    url = normalize_url(url)

    # 境外站点自动带代理（B站/抖音直连更快，不加）
    if not proxy and host_needs_proxy(url) and YTDLP_PROXY:
        proxy = YTDLP_PROXY
        print("检测到境外站点，自动使用代理: %s" % proxy, file=sys.stderr)
        print("（如失败，用 --proxy 指定自己的端口，或设环境变量 VTT_PROXY）", file=sys.stderr)

    h = str(max_height or "1080")
    cmd = [
        VENV_PY, "-m", "yt_dlp",
        "--no-warnings", "--no-playlist",
        "--no-simulate", "--print", "after_move:filepath",
    ]
    if audio_only:
        cmd += ["-f", "bestaudio/best"]
    else:
        fmt = "bv*[height<=%s]+ba/b[height<=%s]/b" % (h, h)
        cmd += ["-f", fmt, "--merge-output-format", "mp4"]
    cmd += ["--windows-filenames",
            "-o", os.path.join(out_dir, "%(title).80s.%(ext)s")]
    if proxy:
        cmd += ["--proxy", proxy]
    if FFMPEG_DIR and os.path.isdir(FFMPEG_DIR):
        cmd += ["--ffmpeg-location", FFMPEG_DIR]
    if cookies_file and os.path.exists(cookies_file):
        cmd += ["--cookies", cookies_file]
    elif cookies_file:
        print("提示: 指定的 cookie 文件不存在(%s)，按无 cookie 继续" % cookies_file, file=sys.stderr)
    if cookies_from_browser:
        cmd += ["--cookies-from-browser", cookies_from_browser]
    cmd.append(url)

    print("调用 yt-dlp 下载（%s）…" % ("仅音频" if audio_only else "最高 %sp" % h), file=sys.stderr)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)

    if r.returncode != 0:
        tail = ((r.stderr or "") + "\n" + (r.stdout or "")).strip()[-2000:]
        raise RuntimeError("yt-dlp 下载失败（返回码 %s）:\n%s" % (r.returncode, tail))

    lines = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    path = lines[-1] if lines else ""

    if not path or not os.path.exists(path):
        cands = []
        for name in os.listdir(out_dir):
            p = os.path.join(out_dir, name)
            if os.path.splitext(name)[1].lower() in MEDIA_EXTS and os.path.isfile(p):
                cands.append(p)
        if cands:
            path = max(cands, key=os.path.getmtime)

    if not path or not os.path.exists(path):
        raise RuntimeError("yt-dlp 执行完成但未找到下载文件。目录: %s" % out_dir)

    print("yt-dlp 已下载: %s" % path, file=sys.stderr)
    return path


# ---------------------------------------------------------------- 飞书下载

def download_feishu(token: str, out_path: str):
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    cli = LARK_CLI if os.path.exists(LARK_CLI) else "lark-cli"
    cmd = [cli, "drive", "+download", "--file-token", token, "--output", out_path]
    print("调用: %s" % " ".join(cmd), file=sys.stderr)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip()
        if "403" in msg:
            raise RuntimeError(
                "飞书多维表格附件用 `drive +download` 会返回 403（scope 限制，非网络问题）。\n"
                "正确做法：用专用命令 `lark-cli base +record-download-attachment "
                "--base-token <BT> --table-id <TID> --record-id <RID> --file-token <FT> "
                "--output <路径> --overwrite`（详见 SKILL.md 第1步）。\n"
                "若这是 Drive 文件而非多维表格附件，请确认 token 类型。\n"
                "原始错误: %s" % msg
            )
        raise RuntimeError("lark-cli 下载失败: %s" % msg)
    print("飞书附件已下载: %s" % out_path, file=sys.stderr)


# ---------------------------------------------------------------- 入口

def main():
    args = sys.argv[1:]
    opts, positional = {}, []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--max-height" and i + 1 < len(args):
            opts["max_height"] = args[i + 1]; i += 2; continue
        if a == "--cookies-from-browser" and i + 1 < len(args):
            opts["cookies_browser"] = args[i + 1]; i += 2; continue
        if a == "--cookies" and i + 1 < len(args):
            opts["cookies_file"] = args[i + 1]; i += 2; continue
        if a == "--proxy" and i + 1 < len(args):
            opts["proxy"] = args[i + 1]; i += 2; continue
        if a == "--audio-only":
            opts["audio_only"] = True; i += 1; continue
        positional.append(a); i += 1

    if len(positional) < 2:
        print("用法: fetch_media.py <来源> <输出路径> [--max-height 1080] [--audio-only] "
              "[--cookies <cookies.txt>] [--cookies-from-browser chrome] "
              "[--proxy http://127.0.0.1:7890]", file=sys.stderr)
        sys.exit(1)

    source, out_path = positional[0], positional[1]

    if os.path.exists(source):
        print(source)  # 本地文件直接复用
        return

    if is_url(source):
        if is_direct_media_url(source):
            try:
                download_url(source, out_path)
                print(out_path)
                return
            except _NeedsYtdlp as e:
                print(str(e), file=sys.stderr)
        url = normalize_url(source)
        if url != source:
            print("链接已归一化: %s" % url, file=sys.stderr)

        cookies_file = opts.get("cookies_file")
        if not cookies_file and "douyin.com" in url.lower() and DOUYIN_COOKIES and os.path.exists(DOUYIN_COOKIES):
            cookies_file = DOUYIN_COOKIES
            print("检测到抖音链接，自动使用 cookie: %s" % cookies_file, file=sys.stderr)
            print("（如报 Fresh cookies needed，跑 scripts/get_douyin_cookies.py 刷新）", file=sys.stderr)

        out_dir = os.path.dirname(os.path.abspath(out_path)) or "."
        path = download_with_ytdlp(source, out_dir,
                                   max_height=opts.get("max_height", "1080"),
                                   audio_only=opts.get("audio_only", False),
                                   cookies_from_browser=opts.get("cookies_browser"),
                                   cookies_file=cookies_file,
                                   proxy=opts.get("proxy"))
        print(path)
        return

    if looks_like_token(source):
        download_feishu(source, out_path)
        print(out_path)
        return

    print("无法识别的来源: %s" % source, file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
