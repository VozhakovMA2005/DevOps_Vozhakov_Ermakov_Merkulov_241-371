"""Прочитать инфраструктурные файлы без запуска Ansible и без вывода значений."""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from pathlib import Path

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

INFRA = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(INFRA.parent / "project" / "scripts"))
import secret_scan  # noqa: E402

SECRET_KEY = re.compile(
    r"(?:^|[_-])(?:password|passwd|pwd|secret|token|(?:api|private|access)[_-]?key)$",
    re.IGNORECASE,
)
ENV_ASSIGNMENT = re.compile(r"^[ \t]*(?:export[ \t]+)?(\w+)[ \t]*=[ \t]*(.*)$", re.MULTILINE)
VAULT_HEX = re.compile(r"[0-9a-f]+", re.IGNORECASE)


def yaml_literals(node: Node | None, seen: set[int]) -> Iterator[int]:
    if node is None or id(node) in seen:
        return
    seen.add(id(node))
    if isinstance(node, MappingNode):
        for key, value in node.value:
            if isinstance(key, ScalarNode) and SECRET_KEY.search(key.value):
                if not isinstance(value, ScalarNode) or not secret_scan.JINJA_VARIABLE.fullmatch(
                    value.value
                ):
                    yield key.start_mark.line + 1
            yield from yaml_literals(value, seen)
    if isinstance(node, SequenceNode):
        for value in node.value:
            yield from yaml_literals(value, seen)


def literal_lines(path: Path, text: str) -> Iterator[int]:
    if path.suffix in {".yml", ".yaml"}:
        for root in yaml.compose_all(text, Loader=yaml.SafeLoader):
            yield from yaml_literals(root, set())
    if path.name.endswith(".env.j2"):
        for match in ENV_ASSIGNMENT.finditer(text):
            key, value = match.groups()
            if SECRET_KEY.search(key) and not secret_scan.JINJA_VARIABLE.fullmatch(
                value.strip().strip("\"'")
            ):
                yield text.count("\n", 0, match.start()) + 1


def scan(root: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            findings.append(f"{name}: проверка не читает символические ссылки")
            continue
        if not path.is_file():
            continue
        secret_scan.check_names(path, name, findings)
        if secret_scan.skipped(name):
            continue
        try:
            text = path.read_text(encoding="utf-8")
            if text.startswith("$ANSIBLE_VAULT;"):
                body = text.splitlines()[1:]
                if not body or not all(VAULT_HEX.fullmatch(line) for line in body):
                    findings.append(f"{name}: неверный формат зашифрованного содержимого Vault")
                continue
            secret_scan.check_content(name, text, findings)
            for line in literal_lines(path, text):
                findings.append(f"{name}:{line}: ожидается ссылка на секретную переменную")
        except yaml.YAMLError:
            findings.append(f"{name}: не удалось разобрать YAML")
        except (UnicodeError, OSError):
            findings.append(f"{name}: не удалось прочитать файл проверки")
    return findings


if __name__ == "__main__":
    findings = scan(INFRA)
    if findings:
        print("\n".join(findings), file=sys.stderr)
        raise SystemExit(1)
    print("infra: открытых секретов в проверенных файлах не найдено")
