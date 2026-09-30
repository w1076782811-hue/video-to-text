#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
用「独立临时配置的无头 Chrome + DevTools 协议」抓取指定站点的 cookie，
写成 Netscape 格式的 cookies.txt，供 yt-dlp 使用。

为什么需要这个脚本（而不是 yt-dlp 自带的 --cookies-from-browser）？
  · Chrome 127+ 起启用了 App-Bound Encryption：cookie 用 v20 前缀加密，
    密钥绑在 Chrome 进程上，任何外部程序（含 yt-dlp）都解不开；
  · 且 Chrome 运行时会独占锁定 Cookies 数据库，连复制都失败
    （报 "Could not copy Chrome cookie database"）。
  · 本脚本让 Chrome **自己去读** cookie（浏览器内部解密），再通过 CDP 的
    Storage.getCookies 把明文吐出来 —— 完全不碰用户日常使用的那个 Chrome 配置，
    也不需要 App-Bound 绕过/注入这类高风险操作。

用法:
  get_douyin_cookies.py [--out <cookies.txt>] [--start-url <URL>] [--nav <URL>]
                        [--browser chrome|edge] [--port 9333] [--headed]

  · 默认抓抖音（start-url = https://www.douyin.com/），输出到 config.json 的
    douyin_cookies（或环境变量 VTT_DOUYIN_COOKIES），否则默认 <skill>/cookies_douyin.txt
  · --nav 可以再导航一次到具体视频页，让平台把完整 cookie 集下发全。
  · 默认无头；若平台识别无头导致 cookie 不全，加 --headed 会弹出一个临时窗口。

依赖: websocket-client（自举时已随 funasr 环境安装）
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent


def _load_cfg():
    cfg = {}
    p = SKILL_DIR / "config.json"
    if p.exists():
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    return cfg


_CFG = _load_cfg()

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    r"/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    r"/usr/bin/google-chrome",
    r"/usr/bin/chromium-browser",
    r"/usr/bin/chromium",
]

DEFAULT_OUT = os.environ.get("VTT_DOUYIN_COOKIES", _CFG.get("douyin_cookies", "")) \
    or str(SKILL_DIR / "cookies_douyin.txt")
DEFAULT_START = "https://www.douyin.com/"
PROFILE_DIR = str(SKILL_DIR / "runtime" / "_chrome_cookie_tmp")
CHROME_LOG = str(SKILL_DIR / "runtime" / "_chrome_cookie_log.txt")

import websocket  # noqa: E402  (websocket-client)


def find_browser(prefer: str = None):
    if prefer:
        low = prefer.lower()
        for p in CHROME_CANDIDATES:
            if low in p.lower() and os.path.exists(p):
                return p
    for p in CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    raise RuntimeError("找不到 Chrome/Edge，请用 --browser 指定，或手动准备 cookies.txt")


def wait_devtools(port: int, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % port, timeout=2) as r:
                return json.load(r)
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("Chrome DevTools 端口未就绪（%d）" % port)


def jget(port: int, path: str):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=5) as r:
        return json.load(r)


class CDP:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=40)
        self.n = 0

    def call(self, method, params=None):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError("%s -> %s" % (method, msg["error"]))
                return msg.get("result", {})

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def main():
    a = sys.argv[1:]
    out = DEFAULT_OUT
    start = DEFAULT_START
    navs = []
    browser = None
    port = 9333
    headed = False
    i = 0
    while i < len(a):
        k = a[i]
        if k == "--out" and i + 1 < len(a):
            out = a[i + 1]; i += 2; continue
        if k == "--start-url" and i + 1 < len(a):
            start = a[i + 1]; i += 2; continue
        if k == "--nav" and i + 1 < len(a):
            navs.append(a[i + 1]); i += 2; continue
        if k == "--browser" and i + 1 < len(a):
            browser = a[i + 1]; i += 2; continue
        if k == "--port" and i + 1 < len(a):
            port = int(a[i + 1]); i += 2; continue
        if k == "--headed":
            headed = True; i += 1; continue
        i += 1

    exe = find_browser(browser)
    print("浏览器: %s" % exe)

    shutil.rmtree(PROFILE_DIR, ignore_errors=True)
    os.makedirs(PROFILE_DIR, exist_ok=True)

    cmd = [exe, "--remote-debugging-port=%d" % port,
           "--remote-allow-origins=*",
           "--user-data-dir=" + PROFILE_DIR,
           "--no-first-run", "--no-default-browser-check",
           "--disable-gpu", "--window-size=1280,900"]
    if not headed:
        cmd.append("--headless=new")
    cmd.append(start)          # 注意：无头模式只接受一个 URL 参数，多给会直接退出

    print("启动浏览器（%s）…" % ("headed" if headed else "headless"))
    log = open(CHROME_LOG, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)

    try:
        ver = wait_devtools(port)
        print("DevTools OK:", ver.get("Browser"))
        time.sleep(7)          # 等首页把 ttwid / msToken 等下发

        pages = [t for t in jget(port, "/json/list") if t.get("type") == "page"]
        if pages:
            page = CDP(pages[0]["webSocketDebuggerUrl"])
            for u in navs:
                try:
                    page.call("Page.navigate", {"url": u})
                    print("已导航:", u)
                except Exception as e:
                    print("导航失败:", e)
                time.sleep(8)
            page.close()

        bcdp = CDP(ver["webSocketDebuggerUrl"])
        cookies = bcdp.call("Storage.getCookies").get("cookies", [])
        bcdp.close()

        # 只保留与 start-url 同域的 cookie（抖音还会下发 .bytedance.com 等）
        root = start.split("//")[-1].split("/")[0].lower()
        base = ".".join(root.split(".")[-2:]) if root.count(".") >= 1 else root
        same = [c for c in cookies if base in (c.get("domain") or "").lower()
                or "bytedance" in (c.get("domain") or "").lower()]
        print("全部 cookie: %d  同域: %d" % (len(cookies), len(same)))
        print("cookie 名:", sorted({c["name"] for c in same if c["name"]}))

        if not same:
            print("!! 没抓到 cookie，可能被无头识别拦了。试试加 --headed 重跑。", file=sys.stderr)

        os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
        lines = ["# Netscape HTTP Cookie File",
                 "# generated by get_douyin_cookies.py via CDP (fresh headless browser)",
                 ""]
        for c in same:
            if not c.get("name"):
                continue
            dom = c["domain"]
            flag = "TRUE" if dom.startswith(".") else "FALSE"
            secure = "TRUE" if c.get("secure") else "FALSE"
            exp = int(c.get("expires") or 0)
            if exp <= 0:
                exp = int(time.time()) + 86400 * 180
            lines.append("\t".join([dom, flag, c.get("path") or "/", secure, str(exp),
                                    c["name"], c.get("value", "")]))
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
        print("已写出: %s (%d bytes, %d 条)" % (out, os.path.getsize(out), len(same)))
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        time.sleep(1)
        shutil.rmtree(PROFILE_DIR, ignore_errors=True)
        print("临时浏览器配置已清理")


if __name__ == "__main__":
    main()
