"""Создать учебный условный дефект каталога только в отдельном fork/checkout."""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fork-checkout", type=Path, required=True)
    parser.add_argument("--confirm-disposable-fork", action="store_true", required=True)
    args = parser.parse_args()
    target = args.fork_checkout / "project/app/api/rooms.py"
    source = target.read_text(encoding="utf-8")
    marker = "    page, page_size = pagination\n"
    if "DEMO_BREAK_CATALOG" in source or source.count(marker) < 1:
        raise SystemExit("Неожиданный исходник; остановка без изменений")
    replacement = """    # Только для изолированного учебного fork: отказ в целевой среде.
    import os

    if os.getenv("DEMO_BREAK_CATALOG") == "true":
        from app.main import error_response

        return error_response(503, "DEMO_CATALOG_FAILURE", "Учебный отказ каталога")

    page, page_size = pagination
"""
    target.write_text(source.replace(marker, replacement, 1), encoding="utf-8", newline="\n")
    print("Учебный дефект добавлен; выполните ревью, make verify и полный CI в fork")


if __name__ == "__main__":
    main()
