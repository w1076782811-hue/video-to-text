---
name: 视频转文字
description: 将视频或音频（本地文件 / 直链 / B站·抖音·小红书·微博·YouTube等平台页面链接 / 飞书多维表格附件）里的说话内容识别成中文或英文文字稿，可带时间戳分段。当用户说"识别这个附件""把这段视频转成文字""转写录屏""这个链接的视频转文字""视频转文字稿""extract audio text""transcribe""audio/video to text"时使用。这是一个通用、可发布的技能：不含任何发布者个人信息，首次导入会自动完成环境自举（建隔离环境、装依赖、下载模型并自测），下载视频与转写稿的存放路径在首次使用时询问用户。
agent_created: true
version: 1.5.0
---

# 视频转文字（通用版，可发布、可自举）

把任意视频/音频里的说话内容，转写成中文或英文文字稿。引擎用 FunASR(SenseVoice)，纯 CPU 运行，能自动识别中英文，无需 GPU。

本技能**不包含任何发布者个人信息**：所有路径都在首次使用时动态询问用户或写入 `config.json`，脚本里没有任何写死的用户名/盘符。

## 能力一览

- **多来源**：本地文件 / 媒体直链 / 平台页面链接（B站·抖音·小红书·微博·YouTube·快手等）/ 飞书多维表格附件
- **中英文自动识别**：SenseVoice 自动判断语言，中英混读也能应付
- **可带时间戳**：输出 `[mm:ss.xx - mm:ss.xx] 文本` 的分段稿
- **只下音频**：平台链接可选只下音频，转写更省流量更快
- **抖音下载**：内置 cookie 自动抓取（绕开 Chrome App-Bound 加密）
- **术语校准**：`calibrate_terms.py` 修正专业术语的同音误识
- **热词模型**：`transcribe_para.py` 用中文专用 paraformer + 热词偏置（可选实验）
- **导出 Word**：`txt_to_docx.py` 把转写稿排版成 .docx

## 首次使用（必须先做，一次性）

首次被调用时，本技能目录下还没有 `config.json`（或 `config.json` 里的 `python` 为空）。此时按下面顺序执行：

### 1) 先问用户两件事
用提问工具（AskUserQuestion）一次性问清楚：

1. **输出目录**：下载的视频、转写出来的文字稿放在哪个根目录？（给几个默认候选，如「我的文档/视频转文字输出」「桌面/视频转文字输出」，同时允许用户自己填一个绝对路径）
2. **是否同意自动下载依赖与模型**：首次自举要下载约 1~2 GB（torch + funasr + SenseVoice 模型等），询问用户是否同意、以及是否愿意装到某个盘（磁盘紧张时可指定）。

### 2) 写入 config.json
把用户选的输出目录写进 `config.json` 的 `media_dir` 字段（保持 `ensure_ascii=False`，UTF-8）。其余字段由 `setup.py` 自动生成。

### 3) 跑自举 + 首次自测
在「任意一个 python3（>=3.9）」下运行（先用 `python --version` 或 `python3 --version` 探测哪个可用）：
```bash
python scripts/setup.py
```
脚本会自动：建隔离 venv → 装依赖（torch CPU / funasr / modelscope / imageio-ffmpeg / yt-dlp / websocket-client）→ 下载模型（SenseVoiceSmall + fsmn-vad）→ 准备 ffmpeg → 冒烟自测（加载模型转写一段静音）。全部通过后写入 `config.json`，并打印「自举完成」。

> 自举耗时取决于网速，一般几分钟到十几分钟。**务必等它跑完**（用后台运行 `run_in_background`，完成后读输出确认出现「冒烟自测通过」）。
> 自举是幂等的，中断后重跑会自动跳过已完成的步骤。

### 4) 自测通过后
向用户报告「环境已就绪」，并说明之后只需「贴链接」即可转写。

## 标准转写流程（每次）

### 第 0 步：确认环境
读 `config.json`，确认 `python` / `models_cache_dir` 字段已存在。若为空，回到「首次使用」。

### 第 1 步：用户给出链接后，先问「下视频还是只下音频」
用户贴来平台链接（B站/抖音/YouTube…）时，用提问工具问用户：
- **下载完整视频**（保留视频文件，适合还要看画面/剪素材）
- **只下载音频**（转写用，更省流量、更省空间、更快）

> 本地文件、直链、飞书附件等来源不需要问，直接转写。

### 第 2 步：落地本地文件
用 `fetch_media.py`（任意 python 即可，脚本内部会调用 config.json 里那个 venv python 跑 yt-dlp）：
```bash
python scripts/fetch_media.py "<来源>" "<输出目录>" [--audio-only] [--max-height 1080] [--proxy http://127.0.0.1:7890]
```
- `<输出目录>` 用 `config.json` 里的 `media_dir`。
- 贴的是平台链接、且用户选了「只下音频」→ 加 `--audio-only`。
- **stdout 会打印真实落地路径**，把那一行喂给第 3 步。
- 支持的来源：本地路径 / 直链 / 平台页面链接（B站·抖音·小红书·微博·YouTube·快手等）。
- **YouTube 等境外站点必须走代理**：`fetch_media.py` 会自动用 `config.json` 的 `proxy`（或 `--proxy` 指定、或环境变量 `VTT_PROXY`）。若用户没有代理，如实告知 YouTube 下不了，国内站点（B站/抖音）不受影响。

### 第 3 步：转写
```bash
python scripts/transcribe.py "<落地路径>" [--timestamps]
```
- stdout 就是纯文字稿（日志在 stderr）。**务必把 stdout 重定向到文件再读**，长稿会被命令回显截断：
  ```bash
  python scripts/transcribe.py "<路径>" --timestamps > "<media_dir>/转写稿.txt" 2>"<media_dir>/转写.log"
  ```
- 加 `--timestamps` 得到 `[mm:ss.xx - mm:ss.xx] 文本` 的分段稿；不加则是一整段纯文本。
- 长视频（>5 分钟）用后台运行，完成后读文件。

### 第 4 步：清理临时文件
转写完成、拿到文字稿后，**删除本次下载的临时媒体**（尤其是「只下音频」场景的音频文件、以及转写过程产生的临时 log）。若用户选了「下载完整视频」并想保留视频，则保留视频文件、只删临时 log。**不要删用户自己原本给过来的本地源文件。**

### 第 5 步：交付
- 默认在聊天窗口直接呈现文字稿正文；长稿附一句说明「来源 / 时长 / 是否含时间戳 / 共多少字」。
- 用户要 Word 时，用 `txt_to_docx.py`（见下方「导出 Word」）把转写稿原样（**不要改写**）排版成 .docx 交付。

## 抖音链接下载（cookie 是硬门槛）

**先说结论：`--cookies-from-browser chrome` 大概率失败，别浪费时间去试。** 原因：
1. Chrome 127+ 启用 **App-Bound Encryption**（cookie 用 v20 前缀加密、密钥绑在 Chrome 进程上，外部程序解不开）；
2. Chrome 运行时会独占锁定 cookie 数据库，连复制都失败。

**正确做法：跑 `get_douyin_cookies.py` 抓一份新鲜 cookie**
```bash
python scripts/get_douyin_cookies.py [--headed]
```
- **原理**：用独立临时配置启动一个无头 Chrome（默认端口 9333），先访问 `douyin.com` 让平台下发 cookie，再通过 CDP 的 `Storage.getCookies` 把明文 cookie 取出来——让浏览器自己解密，绕开 App-Bound 加密。写入 `config.json` 的 `douyin_cookies`（或环境变量 `VTT_DOUYIN_COOKIES`）。
- 全程不碰用户日常使用的 Chrome 配置，跑完自动删临时配置与进程。
- 之后 `fetch_media.py` 检测到 douyin 链接会**自动带上**这个 cookie 文件。
- 成功判据：cookie 名里应含 `ttwid`、`__ac_nonce`、`__ac_signature`、`s_v_web_id`、`odin_tt`、`passport_csrf_token`。
- 抓不到时：加 `--headed` 弹出真实窗口重跑；仍不行才需要用户手动扫码登录（**登录属用户操作，不要代做**）。
- **cookie 会过期**：报 `Fresh cookies needed` 就重跑一次该脚本。

## 术语校准（长课程 / 专业录音强烈建议做）

ASR 的同音误识**不是均匀分布的——它偏偏集中在专业术语上**。脚本：`scripts/calibrate_terms.py`。

**铁律**
- 只改「能确定的」：误识形态在该语境下**无其他合理解释**才动；拿不准的一律不改，只登记进《对照表》的「待人工确认」区。
- **不从音频以外凭空推断**。改「词」不改「句」——语序、口语、语气词、断句全部保留。
- 交付：`校正版/<原名>-校正版.txt` + `误识校准对照表.md`（逐条列出 时间戳 / 改前 / 改后 / 置信度 / 依据）。

**效率关键：先统计，再定性，最后批量跑**
1. `python scripts/calibrate_terms.py --src <文字稿目录> --scan` 先机械扫描，统计全稿英文串词频，列白名单之外的可疑串。
2. 可疑项逐个 grep 上下文再定性——**定性靠「同稿自证」**：说话人自己解释过的原话就是最好的词典。
3. 把结论写成 RULES 列表（脚本里有带注释的模板）批量跑，可复现、可留痕、可增量补规则。

**同音替换的防误伤**
- 英文缩写一定加边界：`(?<![A-Za-z])XXX(?![A-Za-z])`。
- 同族规则**长的排前面**；有包含关系的规则要排对顺序。
- Python `re` **不支持变长后顾**。

**收尾必做：连写自检**——逐条替换可能把重复词拼成连写词，跑完用黑名单扫一遍（脚本模板里有示例）。

## 导出 Word（长录音常用）

用户说「以文档形式发给我 / 出一份 Word」时，用 `scripts/txt_to_docx.py`（转写稿 → docx，一条命令跑完建文档 / 分片插入 / 补标题层级 / 保存）：
```bash
python scripts/txt_to_docx.py config.json
```
config.json 最小内容（`src` 指 transcribe.py `--timestamps` 的输出；相对路径按 config 所在目录解析）：
```json
{ "src": "raw_0920.txt",
  "out": "/绝对路径/xxx.docx",
  "title": "转写文字稿",
  "subtitle": "全程逐段文字稿",
  "source_note": "录音.m4a",
  "outline": [["00:00 - 07:56", "开场与答疑…"]] }
```
`outline` 是自己先速览全稿后写的「内容脉络」表格（可为 `[]`）。依赖 `tencent-local-office-edit` 技能，脚本会从环境变量 `EDS_SKILL` 或常见位置自动探测其目录。

> 注意：`create_doc` 之后文档不是马上可写，脚本里的 `wait_ready` 已处理；`doc_insert_html_content` 的参数名是 `html_text`；`<h1>` 不会自动套 Heading 样式，脚本已用 `doc_apply_named_style` 补齐。这些坑脚本都已处理好，不要手写调用。

## 可选升级：换中文专用模型 + 热词重转

`transcribe.py` 用 SenseVoiceSmall（多语言小模型）。术语密集的课程/会议可换中文专用且支持热词偏置的模型：
```bash
python scripts/transcribe_para.py --timestamps --hotword "SFT RM RLHF PPO DPO RAG Transformer token" "<音频>"
```
- 默认模型 `iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch`，自动挂 punc 模型补标点；首次运行下载约 1GB。
- ⚠️ **换模型前先验 ID**（无效 ID 会让 AutoModel 卡在下载重试）：`curl -s -o /dev/null -w "%{http_code}" https://www.modelscope.cn/api/v1/models/<ns>/<name>` → 必须 200。
- ⚠️ **`--no-punc` 会让带时间戳模式失效**（sentence_info 为空、输出 0 行但 exit code 还是 0）。要时间戳就必须带 punc 模型。
- **换模型属于实验**：先切 10–15 分钟做 A/B 再决定是否全量，用数据说话。实测中 paraformer 在远场多人噪音下会过度切分 + 复读幻觉，**默认继续用 SenseVoiceSmall**，只在近场单人、术语密集时才值得试。

## 飞书附件下载

- 飞书**多维表格附件**下载用专用命令 `lark-cli base +record-download-attachment --base-token <BT> --table-id <TID> --record-id <RID> --file-token <FT> --output <路径> --overwrite`。
- ⚠️ **不要用** `lark-cli drive +download` 下载多维表格附件（会 403，scope 限制）。
- lark-cli 路径通过 `config.json` 的 `lark_cli` 或环境变量 `LARK_CLI` 配置。
- 飞书相关能力需要用户已配置 lark-cli 并登录；未配置时如实告知用户。

## 输出目录结构
`config.json` 的 `media_dir` 下会累积：
- 下载的视频 / 音频文件（文件名 = 视频标题）
- `*-转写稿.txt`（带时间戳 / 纯文本）

## 环境变量（覆盖 config.json，换机/换盘时用）
- `VTT_RUNTIME_DIR`：隔离环境根目录（venv + models + bin），setup.py 读取
- `VTT_PYTHON`：venv 内 python 路径，fetch_media.py 读取
- `VTT_MODELS_CACHE`：模型缓存根目录，transcribe.py / transcribe_para.py 读取
- `VTT_BIN_DIR`：ffmpeg 目录，fetch_media.py / transcribe_para.py 读取
- `VTT_PROXY`：境外站点代理，fetch_media.py 读取
- `VTT_DOUYIN_COOKIES`：抖音 cookie 文件路径
- `LARK_CLI`：lark-cli 可执行路径
- `EDS_SKILL`：tencent-local-office-edit 技能目录，txt_to_docx.py 读取

## 排错
- **`找不到 python` / `找不到 yt-dlp 运行环境`** → 还没自举，先跑 `python scripts/setup.py`。
- **转写中文但期望英文**：SenseVoice 会自动判断语言，无需配置。
- **内存不足（段错误 / not enough memory）**：SenseVoice 模型约 900MB，加载+推理峰值需约 2.3GB 连续空闲内存。关掉无关程序再试；或换更小的 paraformer 模型（会丢数字规整）。
- **平台链接 `Unsupported URL`**：抖音分享链接形态多变，`fetch_media.py` 已内置归一化；若又冒出新形态，扩展 `normalize_url()`。
- **抖音报 `Fresh cookies needed`**：跑一次 `scripts/get_douyin_cookies.py`。
- **YouTube 报 `Unable to connect to proxy` / 超时**：没配代理。让用户提供一个可用代理端口，写进 `config.json` 的 `proxy`（或 `--proxy` 传入）。
- **`ffmpeg not found` / 合并失败**：setup.py 会自动准备 ffmpeg 到 `runtime/bin`；丢了就重跑 `setup.py`。
- **长稿被截断**：不要把转写 stdout 直接丢给工具回显，`> 文件` 落盘后读文件。
- **自举下载模型失败**：模型来自 ModelScope，需网络可达 modelscope.cn；不通则重试或换镜像。
- **抽样速览别用 `awk`/`cut`**：Git Bash 下会按 GBK 解码成乱码，改用 `PYTHONIOENCODING=utf-8` + Python 读写。
- **Windows 下脚本里写死盘符路径**：本技能所有路径都动态获取，请勿在脚本里硬编码任何 `C:\Users\...` 之类路径（会破坏「可发布、无个人信息」这一前提）。

## 发布 / 移植说明
- 整个 `video-to-text` 文件夹就是完整技能包，可直接打包成 zip 发给任何人，或放到 GitHub 仓库。
- 接收方的 Agent 拿到后，按「首次使用」章节自举即可，**无需手动安装任何东西**。
- **通过 GitHub 链接分享时**：接收方 Agent 需把仓库内容落到 `<技能目录>/video-to-text/`——**文件夹名必须是 `video-to-text`，且 `SKILL.md` 直接位于其中**。注意 `git clone` 出来的目录名是仓库名、zip 归档解压出来是 `<仓库名>-main`，二者通常都不符，**必须重命名**。仓库 `README.md` 顶部的「给 AI Agent 的安装指引」章节已写明完整步骤，可直接让接收方 Agent 照做。
- 接收方前置条件：① 一个**能读写本地文件**的 Agent（网页版对话 AI 无法安装）；② 任意 Python 3.9+；③ 能访问 github.com（国内常需代理）；④ 磁盘 ≥2GB 空闲。
- 境外站点（YouTube）下载另需代理，与安装无关。
- 飞书附件、抖音下载、Word 导出属于可选增强能力，需要相应环境（lark-cli / 浏览器 / tencent-local-office-edit 技能）才能启用；核心的「下载 + 转写」不依赖它们。
