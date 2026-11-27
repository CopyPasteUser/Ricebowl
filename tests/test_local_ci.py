"""Fast, compositor-free tests for scripts/local_ci.py (receipt, selection, refusals)."""
from __future__ import annotations

import copy
import getpass
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("local_ci", ROOT / "scripts" / "local_ci.py")
lci = importlib.util.module_from_spec(spec)
sys.modules["local_ci"] = lci
spec.loader.exec_module(lci)

WORKFLOWS = ROOT / ".github" / "workflows"
SHA = "a" * 40


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, env=env).stdout.strip()


def make_repo(root: Path, files: dict[str, str] | None = None) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    for name, text in (files or {"a.txt": "one\n"}).items():
        (repo / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "first [skip ci]")
    return repo, git(repo, "rev-parse", "HEAD")


def passing_record(sid: str, status: str = "PASS", **over) -> dict:
    rec = {
        "id": sid, "workflow": "x.yml", "job": "j", "step": "s", "status": status,
        "exit_code": 0 if status == "PASS" else (None if status == "SKIPPED" else 1),
        "duration_s": 1.0,
        "log": f"logs/{sid}.log" if status in ("PASS", "FAIL") else None,
        "log_sha256": "b" * 64 if status in ("PASS", "FAIL") else None,
        "script_sha256": "c" * 64,
        "detail": "" if status in ("PASS", "FAIL") else "reason",
        "auto_included": False, "timeout_s": 10,
    }
    rec.update(over)
    return rec


def make_receipt(statuses: dict[str, str], tree_clean: bool = True) -> dict:
    records = [passing_record(sid, st) for sid, st in statuses.items()]
    counts = {s: sum(1 for r in records if r["status"] == s) for s in lci.STATUSES}
    return {
        "schema_version": 1, "local_ci_version": 1, "sha": SHA, "commit_date": "2026-11-27T00:00:00+00:00",
        "tree_clean": tree_clean, "tree_clean_after_run": True, "modified_tracked_files": [],
        "host": {"id": "ubuntu", "version_id": "24.04", "pretty_name": "Ubuntu 24.04"},
        "kernel": "6.0 test", "run_as": "rbdev",
        "tools": {k: None for k in lci.TOOL_KEYS},
        "rust_toolchain_pin": {"pinned": "1.88.0", "actual": "1.88.0", "matches": True},
        "worker": "host-a", "runner_name": "local-ci-test",
        "started_at": "2026-11-27T00:00:00+00:00", "finished_at": "2026-11-27T00:01:00+00:00",
        "catalog_sha256": "d" * 64, "selected_steps": list(statuses), "auto_included_steps": [],
        "counts": counts, "complete": lci.is_complete(records, list(statuses), tree_clean),
        "steps": records, "artifacts": {"sg6_worker": None, "sg6_packages": {}, "preview_packages": {}},
    }


class CatalogTests(unittest.TestCase):
    def test_ids_unique_scripts_exist_and_parse(self):
        ids = [s.id for s in lci.CATALOG]
        self.assertEqual(len(ids), len(set(ids)))
        for step in lci.CATALOG:
            self.assertTrue(step.script.is_file(), step.id)
            lci.step_mirrors(step)                      # header present and well-formed
            result = subprocess.run(["bash", "-n", str(step.script)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"{step.id}: {result.stderr}")
        orphans = {p.stem for p in lci.STEP_DIR.glob("*.sh")} - set(ids)
        self.assertFalse(orphans, f"step scripts without a catalog entry: {orphans}")

    def test_prerequisites_exist_and_run_earlier(self):
        position = {s.id: i for i, s in enumerate(lci.CATALOG)}
        for step in lci.CATALOG:
            for need in step.needs:
                self.assertIn(need, position, f"{step.id} needs unknown {need}")
                self.assertLess(position[need], position[step.id], f"{step.id} runs before {need}")

    def test_required_spec_step_ids_exist(self):
        for sid in ("py-tests", "rust-test", "rust-clippy", "rust-fmt", "native-smoke",
                    "sg1-interaction", "sg3-ricepop", "sg5-atspi", "pkg-build"):
            self.assertIn(sid, {s.id for s in lci.CATALOG})

    def test_preflight_tokens_are_known(self):
        for step in lci.CATALOG:
            for token in step.requires:
                kind = token.partition(":")[0]
                self.assertIn(kind if ":" in token else token,
                              {"cmd", "py", "file", "pkgconfig", "docker", "drm"}, token)

    @unittest.skipUnless(WORKFLOWS.is_dir(), "workflows removed from this checkout")
    def test_every_workflow_run_step_is_translated_or_explicitly_excluded(self):
        import yaml
        covered = lci.covered_workflow_steps()
        excluded = {(w, j, n) for w, j, n, _ in lci.NOT_TRANSLATED}
        actual = set()
        for path in sorted(WORKFLOWS.glob("*.yml")):
            doc = yaml.safe_load(path.read_text())
            for job, body in doc["jobs"].items():
                for step in body["steps"]:
                    if "run" in step:
                        actual.add((path.name, job, step["name"]))
        unmapped = actual - covered - excluded
        self.assertFalse(unmapped, f"workflow steps with neither a local step nor an exclusion: {sorted(unmapped)}")
        stale = (covered | excluded) - actual
        self.assertFalse(stale, f"catalog/exclusions name workflow steps that no longer exist: {sorted(stale)}")
        self.assertFalse(covered & excluded, "a step is both translated and excluded")
        for _, _, _, reason in lci.NOT_TRANSLATED:
            self.assertGreater(len(reason), 10)

    @unittest.skipUnless(WORKFLOWS.is_dir(), "workflows removed from this checkout")
    def test_translated_bodies_match_workflow_text(self):
        """Single-step snapshots must still match the workflow body (drift detector)."""
        import yaml
        by_key = {}
        for path in WORKFLOWS.glob("*.yml"):
            doc = yaml.safe_load(path.read_text())
            for job, body in doc["jobs"].items():
                for step in body["steps"]:
                    if "run" in step:
                        by_key[(path.name, job, step["name"])] = step["run"]
        verbatim = ("sg1-sni", "sg1-status", "sg1-interaction", "sg4-imported-rices", "native-smoke",
                    "shared-engine-smoke", "creator-gtk-wayland", "pkg-clean-rebuild", "capture-validation")
        for sid in verbatim:
            wf, job, name = lci.step_mirrors(lci.CATALOG_BY_ID[sid])
            body = lci.CATALOG_BY_ID[sid].script.read_text()
            for line in by_key[(wf, job, name)].strip().splitlines():
                if line.strip():
                    self.assertIn(line.rstrip(), body, f"{sid}: workflow line missing from local step")


class SelectionTests(unittest.TestCase):
    def test_default_and_all_select_everything_in_catalog_order(self):
        ids, auto = lci.select_steps(None)
        self.assertEqual(ids, [s.id for s in lci.CATALOG])
        self.assertEqual(auto, set())
        self.assertEqual(lci.select_steps("all")[0], ids)

    def test_subset_keeps_catalog_order_not_argument_order(self):
        ids, auto = lci.select_steps("rust-fmt,py-compile")
        self.assertEqual(ids, ["py-compile", "rust-fmt"])
        self.assertEqual(auto, set())

    def test_prerequisites_are_auto_included_and_reported(self):
        ids, auto = lci.select_steps("pkg-native-deb")
        self.assertEqual(ids[:3], ["rust-build", "pkg-preview-artifact", "pkg-native-deb"])
        self.assertEqual(auto, {"rust-build", "pkg-preview-artifact"})

    def test_tag_groups(self):
        ids, _ = lci.select_steps("@compositor")
        self.assertIn("native-smoke", ids)
        self.assertNotIn("py-tests", ids)
        self.assertIn("rust-build", ids)                      # pulled in as a prerequisite

    def test_unknown_ids_groups_and_empty_names_are_refused(self):
        for bad in ("nope", "py-tests,nope", "@nope", "py-tests,,rust-test"):
            with self.assertRaises(lci.LocalCIError, msg=bad):
                lci.select_steps(bad)


class ReceiptTests(unittest.TestCase):
    IDS = {"a": "PASS", "b": "PASS", "c": "PASS"}

    def test_complete_requires_every_step_pass_and_clean_tree(self):
        recs = [passing_record(i) for i in "abc"]
        self.assertTrue(lci.is_complete(recs, "abc", True))
        self.assertFalse(lci.is_complete(recs, "abc", False))
        for bad in ("FAIL", "BLOCKED", "SKIPPED"):
            mutated = [passing_record("a"), passing_record("b", bad), passing_record("c")]
            self.assertFalse(lci.is_complete(mutated, "abc", True), bad)
        self.assertFalse(lci.is_complete(recs[:2], "abc", True), "absent step must not count as pass")

    def test_overall_exit_code(self):
        self.assertEqual(lci.overall_exit_code([passing_record("a"), passing_record("b", "SKIPPED")]), 0)
        self.assertEqual(lci.overall_exit_code([passing_record("a"), passing_record("b", "BLOCKED")]), 1)
        self.assertEqual(lci.overall_exit_code([passing_record("a", "FAIL")]), 1)
        self.assertEqual(lci.overall_exit_code([passing_record("a", "SKIPPED")]), 1, "nothing ran")

    def test_valid_receipt_has_no_problems(self):
        self.assertEqual(lci.validate_receipt(make_receipt(self.IDS), list(self.IDS)), [])

    def test_receipt_with_skipped_blocked_or_failed_is_never_complete(self):
        for bad in ("SKIPPED", "BLOCKED", "FAIL"):
            receipt = make_receipt({"a": "PASS", "b": bad})
            self.assertFalse(receipt["complete"], bad)
            self.assertEqual(lci.validate_receipt(receipt, ["a", "b"]), [], bad)
            forged = copy.deepcopy(receipt)
            forged["complete"] = True
            problems = lci.validate_receipt(forged, ["a", "b"])
            self.assertTrue(any("complete" in p for p in problems), f"{bad}: {problems}")

    def test_schema_violations_are_reported(self):
        base = make_receipt(self.IDS)
        cases = {}
        cases["missing"] = {k: v for k, v in base.items() if k != "kernel"}
        cases["extra"] = {**base, "surprise": 1}
        cases["sha"] = {**base, "sha": "short"}
        cases["flag"] = {**base, "tree_clean": "yes"}
        cases["counts"] = {**base, "counts": {**base["counts"], "PASS": 9}}
        dup = copy.deepcopy(base)
        dup["steps"].append(copy.deepcopy(dup["steps"][0]))
        cases["duplicate"] = dup
        nolog = copy.deepcopy(base)
        nolog["steps"][0]["log_sha256"] = None
        cases["log hash"] = nolog
        badstatus = copy.deepcopy(base)
        badstatus["steps"][0]["status"] = "GREEN"
        cases["status"] = badstatus
        noreason = make_receipt({"a": "PASS", "b": "BLOCKED"})
        noreason["steps"][1]["detail"] = ""
        cases["no reason"] = noreason
        notools = copy.deepcopy(base)
        notools["tools"] = {"rustc": None}
        cases["tools"] = notools
        for name, receipt in cases.items():
            self.assertTrue(lci.validate_receipt(receipt, list(self.IDS)), name)
        self.assertTrue(lci.validate_receipt([], None))

    def test_receipt_missing_a_catalog_step_is_flagged(self):
        problems = lci.validate_receipt(make_receipt({"a": "PASS"}), ["a", "b"])
        self.assertTrue(any("absent" in p for p in problems))

    def test_summary_mentions_toolchain_mismatch_and_reasons(self):
        receipt = make_receipt({"a": "PASS", "b": "BLOCKED"})
        receipt["rust_toolchain_pin"] = lci.rust_pin("rustc 1.97.0 (x)")
        text = lci.render_summary(receipt)
        self.assertIn("INCOMPLETE", text)
        self.assertIn("WARNING: Rust toolchain '1.97.0'", text)
        self.assertIn("`b` BLOCKED: reason", text)
        self.assertIn("| `a` | PASS |", text)

    def test_rust_pin(self):
        self.assertTrue(lci.rust_pin("rustc 1.88.0 (abc 2025-06-23)")["matches"])
        self.assertFalse(lci.rust_pin("rustc 1.97.0 (x)")["matches"])
        self.assertIsNone(lci.rust_pin(None)["actual"])

    def test_verify_receipt_detects_log_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "logs").mkdir()
            (out / "logs" / "a.log").write_text("hello\n")
            receipt = make_receipt({s.id: "PASS" for s in lci.CATALOG})
            for rec in receipt["steps"]:
                rec["log"] = None if rec["id"] != "py-compile" else "logs/a.log"
                rec["log_sha256"] = lci.sha256_file(out / "logs" / "a.log") if rec["log"] else "e" * 64
            (out / "receipt.json").write_text(json.dumps(receipt))
            with mock.patch("sys.stderr"), mock.patch("builtins.print"):
                self.assertEqual(lci.verify_receipt(out / "receipt.json"), 0)
                (out / "logs" / "a.log").write_text("tampered\n")
                self.assertEqual(lci.verify_receipt(out / "receipt.json"), 1)


class CommitResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lci-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo, self.sha = make_repo(self.tmp)

    def test_clean_head_resolves_to_full_sha_and_date(self):
        sha, date = lci.resolve_commit(str(self.repo), None)
        self.assertEqual(sha, self.sha)
        self.assertRegex(date, r"^\d{4}-\d\d-\d\dT")

    def test_abbreviated_and_ref_names_resolve(self):
        self.assertEqual(lci.resolve_commit(str(self.repo), self.sha[:10])[0], self.sha)
        self.assertEqual(lci.resolve_commit(str(self.repo), "HEAD")[0], self.sha)

    def test_unknown_sha_ref_and_option_are_refused(self):
        for bad in ("f" * 40, "no-such-branch", "--output=x", "HEAD~50"):
            with self.assertRaises(lci.LocalCIError, msg=bad):
                lci.resolve_commit(str(self.repo), bad)

    def test_missing_repository_is_refused(self):
        with self.assertRaises(lci.LocalCIError):
            lci.resolve_commit(str(self.tmp / "absent"), self.sha)      # not local, not 40-hex remote
        with self.assertRaises(lci.LocalCIError):
            lci.resolve_commit("https://example.invalid/x.git", None)    # remote needs explicit sha
        self.assertEqual(lci.resolve_commit("https://example.invalid/x.git", self.sha)[0], self.sha)

    def test_dirty_tracked_tree_is_refused_for_head(self):
        (self.repo / "a.txt").write_text("edited\n")
        with self.assertRaisesRegex(lci.LocalCIError, "dirty"):
            lci.resolve_commit(str(self.repo), None)
        with self.assertRaisesRegex(lci.LocalCIError, "dirty"):
            lci.resolve_commit(str(self.repo), self.sha)

    def test_dirty_tree_does_not_taint_an_older_explicit_commit(self):
        (self.repo / "b.txt").write_text("two\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "second [skip ci]")
        (self.repo / "a.txt").write_text("edited\n")
        self.assertEqual(lci.resolve_commit(str(self.repo), self.sha)[0], self.sha)
        with self.assertRaises(lci.LocalCIError):
            lci.resolve_commit(str(self.repo), None)

    def test_untracked_files_alone_do_not_make_head_dirty(self):
        (self.repo / "scratch.txt").write_text("x\n")
        self.assertEqual(lci.resolve_commit(str(self.repo), None)[0], self.sha)

    def test_main_refuses_with_status_2_and_writes_nothing(self):
        (self.repo / "a.txt").write_text("edited\n")
        out = self.tmp / "out"
        with mock.patch("sys.stderr"):
            code = lci.main(["--repo", str(self.repo), "--out", str(out), "--steps", "py-compile"])
        self.assertEqual(code, 2)
        self.assertFalse(out.exists())
        with mock.patch("sys.stderr"):
            self.assertEqual(lci.main(["--repo", str(self.repo), "--sha", "f" * 40]), 2)
            self.assertEqual(lci.main(["--repo", str(self.repo), "--steps", "bogus"]), 2)


class CloneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lci-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo, self.sha = make_repo(self.tmp)

    def test_fresh_detached_clone_of_exact_sha(self):
        (self.repo / "later.txt").write_text("later\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "later [skip ci]")
        dest = self.tmp / "clone"
        lci.prepare_clone(str(self.repo), self.sha, dest, None)
        self.assertEqual(git(dest, "rev-parse", "HEAD"), self.sha)
        self.assertFalse((dest / "later.txt").exists())
        self.assertEqual(git(dest, "status", "--porcelain"), "")
        (dest / "target").mkdir()
        (dest / "target" / "x").write_text("build product")
        self.assertEqual(git(dest, "status", "--porcelain"), "", "build products must not dirty the clone")

    def test_unknown_commit_is_refused(self):
        with self.assertRaises(lci.LocalCIError):
            lci.prepare_clone(str(self.repo), "f" * 40, self.tmp / "clone2", None)


class EndToEndTests(unittest.TestCase):
    """Drives the real orchestrator with a tiny fake catalog (no compositor, no network)."""

    def setUp(self):
        if not shutil.which("dbus-run-session"):
            self.skipTest("dbus-run-session not installed")
        self.tmp = Path(tempfile.mkdtemp(prefix="lci-e2e-"))
        os.chmod(self.tmp, 0o755)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo, self.sha = make_repo(self.tmp)
        self.steps = self.tmp / "steps"
        self.steps.mkdir()
        scripts = {
            "ok": 'echo hello from ok; test "$GITHUB_SHA" = "$(git rev-parse HEAD)"; test -z "$XDG_RUNTIME_DIR"',
            "dep": "test -f produced.txt",
            "prod": "echo made > produced.txt",
            "bad": "echo failing; exit 3",
            "blk": 'echo "LOCAL_CI_BLOCKED: network unavailable"; exit 77',
            "slow": "sleep 30",
            "tool": "true",
            "never": "true",
        }
        for sid, body in scripts.items():
            (self.steps / f"{sid}.sh").write_text(f"#!/bin/bash\n# Mirrors: fake.yml / job / step {sid}\n{body}\n")
        self.fake = (
            lci._s("prod", 30, "static"),
            lci._s("ok", 30, "static"),
            lci._s("dep", 30, "static", needs="prod"),
            lci._s("bad", 30, "static"),
            lci._s("blk", 30, "static"),
            lci._s("slow", 2, "static"),
            lci._s("tool", 30, "static", requires="cmd:definitely-not-installed-xyz"),
            lci._s("never", 30, "static", needs="bad"),
        )
        user = ["--user", getpass.getuser() if os.geteuid() else "root"]
        self.base_args = ["--repo", str(self.repo), "--sha", self.sha, "--out", str(self.tmp / "out"),
                          "--cache-dir", str(self.tmp / "cache"), "--tmp-base", str(self.tmp), *user]

    def run_main(self, *extra: str) -> int:
        with mock.patch.object(lci, "CATALOG", self.fake), mock.patch.object(lci, "STEP_DIR", self.steps), \
                mock.patch("builtins.print"):
            return lci.main([*self.base_args, *extra])

    def test_full_fake_run_statuses_receipt_and_exit_code(self):
        code = self.run_main()
        self.assertEqual(code, 1)
        out = self.tmp / "out"
        receipt = json.loads((out / "receipt.json").read_text())
        status = {r["id"]: r for r in receipt["steps"]}
        self.assertEqual({k: v["status"] for k, v in status.items()},
                         {"prod": "PASS", "ok": "PASS", "dep": "PASS", "bad": "FAIL", "blk": "BLOCKED",
                          "slow": "FAIL", "tool": "BLOCKED", "never": "BLOCKED"})
        self.assertEqual(status["bad"]["exit_code"], 3)
        self.assertEqual(status["blk"]["exit_code"], 77)
        self.assertEqual(status["blk"]["detail"], "network unavailable")
        self.assertIn("runner timeout", status["slow"]["detail"])
        self.assertEqual(status["slow"]["exit_code"], 124)
        self.assertIn("definitely-not-installed-xyz", status["tool"]["detail"])
        self.assertIn("bad=FAIL", status["never"]["detail"])
        self.assertIsNone(status["never"]["log"])
        self.assertFalse(receipt["complete"])
        self.assertEqual(receipt["sha"], self.sha)
        self.assertTrue(receipt["tree_clean"])
        self.assertEqual(lci.validate_receipt(receipt, [s.id for s in self.fake]), [])
        self.assertEqual(lci.sha256_file(out / status["ok"]["log"]), status["ok"]["log_sha256"])
        self.assertIn("hello from ok", (out / status["ok"]["log"]).read_text())
        self.assertIn("Not passing", (out / "summary.md").read_text())
        self.assertEqual((out / ".gitignore").read_text().split(), ["logs/", "artifacts/"])
        self.assertFalse(list(self.tmp.glob("rbci.*")), "temporary clone must be removed")

    def test_subset_marks_others_skipped_and_never_complete(self):
        code = self.run_main("--steps", "ok")
        self.assertEqual(code, 0)
        receipt = json.loads((self.tmp / "out" / "receipt.json").read_text())
        status = {r["id"]: r["status"] for r in receipt["steps"]}
        self.assertEqual(status["ok"], "PASS")
        self.assertTrue(all(v == "SKIPPED" for k, v in status.items() if k != "ok"))
        self.assertFalse(receipt["complete"])
        self.assertEqual(receipt["selected_steps"], ["ok"])
        self.assertEqual(receipt["counts"]["SKIPPED"], len(self.fake) - 1)

    def test_prerequisite_is_auto_included_and_shared_clone_state_is_visible(self):
        code = self.run_main("--steps", "dep")
        self.assertEqual(code, 0)
        receipt = json.loads((self.tmp / "out" / "receipt.json").read_text())
        status = {r["id"]: r for r in receipt["steps"]}
        self.assertEqual(status["prod"]["status"], "PASS")
        self.assertTrue(status["prod"]["auto_included"])
        self.assertEqual(receipt["auto_included_steps"], ["prod"])
        self.assertEqual(status["dep"]["status"], "PASS")

    def test_all_pass_catalog_is_complete(self):
        self.fake = (self.fake[0], self.fake[1], self.fake[2])
        self.assertEqual(self.run_main(), 0)
        receipt = json.loads((self.tmp / "out" / "receipt.json").read_text())
        self.assertTrue(receipt["complete"])
        with mock.patch.object(lci, "CATALOG", self.fake), mock.patch.object(lci, "STEP_DIR", self.steps), \
                mock.patch("builtins.print"):
            self.assertEqual(lci.verify_receipt(self.tmp / "out" / "receipt.json"), 0)

    def test_fail_fast_skips_remaining_steps(self):
        self.assertEqual(self.run_main("--fail-fast", "--steps", "bad,blk"), 1)
        receipt = json.loads((self.tmp / "out" / "receipt.json").read_text())
        status = {r["id"]: r for r in receipt["steps"]}
        self.assertEqual(status["bad"]["status"], "FAIL")
        self.assertEqual(status["blk"]["status"], "SKIPPED")     # catalog order: bad runs before blk
        self.assertIn("fail-fast", status["blk"]["detail"])


if __name__ == "__main__":
    unittest.main()
