# -*- coding: utf-8 -*-
r"""术语级校准：把 SenseVoice 的同音误识改为课程语境下唯一可确定的正确写法。

原则：
  - 只改「能确定的」——误识形态在课程语境下无其他合理解释（如 SMT→SFT、IM→RM）。
  - 不改语序、不删口语、不合并断句，正文仍为逐字转写。
  - 拿不准的一律不动，只登记进《对照表》的「待人工确认」区。
输出：
  <outdir>/<原文件名>-校正版.txt
  <outdir>/误识校准对照表.md

用法:
    <通用 python> calibrate_terms.py --src <文字稿目录> [--out <校正版目录>]
    <通用 python> calibrate_terms.py --src <文字稿目录> --scan     # 只扫描，不改文件

  --scan 是「第 1 步：机械扫描」：先把现有 RULES 在内存里套一遍，再对结果做英文串
  词频统计，列出白名单之外的可疑串（含首次出现的行），用来发现新误识、增量补规则。
  它不写任何文件。

  ⚠️ RULES / PENDING 是**按批次维护**的：换一门课 / 换一个领域，第 1–3 步必须重做，
  规则表不能直接搬。可复用的是「流程」，不是「知识」。
"""
import io
import os
import re
import glob
import sys
import collections

def _parse_args(argv):
    src, out, scan = None, None, False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--src" and i + 1 < len(argv):
            i += 1
            src = argv[i]
        elif a == "--out" and i + 1 < len(argv):
            i += 1
            out = argv[i]
        elif a == "--scan":
            scan = True
        i += 1
    if not src:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    src = os.path.abspath(src)
    out = os.path.abspath(out) if out else os.path.join(src, "校正版")
    return src, out, scan


# 扫描用的已知正确词汇白名单（避免每次把正确的词再报一遍）。
# 只在 --scan 里起作用，**不影响替换**。
WHITELIST = set("""
OK ok AI PE SFT RM RL RLHF RLVR PPO DPO RAG LLM GPT Transformer Token token
query key value attention self reward response answer model training pre post
embedding prompt engineer base system ID top IDD QQV QKV XYZ EXCEL WORD EXCEL
PPT APP PS PC IP UI CEO KPI VS NO YES ALL FROM FOR IS YOU NEED BY FINE SUPER
GROUND CHILDREN GEN ZERO HTML PDF PART ONE CASE EXCEL JAVA CLOUD SAAS API
""".split())

H = "高"   # 高置信：上下文唯一可确定
M = "中"   # 中置信：极可能，但存在其他解读

# ============================================================================
# 术语校准规则表 —— 使用前请按你的领域重写
# ============================================================================
# RULES 每条是 (序号, 规则类型, 匹配, 替换, 置信度, 依据) 六元组：
#   · 规则类型 "lit" = 字面量替换（str.replace）；"re" = 正则替换（re.sub）
#   · 置信度 H(高)/M(中)；依据 = 为什么这么改（"同稿自证"是最可靠依据）
#
# 怎么填（三步法，详见 SKILL.md「术语校准」章节）：
#   1. 先 --scan 机械扫描，统计英文串词频，找白名单之外的可疑串
#   2. 可疑项逐个 grep 上下文定性——定性靠「同稿自证」：说话人自己解释过的原话
#      就是最好的词典（如「它可以叫 RAG」→ 把 RNG/RNRT 等都归到 RAG）
#   3. 把结论写成 RULES 批量跑，可复现、可留痕、可增量补规则
#
# 同音替换防误伤要点（重要）：
#   · 英文缩写一定加边界： (?<![A-Za-z])XXX(?![A-Za-z])
#   · 同族规则「长的排前面」；有包含关系的规则排对顺序
#   · Python re 不支持变长后顾（(?<![A-Za-z](?:I)?) 会直接报错）
#
# 下面给两条示例（注意这是占位示例，不是真实规则，请替换成你自己的）：
RULES = [
    # 示例：把同音误识的英文缩写归位（"lit" 字面量）
    # ("SFT", "lit", "SMT", "SFT", H, "监督微调 Supervised Fine-Tuning 的同音误识"),
    # 示例：正则 + 边界（"re" 正则）
    # ("token", "re", r"(?<![A-Za-z])tokken(?![A-Za-z])", "token", H, "token 的同音误识"),
    # 示例：重复词合并（放在 RULES 末尾，能看到前面刚替换出的结果）
    # ("重复合并", "re", r"agent(?:agent)+", "agent agent", H, "说话人重复该词，补空格还原"),
]

# 待人工确认（不改，仅登记进对照表文末）
# 每条是 (出处/时间戳, 原文, 说明) 三元组
PENDING = [
    # ("① 02:19", "预须", "疑「预训练」，未定"),
]

TS = re.compile(r"^\[(\d{2,3}:\d\d\.\d\d)\s*-\s*(\d{2,3}:\d\d\.\d\d)\]\s*(.*)$")


def apply_rules(lines):
    """逐行套规则，返回 (新行列表, 命中记录)。"""
    hits = collections.defaultdict(list)   # 规则名 -> [(时间戳, 改前, 改后)]
    out = []
    for ln in lines:
        m = TS.match(ln.strip())
        ts, body = (m.group(1), m.group(3)) if m else ("", ln)
        new = body
        for name, kind, pat, repl, conf, why in RULES:
            if kind == "lit":
                if pat in new:
                    before = new
                    new = new.replace(pat, repl)
                    if new != before:
                        hits[name].append((ts, before, new))
            else:
                if re.search(pat, new):
                    before = new
                    new = re.sub(pat, repl, new)
                    if new != before:
                        hits[name].append((ts, before, new))
        if new != body:
            if ts:
                out.append(f"[{ts} - {m.group(2)}] {new}")
            else:
                out.append(new)
        else:
            out.append(ln)
    return out, hits


def scan(src_dir):
    """第 1 步：先套现有规则，再对结果做英文串词频统计，列出白名单之外的可疑串。不写文件。"""
    toks = collections.Counter()
    first = {}
    nfiles = 0
    for p in sorted(glob.glob(os.path.join(src_dir, "*.txt"))):
        nfiles += 1
        raw = io.open(p, encoding="utf-8").read().splitlines()
        new, _ = apply_rules(raw)
        for ln in new:
            for t in re.findall(r"[A-Za-z][A-Za-z0-9\-\.]{1,}", ln):
                toks[t] += 1
                first.setdefault(t, (os.path.basename(p), ln.strip()[:160]))
    print(f"扫描 {nfiles} 个文件（已套现有规则），白名单之外的可疑英文串：")
    n = 0
    for t, c in toks.most_common():
        if t in WHITELIST:
            continue
        n += 1
        f, ctx = first[t]
        print(f"  {t:20s} x{c:<4d} {f[:12]} | {ctx}")
    print(f"合计 {n} 个可疑串（含闲聊噪音，需逐个 grep 上下文定性）")


def main():
    src_dir, out_dir, do_scan = _parse_args(sys.argv[1:])
    if do_scan:
        scan(src_dir)
        return
    os.makedirs(out_dir, exist_ok=True)
    allhits = collections.defaultdict(list)
    summary = []
    srcs = sorted(glob.glob(os.path.join(src_dir, "*.txt")))
    marks = "①②③④⑤⑥⑦⑧⑨"
    short = {os.path.basename(p): (marks[i] if i < len(marks) else os.path.basename(p))
             for i, p in enumerate(srcs)}
    for p in srcs:
        base = os.path.basename(p)
        raw = io.open(p, encoding="utf-8").read().splitlines()
        new, hits = apply_rules(raw)
        io.open(os.path.join(out_dir, base.replace(".txt", "-校正版.txt")), "w",
                encoding="utf-8").write("\n".join(new) + "\n")
        n = sum(len(v) for v in hits.values())
        summary.append((base, n))
        print(f"{base}: 命中 {n} 处，涉及 {len(hits)} 类规则")
        for k, v in hits.items():
            allhits[k].extend([(base,) + x for x in v])

    # ---- 生成对照表 ----
    L = ["# 转写稿 · 误识校准对照表", "",
         "> 校准范围：**仅专业术语与专有名词的同音误识**。不改语序、不删口语、不合并断句，正文仍为逐字转写。",
         "> 判定依据：课程本身的术语体系与上下文（可唯一确定的才改）；拿不准的一律不动，列入文末「待人工确认」。",
         "> 置信度：**高** = 上下文唯一可确定；**中** = 极可能但存在其他解读（已改，建议抽听核对）。", "",
         "## 一、改动汇总", "",
         "| 规则 | 校正为 | 置信度 | 命中次数 | 覆盖文件 |", "|---|---|---|---|---|"]
    for name, kind, pat, repl, conf, why in RULES:
        v = allhits.get(name)
        if not v:
            continue
        files = sorted({short.get(f, os.path.basename(f)) for f, *_ in v})
        L.append(f"| {name} | `{repl}` | {conf} | {len(v)} | {'、'.join(files)} |")
    L += ["", "## 二、逐条改动明细", ""]
    for name, kind, pat, repl, conf, why in RULES:
        v = allhits.get(name)
        if not v:
            continue
        L += [f"### {name} → `{repl}`　（{conf}置信｜依据：{why}）", "",
              "| 出处 | 时间戳 | 改前 | 改后 |", "|---|---|---|---|"]
        for f, ts, before, after in v:
            b = before.replace("|", "｜")[:150]
            a = after.replace("|", "｜")[:150]
            L.append(f"| {short.get(f, os.path.basename(f))} | {ts} | {b} | {a} |")
        L.append("")
    L += ["## 三、待人工确认（未改动，原样保留）", "",
          "以下位置本机无法可靠判定，**保留了引擎原文**，建议对着录音原声听一遍再定：", "",
          "| 出处 | 原文 | 说明 |", "|---|---|---|"]
    for loc, txt, note in PENDING:
        L.append(f"| {loc} | {txt} | {note} |")
    L += ["", "## 四、遗留说明", "",
          "- 本表只覆盖**专业术语层**。学员闲聊、方言口音、拉远的说话声造成的整句乱码（尤其录音①后半段与各段的课间对话）**未做处理**——那类内容无法在不听原声的前提下还原，强行改写等同编造。",
          "- 校正只动「词」，不动「句」。若需要通顺可读的书面稿，属于另一档工作（会失去逐字转写的保真性），需另行确认。", ""]
    io.open(os.path.join(out_dir, "误识校准对照表.md"), "w", encoding="utf-8").write("\n".join(L))
    print("\n合计命中：", sum(n for _, n in summary))


if __name__ == "__main__":
    main()
