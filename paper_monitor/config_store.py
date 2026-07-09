import json
import os
import shutil
import threading
import uuid
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional

_CONFIG_UPDATE_LOCK = threading.RLock()


ConfigMutator = Callable[[Dict[str, object]], Optional[Mapping[str, object]]]


def update_config_atomic(config_path: Path, mutator: ConfigMutator) -> Dict[str, object]:
    """Read, mutate, backup, and atomically replace a JSON config file."""

    path = Path(config_path)
    with _CONFIG_UPDATE_LOCK:
        payload = _read_json_object(path)
        mutated = mutator(payload)
        updated = dict(mutated) if mutated is not None else payload
        _write_json_with_backup(path, updated)
        return updated


def _read_json_object(path: Path) -> Dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("Config file must contain a JSON object.")
    return raw


def _write_json_with_backup(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = path.with_name(path.name + ".bak")
    temp_path = path.with_name(".%s.%s.tmp" % (path.name, uuid.uuid4().hex))
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    if path.exists():
        shutil.copy2(str(path), str(backup_path))

    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temp_path), str(path))
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
