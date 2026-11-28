"""Converge AudFond to a published image and the managed runtime configuration."""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from cd import ReleaseError, Runtime, atomic_json, lock

ENV_FILES = ("deploy.env", "app.env", "db.env", "smoke.env")
CHANGE_MESSAGE = "Управляемое состояние приложения обновлено"


def config_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for name in ENV_FILES:
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update((root / name).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def release_command(root: Path, action: str, tag: str) -> None:
    controller = Path(__file__).with_name("cd.py")
    subprocess.run(
        [sys.executable, "-B", str(controller), action, "--root", str(root), "--tag", tag],
        check=True,
    )


def converge(root: Path, tag: str) -> bool:
    if not re.fullmatch(r"sha-[0-9a-f]{40}", tag):
        raise ReleaseError("Specify an image tag pinned to a complete commit SHA")

    state_path = root / "release-state.json"
    config_path = root / ".lr7-config-applied.json"
    with lock(root / ".lr7-apply.lock"):
        desired_config = config_digest(root)
        state = read_json(state_path)
        current = state.get("current")
        if state.get("pending") or (state_path.exists() and not current):
            raise ReleaseError("Recover the incomplete AudFond release before applying LR7")

        if not current:
            release_command(root, "bootstrap", tag)
        elif current["commit"] != tag[4:]:
            release_command(root, "deploy", tag)
        elif read_json(config_path).get("sha256") != desired_config:
            with lock(root / "deploy.lock"):
                if read_json(state_path) != state:
                    raise ReleaseError("The release changed concurrently; run the play again")
                runtime = Runtime(root)
                runtime.activate(current)
                runtime.verify(current)
        else:
            return False

        atomic_json(config_path, {"sha256": desired_config})
        return True


if __name__ == "__main__":
    try:
        if converge(Path(sys.argv[1]), sys.argv[2]):
            print(CHANGE_MESSAGE)
    except (OSError, ValueError, ReleaseError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
