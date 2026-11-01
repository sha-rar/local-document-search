"""User settings persisted as JSON beside the index."""

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .storage import default_db_path

DEFAULT_RESULT_LIMIT = 100
MIN_RESULT_LIMIT = 10
MAX_RESULT_LIMIT = 1000


@dataclass
class Settings:
    folders: list[str] = field(default_factory=list)
    excluded_folders: list[str] = field(default_factory=list)
    result_limit: int = DEFAULT_RESULT_LIMIT
    index_on_startup: bool = False
    watch_folders: bool = True


def default_settings_path() -> Path:
    return default_db_path().with_name("settings.json")


def _valid(name: str, value: object) -> bool:
    if name in ("folders", "excluded_folders"):
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if name == "result_limit":
        return isinstance(value, int) and not isinstance(value, bool)
    if name in ("index_on_startup", "watch_folders"):
        return isinstance(value, bool)
    return False


def load_settings(path: Path) -> Settings:
    """Read settings, falling back to defaults for a missing file or invalid values."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    known = {f.name for f in fields(Settings)}
    settings = Settings(**{k: v for k, v in data.items() if k in known and _valid(k, v)})
    settings.result_limit = min(max(settings.result_limit, MIN_RESULT_LIMIT), MAX_RESULT_LIMIT)
    return settings


def save_settings(settings: Settings, path: Path) -> None:
    """Write settings atomically so a crash can't leave a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".settings-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(asdict(settings), fh, indent=2)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
