"""
minimax_cli
~~~~~~~~~~~

A pure-Python reimplementation of the official MiniMax mmx-cli.

This package intentionally does NOT depend on the official npm ``mmx-cli``.
It speaks the MiniMax HTTP APIs directly and exposes a ``mmx`` console
script (provided by :mod:`minimax_cli.cli`) that is command-compatible with
the upstream CLI.

Capabilities (all of them implemented in pure Python, no Node.js needed):

* ``mmx auth login/status/refresh/logout``
* ``mmx config show/set``
* ``mmx text chat``          – chat completion (streaming, JSON mode, multi-turn)
* ``mmx image generate``     – text-to-image
* ``mmx video generate``     – async text-to-video with task query/download
* ``mmx speech synthesize``  – TTS, multiple voices, streaming
* ``mmx music generate``     – text-to-music (lyrics / instrumental)
* ``mmx vision describe``    – image understanding (file / URL / file id)
* ``mmx search query``       – built-in web search
* ``mmx audio transcribe``   – speech-to-text (drop-in Whisper replacement)
* ``mmx quota``              – Token Plan quota
* ``mmx update``             – self-update check
* ``mmx``                    – the interactive REPL/dashboard panel
"""

from .client import (
    MiniMaxClient,
    ChatMessage,
    ChatChoice,
    ChatResponse,
    Usage,
    TranscriptionResult,
    TranscriptionSegment,
    ImageResult,
    VideoTask,
)
from .config import Config, Region
from .auth import AuthStore, AuthState
from .exceptions import (
    MiniMaxError,
    AuthenticationError,
    QuotaExceededError,
    APIError,
    ValidationError,
    FileTooLargeError,
    NetworkError,
)

__version__ = "0.1.0"

__all__ = [
    "MiniMaxClient",
    "ChatMessage",
    "ChatChoice",
    "ChatResponse",
    "Usage",
    "TranscriptionResult",
    "TranscriptionSegment",
    "ImageResult",
    "VideoTask",
    "Config",
    "Region",
    "AuthStore",
    "AuthState",
    "MiniMaxError",
    "AuthenticationError",
    "QuotaExceededError",
    "APIError",
    "ValidationError",
    "FileTooLargeError",
    "NetworkError",
    "__version__",
]
