# Local CI receipts

Hosted GitHub Actions are not used (owner decision, 27 November 2026; see
[de-integration-governance.md](../../de-integration-governance.md)). Wherever a
gate says *exact-head CI*, *exact-main CI* or *hosted CI*, the evidence is a
**local CI receipt** produced by `scripts/local_ci.sh` for that exact SHA.
Every commit and merge commit keeps `[skip ci]`, so a push never starts a hosted run.

Only `receipt.json` and `summary.md` of a run are meant to be committed. The
per-step logs under `<sha12>/logs/` and any built packages under
`<sha12>/artifacts/` are local-only (`.gitignore`); the receipt stores each
log's SHA-256 so a reviewer holding the logs can verify them.

## Running it

```sh
# Full run of the current clean HEAD (as root on the CI host; it drops to rbdev itself)
scripts/local_ci.sh

# A specific commit, from a specific checkout, into a specific directory
scripts/local_ci.sh --repo /path/to/repo --sha <40-hex-or-ref> --out /some/dir

# List the steps, which workflow step each mirrors, and what is deliberately not translated
scripts/local_ci.sh --list

# Subsets: ids and/or @tag groups; prerequisites are added and reported as auto_included
scripts/local_ci.sh --steps py-tests,rust-test,rust-clippy,rust-fmt
scripts/local_ci.sh --steps @static          # no compositor, no X11, no Docker
scripts/local_ci.sh --steps @compositor      # every labwc smoke (plus rust-build etc.)

# Check an existing receipt (schema, `complete` really derived from the steps, log hashes)
scripts/local_ci.sh --verify-receipt docs/evidence/local-ci/<sha12>/receipt.json
```

Tags: `static` (unit/syntax/build/package, no display), `unit`, `build`,
`packaging`, `x11` (Xvfb GTK), `compositor` (real labwc), `docker`.

What a run does:

1. Resolves the SHA and **refuses** (exit 2, nothing written) if it cannot be
   resolved to a commit, or if it is the checked-out `HEAD` of a local
   `--repo` that has uncommitted tracked changes. A remote `--repo` needs an
   explicit 40-hex `--sha`.
2. Clones the commit fresh (`git clone --no-hardlinks`, detached checkout,
   `HEAD == SHA`, status clean) into `/var/tmp/rbci.*`, owned by `rbdev`, and
   removes it afterwards (`--keep` keeps it). `target/` and `dist/` are excluded
   in the clone's private `.git/info/exclude`; tracked files are never touched.
3. Runs each selected step **strictly sequentially** as `rbdev` via `runuser`,
   with a scrubbed environment: `LANG=C.UTF-8`, `XDG_RUNTIME_DIR=` (empty),
   every step inside `dbus-run-session`, `python3` pinned to `/usr/bin/python3`
   (as on the hosted runners), a fresh private `HOME`, `TMPDIR` and `RUNNER_TEMP` per run (cargo still uses
   `/home/rbdev/.cargo` for the offline crate cache) so
   concurrent smokes on the same host cannot see each other's runtimes, and
   `GITHUB_SHA` set to the tested SHA. `GITHUB_ACTIONS` is deliberately **not**
   set. The agent proxy CA is handed over exactly as `/usr/local/bin/rb-run` does.
4. Enforces a per-step timeout (the workflow step's `timeout-minutes` when it has
   one, else the internal `timeout` of the step plus a margin, else the job
   timeout; see `scripts/local_ci.py`). A runner timeout is a FAIL (exit code 124).
   The step's whole process group is terminated when it ends, so no compositor
   or daemon outlives its step.
5. Writes `logs/<id>.log`, `receipt.json` and `summary.md`.

Exit status: `0` only if every selected step is PASS; `1` if any is
FAIL/BLOCKED; `2` for usage errors and refusals.

## Statuses

| Status | Meaning |
| --- | --- |
| `PASS` | the translated workflow commands ran and exited 0 |
| `FAIL` | a command failed or the runner timeout expired |
| `BLOCKED` | the step could not run honestly: a required tool is missing (the preflight replaces the workflows' `apt install`), a prerequisite step is not PASS, the Docker daemon is not reachable, a pinned source cannot be fetched (a step may exit `77` after printing `LOCAL_CI_BLOCKED: <reason>`). Nothing is mocked or substituted. |
| `SKIPPED` | not selected by `--steps` (or after `--fail-fast`) |

## What a complete receipt means

`"complete": true` means **all** of: the whole catalog (every step, not a subset)
ran against a clean checkout of the exact SHA and **every** step is PASS. Any
SKIPPED, FAIL or BLOCKED step makes the receipt incomplete, so a `--steps`
subset is never complete. `--verify-receipt` recomputes the flag from the step
records and rejects a receipt whose flag disagrees.

A complete receipt is the local replacement for green hosted CI on that SHA. It is
**software evidence only**:

- it does not replace the physical-device/hardware sign-off, which is recorded
  separately in `.github/release-signoff-1.0.json` and never inferred from CI;
- it is unsigned: no sigstore/OIDC attestation exists locally, and the receipt
  is only as trustworthy as the host and the person committing it;
- the receipt records the actual toolchain. The hosted workflows pin Rust
  `1.88.0`; `rust_toolchain_pin.matches` is `false` when the host differs, and
  `summary.md` says so. Treat build/lint results as valid for the toolchain
  recorded, not for 1.88.0;
- `tree_clean_after_run` and `modified_tracked_files` show whether any step
  rewrote tracked files (the screenshot gallery regenerates tracked PNGs).

Receipt fields: `schema_version`, `sha`, `commit_date`, `tree_clean`,
`host` (from `/etc/os-release`), `kernel`, `run_as`, `tools` (rustc, cargo,
clippy, rustfmt, python, labwc, labwc_sg5, mako, mako_1_11, gtk, docker,
dpkg_deb, meson), `rust_toolchain_pin`, `worker`, `runner_name`,
`catalog_sha256` (catalog definition plus every step script), `selected_steps`,
`auto_included_steps`, `counts`, `complete`, `artifacts` (package SHA-256s) and
per step: `id`, the mirrored `workflow` / `job` / `step`, `status`, `exit_code`,
`duration_s`, `log`, `log_sha256`, `script_sha256`, `detail`, `auto_included`,
`timeout_s`.

## Host prerequisites and known BLOCKED steps

Preflight checks replace the workflows' `apt install` steps; the runner never
installs or reconfigures anything on the host. Specific tooling:

- **SG5**: labwc 0.7.2 prebuilt at `/opt/labwc-sg5` (put first on `PATH` for
  `sg5-atspi` only); `sg5-labwc-pin` verifies it was built from the pinned upstream
  commit `b41af54a1bd7d9270d19de4c9a2b77d882cf3ede` in `/opt/labwc-sg5-src`.
- **SG3**: `mako-build` builds the source-locked Mako 1.11.0 (commit
  `91c6b799...`) into `/var/cache/ricebowl-local-ci/mako-1.11.0-build` and reuses it
  on later runs; `sg3-ricepop` puts it first on `PATH` for that step only. The
  host's own Mako is never replaced. It needs network access to GitHub once.
- **Creator hand-off smokes** put `components/riceplate-wayland/target/release`
  on `PATH` themselves, as in the workflow; `rust-build` must have run (it is a
  prerequisite and is auto-included).
- **Tools that must exist for a complete receipt** (checked per step; absent =
  BLOCKED): Xvfb, `xfwm4`, `thunar`, `xdotool` (X11 gallery steps), `pulseaudio` +
  `pactl` (`ricespice-pulse`), a Docker daemon reachable by `rbdev`
  (`pkg-docker-install`, `pkg-upgrade-rollback`, `mint-compat`), the pinned
  third-party portal backend installed at
  `/usr/libexec/xdg-desktop-portal-generic` by the operator
  (`portal-strict-frame`; local CI never writes `/usr`) and a DRM render node
  (`portal-gpu-frame`, which mirrors the manual self-hosted `gpu` input).

Workflow steps that are **not** translated (and why) are printed by `--list`
and enforced by `tests/test_local_ci.py`: apt installs and apt-mirror rewrites,
the hosted GitHub Release creation, sigstore attestations, the SG6 compare/attest
jobs (replaced by the two-session procedure below), the SG7 dossier collector and
`check_release_workflows.py` (both query the hosted Actions API), and the portal
backend build/registration (system-wide install). The test fails if a workflow
`run:` step is neither mapped to a local step nor listed with a reason.

## How the translation is maintained

Each step lives in `scripts/local_ci/steps/<id>.sh`. The file starts with
`# Mirrors: <workflow> / <job> / <step name>` and is a snapshot of the workflow's
`run:` text (cut at the sub-blocks listed in `scripts/local_ci.py`), plus a
`# Local adaptation:` line wherever it differs (private `$TMPDIR`, cached Mako,
pinned labwc, `LCI_WORKER`, `git fetch` replaced by an object check). To change
what CI proves, edit the script and the catalog in `scripts/local_ci.py`; the
receipt's `catalog_sha256` and per-step `script_sha256` identify exactly which
translation produced it. Steps run in catalog order; `needs` lists consumers of
earlier steps' outputs (for example `pkg-*` consume `rust-build`).

## SG7: two-session reproducibility of the four Debian packages

SG6/SG7 asked two independent hosted runners to build the four `.deb` files and
compared them. Locally, build the same SHA in **two fresh cloud sessions** (each
needs the repository at that SHA and the Rust/dpkg tooling) and compare:

```sh
# Session A (fresh): build only the packages and record the SG6 receipt as host-a
scripts/local_ci.sh --sha <SHA> --worker host-a --steps pkg-build --out /srv/sg6-a

# Session B (fresh, a different VM): same SHA, worker host-b
scripts/local_ci.sh --sha <SHA> --worker host-b --steps pkg-build --out /srv/sg6-b

# Bring both /srv/sg6-*/artifacts/sg6 directories to one machine, then compare
scripts/local_ci.sh --sha <SHA> --compare-sg6 /srv/sg6-a/artifacts/sg6 /srv/sg6-b/artifacts/sg6 \
    --out docs/evidence/local-ci/<sha12>
```

`--compare-sg6` runs the existing `scripts/verify_sg6_cross_runner.py compare`
inside a fresh clone of the SHA, so it checks exactly what the hosted comparison
did: both receipts name the exact SHA and the commit's `SOURCE_DATE_EPOCH`, carry
**distinct runner names** (`--runner-name` overrides the default
`local-ci-<hostname>`; the two sessions must differ), identical Rust/Cargo/dpkg
versions and the same `Cargo.lock` hash, every package's SHA-256 matches its
receipt, and all four `.deb` files are byte-identical. It writes
`sg6-comparison.json` (commit this alongside the receipt). Use the same toolchain
in both sessions: a differing `rustc` is rejected as an unpinned build environment.

Limits, stated in the report itself: two cloud sessions are not independent
third-party builders, runner and host names are not cryptographic machine
identities, nothing is attested, and `hardware_accepted` stays `false`. Passing
shows repeatable bytes across two fresh VMs only. `pkg-build` also needs to run
on the same SHA as the rest of the receipt: the per-session `receipt.json`
records the package SHA-256s under `artifacts.sg6_packages`, so the full-catalog
receipt and the two-session comparison can be read together.

## Provisioning a fresh cloud container

Claude Code cloud sessions run `.claude/hooks/session-start.sh` at start,
which calls `scripts/local_ci/provision.sh` (root, idempotent, installs only
what is missing: every workflow apt package, the `rbdev` user and venv,
Rust 1.88.0, the pinned labwc 0.7.2, `rb-sync`/`rb-run`, and starts `dockerd`
for the packaging steps). The hook does nothing outside a cloud session
(`CLAUDE_CODE_REMOTE` unset) or as non-root. In any other disposable
container, run `sudo scripts/local_ci/provision.sh` once.
