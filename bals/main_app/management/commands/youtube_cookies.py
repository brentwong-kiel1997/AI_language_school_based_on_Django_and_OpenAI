"""Manage YouTube cookies for headless / server deployments.

YouTube increasingly blocks unauthenticated automated access. The only
server-friendly way past that block is a **cookie file** (Netscape format):
a plain text file that yt-dlp reads directly, with no browser and no OS
keychain involved — so it never prompts for a password on a server.

Typical workflow
----------------
1. On a machine that *has* a browser where you are logged into YouTube,
   export the cookies once::

       python manage.py youtube_cookies export --from-browser chrome cookies.txt

   (or use a browser extension such as "Get cookies.txt LOCALLY").
2. Copy ``cookies.txt`` to the server and install it::

       python manage.py youtube_cookies install cookies.txt
3. Verify it works against a live video::

       python manage.py youtube_cookies check

The installed file is stored at ``YOUTUBE_COOKIE_FILE`` (or
``<BASE_DIR>/cookies/youtube.txt`` by default) with mode ``0600``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import yt_dlp as youtube_dl

# A stable, captioned video used only to probe whether cookies are accepted.
_PROBE_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def _default_cookie_file() -> Path:
    env = os.environ.get("YOUTUBE_COOKIE_FILE", "").strip()
    if env:
        return Path(env).expanduser()
    return Path(settings.BASE_DIR) / "cookies" / "youtube.txt"


class _QuietLogger:
    """Minimal logger satisfying yt-dlp's cookie helpers."""

    def __init__(self, stdout, stderr):
        self._out = stdout
        self._err = stderr

    def debug(self, msg):
        pass

    def info(self, msg):
        self._out.write(f"{msg}\n")

    def warning(self, msg):
        self._err.write(f"warning: {msg}\n")

    def error(self, msg):
        self._err.write(f"error: {msg}\n")


class Command(BaseCommand):
    help = "Export, install and verify YouTube cookies for server deployments."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="action", required=True)

        p_export = sub.add_parser(
            "export",
            help="Export cookies from a local browser into a Netscape cookie file.",
        )
        p_export.add_argument(
            "--from-browser",
            required=True,
            choices=["chrome", "firefox", "safari", "edge", "brave", "chromium", "opera"],
            help="Browser to read cookies from (run on a machine with that browser).",
        )
        p_export.add_argument("--profile", default=None, help="Browser profile name/path.")
        p_export.add_argument(
            "output",
            nargs="?",
            default="cookies.txt",
            help="Output cookie file path (default: cookies.txt).",
        )

        p_install = sub.add_parser(
            "install",
            help="Install a cookie file to the server path and lock its permissions.",
        )
        p_install.add_argument("source", help="Path to the Netscape cookie file to install.")

        sub.add_parser(
            "check",
            help="Probe YouTube with the configured cookies and report whether they work.",
        )

        p_path = sub.add_parser("path", help="Show the configured cookie file path.")
        p_path.add_argument("--set", dest="set_path", default=None,
                            help="Print the .env line to point at a given file.")

    def handle(self, *args, **options):
        action = options["action"]
        if action == "export":
            self._do_export(options)
        elif action == "install":
            self._do_install(options)
        elif action == "check":
            self._do_check()
        elif action == "path":
            self._do_path(options)

    # -- export -------------------------------------------------------------
    def _do_export(self, options):
        try:
            from yt_dlp.cookies import extract_cookies_from_browser
        except ImportError as exc:
            raise CommandError(
                "Could not import yt-dlp cookie helpers. "
                "Upgrade yt-dlp: pip install -U yt-dlp"
            ) from exc

        browser = options["from_browser"]
        out = Path(options["output"]).expanduser()
        logger = _QuietLogger(self.stdout, self.stderr)
        self.stdout.write(f"Reading cookies from {browser} (close the browser first if it locks)...\n")
        try:
            jar = extract_cookies_from_browser(
                browser, profile=options.get("profile"), logger=logger
            )
        except Exception as exc:  # noqa: BLE001 - yt-dlp raises assorted errors
            raise CommandError(
                f"Failed to read cookies from {browser}: {exc}\n"
                "Make sure you are logged into YouTube in that browser, and close it "
                "before exporting so the cookie database is not locked."
            ) from exc

        out.parent.mkdir(parents=True, exist_ok=True)
        jar.save(str(out), ignore_discard=True, ignore_expires=True)
        try:
            os.chmod(out, 0o600)
        except OSError:
            pass
        count = len(list(jar))
        self.stdout.write(self.style.SUCCESS(
            f"Exported {count} cookie(s) to {out}\n"
            "Next: copy this file to the server and run:\n"
            f"  python manage.py youtube_cookies install {out}"
        ))

    # -- install ------------------------------------------------------------
    def _do_install(self, options):
        src = Path(options["source"]).expanduser()
        if not src.is_file():
            raise CommandError(f"Cookie file not found: {src}")
        dest = _default_cookie_file()
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        try:
            os.chmod(dest, 0o600)
        except OSError:
            pass
        self.stdout.write(self.style.SUCCESS(
            f"Installed cookies to {dest} (mode 0600).\n"
            "Make sure .env contains:\n"
            f"  YOUTUBE_COOKIE_FILE={dest}\n"
            "Then verify with: python manage.py youtube_cookies check"
        ))

    # -- check --------------------------------------------------------------
    def _do_check(self):
        from main_app.utils import Transcribe

        cookie_path = Transcribe._cookie_file_path()
        browser = os.environ.get("YOUTUBE_COOKIES_FROM_BROWSER", "").strip()
        if cookie_path is None and not browser:
            raise CommandError(
                "No cookies configured. Set YOUTUBE_COOKIE_FILE in .env "
                "(run `youtube_cookies install <file>` first)."
            )
        if cookie_path is not None:
            self.stdout.write(f"Using cookie file: {cookie_path}\n")
        else:
            self.stdout.write(
                f"WARNING: no cookie file; will use live browser '{browser}' "
                "(not suitable for servers).\n"
            )

        opts = Transcribe._yt_dlp_base_opts(with_cookies=True)
        try:
            with youtube_dl.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(_PROBE_URL, download=False)
            title = (info or {}).get("title", "?")
            self.stdout.write(self.style.SUCCESS(
                f"OK — cookies accepted by YouTube. Probe video: {title}"
            ))
        except youtube_dl.utils.DownloadError as exc:
            msg = str(exc).lower()
            if "sign in" in msg or "bot" in msg or "login" in msg or "consent" in msg:
                raise CommandError(
                    "Cookies were rejected (YouTube still asks to sign in). "
                    "They are likely expired — re-export from a logged-in browser."
                ) from exc
            raise CommandError(f"YouTube probe failed: {exc}") from exc

    # -- path ---------------------------------------------------------------
    def _do_path(self, options):
        dest = _default_cookie_file()
        if options.get("set_path"):
            self.stdout.write(f"YOUTUBE_COOKIE_FILE={Path(options['set_path']).expanduser()}")
        else:
            exists = dest.is_file()
            self.stdout.write(f"{dest}  [{'present' if exists else 'missing'}]")
