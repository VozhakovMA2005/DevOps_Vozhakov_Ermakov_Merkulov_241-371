"""Конвейер CI и make ci совпадают (ЛР5, пункт 4; ТЗ 7.1).

Файлы конвейера здесь не читаются — в образ проверок корень репозитория не
попадает. Проверяются правила на коротких образцах; сами файлы сверяет
make ci-sync.
"""

from __future__ import annotations

from scripts import ci_sync_check as sync

TZ_JOBS = "\n".join(
    f"  {name}:\n    name: {name}\n    needs: {prev}\n    steps:\n      - uses: actions/checkout@v6\n      - name: x\n        run: make {target}\n"
    for name, prev, target in [
        ("lint", "config", "quality"),
        ("types", "lint", "types"),
        ("sast", "types", "sast"),
        ("test", "sast", "test-unit"),
        ("test-int", "test", "test-int"),
        ("migrate-check", "test-int", "migrate-check"),
        ("schema-check", "migrate-check", "schema-check"),
        ("secrets-scan", "schema-check", 'secrets-scan BASE="$BASE"'),
        ("deps-check", "secrets-scan", "deps-check"),
    ]
)

WORKFLOW = f"""name: CI
jobs:
  config:
    steps:
      - run: echo ok
{TZ_JOBS}
  ci-gate:
    needs:
      - config
      - lint
      - types
      - sast
      - test
      - test-int
      - migrate-check
      - schema-check
      - secrets-scan
      - deps-check
  publish:
    needs: ci-gate
"""

STAGES = """
STAGES=(
    "lint — стиль|quality"
    "types — типы|types"
    "sast — код|sast"
    "test — модульные|test-unit"
    "test-int — интеграционные|test-int"
    "migrate-check — миграции|migrate-check"
    "schema-check — схема|schema-check"
    "secrets-scan — секреты|secrets-scan"
    "deps-check — зависимости|deps-check"
)
"""


def problems(workflow: str = WORKFLOW, stages: str = STAGES) -> list[str]:
    return sync.check(sync.parse_workflow(workflow), sync.parse_stages(stages))


def test_matching_pipeline_passes() -> None:
    assert problems() == []


def test_make_targets_ignore_variables() -> None:
    assert sync.make_targets('make secrets-scan BASE="$BASE"') == {"secrets-scan"}


def test_needs_in_all_forms_are_parsed() -> None:
    jobs = sync.parse_workflow(WORKFLOW + "  build:\n    needs: [guard, backup]\n")

    assert jobs["types"].needs == ["lint"]
    assert jobs["build"].needs == ["guard", "backup"]
    assert "deps-check" in jobs["ci-gate"].needs


def test_broken_tz_order_is_found() -> None:
    broken = WORKFLOW.replace(
        "  sast:\n    name: sast\n    needs: types",
        "  sast:\n    name: sast\n    needs: config",
    )

    assert any("«sast» должна идти после «types»" in p for p in problems(broken))


def test_check_only_on_server_is_found() -> None:
    extra = WORKFLOW + "  e2e:\n    needs: deps-check\n    steps:\n      - run: make e2e\n"

    found = problems(extra)

    assert any("«e2e» отсутствует в make ci" in p for p in found)
    assert any("ci-gate не ждёт стадии: e2e" in p for p in found)


def test_different_targets_are_found() -> None:
    local = STAGES.replace("sast — код|sast", "sast — код|sast secrets")

    assert any(p.startswith("«sast»: в make ci цели") for p in problems(stages=local))


def test_continue_on_error_and_suppression_are_found() -> None:
    weak = WORKFLOW.replace(
        "  lint:\n    name: lint\n", "  lint:\n    name: lint\n    continue-on-error: true\n"
    ).replace("run: make types", "run: make types || true")

    found = problems(weak)

    assert any("«lint»: continue-on-error" in p for p in found)
    assert any("«types»: ошибка make подавлена" in p for p in found)


def test_third_party_and_floating_actions_are_found() -> None:
    risky = WORKFLOW.replace(
        "  sast:\n    name: sast\n    needs: types\n    steps:\n      - uses: actions/checkout@v6",
        "  sast:\n    name: sast\n    needs: types\n    steps:\n      - uses: aquasecurity/trivy-action@master",
    )

    assert any("aquasecurity/trivy-action@master" in p for p in problems(risky))


def test_publish_without_gate_is_found() -> None:
    early = WORKFLOW.replace("  publish:\n    needs: ci-gate", "  publish:\n    needs: build")

    assert any("«publish» должна ждать ci-gate" in p for p in problems(early))


def test_exit_zero_and_disabled_steps_are_found() -> None:
    weak = WORKFLOW.replace("run: make types", "run: make types; exit 0").replace(
        "      - name: x\n        run: make sast",
        "      - name: x\n        if: false\n        run: make sast",
    )

    found = problems(weak)

    assert any("«types»: ошибка make подавлена" in p for p in found)
    assert any("«sast»: шаг или задача выключены" in p for p in found)


def test_expression_continue_on_error_is_found() -> None:
    weak = WORKFLOW.replace(
        "  lint:\n    name: lint\n",
        "  lint:\n    name: lint\n    continue-on-error: ${{ true }}\n",
    )

    assert any("«lint»: continue-on-error" in p for p in problems(weak))


def test_action_pinned_by_sha_is_allowed() -> None:
    pinned = WORKFLOW.replace("actions/checkout@v6", "actions/checkout@" + "a" * 40)

    assert problems(pinned) == []
