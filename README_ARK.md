# Ark CLI

独立的火山方舟（Volcengine Ark）客户端与 `ark` 命令行。**当前 Django 主应用不再依赖本包**（课件走 `minimax_cli`，字幕走 YouTube captions）。本仓库保留本包供 Chat / Seed ASR 单独冒烟或二次集成。

## 安装

```bash
pip install -e .
# 若包未打进 pyproject，可用：PYTHONPATH=. python -m ark_cli ...
```

## 配置

键名可用环境变量或仓库根 / `bals/.env`（`setdefault`，不覆盖已有 OS 环境）：

| 变量 | 用途 |
|------|------|
| `ARK_API_KEY` | Chat + Seed ASR 鉴权 |
| `ARK_BASE_URL` | 默认 `https://ark.cn-beijing.volces.com/api/plan/v3` |
| `ARK_MODEL` | 默认 `doubao-seed-2.0-lite` |
| `ARK_TIMEOUT_SECONDS` | Chat HTTP 超时 |
| `ARK_MAX_TOKENS` | 默认输出上限 |
| `SEED_ASR_*` | WebSocket URL / resource / segment / timeout |

## CLI

```bash
ark config show
ark chat --message "返回 JSON：{\"ok\": true}"
ark asr transcribe --wav ./audio.wav --language ru-RU
```

## Python

```python
from ark_cli import ArkChatClient, Config, get_client, asr

client = get_client(Config.load())
text = client.chat([{"role": "user", "content": "hi"}], model="doubao-seed-2.0-lite")

result = asr.transcribe_wav("audio.wav", language="zh-CN")
```

## 与 Django 的边界

- **本包**：`ArkChatClient`、`get_client` / `reset_client`、Seed ASR。
- **Django `main_app`**：`Generator`（OpenAI Compatible `LLM_*` + `prompts`）、`Transcribe`（字幕 / yt-dlp）、`run_in_background`。

```bash
python -m unittest tests.test_ark_cli -v
```
