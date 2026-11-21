#!/usr/bin/env python3
"""Доставка и проверка релиза. Только стандартная библиотека Python 3.12+."""

from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import os
import re
import subprocess  # nosec B404  # Docker вызывается через argv без shell
import sys
import urllib.error
import urllib.request
from pathlib import Path


class ReleaseError(RuntimeError):
    pass


def run(*args, timeout=240, env=None):
    # Never include command output: Docker may print expanded environment values.
    result = subprocess.run(  # nosec B603  # команды заданы кодом; тег проверен, shell не используется
        args, capture_output=True, text=True, timeout=timeout, check=False, env=env
    )
    if result.returncode:
        raise ReleaseError(f"Команда {args[0]} завершилась с кодом {result.returncode}")
    return result.stdout.strip()


def read_env(path, required):
    data = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in data:
            raise ReleaseError(f"Неверный формат {path.name}; ожидаются уникальные KEY=value")
        # Deliberately no shell evaluation, quoting, or variable expansion.
        data[key] = value
    missing = [key for key in required if not data.get(key) or data[key].startswith("CHANGE_")]
    if missing:
        raise ReleaseError(f"{path.name}: не заданы " + ", ".join(missing))
    return data


def atomic_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.chmod(0o600)
    temp.replace(path)


@contextlib.contextmanager
def lock(path):
    import fcntl  # Linux host; imported lazily so pure tests also run on Windows.

    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ReleaseError("Другое развертывание уже выполняется") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def request(base, path, token=None, payload=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(  # nosec B310  # base задан Runtime как loopback http, пути заданы кодом
        base + path, data=data, headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:  # nosec B310  # запрос только к loopback стенда
            body = json.load(response)
            if not isinstance(body, dict):
                raise ReleaseError("Некорректный JSON-контракт: " + path)
            return body
    except (OSError, ValueError) as exc:
        raise ReleaseError("Не пройдена HTTP-проверка: " + path) from exc


def smoke(base, release, credentials):
    for path in ("/healthz", "/readyz"):
        if request(base, path).get("status") != "ok":
            raise ReleaseError("Не пройдена проверка " + path)
    version = request(base, "/version")
    if (
        version.get("version") != release["version"]
        or version.get("commit") != release["commit"]
    ):
        raise ReleaseError("/version не соответствует ожидаемым версии и коммиту")
    login = request(
        base,
        "/api/v1/auth/login",
        payload={
            "username": credentials["SMOKE_USERNAME"],
            "password": credentials["SMOKE_PASSWORD"],
        },
    )
    token = login.get("access_token")
    if not isinstance(token, str) or not token:
        raise ReleaseError("Вход не выдал токен")
    me = request(base, "/api/v1/auth/me", token)
    if me.get("username") != credentials["SMOKE_USERNAME"] or not me.get("is_active"):
        raise ReleaseError("Не подтверждена учетная запись")
    # Non-empty fixture is intentional: a broken/empty catalogue must not pass.
    rooms = request(base, "/api/v1/rooms?page_size=10", token)
    if (
        not isinstance(rooms.get("items"), list)
        or not rooms["items"]
        or rooms.get("total", 0) < 1
    ):
        raise ReleaseError("Каталог помещений пуст или нарушен контракт")
    room = rooms["items"][0]
    card = request(base, "/api/v1/rooms/" + str(room["id"]), token)
    if card.get("id") != room["id"] or not card.get("number"):
        raise ReleaseError("Не открылась карточка помещения")


class Runtime:
    def __init__(self, root):
        self.root = root
        self.bootstrap = False
        self.config = read_env(root / "deploy.env", ("IMAGE_REPOSITORY",))
        repo = self.config["IMAGE_REPOSITORY"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9.:/_-]+/audfond", repo):
            raise ReleaseError("IMAGE_REPOSITORY: ожидается путь registry/.../audfond")
        self.repository = repo
        self.port = int(self.config.get("HTTP_PORT", "18080"))
        if not 1024 <= self.port <= 65535:
            raise ReleaseError("HTTP_PORT должен быть 1024..65535")
        self.base = "http://127.0.0.1:" + str(self.port)
        app = read_env(root / "app.env", ("DATABASE_URL", "JWT_SECRET"))
        if len(app["JWT_SECRET"]) < 32:
            raise ReleaseError("JWT_SECRET короче 32 символов")
        if (
            "GIT_COMMIT" in app
            or "INSTANCE_ID" in app
            or app.get("MIGRATE_ON_START") != "false"
        ):
            raise ReleaseError(
                "app.env: нельзя подменять коммит/instance; MIGRATE_ON_START=false"
            )
        container_host = "0.0.0.0"  # nosec B104  # адрес внутри контейнера, не публикация порта на хосте
        if app.get("APP_ENV") != "production" or app.get("APP_HOST") != container_host:
            raise ReleaseError("app.env: нужны APP_ENV=production и APP_HOST=0.0.0.0")
        db = read_env(root / "db.env", ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"))
        from urllib.parse import quote

        expected = (
            f"postgresql+psycopg://{quote(db['POSTGRES_USER'], safe='')}:"
            f"{quote(db['POSTGRES_PASSWORD'], safe='')}@db:5432/{db['POSTGRES_DB']}"
        )
        if app["DATABASE_URL"] != expected:
            raise ReleaseError("DATABASE_URL не соответствует db.env и адресу db:5432")
        self.credentials = read_env(root / "smoke.env", ("SMOKE_USERNAME", "SMOKE_PASSWORD"))
        for name in ("deploy.env", "app.env", "db.env", "smoke.env"):
            if (root / name).stat().st_mode & 0o077:
                raise ReleaseError(name + ": установите права 600")

    def compose(self, *args, env=None):
        return run(
            "docker",
            "compose",
            "--project-name",
            "audfond-staging",
            "-f",
            str(self.root / "compose.json"),
            *args,
            env=env,
        )

    def resolve(self, tag, commit=None):
        if not re.fullmatch(
            r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)|sha-[0-9a-f]{40}", tag
        ):
            raise ReleaseError("Тег: X.Y.Z или sha-<полный SHA>; latest запрещен")
        ref = self.repository + ":" + tag
        run("docker", "pull", ref)
        info = json.loads(run("docker", "image", "inspect", ref))[0]
        labels = info["Config"].get("Labels") or {}
        revision = labels.get("org.opencontainers.image.revision", "")
        version = labels.get("org.opencontainers.image.version", "")
        if not re.fullmatch(r"[0-9a-f]{40}", revision) or not re.fullmatch(
            r"\d+\.\d+\.\d+", version
        ):
            raise ReleaseError("В образе нет корректных OCI version/revision")
        expected = tag[4:] if tag.startswith("sha-") else commit
        if expected and revision != expected:
            raise ReleaseError("Метка revision не совпадает с ожидаемым коммитом")
        if not tag.startswith("sha-") and version != tag:
            raise ReleaseError("Версия образа не совпадает с тегом")
        digests = [
            x
            for x in info.get("RepoDigests", [])
            if x.startswith(self.repository + "@sha256:")
        ]
        if not digests:
            raise ReleaseError("Нет digest скачанного образа")
        return dict(tag=tag, image=digests[0], commit=revision, version=version)

    def prepare(self, release):
        # Re-pull by digest for rollback too. Abort before touching the active stack.
        run("docker", "pull", release["image"])
        run("docker", "pull", "postgres:17.2-alpine")
        run("docker", "pull", "nginxinc/nginx-unprivileged:1.27.3-alpine")
        heads = run(
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            release["image"],
            "python",
            "-m",
            "alembic",
            "heads",
        )
        revisions = re.findall(r"^([a-zA-Z0-9_]+) \(head\)", heads, re.M)
        if len(revisions) != 1:
            raise ReleaseError("Ожидается одна head-ревизия Alembic")
        release["schema"] = revisions[0]

    def render(self, release):
        hardening = dict(
            read_only=True,
            security_opt=["no-new-privileges:true"],
            cap_drop=["ALL"],
            tmpfs=["/tmp:size=64m"],  # nosec B108  # приватный tmpfs контейнера, не файл на хосте
            restart="unless-stopped",
            mem_limit="384m",
            cpus="0.50",
            pids_limit=128,
        )
        app = dict(
            hardening,
            image=release["image"],
            env_file=[str(self.root / "app.env")],
            networks=["backend", "frontend"],
            stop_grace_period="15s",
            healthcheck=dict(
                test=[
                    "CMD",
                    "python",
                    "-c",
                    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz',timeout=3)",
                ],
                interval="5s",
                timeout="4s",
                retries=6,
                start_period="15s",
            ),
        )
        db = dict(
            image="postgres:17.2-alpine",
            user="70:70",
            restart="unless-stopped",
            env_file=[str(self.root / "db.env")],
            networks=["backend"],
            volumes=["db-data:/var/lib/postgresql/data"],
            mem_limit="512m",
            cpus="1.0",
            pids_limit=200,
            security_opt=["no-new-privileges:true"],
            cap_drop=["ALL"],
            healthcheck=dict(
                test=["CMD-SHELL", 'pg_isready -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'],
                interval="5s",
                timeout="3s",
                retries=10,
            ),
        )
        nginx = dict(
            hardening,
            image="nginxinc/nginx-unprivileged:1.27.3-alpine",
            user="101:101",
            networks=["frontend"],
            ports=[f"127.0.0.1:{self.port}:8080"],
            tmpfs=[
                "/tmp:size=32m",  # nosec B108  # приватный tmpfs контейнера, не файл хоста
                "/var/cache/nginx:size=16m",
                "/var/run:size=1m",
            ],
            volumes=[str(self.root / "nginx.conf") + ":/etc/nginx/conf.d/default.conf:ro"],
            healthcheck=dict(
                test=["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/healthz"],
                interval="5s",
                timeout="3s",
                retries=6,
            ),
        )
        config = dict(
            services=dict(db=db, app=app, nginx=nginx),
            networks=dict(backend=dict(internal=True), frontend={}),
            volumes={"db-data": {}},
        )
        atomic_json(self.root / "compose.json", config)
        conf = (
            "server { listen 8080; server_tokens off; location / { "
            "proxy_pass http://app:8000; proxy_set_header Host $host; "
            "proxy_set_header X-Forwarded-Proto $scheme; "
            "proxy_set_header X-Forwarded-For $remote_addr; } }\n"
        )
        nginx_conf = self.root / "nginx.conf"
        nginx_conf.write_text(conf, encoding="utf-8")
        nginx_conf.chmod(0o644)

        self.compose("config", "--quiet")

    def activate(self, release):
        self.render(release)
        self.compose(
            "up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "90", "db"
        )
        self.compose("run", "--rm", "--no-deps", "--pull", "never", "app", "migrate")
        if self.bootstrap:
            if self.credentials["SMOKE_USERNAME"] != "observer":
                raise ReleaseError("Bootstrap создает тестового observer")
            seed_env = dict(os.environ, SEED_PASSWORD=self.credentials["SMOKE_PASSWORD"])
            self.compose(
                "run",
                "--rm",
                "--no-deps",
                "--pull",
                "never",
                "-e",
                "SEED_PASSWORD",
                "app",
                "python",
                "scripts/seed_demo.py",
                env=seed_env,
            )
        self.compose(
            "up",
            "-d",
            "--no-build",
            "--pull",
            "never",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            "90",
            "app",
        )
        # Recreate proxy to refresh Docker DNS after replacing app.
        self.compose(
            "up",
            "-d",
            "--no-build",
            "--pull",
            "never",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            "90",
            "nginx",
        )

    def verify(self, release):
        for service in ("db", "app", "nginx"):
            cid = self.compose("ps", "-q", service)
            if (
                not cid
                or run("docker", "inspect", "-f", "{{.State.Health.Status}}", cid) != "healthy"
            ):
                raise ReleaseError("Контейнер не healthy: " + service)
        smoke(self.base, release, self.credentials)


def deliver(
    runtime,
    state,
    candidate,
    rollback=False,
    audit=lambda value: None,
    save=lambda value: None,
):
    old = state.get("current")
    runtime.prepare(candidate)
    if old and old["image"] == candidate["image"] and old["commit"] == candidate["commit"]:
        runtime.verify(old)
        return state
    if old and old.get("schema") != candidate["schema"]:
        raise ReleaseError(
            "Схема изменилась: нужен отдельный план миграции и восстановления БД"
        )
    # Persist intent before changing anything: interrupted deliveries require recovery.
    pending = dict(state, pending=candidate)
    save(pending)
    audit(dict(status="started", candidate=candidate))
    try:
        runtime.activate(candidate)
        runtime.verify(candidate)
    except Exception as exc:
        audit(dict(status="failed", candidate=candidate, error=type(exc).__name__))
        if old:
            try:
                runtime.activate(old)
                runtime.verify(old)
                save(state)
                audit(dict(status="restored", current=old))
            except Exception as recovery:
                audit(dict(status="recovery-failed", error=type(recovery).__name__))
                raise ReleaseError(
                    "Выпуск и автоматическое восстановление не прошли; pending сохранен"
                ) from recovery
        raise ReleaseError(
            "Выпуск отклонен; предыдущий релиз восстановлен"
            if old
            else "Первый выпуск отклонен; принятого релиза нет, pending сохранен"
        ) from exc
    result = dict(
        current=candidate,
        previous=old,
        accepted_at=datetime.datetime.now(datetime.UTC).isoformat(),
        operation="rollback" if rollback else "deploy",
    )
    save(result)
    audit(dict(status="accepted", current=candidate))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("bootstrap", "deploy", "rollback", "recover", "check", "status")
    )
    parser.add_argument("--root", type=Path, default=Path("/srv/audfond-staging"))
    parser.add_argument("--tag")
    parser.add_argument("--commit")
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        raise ReleaseError("Сначала подготовьте отдельный каталог стенда")
    with lock(root / "deploy.lock"):
        state_path = root / "release-state.json"
        state = (
            json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        )
        if args.action == "status":
            print(json.dumps(state, ensure_ascii=False, indent=2))
            return
        runtime = Runtime(root)
        if args.action == "bootstrap":
            if state:
                raise ReleaseError("Bootstrap только для пустого нового стенда")
            runtime.bootstrap = True
        if args.action == "check":
            if state.get("pending") or not state.get("current"):
                raise ReleaseError("Нет однозначно принятого релиза")
            runtime.verify(state["current"])
            print("Работающий релиз проверен")
            return

        def audit(value):
            value["time"] = datetime.datetime.now(datetime.UTC).isoformat()
            with (root / "release-history.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(value, ensure_ascii=False) + "\n")

        def save(value):
            atomic_json(state_path, value)

        if args.action == "recover":
            # Recovery always targets the last accepted image, never pending.
            if not state.get("pending") or not state.get("current"):
                raise ReleaseError("Recover требует pending и предыдущий принятый current")
            runtime.prepare(state["current"])
            runtime.activate(state["current"])
            runtime.verify(state["current"])
            state.pop("pending")
            save(state)
            audit(dict(status="recovered", current=state["current"]))
            return
        if state.get("pending"):
            raise ReleaseError(
                "Незавершенное развертывание: выполните recover или разберите первый выпуск"
            )
        if args.action == "rollback":
            candidate = state.get("previous")
            if not candidate:
                raise ReleaseError("Нет предыдущего принятого релиза")
        else:
            if not args.tag:
                raise ReleaseError("Укажите --tag")
            candidate = runtime.resolve(args.tag, args.commit)
        deliver(runtime, state, candidate, args.action == "rollback", audit, save)
        print("Релиз принят после проверки")


if __name__ == "__main__":
    try:
        main()
    except (ReleaseError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        # No raw exception text from subprocess/HTTP: could contain credentials.
        print(
            str(error)
            if isinstance(error, ReleaseError)
            else "Ошибка окружения или контракта; проверьте настройки и состояние стенда",
            file=sys.stderr,
        )
        sys.exit(1)
