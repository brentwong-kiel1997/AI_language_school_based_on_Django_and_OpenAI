# minimax_cli

A **pure-Python, command-compatible** reimplementation of the official
[MiniMax mmx-cli](https://platform.minimaxi.com/docs/token-plan/minimax-cli).

> ⚠️ This package **does NOT** shell-out to or import the official Node.js
> `mmx-cli`. It speaks the MiniMax HTTP APIs directly using `httpx`, so
> you can drive every capability from a single Python dependency.

---

## Why a reimplementation?

* The upstream `mmx-cli` is a Node.js binary distributed via npm. Some
  environments (e.g. the `pythonanywhere` host this Django project lives
  on) make it painful to install Node + npm on demand.
* Django views, Celery tasks and other Python code can call the same
  capabilities through a normal Python API.
* A Python package is easier to ship, version, and test in CI.

Every command listed in the official mmx-cli docs is implemented here:

| mmx command            | implemented as                                  |
| ---------------------- | ----------------------------------------------- |
| `mmx`                  | `minimax_cli.panel.render_panel`                |
| `mmx auth login`       | `minimax_cli.cli.cmd_auth / AuthStore.login`    |
| `mmx auth status`      | `AuthStore.status`                              |
| `mmx auth refresh`     | `AuthStore.refresh`                             |
| `mmx auth logout`      | `AuthStore.logout`                              |
| `mmx config show`      | `Config.to_dict`                                |
| `mmx config set`       | `Config.set`                                    |
| `mmx text chat`        | `MiniMaxClient.text_chat`                       |
| `mmx image generate`   | `MiniMaxClient.image_generate`                  |
| `mmx video generate`   | `MiniMaxClient.video_generate`                  |
| `mmx video status`     | `MiniMaxClient.video_query`                     |
| `mmx video download`   | `MiniMaxClient._download_to_dir`                |
| `mmx speech synthesize`| `MiniMaxClient.speech_synthesize`               |
| `mmx music generate`   | `MiniMaxClient.music_generate`                  |
| `mmx vision describe`  | `MiniMaxClient.vision_describe`                 |
| `mmx search query`     | `MiniMaxClient.search_query`                    |
| `mmx audio transcribe` | `MiniMaxClient.audio_transcribe` (Whisper-repl.) |
| `mmx quota`            | `MiniMaxClient.quota`                           |
| `mmx update`           | `minimax_cli.update.check_latest`               |

---

## Install

```bash
pip install -e .         # this repo
# or
pip install minimax-cli  # once published
```

## Login

```bash
mmx auth login --api-key sk-cp-xxxxxxxx
# If the key is from the global console:
mmx config set --key region --value global
mmx auth status
```

All keys/regions are persisted to `~/.mmx/config.json` (chmod 600) and
mirrored in `~/.mmx/auth.json` – exactly like the upstream CLI.

## Examples

```bash
# Language
mmx text chat --message "用 4 言诗描述 AI"

# Video
mmx video generate "夕阳下,一只猫坐在窗边望向远方"

# Music
mmx music generate "轻快爵士,夏天的海边" --out jazz-summer.mp3

# Speech
mmx speech synthesize --text "欢迎使用 MiniMax" --out hello.mp3

# Image
mmx image generate "赛博朋克城市夜景,16:9" --aspect-ratio 16:9

# Vision
mmx vision describe --image ./cat.png --prompt "图片里有什么?"

# Search
mmx search query "MiniMax Token Plan 怎么收费"

# Audio (Whisper replacement)
mmx audio transcribe ./voice.mp3 --format verbose_json
```

## Library use

```python
from minimax_cli import MiniMaxClient, ChatMessage

client = MiniMaxClient(api_key="sk-cp-xxx", region="cn")

resp = client.text_chat(
    messages=[ChatMessage.user("写一首关于 AI 的 4 言诗")],
    model="MiniMax-Text-01",
    temperature=0,
    stream=True,
    on_delta=lambda t: print(t, end="", flush=True),
)
print()
```

---

## Configuration

Configuration is read from the following sources, in order of priority:

1. CLI flags (`--api-key`, `--region`)
2. Environment variables (`MINIMAX_API_KEY`, `MINIMAX_REGION`)
3. `~/.mmx/config.json` (managed by `mmx config` / `mmx auth`)
4. Built-in defaults

Keys:

| key             | default            | meaning                                |
| --------------- | ------------------ | -------------------------------------- |
| `api_key`       | _empty_            | MiniMax Token Plan API key             |
| `region`        | `cn`               | `cn` (api.minimaxi.com) / `global`     |
| `default_model` | `MiniMax-Text-01`  | Used by `mmx text chat` when no `--model` |
| `output_dir`    | `minimax-output`   | Where generated files are saved        |
| `stream`        | `true`             | Default streaming for chat / speech    |

---

## Replace OpenAI in this Django project

`bals/main_app/utils.py` was using `openai.OpenAI()` for both Whisper and
`gpt-3.5-turbo`. The new `utils.py` uses `minimax_cli.MiniMaxClient`
instead:

* `Transcribe.audio2text`  → `client.audio_transcribe(...)`
* `Generator.chatbox`      → `client.text_chat(... json_mode=True)`

The dataclasses (`TranscriptionResult.text_with_ts`, `ChatResponse.text`)
are deliberately drop-in compatible with the previous Whisper/OpenAI
shapes so the Django views / templates do not need to change.

---

## Development

```bash
# show help
mmx --help
mmx text chat --help

# panel
mmx

# run as a module
python -m minimax_cli text chat --message "hi"

# self-check
python -c "import minimax_cli; print(minimax_cli.__version__)"
```

## License

MIT. MiniMax, mmx-cli, Hailuo, Speech-2.8, Music-2.6 etc. are trademarks
of their respective owners; this package is an unofficial third-party
port and is not affiliated with MiniMax.
