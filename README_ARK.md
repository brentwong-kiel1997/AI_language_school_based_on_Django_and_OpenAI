# Ark CLI

独立的火山方舟（Volcengine Ark）客户端包。当前 Django 应用**仅用其中的 Seed ASR**（无字幕时的 STT）；课件文本生成已切到 `minimax_cli`。本包仍提供独立的 `ark` CLI 供 Chat/ASR 冒烟。

## 安装

```bash
pip install -e .
# or: PYTHONPATH=. python -m ark_cli ...
```

## 配置

键名与原先一致，可用环境变量或仓库根 / `bals/.env`（`setdefault`，不覆盖已有 OS 环境）：

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

- **在本包**：`ArkChatClient`、`get_client` / `reset_client`、Seed ASR 协议与转写。
- **在 Django `main_app.utils`**：`Generator`（课件 prompt / 校验 / repair）、`Transcribe`（字幕 / yt-dlp）、`run_in_background`。

```bash
python -m unittest tests.test_ark_cli -v
```
