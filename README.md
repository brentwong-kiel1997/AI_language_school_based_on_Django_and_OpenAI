# BALS — AI Language School

基于 **Django** 与任意 **OpenAI Compatible LLM** 的语言学习应用：粘贴带字幕的 YouTube 视频链接，自动生成词汇、语法、听力、表达与翻译等个性化课件。

目标语言示例：英语 / 德语 / 俄语；母语可选中文、英语、乌克兰语等（见 `bals/main_app/forms.py`）。

---

## 功能概览

- 从 YouTube **字幕**生成带时间戳的文稿（需视频自带字幕；无字幕会报错）
- LLM 并行生成多模块课件（目标 / 热身 / 词汇 / 语法 / 听力 / 表达 / 翻译）
- 账号体系：注册登录、我的课程、学习进度
- 课件导出：TXT / PDF；可下载视频到本地（登录后）
- 界面中英文切换（i18n）

视频时长上限：**15 分钟**。

应用侧 AI **只用到文本 LLM**（Chat Completions），不依赖图片 / 语音 / 视频等多模态接口。

---

## 环境要求

| 依赖 | 说明 |
|------|------|
| Python 3.9+ | 推荐 3.10+ |
| FFmpeg | 需在 `PATH` 中 |
| JS 运行时 | yt-dlp ≥ 2026 需要；macOS 可用 `brew install deno` |
| LLM API | 任意 OpenAI Compatible：`LLM_API_KEY` + `LLM_BASE_URL` + `LLM_MODEL` |

---

## 快速启动

在仓库根目录执行：

```bash
# 1. 虚拟环境（任选）
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 2. 安装 Django 依赖 + prompts 包
pip install -r bals/requirements.txt
pip install -e .

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，至少填入：
#   LLM_API_KEY=你的密钥
#   LLM_BASE_URL=https://api.minimaxi.com/v1   # 或其他 OpenAI Compatible 根路径
#   LLM_MODEL=MiniMax-M3
#   YOUTUBE_COOKIE_FILE=cookies/youtube.txt   # 推荐，见下文

# 4. 数据库
cd bals
python manage.py migrate
python manage.py createsuperuser   # 邮箱登录

# 5. 启动（需能 import 仓库根下的 prompts）
cd bals
PYTHONPATH="$(pwd)/.." python manage.py runserver 0.0.0.0:8000
```

浏览器打开：<http://127.0.0.1:8000/>

| 入口 | 地址 |
|------|------|
| 首页 / 课程库 | `/` |
| 登录 | `/accounts/login/` |
| 创建课程 | `/url_input`（需登录） |
| Django Admin | `/admin/` |

---

## LLM 配置（OpenAI Compatible）

课件生成请求：

`POST {LLM_BASE_URL}/chat/completions`

| 提供商 | `LLM_BASE_URL` 示例 | `LLM_MODEL` 示例 |
|--------|---------------------|------------------|
| MiniMax 国区 | `https://api.minimaxi.com/v1` | `MiniMax-M3` |
| MiniMax 国际 | `https://api.minimax.io/v1` | `MiniMax-M3` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| 本地 vLLM / Ollama 兼容层 | `http://127.0.0.1:8000/v1` | 你的模型名 |

`LLM_BASE_URL` 填到 **含 `/v1` 的根**，不要带 `/chat/completions`。  
旧的 `MINIMAX_*` 变量仍可作为回退读取，新部署请只用 `LLM_*`。

可选：`LLM_JSON_MODE=prompt|response_format|off`（默认 `prompt`，兼容性最好）。

独立的 MiniMax 多媒体 CLI 仍见 [`README_MINIMAX.md`](README_MINIMAX.md)，**与 Django 课件主路径无关**。

---

## YouTube Cookie（强烈建议）

YouTube 常拦截自动化访问。推荐用 **cookie 文件**（服务器友好，不会弹出系统钥匙串密码）：

```bash
cd bals
PYTHONPATH="$(pwd)/.." python manage.py youtube_cookies export --from-browser chrome cookies.txt
PYTHONPATH="$(pwd)/.." python manage.py youtube_cookies install cookies.txt
PYTHONPATH="$(pwd)/.." python manage.py youtube_cookies check
```

```bash
YOUTUBE_COOKIE_FILE=cookies/youtube.txt
```

仅本地调试可选用 `YOUTUBE_COOKIES_FROM_BROWSER=chrome`（可能弹密码、不适合无头服务器）。Cookie 目录已 gitignore。

---

## 常用配置（`.env`）

完整示例见 [`.env.example`](.env.example)。

| 变量 | 用途 |
|------|------|
| `LLM_API_KEY` | 课件生成（必填） |
| `LLM_BASE_URL` | OpenAI Compatible 根，默认 MiniMax 国区 `/v1` |
| `LLM_MODEL` | 模型 ID |
| `LLM_CONTEXT_WINDOW_TOKENS` | 输入上下文，默认 `1000000`；用于计算送进模型的字幕长度 |
| `LLM_MAX_TOKENS` | 输出上限，默认 `131072`（拉满） |
| `LLM_MODULE_WORKERS` | 模块并行数，默认 `6` |
| `LLM_WORDS_BATCHES` | 词汇分批并行，默认 `2` |
| `YOUTUBE_COOKIE_FILE` | Netscape cookie 路径 |
| `DJANGO_SECRET_KEY` | 生产环境务必覆盖 |
| `DJANGO_DEBUG` | `True` / `False` |
| `DJANGO_ALLOWED_HOSTS` | 逗号分隔 |

---

## 测试

```bash
cd bals
PYTHONPATH="$(pwd)/.." python manage.py test main_app accounts -v1
# 可选：独立 MiniMax CLI 包
cd .. && python -m unittest tests.test_minimax_cli -v
```

---

## 项目结构（简要）

```
├── bals/                 # Django 项目
│   ├── main_app/         # 课件流水线、OpenAI Compatible LLM、yt-dlp
│   ├── accounts/         # 用户与进度
│   └── manage.py
├── prompts/              # 分语言课件提示词
├── minimax_cli/          # 可选：MiniMax 多媒体 CLI（mmx），非 Django 必需
├── .env.example
├── README_MINIMAX.md
└── README_ARK.md         # 可选火山方舟 CLI
```

核心逻辑：`bals/main_app/utils.py`（字幕 / LLM 生成）、`bals/main_app/views.py`。

---

## 使用说明

1. 注册并登录 → **创建课程** → 粘贴带字幕的 YouTube URL（≤ 15 分钟）
2. 等待转写完成后选择母语 → 生成课件
3. 也可从首页课程库打开已有课件

**注意**

- 下载依赖 [yt-dlp](https://github.com/yt-dlp/yt-dlp)；失败时请升级 yt-dlp 并刷新 cookie
- 课件生成需要有效的 `LLM_API_KEY` 与可访问的 `LLM_BASE_URL`

---

## 免责声明

**请勿传播用本项目下载的 YouTube 视频文件。**

分享学习材料时请使用 **YouTube 链接** 或官方嵌入，确保创作者获得播放收益。生成内容按学习 **评注 / 练习材料** 使用。

---

## 许可

见仓库内许可证文件（若有）；工具包子包说明见 `pyproject.toml`。
