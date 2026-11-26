"""SG4 WP4.2: Creator -> supervisor apply/restore robustness in disposable sessions.

Every case runs against a private HOME/XDG tree. The supervisor and the
Creator client are real, separate OS processes talking over the real private
control socket; crashes are real SIGKILLs injected at the real write
boundaries (journal publish, selection commit, pack-import publish). Only the
compositor-facing children (labwc/waybar/swaybg) are in-process stand-ins, so
these tests do not certify a real compositor (see the SG4 QA document).
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from macrice.de import (creator_activation as activation, creator_workspace as workspace,
                        live, live_recovery, pack, recipes, staging)
from macrice.de.session import _LiveSwitch, resources
from tests.test_de_live import FakeProcess

ROOT = Path(__file__).resolve().parents[1]

# A real supervisor loop (listener + _LiveSwitch) with fake compositor
# children. SG4_CRASH selects a SIGKILL at a genuine write boundary.
SUPERVISOR = r"""
import os, signal, sys
from contextlib import ExitStack
from unittest import mock
from macrice.de import live, live_recovery, recipes
from macrice.de.session import _LiveSwitch

def die():
    os.kill(os.getpid(), signal.SIGKILL)

class P:
    dead = False
    def poll(self): return 0 if self.dead else None
    def terminate(self): self.dead = True
    kill = terminate
    def wait(self, timeout=None): return 0

crash = os.environ.get("SG4_CRASH")
if crash == "torn_journal":
    real = recipes._write_private_new
    def torn(destination, payload, **kw):
        if kw.get("suffix") == ".pending":
            keep = int(os.environ["SG4_TORN_BYTES"])
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, payload[:keep]); os.close(fd); die()
        return real(destination, payload, **kw)
    recipes._write_private_new = torn
elif crash == "before_link":
    real_link = os.link
    def link(src, dst, *a, **kw):
        if str(dst).endswith(".live-switch.pending"):
            die()
        return real_link(src, dst, *a, **kw)
    os.link = link
elif crash == "after_journal":
    real = live_recovery.begin
    def begin(*a, **kw):
        result = real(*a, **kw); die(); return result
    live_recovery.begin = begin
elif crash == "after_selection":
    real = recipes.change_selection
    def change(*a, **kw):
        result = real(*a, **kw); die(); return result
    recipes.change_selection = change

env = dict(os.environ)
wallpaper = P()
controller = _LiveSwitch(env=env, mode="native", which=lambda name: "/usr/bin/" + name,
                         spawn=lambda command, **kw: P(), cleanup=ExitStack(),
                         initial_panel=P(), initial_wallpaper=wallpaper,
                         background=[wallpaper], frame_readiness=False)
controller._reconfigure = lambda: None
with mock.patch("macrice.de.session.time.sleep"), live.listen(env) as listener:
    print("ready", flush=True)
    while True:
        live.serve_once(listener, controller.handle)
"""

# The real Creator client path (inspect_live + apply_live/restore_live) that
# dies the instant the confirmed request has been written to the socket.
CREATOR = r"""
import os, signal, sys
from pathlib import Path
from macrice.de import creator_activation as activation, creator_workspace as workspace, live

def die(client):
    os.kill(os.getpid(), signal.SIGKILL)

if sys.argv[1] == "apply":
    plan = activation.inspect_live(workspace.open_draft(Path(sys.argv[2])))
    live._read_response = die
    activation.apply_live(plan)
else:
    plan = activation.inspect_restore()
    live._read_response = die
    activation.restore_live(plan)
"""

READ_LOGIN = r"""
import json
from macrice.de import live_recovery, recipes, staging
report = live_recovery.reconcile()
try:
    selected = recipes.selected_recipe()
except recipes.RecipeError as exc:
    selected = "ERROR: " + str(exc)
print(json.dumps({"reconcile": report, "selected": selected,
                  "snapshot": recipes._selection_snapshot() if report["status"] != "unsafe" else None}))
"""


def digest_tree(root: Path, skip: tuple[Path, ...] = ()) -> dict[str, tuple]:
    """Byte-exact snapshot (content, mode, mtime) of everything outside `skip`."""
    seen = {}
    for path in sorted(root.rglob("*")):
        if any(path == item or item in path.parents for item in skip):
            continue
        info = path.lstat()
        body = (hashlib.sha256(path.read_bytes()).hexdigest()
                if stat.S_ISREG(info.st_mode) else
                os.readlink(path) if stat.S_ISLNK(info.st_mode) else None)
        seen[str(path.relative_to(root))] = (
            body, stat.S_IMODE(info.st_mode),
            info.st_mtime_ns if stat.S_ISREG(info.st_mode) else None)
    return seen


class DisposableSession(unittest.TestCase):
    """Private HOME/XDG tree with sentinel XFCE and login state."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.home = self.root / "home"
        self.runtime = self.root / "run"
        self.config = self.home / ".config"
        self.state = self.home / ".local/state"
        for path in (self.home, self.runtime, self.config, self.state):
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        xfce = self.config / "xfce4/xfconf/xfce-perchannel-xml"
        xfce.mkdir(parents=True)
        (xfce / "xfce4-session.xml").write_text("<channel name='xfce4-session'/>")
        (self.home / ".dmrc").write_text("[Desktop]\nSession=xfce\n")
        (self.home / ".xsession").write_text("exec startxfce4\n")
        self.session_dir = self.runtime / "ricebowl-labwc-test"
        self.session_dir.mkdir(mode=0o700)
        (self.session_dir / "menu.xml").write_text(
            (resources() / "labwc/menu.xml").read_text())
        (self.session_dir / "rc.xml").write_text((resources() / "labwc/rc.xml").read_text())
        self.env = {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.config),
                    "XDG_STATE_HOME": str(self.state), "XDG_RUNTIME_DIR": str(self.runtime),
                    "RICEBOWL_DE_SESSION_CONFIG": str(self.session_dir),
                    "WAYLAND_DISPLAY": "wayland-sg4", "RICEBOWL_DE_RECIPE": "classic"}
        patch = mock.patch.dict(os.environ, self.env)
        patch.start()
        self.addCleanup(patch.stop)
        self.xfce_before = self.xfce_state()

    def xfce_state(self):
        return digest_tree(self.home, skip=(self.config / "ricebowl",
                                            self.state / "ricebowl"))

    def assert_xfce_untouched(self):
        self.assertEqual(self.xfce_state(), self.xfce_before)

    def child(self, code, *args, extra=None, timeout=30):
        return subprocess.run([sys.executable, "-c", code, *args], cwd=ROOT,
                              env={**os.environ, **(extra or {})}, check=False,
                              capture_output=True, text=True, timeout=timeout)

    def start_supervisor(self, **extra):
        process = subprocess.Popen([sys.executable, "-c", SUPERVISOR], cwd=ROOT,
                                   env={**os.environ, **extra}, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(self._reap, process)
        line = process.stdout.readline()
        if line.strip() != "ready":
            process.kill()
            raise AssertionError(f"supervisor did not start: {process.stderr.read()}")
        return process

    @staticmethod
    def _reap(process):
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        for stream in (process.stdout, process.stderr):
            stream.close()

    def crashed(self, process):
        self.assertEqual(process.wait(timeout=15), -signal.SIGKILL)

    def selection_bytes(self):
        path = recipes._private_recipe_dir(create=False) / ".active-recipe"
        return path.read_bytes() if path.exists() else None

    def journal(self):
        return recipes._private_recipe_dir(create=False) / live_recovery.FILE_NAME

    def install_creator_rice(self):
        draft = workspace.create_draft("heritage")
        self.assertTrue(activation.install(activation.inspect_install(draft)))
        return draft


class CreatorKilledAfterConfirmedApplyTests(DisposableSession):
    def kill_creator(self, mode, *args):
        result = self.child(CREATOR, mode, *args)
        self.assertEqual(result.returncode, -signal.SIGKILL, result.stderr)

    def wait_for(self, active):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            status = live.request("status")  # serialized behind the in-flight apply
            if status["active"] == active:
                return status
            time.sleep(0.05)
        self.fail(f"supervisor never reached {active}")

    def test_sigkill_creator_after_confirmed_apply_then_explicit_restore(self):
        draft = self.install_creator_rice()
        digest = draft.semantic_sha256
        supervisor = self.start_supervisor()
        original = self.selection_bytes()
        self.assertIsNone(original)
        self.kill_creator("apply", str(draft.path))

        # Fully applied, never half applied: supervisor still alive and
        # serving, selection, journal and runtime files all agree.
        status = self.wait_for(draft.recipe_id)
        self.assertIsNone(supervisor.poll())
        self.assertEqual((status["previous"], status["can_restore"]), ("classic", True))
        self.assertEqual(status["semantic_sha256"], digest)
        self.assertEqual(recipes.current_selection(), (draft.recipe_id, "classic"))
        self.assertEqual(recipes.selected_recipe(), draft.recipe_id)
        self.assertFalse(self.journal().exists())
        self.assertEqual(live_recovery.status()["pending"], False)
        recipe = recipes.load(draft.recipe_id)
        self.assertEqual((self.session_dir / "menu.xml").read_text(),
                         recipes.labwc_menu(recipe, nested=False) if recipe.menu is not None
                         else (resources() / "labwc/menu.xml").read_text())

        # A brand-new Creator process can inspect and explicitly restore.
        plan = activation.inspect_restore()
        self.assertEqual((plan.expected_active, plan.previous), (draft.recipe_id, "classic"))
        restored = activation.restore_live(plan)
        self.assertEqual((restored["active"], restored["previous"]),
                         ("classic", draft.recipe_id))
        self.assertEqual(recipes.current_selection(), ("classic", draft.recipe_id))
        self.assertEqual((self.session_dir / "menu.xml").read_text(),
                         (resources() / "labwc/menu.xml").read_text())
        self.assertFalse(self.journal().exists())
        self.assertIsNone(supervisor.poll())
        self.assert_xfce_untouched()

    def test_sigkill_creator_after_confirmed_restore_still_completes_exactly_once(self):
        draft = self.install_creator_rice()
        self.start_supervisor()
        activation.apply_live(activation.inspect_live(draft))
        self.kill_creator("restore")
        status = self.wait_for("classic")
        self.assertEqual((status["previous"], status["can_restore"]),
                         (draft.recipe_id, True))
        self.assertEqual(recipes.current_selection(), ("classic", draft.recipe_id))
        self.assertFalse(self.journal().exists())
        # The dead Creator's retry token is stale, not silently re-applied.
        with self.assertRaises(activation.ActivationError):
            activation.restore_live(activation.RestorePlan(draft.recipe_id, "classic", True))
        self.assertEqual(live.request("status")["active"], "classic")
        self.assert_xfce_untouched()


class InterruptedJournalTests(DisposableSession):
    def crash_apply(self, crash, **extra):
        supervisor = self.start_supervisor(SG4_CRASH=crash, **extra)
        with self.assertRaises(live.LiveError):
            live.request("apply", recipe="chrome", sha256=staging._hash("chrome"),
                         expected="classic")
        self.crashed(supervisor)

    def fresh_login(self):
        result = self.child(READ_LOGIN)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_crash_before_journal_becomes_visible_leaves_nothing_and_is_retryable(self):
        original = self.selection_bytes()
        self.crash_apply("before_link")
        self.assertFalse(self.journal().exists())
        leftovers = list(self.journal().parent.glob(".ricebowl-recipe-*"))
        self.assertEqual(len(leftovers), 1)  # only the unpublished temp file
        login = self.fresh_login()
        self.assertEqual(login["reconcile"], {"status": "clean", "use_saved_selection": True})
        self.assertEqual(self.selection_bytes(), original)
        self.assertIsNone(login["selected"])
        # The next supervisor is fully functional despite the stray temp file.
        self.start_supervisor()
        self.assertEqual(live.request("apply", recipe="chrome", sha256=staging._hash("chrome"),
                                      expected="classic")["active"], "chrome")
        self.assert_xfce_untouched()

    def test_crash_after_complete_journal_before_selection_commit_rolls_back(self):
        original = self.selection_bytes()
        self.crash_apply("after_journal")
        self.assertTrue(self.journal().is_file())
        self.assertEqual(self.selection_bytes(), original)  # chrome was never committed
        self.assertTrue(live_recovery.status()["pending"])
        self.assertFalse(live_recovery.status()["owner_running"])
        login = self.fresh_login()
        self.assertEqual(login["reconcile"], {"status": "unchanged", "use_saved_selection": True})
        self.assertIsNone(login["selected"])
        self.assertFalse(self.journal().exists())
        self.assertEqual(self.selection_bytes(), original)
        self.assertEqual(self.fresh_login()["reconcile"]["status"], "clean")
        self.assert_xfce_untouched()

    def test_crash_after_selection_commit_rolls_back_to_exact_prior_state(self):
        staging.stage("chrome", staging._hash("chrome"))
        original = self.selection_bytes()
        supervisor = self.start_supervisor(SG4_CRASH="after_selection",
                                           RICEBOWL_DE_RECIPE="chrome")
        with self.assertRaises(live.LiveError):
            live.request("apply", recipe="classic", sha256=staging._hash("classic"),
                         expected="chrome")
        self.crashed(supervisor)
        self.assertNotEqual(self.selection_bytes(), original)  # committed, journal pending
        self.assertTrue(self.journal().is_file())
        login = self.fresh_login()
        self.assertEqual(login["reconcile"], {"status": "restored", "use_saved_selection": True})
        self.assertEqual(login["selected"], "chrome")
        # Same pinned state (the journal re-serializes keys in sorted order).
        self.assertEqual(json.loads(self.selection_bytes()), json.loads(original))
        self.assertFalse(self.journal().exists())
        self.assert_xfce_untouched()

    def test_torn_journal_is_never_applied_and_fails_closed_to_classic(self):
        staging.stage("chrome", staging._hash("chrome"))
        original = self.selection_bytes()
        for keep in (0, 1, 60, 150):
            with self.subTest(torn_bytes=keep):
                supervisor = self.start_supervisor(
                    SG4_CRASH="torn_journal", SG4_TORN_BYTES=str(keep),
                    RICEBOWL_DE_RECIPE="chrome")
                with self.assertRaises(live.LiveError):
                    live.request("apply", recipe="classic", sha256=staging._hash("classic"),
                                 expected="chrome")
                self.crashed(supervisor)
                self.assertEqual(self.journal().stat().st_size, keep)
                self.assertEqual(self.selection_bytes(), original)
                login = self.fresh_login()
                # Neither completed nor rolled back from guesswork: the saved
                # selection is not honored and nothing is rewritten.
                self.assertEqual(login["reconcile"],
                                 {"status": "unsafe", "use_saved_selection": False})
                self.assertEqual(self.selection_bytes(), original)
                self.assertTrue(self.journal().exists())
                self.assertFalse(live_recovery.status()["ok"])
                # A new supervisor refuses further live switching until an
                # operator clears the damaged journal; the active rice is kept.
                fresh = self.start_supervisor(RICEBOWL_DE_RECIPE="chrome")
                refused = live.request("apply", recipe="classic",
                                       sha256=staging._hash("classic"), expected="chrome")
                self.assertFalse(refused["ok"])
                self.assertEqual(refused["error"]["code"], "recovery_required")
                self.assertEqual(live.request("status")["active"], "chrome")
                self.assertEqual(self.selection_bytes(), original)
                fresh.kill()
                fresh.wait(timeout=10)
                self.journal().unlink()  # the documented operator recovery step
                self.assertEqual(self.fresh_login()["reconcile"]["status"], "clean")
        self.assert_xfce_untouched()


class MalformedConfigurationTests(DisposableSession):
    def setUp(self):
        super().setUp()
        self.spawned = []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.initial = (FakeProcess(), FakeProcess())

        def spawn(command, **kwargs):
            process = FakeProcess()
            self.spawned.append(process)
            return process

        self.controller = _LiveSwitch(
            env=dict(self.env), mode="native", which=lambda name: "/usr/bin/" + name,
            spawn=spawn, cleanup=self.stack, initial_panel=self.initial[0],
            initial_wallpaper=self.initial[1], background=[self.initial[1]],
            frame_readiness=False)
        patches = [mock.patch.object(self.controller, "_reconfigure"),
                   mock.patch("macrice.de.session.time.sleep")]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.menu = self.session_dir / "menu.xml"

    def handle(self, action, token=None, digest=None, expected=None):
        return self.controller.handle({"action": action, "recipe": token,
                                       "sha256": digest, "expected": expected})

    def assert_failed_closed(self, action, token, digest, expected, codes):
        menu, selection = self.menu.read_bytes(), self.selection_bytes()
        previous, started = self.controller.previous, len(self.spawned)
        with self.assertRaises(live.LiveError) as caught:
            self.handle(action, token, digest, expected)
        self.assertIn(caught.exception.code, codes)
        self.assertEqual(self.controller.active, expected)
        self.assertEqual(self.controller.previous, previous)
        self.assertEqual(self.menu.read_bytes(), menu)
        self.assertEqual(self.selection_bytes(), selection)
        self.assertFalse(self.journal().exists())
        self.assertTrue(all(process.terminated for process in self.spawned[started:]))
        self.assertFalse(self.controller.panel.terminated)

    def installed(self):
        source = self.root / "source.json"
        recipes.create_from_template(source="classic", destination=source,
                                     recipe_id="pack-rice", name="Pack rice",
                                     schema_version=5)
        recipes.import_recipe(source)
        return recipes._private_recipe_dir(create=False) / "pack-rice.json"

    def test_corrupt_installed_recipe_is_refused_and_previous_rice_stays_usable(self):
        target = self.installed()
        digest = staging._hash("pack-rice")
        good = target.read_bytes()
        self.handle("apply", "chrome", staging._hash("chrome"), "classic")
        outside = self.root / "outside.json"
        outside.write_bytes(good)
        outside.chmod(0o600)
        corruptions = {
            "truncated": lambda: target.write_bytes(good[: len(good) // 2]),
            "empty": lambda: target.write_bytes(b""),
            "garbage": lambda: target.write_bytes(b"\xff\xfe not json"),
            "oversize": lambda: target.write_bytes(b" " * (recipes.MAX_RECIPE_BYTES + 1)),
            "wrong id": lambda: target.write_bytes(good.replace(b'"pack-rice"', b'"other-rice"')),
            "group readable": lambda: target.chmod(0o640),
            "symlink": lambda: (target.unlink(), target.symlink_to(outside)),
        }
        for label, corrupt in corruptions.items():
            with self.subTest(label):
                target.unlink(missing_ok=True)
                target.write_bytes(good)
                target.chmod(0o600)
                corrupt()
                self.assert_failed_closed("apply", "pack-rice", digest, "chrome",
                                          {"invalid_recipe", "recipe_changed"})
                with self.assertRaises(staging.StageError):
                    staging.stage("pack-rice", digest)
                self.assertEqual(recipes.current_selection(), ("chrome", "classic"))
        self.assertEqual(outside.read_bytes(), good)
        # The previously working rice is still live, selectable and restorable.
        target.unlink(missing_ok=True)
        target.write_bytes(good)
        target.chmod(0o600)
        self.assertEqual(self.handle("restore", expected="chrome")["active"], "classic")
        self.assertEqual(self.handle("apply", "pack-rice", digest, "classic")["active"],
                         "pack-rice")
        self.assert_xfce_untouched()

    def test_corrupt_selection_state_fails_closed_everywhere(self):
        self.handle("apply", "chrome", staging._hash("chrome"), "classic")
        path = recipes._private_recipe_dir(create=False) / ".active-recipe"
        good = path.read_bytes()
        outside = self.root / "outside-selection"
        outside.write_bytes(good)
        outside.chmod(0o600)

        def make_symlink():
            path.unlink()
            path.symlink_to(outside)

        corruptions = {
            "truncated": lambda: path.write_bytes(good[:20]),
            "empty": lambda: path.write_bytes(b""),
            "duplicate keys": lambda: path.write_bytes(
                b'{"schema_version":1,"active":"chrome","active":"classic","previous":"classic"}'),
            "unknown version": lambda: path.write_bytes(
                b'{"schema_version":9,"active":"chrome","previous":"classic"}'),
            "path as recipe": lambda: path.write_bytes(
                b'{"schema_version":1,"active":"/etc/passwd","previous":"classic"}'),
            "world readable": lambda: path.chmod(0o644),
            "symlink": make_symlink,
        }
        for label, corrupt in corruptions.items():
            with self.subTest(label):
                path.unlink(missing_ok=True)
                path.write_bytes(good)
                path.chmod(0o600)
                corrupt()
                damaged = path.read_bytes() if path.exists() else None
                with self.assertRaises(recipes.RecipeError):
                    recipes.current_selection()
                with self.assertRaises(recipes.RecipeError):
                    recipes.selected_recipe()
                with self.assertRaises(staging.StageError) as refused:
                    staging.status()
                self.assertEqual(refused.exception.code, "invalid_selection_state")
                with self.assertRaises(staging.StageError):
                    staging.stage("classic", staging._hash("classic"))
                menu = self.menu.read_bytes()
                with self.assertRaises(live.LiveError):
                    self.handle("apply", "classic", staging._hash("classic"), "chrome")
                self.assertEqual(self.controller.active, "chrome")
                self.assertEqual(self.menu.read_bytes(), menu)
                self.assertFalse(self.journal().exists())
                self.assertEqual(path.read_bytes() if path.exists() else None, damaged)
                # A new supervisor does not die on it either; it serves classic.
                restarted = _LiveSwitch(
                    env={**self.env, "RICEBOWL_DE_RECIPE": "classic"}, mode="native",
                    which=lambda name: "/usr/bin/" + name, spawn=lambda *a, **k: FakeProcess(),
                    cleanup=ExitStack(), initial_panel=FakeProcess(),
                    initial_wallpaper=FakeProcess(), background=[],
                    frame_readiness=False)
                self.assertEqual(restarted.status()["active"], "classic")
        self.assertEqual(outside.read_bytes(), good)
        self.assert_xfce_untouched()

    def test_fifo_planted_over_state_files_cannot_hang_the_session(self):
        target = self.installed()
        self.handle("apply", "chrome", staging._hash("chrome"), "classic")
        directory = recipes._private_recipe_dir(create=False)
        snippet = ("import sys; from macrice.de import recipes\n"
                   "calls = {'load': lambda: recipes.load('pack-rice'),\n"
                   "         'current': recipes.current_selection,\n"
                   "         'selected': recipes.selected_recipe,\n"
                   "         'change': lambda: recipes.change_selection('classic')}\n"
                   "try: calls[sys.argv[1]](); print('no-error')\n"
                   "except (recipes.RecipeError, OSError): print('failed-closed')\n")
        cases = ((target.name, "load"), (".active-recipe", "current"),
                 (".active-recipe", "selected"), (".active-recipe", "change"),
                 (".active-recipe.lock", "change"))
        for name, call in cases:
            with self.subTest(name=name, call=call):
                path = directory / name
                backup = self.root / "backup"
                path.rename(backup)
                os.mkfifo(path, mode=0o600)
                try:
                    # A blocking open() would hit the timeout, not return.
                    result = self.child(snippet, call, timeout=15)
                finally:
                    path.unlink()
                    backup.rename(path)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "failed-closed")

    def test_unsafe_collection_directory_blocks_apply_but_not_the_running_rice(self):
        self.handle("apply", "chrome", staging._hash("chrome"), "classic")
        directory = recipes._private_recipe_dir(create=False)
        for label, damage in (("group writable", lambda: directory.chmod(0o770)),
                              ("world readable", lambda: directory.chmod(0o755))):
            with self.subTest(label):
                directory.chmod(0o700)
                damage()
                menu = self.menu.read_bytes()
                with self.assertRaises(live.LiveError):
                    self.handle("restore", expected="chrome")
                self.assertEqual(self.controller.active, "chrome")
                self.assertEqual(self.menu.read_bytes(), menu)
                with self.assertRaises(staging.StageError):
                    staging.status()
        directory.chmod(0o700)
        self.assertEqual(self.handle("restore", expected="chrome")["active"], "classic")
        # A symlink in place of the whole collection is equally refused.
        moved = directory.with_name("recipes-real")
        directory.rename(moved)
        directory.symlink_to(moved)
        with self.assertRaises(live.LiveError):
            self.handle("apply", "chrome", staging._hash("chrome"), "classic")
        self.assertEqual(self.controller.active, "classic")

    def test_corrupt_provenance_receipt_blocks_export_not_the_rice(self):
        draft = workspace.create_draft("heritage")
        archive = self.root / "heritage.ricepack"
        workspace.export_draft(draft, archive)
        pack.import_pack(archive)
        receipt = recipes._private_recipe_dir(create=False) / (
            f"{draft.recipe_id}.ricepack-provenance")
        good = receipt.read_bytes()
        self.handle("apply", "chrome", staging._hash("chrome"), "classic")
        for label, corrupt in {"truncated": lambda: receipt.write_bytes(good[:30]),
                               "wrong mode": lambda: receipt.chmod(0o644),
                               "empty": lambda: receipt.write_bytes(b"")}.items():
            with self.subTest(label):
                receipt.unlink()
                receipt.write_bytes(good)
                receipt.chmod(0o600)
                corrupt()
                output = self.root / f"{label.replace(' ', '-')}.ricepack"
                with self.assertRaises(pack.PackError):
                    pack.export_pack(draft.recipe_id, output)
                self.assertFalse(output.exists())
                self.assertEqual(self.controller.active, "chrome")
                self.assertEqual(recipes.current_selection(), ("chrome", "classic"))
        self.assert_xfce_untouched()


class NextLoginPersistenceTests(DisposableSession):
    def relaunch(self):
        result = self.child(READ_LOGIN + """
from macrice.de import staging
print(json.dumps(staging.status()))
""")
        self.assertEqual(result.returncode, 0, result.stderr)
        first, second = result.stdout.strip().splitlines()
        return json.loads(first), json.loads(second)

    def test_staged_selection_survives_restart_exactly_and_rollback_does_not_reappear(self):
        draft = self.install_creator_rice()
        confirmed = staging.stage(draft.recipe_id, draft.semantic_sha256)
        self.assertEqual((confirmed["next_session"], confirmed["previous"]),
                         (draft.recipe_id, "classic"))
        login, status = self.relaunch()
        self.assertEqual(login["reconcile"], {"status": "clean", "use_saved_selection": True})
        self.assertEqual(login["selected"], draft.recipe_id)
        self.assertEqual((status["next_session"], status["semantic_sha256"],
                          status["previous"], status["can_restore"]),
                         (draft.recipe_id, draft.semantic_sha256, "classic", True))
        # A stage with a stale review is rejected and never persists.
        with self.assertRaises(staging.StageError):
            staging.stage("chrome", "0" * 64)
        self.assertEqual(self.relaunch()[0]["selected"], draft.recipe_id)

        rolled = staging.rollback(expected_active=draft.recipe_id)
        self.assertEqual(rolled["next_session"], "classic")
        login, status = self.relaunch()
        self.assertEqual(login["selected"], "classic")
        self.assertEqual(status["next_session"], "classic")
        self.assertNotEqual(status["next_session"], draft.recipe_id)
        # A second restart still does not resurrect the rolled-back stage.
        self.assertEqual(self.relaunch()[0]["selected"], "classic")
        self.assert_xfce_untouched()

    def test_failed_live_apply_leaves_no_trace_for_the_next_login(self):
        draft = self.install_creator_rice()
        original = self.selection_bytes()
        stack = ExitStack()
        self.addCleanup(stack.close)
        controller = _LiveSwitch(
            env=dict(self.env), mode="native", which=lambda name: "/usr/bin/" + name,
            spawn=lambda command, **kw: FakeProcess(
                exit_code=1 if command[0].endswith("riceplate-native") else None),
            cleanup=stack, initial_panel=FakeProcess(), initial_wallpaper=FakeProcess(),
            background=[], frame_readiness=False)
        with (mock.patch.object(controller, "_reconfigure"),
              mock.patch("macrice.de.session.time.sleep"),
              self.assertRaises(live.LiveError)):
            controller.handle({"action": "apply", "recipe": draft.recipe_id,
                               "sha256": draft.semantic_sha256, "expected": "classic"})
        self.assertEqual(self.selection_bytes(), original)
        login, _ = self.relaunch()
        self.assertEqual(login["reconcile"], {"status": "clean", "use_saved_selection": True})
        self.assertIsNone(login["selected"])

    def test_confirmed_live_apply_persists_across_supervisor_and_login_restart(self):
        draft = self.install_creator_rice()
        supervisor = self.start_supervisor()
        activation.apply_live(activation.inspect_live(draft))
        supervisor.kill()
        supervisor.wait(timeout=10)  # session ends without any shutdown handshake
        login, _ = self.relaunch()
        self.assertEqual(login["reconcile"], {"status": "clean", "use_saved_selection": True})
        self.assertEqual(login["selected"], draft.recipe_id)
        self.assertEqual(login["snapshot"]["active_sha256"], draft.semantic_sha256)
        # The next login's supervisor starts on it and can restore the original.
        self.start_supervisor(RICEBOWL_DE_RECIPE=draft.recipe_id)
        status = live.request("status")
        self.assertEqual((status["active"], status["previous"]), (draft.recipe_id, "classic"))
        self.assertEqual(live.request("restore", expected=draft.recipe_id)["active"], "classic")
        self.assert_xfce_untouched()


PACK_CRASH = r"""
import os, signal, sys
from pathlib import Path
from macrice.de import pack, recipes

point = os.environ["SG4_PACK_CRASH"]
real = recipes._write_private_new

def hooked(destination, payload, **kw):
    name = destination.name
    pending = name == ".ricepack-import-pending.ricepack"
    receipt = name.endswith(".ricepack-provenance")
    recipe = name.endswith(".json") and not name.startswith(".")
    if point == "before_recipe" and recipe:
        os.kill(os.getpid(), signal.SIGKILL)
    result = real(destination, payload, **kw)
    if (point == "pending_only" and pending) or (point == "after_receipt" and receipt):
        os.kill(os.getpid(), signal.SIGKILL)
    return result

recipes._write_private_new = hooked
pack.import_pack(Path(sys.argv[1]))
"""


class PackImportCrashTests(DisposableSession):
    def export(self):
        draft = workspace.create_draft("orbit")
        archive = self.root / "orbit.ricepack"
        emitted = workspace.export_draft(draft, archive)
        return draft, archive, emitted

    def test_killed_import_never_exposes_a_partial_rice_and_recovers_exactly(self):
        draft, archive, emitted = self.export()
        for point in ("pending_only", "after_receipt", "before_recipe"):
            with self.subTest(point):
                folder = recipes._private_recipe_dir(create=True)
                for leftover in folder.iterdir():
                    leftover.unlink()
                result = self.child(PACK_CRASH, str(archive), extra={"SG4_PACK_CRASH": point})
                self.assertEqual(result.returncode, -signal.SIGKILL, result.stderr)
                self.assertFalse((folder / f"{draft.recipe_id}.json").exists())
                with self.assertRaises(recipes.RecipeError):
                    recipes.load(draft.recipe_id)
                with self.assertRaises(staging.StageError):
                    staging.stage(draft.recipe_id, draft.semantic_sha256)
                self.assertEqual(recipes.current_selection(), ("classic", None))
                self.assertIsNone(self.selection_bytes())
                recovered = pack.recover_pack_import()
                self.assertTrue(recovered["recovered"] and recovered["imported"], recovered)
                self.assertFalse(recovered["applied"])
                self.assertEqual(recovered["semantic_sha256"], draft.semantic_sha256)
                self.assertEqual(staging._hash(draft.recipe_id), draft.semantic_sha256)
                self.assertEqual(
                    (folder / f"{draft.recipe_id}.json").stat().st_mode & 0o777, 0o600)
                self.assertFalse(pack.recover_pack_import()["pending"])
                self.assertEqual(recipes.current_selection(), ("classic", None))
        self.assert_xfce_untouched()

    def test_torn_or_tampered_pending_archive_is_blocked_not_half_applied(self):
        draft, archive, emitted = self.export()
        result = self.child(PACK_CRASH, str(archive),
                            extra={"SG4_PACK_CRASH": "pending_only"})
        self.assertEqual(result.returncode, -signal.SIGKILL, result.stderr)
        folder = recipes._private_recipe_dir(create=False)
        pending = folder / ".ricepack-import-pending.ricepack"
        good = pending.read_bytes()
        for label, damage in {"truncated": lambda: pending.write_bytes(good[: len(good) // 2]),
                              "empty": lambda: pending.write_bytes(b""),
                              "wrong mode": lambda: pending.chmod(0o644)}.items():
            with self.subTest(label):
                pending.unlink(missing_ok=True)
                pending.write_bytes(good)
                pending.chmod(0o600)
                damage()
                with self.assertRaises(pack.PackError):
                    pack.recover_pack_import()
                with self.assertRaises(pack.PackError):
                    pack.import_pack(archive)  # must not bypass a blocked journal
                self.assertFalse((folder / f"{draft.recipe_id}.json").exists())
                self.assertEqual(recipes.current_selection(), ("classic", None))
        pending.unlink()
        pending.write_bytes(good)
        pending.chmod(0o600)
        self.assertTrue(pack.recover_pack_import()["imported"])
        self.assertEqual(staging._hash(draft.recipe_id), draft.semantic_sha256)


if __name__ == "__main__":
    unittest.main()
