"""Отказы доставки и HTTP-приемки без Docker/БД, unittest stdlib."""

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("cd", Path(__file__).with_name("cd.py"))
cd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cd)

OLD = dict(
    tag="0.5.0", version="0.5.0", image="r/audfond@sha256:old", commit="a" * 40, schema="0001"
)
NEW = dict(
    tag="0.6.0", version="0.6.0", image="r/audfond@sha256:new", commit="b" * 40, schema="0001"
)


class FakeRuntime:
    def __init__(self, fail=None):
        self.fail = fail
        self.activated = []
        self.checked = []

    def prepare(self, candidate):
        if self.fail == "registry":
            raise cd.ReleaseError("registry")

    def activate(self, candidate):
        self.activated.append(candidate["tag"])
        if self.fail == "health" and candidate["tag"] == NEW["tag"]:
            raise cd.ReleaseError("health")

    def verify(self, candidate):
        self.checked.append(candidate["tag"])
        if self.fail in ("scenario", "recovery") and (
            candidate["tag"] == NEW["tag"] or self.fail == "recovery"
        ):
            raise cd.ReleaseError("scenario")


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.state = dict(current=copy.deepcopy(OLD))
        self.new = copy.deepcopy(NEW)
        self.saved = []
        self.events = []

    def call(self, runtime, state=None, rollback=False):
        return cd.deliver(
            runtime,
            self.state if state is None else state,
            self.new,
            rollback,
            self.events.append,
            lambda x: self.saved.append(copy.deepcopy(x)),
        )

    def test_success_records_previous_only_after_verification(self):
        r = FakeRuntime()
        result = self.call(r)
        self.assertIn("pending", self.saved[0])
        self.assertNotIn("pending", result)
        self.assertEqual(result["previous"], OLD)
        self.assertEqual(r.checked, ["0.6.0"])

    def test_registry_failure_changes_nothing(self):
        r = FakeRuntime("registry")
        with self.assertRaises(cd.ReleaseError):
            self.call(r)
        self.assertEqual(r.activated, [])
        self.assertEqual(self.saved, [])

    def test_schema_change_blocked_before_mutation(self):
        self.new["schema"] = "0002"
        r = FakeRuntime()
        with self.assertRaises(cd.ReleaseError):
            self.call(r)
        self.assertEqual(r.activated, [])

    def test_health_failure_restores_and_still_fails(self):
        r = FakeRuntime("health")
        with self.assertRaises(cd.ReleaseError):
            self.call(r)
        self.assertEqual(r.activated, ["0.6.0", "0.5.0"])
        self.assertEqual(self.saved[-1], self.state)
        self.assertEqual(self.events[-1]["status"], "restored")

    def test_business_failure_restores_and_still_fails(self):
        r = FakeRuntime("scenario")
        with self.assertRaises(cd.ReleaseError):
            self.call(r)
        self.assertEqual(r.checked, ["0.6.0", "0.5.0"])
        self.assertEqual(self.saved[-1], self.state)

    def test_recovery_failure_keeps_pending(self):
        with self.assertRaises(cd.ReleaseError):
            self.call(FakeRuntime("recovery"))
        self.assertIn("pending", self.saved[-1])
        self.assertEqual(self.events[-1]["status"], "recovery-failed")

    def test_first_failure_has_no_previous(self):
        with self.assertRaises(cd.ReleaseError):
            self.call(FakeRuntime("scenario"), {})
        self.assertIn("pending", self.saved[-1])

    def test_manual_rollback_records_operation(self):
        self.assertEqual(self.call(FakeRuntime(), rollback=True)["operation"], "rollback")

    def test_invalid_tag_before_registry(self):
        r = object.__new__(cd.Runtime)
        r.repository = "r/audfond"
        for tag in ("latest", "../bad", "0.6", "v0.6.0", "x;rm -rf /"):
            with self.subTest(tag=tag), patch.object(cd, "run") as command:
                with self.assertRaises(cd.ReleaseError):
                    r.resolve(tag)
                command.assert_not_called()

    def test_wrong_version_or_commit_rejected(self):
        r = object.__new__(cd.Runtime)
        r.repository = "r/audfond"
        info = [
            dict(
                Config=dict(
                    Labels={
                        "org.opencontainers.image.version": "0.5.0",
                        "org.opencontainers.image.revision": "a" * 40,
                    }
                ),
                RepoDigests=["r/audfond@sha256:" + "a" * 64],
            )
        ]
        with (
            patch.object(cd, "run", side_effect=["", json.dumps(info)]),
            self.assertRaises(cd.ReleaseError),
        ):
            r.resolve("0.6.0")
        with (
            patch.object(cd, "run", side_effect=["", json.dumps(info)]),
            self.assertRaises(cd.ReleaseError),
        ):
            r.resolve("sha-" + "b" * 40)

    def test_same_image_does_not_erase_previous(self):
        self.new = copy.deepcopy(OLD)
        self.state["previous"] = dict(OLD, tag="0.4.0")
        r = FakeRuntime()
        self.assertEqual(self.call(r), self.state)
        self.assertEqual(r.activated, [])
        self.assertEqual(self.saved, [])

    def test_compose_has_no_build_no_secrets_and_only_proxy_port(self):
        with tempfile.TemporaryDirectory() as directory:
            r = object.__new__(cd.Runtime)
            r.root = Path(directory)
            r.port = 18080
            with patch.object(r, "compose"):
                r.render(NEW)
            config = json.loads((r.root / "compose.json").read_text())
            for name, service in config["services"].items():
                self.assertNotIn("build", service)
                self.assertIn("healthcheck", service)
                self.assertIn("mem_limit", service)
                self.assertNotIn("environment", service)
                if name != "nginx":
                    self.assertNotIn("ports", service)
            self.assertEqual(config["services"]["app"]["image"], NEW["image"])
            self.assertEqual(config["services"]["nginx"]["ports"], ["127.0.0.1:18080:8080"])

    def test_missing_env(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "app.env"
            p.write_text("JWT_SECRET=\n")
            with self.assertRaises(cd.ReleaseError):
                cd.read_env(p, ["JWT_SECRET"])


class SmokeTests(unittest.TestCase):
    def responses(self):
        return [
            dict(status="ok"),
            dict(status="ok"),
            dict(version=NEW["version"], commit=NEW["commit"]),
            dict(access_token="fake"),
            dict(username="observer", is_active=True),
            dict(items=[dict(id=1)], total=1),
            dict(id=1, number="A101"),
        ]

    def check(self, values):
        with patch.object(cd, "request", side_effect=values):
            cd.smoke(
                "http://127.0.0.1", NEW, dict(SMOKE_USERNAME="observer", SMOKE_PASSWORD="test")
            )

    def test_success(self):
        self.check(self.responses())

    def test_version_mismatch(self):
        values = self.responses()
        values[2]["commit"] = "a" * 40
        with self.assertRaises(cd.ReleaseError):
            self.check(values)

    def test_running_app_but_empty_catalogue(self):
        values = self.responses()
        values[5] = dict(items=[], total=0)
        with self.assertRaises(cd.ReleaseError):
            self.check(values)

    def test_broken_login(self):
        values = self.responses()
        values[3] = {}
        with self.assertRaises(cd.ReleaseError):
            self.check(values)

    def test_broken_card(self):
        values = self.responses()
        values[-1] = dict(id=999)
        with self.assertRaises(cd.ReleaseError):
            self.check(values)


if __name__ == "__main__":
    unittest.main(verbosity=2)
