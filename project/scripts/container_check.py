"""Автоматическая проверка контейнерного окружения — ЛР4, пункты 12–14.

Команда make container-check. Окружение не принимается, если нарушено хотя
бы одно эксплуатационное требование. Запреты (пункт 13) проверяются здесь,
а не только записаны в CONTRIBUTING.md:

    latest           — все образы закреплены точной версией
    root             — ни один процесс не работает от root
    секреты в образе — нет .env и секретных переменных внутри образа
    healthcheck      — есть у каждой долгоживущей службы и не отключён
    лишние порты     — наружу опубликован только порт Nginx

Плюс то, без чего окружение нельзя считать воспроизводимым и устойчивым:
закреплённые с контрольными суммами зависимости, лимиты ресурсов, постоянный
том базы, закрытая внутренняя сеть.

Проверка идёт в три слоя, каждый следующий — если есть что проверять:

    1. файлы      Dockerfile, .dockerignore, lock-файл, docker-compose.yml
    2. образ      собранный образ приложения (make build)
    3. запуск     работающие контейнеры (после make up)

    python3 scripts/container_check.py              все доступные слои
    python3 scripts/container_check.py --no-runtime без работающих контейнеров
    python3 scripts/container_check.py --static     только файлы

Код возврата 1 — нарушение. Исключения не предусмотрены ключами: правило
меняется правкой этого файла с обоснованием в запросе на слияние (ТЗ 7.2).
Только стандартная библиотека: запускается на машине без окружения проекта.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess  # nosec B404  # опрос docker: служебный сценарий проверок
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "docker" / "Dockerfile"
COMPOSE_FILE = ROOT / "docker-compose.yml"
ENV_FILE = ROOT / ".env.docker"
ENV_SAMPLE = ROOT / ".env.docker.example"
APP_IMAGE = "audfond:0.4.0"
PROJECT = "audfond"

#: Единственный разрешённый опубликованный порт: служба -> порт в контейнере
ALLOWED_PORTS = {"nginx": {8080}}
#: Одноразовые службы: отрабатывают и выходят, им не нужен restart и порт
ONE_SHOT = {"migrate", "tests"}
#: Переменные, которые в .env.docker обязаны быть не заглушкой
SECRET_VARS = ("POSTGRES_PASSWORD", "JWT_SECRET", "ADMIN_PASSWORD")
PLACEHOLDER = re.compile(r"CHANGE_ME|СГЕНЕРИРУЙТЕ|ваш[-_]", re.IGNORECASE)
SECRET_NAME = re.compile(r"PASSWORD|SECRET|TOKEN|PRIVATE_KEY|API_KEY", re.IGNORECASE)

DOCKER = shutil.which("docker")


class Report:
    def __init__(self) -> None:
        self.failed = 0
        self.passed = 0

    def section(self, title: str) -> None:
        print(f"\n{title}")

    def check(self, ok: bool, text: str, hint: str = "") -> None:
        if ok:
            self.passed += 1
            print(f"  ОК    {text}")
        else:
            self.failed += 1
            print(f"  СБОЙ  {text}")
            if hint:
                print(f"        {hint}")

    def skip(self, text: str) -> None:
        print(f"  —     {text}")


def docker(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    if DOCKER is None:
        raise RuntimeError("docker не установлен")
    return subprocess.run(  # nosec B603  # argv собран здесь, данных извне нет
        [DOCKER, *args], capture_output=True, text=True, check=False, input=stdin
    )


def compose(*args: str) -> subprocess.CompletedProcess[str]:
    env_file = ENV_FILE if ENV_FILE.exists() else ENV_SAMPLE
    return docker(
        "compose",
        "--project-directory",
        str(ROOT),
        "-f",
        str(COMPOSE_FILE),
        "--env-file",
        str(env_file),
        *args,
    )


def pinned(image: str) -> bool:
    """Образ закреплён: есть тег с цифрой или дайджест, и это не latest."""
    if "@sha256:" in image:
        return True
    name, _, tag = image.rpartition(":")
    if not name or "/" in tag:  # двоеточие было в адресе реестра, тега нет
        return False
    return tag != "latest" and any(ch.isdigit() for ch in tag)


# --------------------------------------------------------------------------- #
# 1. Файлы
# --------------------------------------------------------------------------- #


def dockerfile_images(text: str) -> list[str]:
    args = dict(re.findall(r"^ARG\s+(\w+)=(\S+)", text, re.MULTILINE))
    stages = set(re.findall(r"^FROM\s+\S+\s+AS\s+(\w+)", text, re.MULTILINE | re.IGNORECASE))
    images = []
    for ref in re.findall(r"^FROM\s+(\S+)", text, re.MULTILINE):
        ref = re.sub(r"\$\{?(\w+)\}?", lambda m: args.get(m.group(1), m.group(0)), ref)
        if ref not in stages:
            images.append(ref)
    return images


def check_files(r: Report) -> None:
    r.section("1. Файлы окружения")
    text = DOCKERFILE.read_text(encoding="utf-8")

    for image in dockerfile_images(text) or ["(FROM не найден)"]:
        r.check(
            pinned(image),
            f"Dockerfile: базовый образ закреплён — {image}",
            "латест запрещён: укажите точную версию, например python:3.12.16-slim",
        )

    runtime = text.split("AS runtime", 1)[-1].split("\nFROM ", 1)[0]
    users = re.findall(r"^USER\s+(\S+)", runtime, re.MULTILINE)
    r.check(
        bool(users) and users[-1].split(":")[0] not in {"root", "0"},
        f"Dockerfile: приложение запускается не от root (USER {users[-1] if users else '—'})",
    )

    health = re.findall(r"^HEALTHCHECK\s+(.*)$", runtime, re.MULTILINE)
    r.check(
        bool(health) and not health[0].strip().upper().startswith("NONE"),
        "Dockerfile: в образе объявлен healthcheck",
    )
    r.check(
        "STOPSIGNAL SIGTERM" in runtime
        and "exec uvicorn" in (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8"),
        "Dockerfile: SIGTERM доходит до сервера (STOPSIGNAL и exec в entrypoint)",
    )

    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    r.check(
        ".env" in ignore and ".env.*" in ignore and ".git" in ignore,
        ".dockerignore: файлы окружения и .git в образ не попадают",
    )

    lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    pins = re.findall(r"^([A-Za-z0-9_.\-]+)==", lock, re.MULTILINE)
    hashes = lock.count("--hash=sha256:")
    r.check(
        bool(pins) and hashes >= len(pins) and "--require-hashes" in text,
        f"сборка воспроизводима: {len(pins)} пакетов закреплены с контрольными суммами",
    )


# --------------------------------------------------------------------------- #
# 2. docker-compose.yml
# --------------------------------------------------------------------------- #


def check_env_file(r: Report) -> None:
    if not ENV_FILE.exists():
        r.check(False, ".env.docker создан", "выполните make docker-env")
        return
    mode = stat.S_IMODE(ENV_FILE.stat().st_mode)
    r.check(
        mode & 0o077 == 0,
        f".env.docker закрыт от других пользователей (права {mode:o})",
        "chmod 600 .env.docker",
    )
    values = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip().strip('"')
    weak = [n for n in SECRET_VARS if not values.get(n) or PLACEHOLDER.search(values[n])]
    r.check(
        not weak,
        "в .env.docker нет заглушек вместо паролей и ключей"
        + (f" (заглушка: {', '.join(weak)})" if weak else ""),
        "make docker-env",
    )


def check_compose(r: Report) -> dict[str, Any]:
    r.section("2. docker-compose.yml")
    check_env_file(r)

    result = compose("--profile", "test", "config", "--format", "json")
    if result.returncode != 0:
        r.check(False, "docker compose config разбирает файл", result.stderr.strip()[:300])
        return {}
    config: dict[str, Any] = json.loads(result.stdout)
    services: dict[str, Any] = config.get("services", {})

    raw = COMPOSE_FILE.read_text(encoding="utf-8")
    literal = [
        m.group(1)
        for m in re.finditer(r"^\s+([A-Z_]+):\s*(.+)$", raw, re.MULTILINE)
        if SECRET_NAME.search(m.group(1)) and "${" not in m.group(2)
    ]
    r.check(
        not literal,
        "секреты в docker-compose.yml не записаны, только подставляются"
        + (f" (записаны: {', '.join(literal)})" if literal else ""),
    )

    for name, svc in sorted(services.items()):
        problems = []
        image = svc.get("image", "")
        if not pinned(image):
            problems.append(f"образ не закреплён ({image or 'нет тега'})")

        health = svc.get("healthcheck") or {}
        if health.get("disable") or health.get("test") in (["NONE"], "NONE"):
            problems.append("healthcheck отключён")
        elif not health and name not in ONE_SHOT and not image.startswith("audfond"):
            # у образов приложения healthcheck объявлен в Dockerfile
            problems.append("нет healthcheck")

        published = {
            int(p.get("target", 0)) for p in svc.get("ports") or [] if p.get("published")
        }
        extra = published - ALLOWED_PORTS.get(name, set())
        if extra:
            problems.append(f"опубликован лишний порт {sorted(extra)}")

        limits = (svc.get("deploy") or {}).get("resources", {}).get("limits", {})
        if not limits.get("cpus") or not limits.get("memory"):
            problems.append("нет лимитов CPU и памяти")

        user = str(svc.get("user", "")).split(":")[0]
        if user in {"root", "0"} or svc.get("privileged"):
            problems.append("запуск от root или privileged")
        if "no-new-privileges:true" not in (svc.get("security_opt") or []):
            problems.append("нет no-new-privileges")

        r.check(
            not problems,
            f"служба {name}: "
            + (
                "; ".join(problems)
                if problems
                else "образ закреплён, healthcheck, лимиты, без лишних портов"
            ),
        )

    db_volumes = services.get("db", {}).get("volumes") or []
    r.check(
        any(
            v.get("type") == "volume" and v.get("target") == "/var/lib/postgresql/data"
            for v in db_volumes
        ),
        "данные базы — на постоянном томе, а не в слое контейнера",
    )
    r.check(not services.get("db", {}).get("ports"), "порт базы наружу не публикуется")
    for app in ("app1", "app2"):
        r.check(
            not services.get(app, {}).get("ports"),
            f"{app}: прямого доступа к приложению нет, только через Nginx",
        )
    backend = config.get("networks", {}).get("backend", {})
    r.check(bool(backend.get("internal")), "сеть базы backend внутренняя, без выхода наружу")
    return config


# --------------------------------------------------------------------------- #
# 3. Образ
# --------------------------------------------------------------------------- #


def check_image(r: Report) -> bool:
    r.section(f"3. Образ {APP_IMAGE}")
    inspect = docker("image", "inspect", APP_IMAGE)
    if inspect.returncode != 0:
        r.check(False, "образ собран", "выполните make build")
        return False
    cfg = json.loads(inspect.stdout)[0]["Config"]

    user = (cfg.get("User") or "root").split(":")[0]
    r.check(user not in {"root", "0", ""}, f"пользователь образа не root ({user})")
    health = (cfg.get("Healthcheck") or {}).get("Test") or []
    r.check(bool(health) and health[0] != "NONE", "в образе есть healthcheck")

    # Пользователь приложения должен прочитать код: права файлов переносятся
    # в образ как есть, и закрытые файлы ломают импорт уже в контейнере
    imported = docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--entrypoint",
        "python",
        APP_IMAGE,
        "-c",
        "import app.main; from app.models import Base; open('alembic.ini').read(); "
        "open('migrations/env.py').read()",
    )
    r.check(
        imported.returncode == 0,
        "пользователь приложения читает код и импортирует приложение",
        (imported.stderr.strip().splitlines() or ["?"])[-1],
    )

    env_names = [e.split("=", 1)[0] for e in cfg.get("Env") or []]
    secret_env = [n for n in env_names if SECRET_NAME.search(n)]
    r.check(
        not secret_env,
        "в переменных образа нет секретов"
        + (f" (найдены: {', '.join(secret_env)})" if secret_env else ""),
    )

    # Файлы окружения ищутся по всему образу; ключи и дампы — там, куда их
    # мог бы занести COPY. Публичные корневые сертификаты (/etc/ssl, certifi)
    # секретом не являются
    found = docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--entrypoint",
        "sh",
        APP_IMAGE,
        "-c",
        "find / -xdev \\( -name '.env' -o -name '.env.*' \\) 2>/dev/null; "
        "find /app /opt /root /home /tmp -xdev \\( -name '*.pem' -o -name '*.key' "
        "-o -name '*.dump' -o -name 'id_rsa*' -o -name 'id_ed25519*' \\) "
        "-not -path '*/certifi/*' 2>/dev/null; "
        "grep -rlIE '^-----BEGIN [A-Z ]*PRIVATE KEY-----$' /app /opt 2>/dev/null; true",
    )
    files = found.stdout.split()
    r.check(
        found.returncode == 0 and not files,
        "в файлах образа нет .env, ключей и дампов"
        + (f" (найдены: {', '.join(files[:5])})" if files else ""),
    )

    freeze = docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--entrypoint",
        "pip",
        APP_IMAGE,
        "freeze",
        "--all",
        "--exclude-editable",
    )
    lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    want = {
        n.lower().replace("_", "-"): v
        for n, v in re.findall(r"^([A-Za-z0-9_.\-]+)==(\S+)", lock, re.MULTILINE)
    }
    have = {
        n.lower().replace("_", "-"): v
        for n, v in re.findall(r"^([A-Za-z0-9_.\-]+)==(\S+)", freeze.stdout, re.MULTILINE)
    }
    drift = sorted(n for n, v in want.items() if have.get(n) != v)
    r.check(
        freeze.returncode == 0 and not drift,
        f"в образе ровно версии из requirements.lock ({len(want)} пакетов)"
        + (f"; расходятся: {', '.join(drift[:5])}" if drift else ""),
    )
    return True


# --------------------------------------------------------------------------- #
# 4. Работающие контейнеры
# --------------------------------------------------------------------------- #


def check_runtime(r: Report, config: dict[str, Any]) -> None:
    r.section("4. Работающие контейнеры")
    listed = docker(
        "ps",
        "--filter",
        f"label=com.docker.compose.project={PROJECT}",
        "--format",
        '{{.ID}} {{.Label "com.docker.compose.service"}}',
    )
    # Одноразовые службы (миграции, проверки) в этот слой не входят: они не
    # обслуживают запросы и завершаются сами
    running = [
        parts
        for parts in (line.split() for line in listed.stdout.splitlines() if line.strip())
        if len(parts) == 2 and parts[1] not in ONE_SHOT
    ]
    if not running:
        r.skip("контейнеры не запущены — проверка запуска пропущена (make up)")
        return

    for cid, service in sorted(running, key=lambda x: x[1]):
        top = docker("top", cid, "-eo", "uid,pid")
        uids = {line.split()[0] for line in top.stdout.splitlines()[1:] if line.strip()}
        r.check(
            top.returncode == 0 and "0" not in uids,
            f"{service}: процессы не от root (uid {', '.join(sorted(uids)) or '?'})",
        )

        state = json.loads(docker("inspect", cid).stdout)[0]
        health = (state["State"].get("Health") or {}).get("Status", "нет healthcheck")
        r.check(health == "healthy", f"{service}: состояние {health}")

        ports = state["NetworkSettings"].get("Ports") or {}
        published = {int(k.split("/")[0]) for k, v in ports.items() if v}
        extra = published - ALLOWED_PORTS.get(service, set())
        r.check(
            not extra,
            f"{service}: опубликованы только разрешённые порты"
            + (f" (лишние: {sorted(extra)})" if extra else ""),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка контейнерного окружения (ЛР4)")
    parser.add_argument("--static", action="store_true", help="только файлы")
    parser.add_argument("--no-runtime", action="store_true", help="без работающих контейнеров")
    args = parser.parse_args()

    os.chdir(ROOT)
    r = Report()
    print("Проверка контейнерного окружения AudFond")
    check_files(r)

    if DOCKER is None:
        r.section("2–4. Docker")
        r.check(False, "docker установлен", "проверки compose, образа и запуска невозможны")
    else:
        config = check_compose(r)
        if not args.static:
            check_image(r)
            if not args.no_runtime:
                check_runtime(r, config)

    print(f"\nПройдено: {r.passed}, нарушений: {r.failed}")
    if r.failed:
        print("Окружение НЕ принимается: устраните нарушения (CONTRIBUTING.md, раздел 5)")
        return 1
    print("Окружение соответствует требованиям (ЛР4, пункты 12–13)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
