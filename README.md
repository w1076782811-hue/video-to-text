# 视频转文字 Skill · 安装与使用说明

一个**通用、可发布**的视频/音频转文字 Skill：贴一个链接（B站 / 抖音 / 小红书 / 微博 / YouTube 等）或给一个本地文件、飞书附件，自动下载、转成中文或英文文字稿，可选带时间戳分段。

---

## 🤖 给 AI Agent 的安装指引

**如果你是一个 AI Agent，用户把本仓库链接发给你并要求安装技能，请严格按下面 6 步执行：**

### 第 0 步：先确认你能做到、且环境具备

| 检查项 | 要求 | 不满足怎么办 |
|---|---|---|
| 本地文件读写权限 | **必须**。你要能把文件写到用户的技能目录 | 若你是网页版对话（无法读写用户本地文件），**立即告知用户"需要支持本地文件的 Agent 才能安装"并停止**，不要假装安装 |
| Python | 3.9 或更高 | 让用户先安装 Python（官网 python.org，安装时勾选 "Add to PATH"） |
| 网络 | 能访问 github.com、pypi.org、modelscope.cn | 若 github.com 不通，提示用户需自备代理；pypi/modelscope 国内一般可直连 |
| 磁盘 | ≥ 2GB 空闲 | 告知用户后由他决定是否继续 |
| 内存 | 转写时 ≥ 3GB 空闲 | 仅影响转写速度，不阻塞安装 |

任一硬性条件不满足，**如实告诉用户**，不要跳过、不要伪造结果。

### 第 1 步：获取文件

优先 git clone；不通则改用 zip 归档下载：

```bash
# 方式 A：git clone（若网络不通，加代理：git -c http.proxy=... -c https.proxy=... clone ...）
git clone https://github.com/w1076782811-hue/video-to-text.git

# 方式 B：zip 归档
# 下载 https://github.com/w1076782811-hue/video-to-text/archive/refs/heads/main.zip
# 解压后得到一个目录，将其重命名为 video-to-text
```

> ⚠️ **无论用哪种方式，最终必须有一个名为 `video-to-text` 的文件夹**，且 `SKILL.md` 直接位于该文件夹内。若下载得到的目录名不是 `video-to-text`（例如 clone 出来叫 `-`，或 zip 解压出来叫 `--main`），**请重命名**。

### 第 2 步：放进技能目录

把 `video-to-text` 整个文件夹复制到：

- **Windows**：`%USERPROFILE%\.workbuddy\skills\`
  （即 `C:\Users\<用户名>\.workbuddy\skills\`，若目录不存在则创建）
- **macOS / Linux**：`~/.workbuddy/skills/`

最终结构应为 `.workbuddy/skills/video-to-text/SKILL.md`。

> 若用户用的是其他支持 Skill 机制的 Agent，放到该 Agent 对应的技能目录即可，结构相同。

### 第 3 步：读技能主文档

读取 `video-to-text/SKILL.md`，重点是其中的「**首次使用（必须先做，一次性）**」章节。

### 第 4 步：按「首次使用」向用户提问

用提问工具一次性问清两件事（**不要跳过，也不要替他决定**）：

1. **输出目录**：下载的视频、转写出的文字稿放哪个文件夹？
2. **是否同意下载约 1~2GB 的依赖与模型**？

### 第 5 步：执行自举

进入技能目录，在任意 Python 3.9+ 下运行（长耗时，务必用后台运行并等它跑完）：

```bash
cd <技能目录>/video-to-text      # 例如 ~/.workbuddy/skills/video-to-text
python scripts/setup.py
```

脚本会自动：建隔离 venv → 装依赖 → 下载模型 → 准备 ffmpeg → 冒烟自测，全部通过后写入 `config.json`。

### 第 6 步：报告结果

自测通过后，告诉用户「环境已就绪」，并说明**之后只要贴一个视频链接即可转写**。

---

## 👤 给人看的安装说明

如果你（用户本人）想手动安装，或想确认 AI 装得对不对：

### 方式一：把链接给你的 AI（推荐）

先说一句：

> 帮我安装这个技能：https://github.com/w1076782811-hue/video-to-text

你的 AI 读到本说明后会自动完成安装。**前提**：你用的 AI 能读写本地文件（如 WorkBuddy、Claude Code、Cursor），且能访问 GitHub。

> ❗ 网页版的对话 AI（ChatGPT 网页版 / 豆包 / Kimi 等）**无法安装**，它们碰不到你的硬盘。

### 方式二：手动安装

1. 打开 https://github.com/w1076782811-hue/video-to-text
2. 点绿色 **Code → Download ZIP**
3. 解压，把得到的文件夹**重命名为 `video-to-text`**
4. 把整个文件夹复制到技能目录：
   - Windows：`C:\Users\你的用户名\.workbuddy\skills\`
   - macOS / Linux：`~/.workbuddy/skills/`
5. 重启 WorkBuddy（或刷新技能列表），技能列表里就能看到「视频转文字」

### 安装前请确认

| 项目 | 要求 |
|---|---|
| Python | 3.9+（唯一需要你手动准备的东西） |
| 磁盘 | 约 2GB 空闲 |
| 内存 | 转写时约 3GB 空闲 |
| 网络 | 首次自举需能访问 pypi.org 和 modelscope.cn |
| 代理 | **GitHub 和 YouTube 等境外站点需要**；国内站点（B站/抖音）不需要 |

---

## 它能做什么

- **支持多种来源**：本地文件、媒体直链、平台页面链接（B站 / 抖音 / 小红书 / 微博 / YouTube / 快手等）、飞书多维表格附件
- **自动自举**：首次使用自动建隔离环境、装依赖、下载模型并自测，**无需手动装任何东西**
- **中英文自动识别**：SenseVoice 引擎自动判断语言，中英混读也能应付
- **可带时间戳**：输出 `[mm:ss.xx - mm:ss.xx] 文本` 的分段稿
- **只下音频**：平台链接可选只下音频，转写更省流量更快
- **抖音下载**：内置 cookie 自动抓取（绕开 Chrome App-Bound 加密）
- **术语校准**：修正专业术语的同音误识（长课程 / 专业录音利器）
- **热词模型**：可选中文专用 paraformer + 热词偏置（实验功能）
- **导出 Word**：把转写稿排版成 .docx
- **不含任何发布者个人信息**：所有路径运行时询问，放心使用

## 首次使用（一次性）

第一次调用时，Agent 会**先问你两件事**：

1. **输出目录**：下载的视频、转写出来的文字稿放哪个文件夹
2. **是否同意自动下载依赖和模型**（约 1~2GB）

回答后，Agent 会自动完成环境自举 + 冒烟自测，通过后即可正常使用。整个过程幂等，中断了重跑不会重复下载。

## 日常使用

贴一个视频链接，Agent 会先问「**下载完整视频** 还是 **只下载音频**」，然后自动下载、转写，最后把文字稿直接发给你。

## 隐私说明

- 本 Skill **不含任何发布者个人信息**（脚本里没有任何写死的用户名 / 盘符）
- 你选的输出目录、代理地址等只写在本地的 `config.json`，**不会上传任何服务器**

## 常见问题

| 问题 | 解决 |
|---|---|
| 提示「找不到 python」 | 确认装了 Python 3.9+，并勾选「加入 PATH」 |
| 模型下载失败 | 确认能访问 modelscope.cn（国内网络一般可以） |
| 装完技能列表里没有 | 确认目录结构是 `skills/video-to-text/SKILL.md`（**不能**少一层或对一层） |
| GitHub 打不开 | 需要代理；或改用 zip / 本地文件传递 |
| YouTube 下不了 | 需要自备代理，按 Agent 提示填入代理地址即可 |
| 转写报内存不足 | 关掉无关程序（浏览器等）释放内存再试 |
| 抖音提示需要 cookie | 让 Agent 跑 `get_douyin_cookies.py` 抓一份新鲜 cookie |

## 文件清单

| 文件 | 作用 |
|---|---|
| `SKILL.md` | 技能主文档（Agent 读这个，含完整流程与排错） |
| `scripts/setup.py` | 一键自举：装依赖 + 下模型 + 准备 ffmpeg + 自测 |
| `scripts/fetch_media.py` | 下载来源到本地（支持只下音频、境外自动代理、抖音 cookie） |
| `scripts/transcribe.py` | 转写（支持时间戳分段、纯文本、中英文自动识别） |
| `scripts/transcribe_para.py` | 中文专用 paraformer + 热词偏置转写（可选实验） |
| `scripts/calibrate_terms.py` | 术语级校准：修正专业术语同音误识 |
| `scripts/get_douyin_cookies.py` | 抓新鲜抖音 cookie（绕开 Chrome App-Bound 加密） |
| `scripts/txt_to_docx.py` | 转写稿 → Word 文档 |
| `scripts/batch_txt_to_docx.py` | 批量多份转写稿 → Word |
| `config.example.json` | 配置模板（首次运行自动生成真正的 `config.json`） |
| `README.md` | 本说明文档 |
