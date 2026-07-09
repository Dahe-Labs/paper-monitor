import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional

from .filtering import MatchResult
from .models import Article

NOTIFICATION_TIMEOUT_SECONDS = 5


def build_osascript_command(article: Article) -> List[str]:
    title = _truncate(article.title, 120)
    subtitle = _truncate(article.journal or article.source, 80)
    body = article.doi or article.url
    script_lines = [
        "on run argv",
        "set notificationBody to item 1 of argv",
        "set notificationTitle to item 2 of argv",
        "set notificationSubtitle to item 3 of argv",
        'display notification notificationBody with title notificationTitle subtitle notificationSubtitle sound name "Glass"',
        "end run",
    ]
    command = ["osascript"]
    for line in script_lines:
        command.extend(["-e", line])
    command.extend([body, title, subtitle])
    return command


def build_terminal_notifier_command(
    terminal_notifier_path: Path,
    article: Article,
    dashboard_path: Path,
) -> List[str]:
    return [
        _posix_path(terminal_notifier_path),
        "-title",
        _truncate(article.title, 120),
        "-subtitle",
        _truncate(article.journal or article.source, 80),
        "-message",
        article.doi or article.url,
        "-sound",
        "default",
        "-ignoreDnD",
        "-execute",
        _open_command(article_open_target(article, dashboard_path)),
    ]


def article_open_target(article: Article, dashboard_path: Path = None) -> str:
    if article.url and article.url.startswith(("http://", "https://")):
        return article.url
    if article.doi:
        return "https://doi.org/" + article.doi
    if dashboard_path is not None:
        return dashboard_path.resolve().as_uri()
    return "https://example.org"


def find_terminal_notifier(candidates: Iterable[Path] = None) -> Optional[Path]:
    found = shutil.which("terminal-notifier")
    if found:
        return Path(found)
    search_paths = candidates or (
        Path("/opt/homebrew/bin/terminal-notifier"),
        Path("/usr/local/bin/terminal-notifier"),
    )
    for candidate in search_paths:
        if candidate.exists():
            return candidate
    return None


def run_notification_command(command: List[str]) -> bool:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=NOTIFICATION_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def notify_article(article: Article, match: MatchResult, dashboard_path: Path = None) -> bool:
    if sys.platform == "win32":
        return _notify_windows_article(article, dashboard_path)

    terminal_notifier = find_terminal_notifier()
    if terminal_notifier and dashboard_path is not None:
        return run_notification_command(
            build_terminal_notifier_command(terminal_notifier, article, dashboard_path)
        )
    return run_notification_command(build_osascript_command(article))


def _notify_windows_article(article: Article, dashboard_path: Path = None) -> bool:
    from .windows_tray import WindowsToastNotifier, windows_icon_path

    notifier = WindowsToastNotifier(icon_path=windows_icon_path())
    dashboard_path = dashboard_path or Path.cwd()
    return notifier.notify_article(
        {
            "title": article.title,
            "journal": article.journal,
            "url": article.url,
            "doi": article.doi,
            "source": article.source,
        },
        dashboard_path,
    )


def _truncate(value: str, limit: int) -> str:
    compact = " ".join((value or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


def _open_command(target: str) -> str:
    return "/usr/bin/open " + shlex.quote(target)


def _posix_path(path: Path) -> str:
    return str(path).replace("\\", "/")
