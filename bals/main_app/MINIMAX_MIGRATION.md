# OpenAI → MiniMax migration notes

## What changed

The project no longer imports `openai`. Both call sites in
`bals/main_app/utils.py` now go through the in-house `minimax_cli`
package (a from-scratch reimplementation of the official MiniMax
`mmx-cli` tool – it does **not** shell out to the Node version).

| Old (OpenAI)                                         | New (MiniMax via `minimax_cli`)                   |
| ---------------------------------------------------- | -------------------------------------------------- |
| `from openai import OpenAI`                          | `from minimax_cli import MiniMaxClient, ChatMessage` |
| `client.audio.transcriptions.create(model="whisper-1", response_format="verbose_json", timestamp_granularities=["segment"])` | `client.audio_transcribe(path, model="MiniMax-ASR-01", response_format="verbose_json")` |
| `client.chat.completions.create(model="gpt-3.5-turbo", response_format={"type":"json_object"})` | `client.text_chat(messages, model="MiniMax-Text-01", json_mode=True)` |
| `response.choices[0].message.content`                | `response.text` (or `response.to_json()`)         |
| `transcript.segments` (list of dicts with start/end) | `result.segments` (`TranscriptionSegment` dataclass) |
| `text_with_ts` dict built manually with `timedelta`  | `result.text_with_ts` property (identical shape)   |

The Django views (`wait_view`, `wait_for_chatbot`, `transcript`,
`learning_material`) and the templates (`transcript.html`,
`learning_material.html`) were not touched – the dataclasses returned
by `minimax_cli` mirror the previous OpenAI shapes closely enough that
the existing `ast.literal_eval(model.video_text)` / `json.loads(reply)`
calls still work.

## Credentials

* Run `mmx auth login --api-key <key>` once on the host. The key is
  saved to `~/.mmx/config.json` (chmod 600).
* Alternatively, set `MINIMAX_API_KEY` in the environment.
* `MINIMAX_REGION` (default `cn`) selects the endpoint.

## Region

The default region is `cn` (api.minimaxi.com). To switch:

```bash
mmx config set --key region --value global
```

## Verifying the new code path

```bash
cd bals
python -c "from main_app.utils import _get_client; c=_get_client(); print(c.base_url, c.api_key[:6]+'...')"
```

## Uninstalling the OpenAI SDK

After the migration, `openai` is no longer imported. It can be removed
from `bals/requirements.txt` and uninstalled via `pip uninstall openai`
if you wish – the project will continue to run.
