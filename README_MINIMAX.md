# MiniMax CLI

独立的中国区 MiniMax Token Plan 客户端与命令行工具（`mmx` / `python -m minimax_cli`）。默认区域为 `cn`（`https://api.minimaxi.com`），与 Django Ark / Seed ASR 路径完全隔离。

## 安装

```bash
pip install -e .
# or: PYTHONPATH=. python -m minimax_cli ...
```

## 配置

环境变量优先于 `~/.mmx/config.json`（可用 `MINIMAX_CONFIG_DIR` 覆盖目录）：

| 变量 | 默认 |
|------|------|
| `MINIMAX_API_KEY` | （空） |
| `MINIMAX_REGION` | `cn`（可选 `global` → `https://api.minimax.io`） |
| `MINIMAX_BASE_URL` | 随 region |
| `MINIMAX_TEXT_MODEL` | `MiniMax-M3` |
| `MINIMAX_IMAGE_MODEL` | `image-01` |
| `MINIMAX_SPEECH_MODEL` | `speech-2.8-hd` |
| `MINIMAX_VIDEO_MODEL` | `MiniMax-Hailuo-2.3` |
| `MINIMAX_MUSIC_MODEL` | `music-2.6` |
| `MINIMAX_VISION_MODEL` | `MiniMax-VL` |
| `MINIMAX_CONTEXT_WINDOW_TOKENS` | `1000000` |
| `MINIMAX_MAX_TOKENS` | `131072` |
| `MINIMAX_TIMEOUT_SECONDS` | `120` |
| `MINIMAX_VIDEO_TIMEOUT_SECONDS` | `600` |
| `MINIMAX_POLL_INTERVAL_SECONDS` | `5` |
| `MINIMAX_OUTPUT_DIR` | `.` |

```bash
export MINIMAX_API_KEY=你的密钥
mmx auth login --api-key "$MINIMAX_API_KEY"
mmx config set --key region --value cn
mmx config show
mmx auth status
```

`mmx auth refresh` 为 OAuth Device Code 占位：当前未实现完整浏览器 OAuth，请使用 API key。

## 命令

```bash
mmx text chat --message "你好"
mmx text chat --message "user:hi" --message "assistant:hello" --message "user:继续" --stream
mmx text chat --message "返回 JSON" --json

mmx image generate --prompt "太空中的猫" --out-dir ./out
mmx image "太空中的猫" --out ./cat.jpg          # 快捷写法

mmx speech synthesize --text "你好" --out hello.mp3 --voice English_expressive_narrator
mmx speech voices --lang en

mmx video generate --prompt "日落海浪" --download sunset.mp4
mmx video generate --prompt "机器人画画" --async
mmx video task get --task-id <id>
mmx video download --file-id <id> --out clip.mp4

mmx music generate --prompt "轻快流行" --lyrics "[verse] sunny day" --out song.mp3
mmx music generate --prompt "电影配乐" --instrumental --out score.mp3
mmx music cover --prompt "Indie folk" --audio-file ref.mp3 --out cover.mp3

mmx vision describe --image ./photo.jpg --prompt "这是什么？"
mmx vision describe --image https://example.com/a.jpg

mmx search query "MiniMax Token Plan"
mmx quota
mmx --output json quota
```

## 客户端 API

```python
from minimax_cli import Config, MiniMaxClient

with MiniMaxClient(Config.load()) as client:
    chat = client.text_chat([{"role": "user", "content": "hi"}])
    speech = client.speech_synthesize("hello", out="a.mp3")
    image = client.image_generate("a cat", out_dir="./out")
    video = client.video_generate("ocean", download="v.mp4")  # 内部轮询
    music = client.music_generate(prompt="pop", lyrics="[verse] hi", out="m.mp3")
    vision = client.vision_describe(image="./x.jpg")
```

## 实现边界

**已支持：** 文本（非流式 / SSE）、image、speech、voices、video 异步闭环、music / cover、vision（coding plan VLM）、search、quota、region/cn|global、文件上传/检索 helper、本地二进制落盘。

**刻意不做 / 未完成：**

- 完整 OAuth Device Code 登录与 `auth refresh`（需浏览器交互）
- `mmx update` 自更新
- Anthropic Messages 兼容路径（文本仍走国区可用的 `/v1/text/chatcompletion_v2`）
- Django `main_app` 集成（本包保持独立）

接口字段随 Token Plan / 模型版本可能变化；客户端保留 raw 响应，并通过可配置 endpoint 兼容。`json_mode` 仅靠 system 指令约束 JSON，不发送可能被拒绝的 `response_format`。默认 quota 为 `/v1/coding_plan/quota`（可用 `MINIMAX_QUOTA_ENDPOINT` 覆盖；官方 global CLI 常用 `/v1/token_plan/remains`）。

测试全部使用 mock transport，不依赖真实 MiniMax 网络：

```bash
python -m unittest tests.test_minimax_cli -v
```
