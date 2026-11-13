"""Pure, versioned AI/human authoring contract for real panel components.

Kept separate from file IO, live Wayland state and the renderer. Agents can
discover the exact vocabulary before producing any draft edit data.
"""

from __future__ import annotations

from . import recipes
from .shell_contract import describe as describe_shell_actions

EDIT_VERSION = 1
MAX_EDIT_BYTES = 16 * 1024
MAX_OPERATIONS = 16


def describe_visual_qa() -> dict[str, object]:
    """Published on-demand Creator CLI contract, never a resident process."""
    return {
        "contract_version": 2,
        "command": "de visual-compare",
        "required_options": ["--reference", "--actual"],
        "optional_options": ["--recipe", "--threshold", "--tolerance-radius", "--overlay",
                             "--heatmap", "--tolerant-heatmap", "--baseline", "--json"],
        "capture_format": "PNG",
        "image_limit_megapixels": 16,
        "pixel_threshold": {"default": 24, "min": 0, "max": 255},
        "regions": ["panel", "desktop", "desktop-icon-*"],
        "region_semantics": "recipe coordinates; may be clipped",
        "artifact_behavior": "new private absolute PNGs; no overwrite",
        "success_exit_code": 0,
        "invalid_input_exit_code": 2,
        "invalid_options_exit_code": 1,
        "regression_exit_code": 3,
        "error_code": "invalid_visual_input",
        "requires_running_wayland_session": False,
        "captures_live_desktop": False,
        "mutates_active_desktop": False,
        "perceptual_or_functional_accuracy": "not_measured",
    }


def describe_capture() -> dict[str, object]:
    """Explicit capture of the user's current Wayland display, not a renderer."""
    return {
        "contract_version": 1,
        "command": "de capture",
        "required_options": ["--output"],
        "optional_options": ["--json"],
        "requires_running_wayland_session": True,
        "requires_binary": "grim",
        "capture_source": "current-wayland-compositor",
        "output": "new absolute owner-private PNG, never overwrite",
        "max_bytes": 64 * 1024 * 1024,
        "max_pixels": 16_777_216,
        "timeout_seconds": 30,
        "success_exit_code": 0,
        "capture_error_exit_code": 2,
        "error_codes": ["invalid_capture_request", "capture_unavailable", "capture_failed"],
        "creates_nested_session": False,
        "captures_live_desktop": True,
        "requires_explicit_invocation": True,
        "mutates_active_desktop": False,
        "screenshot_may_contain_private_data": True,
    }


def describe_render() -> dict[str, object]:
    """Offline optional headless renderer for one validated native recipe."""
    return {
        "contract_version": 1,
        "command": "de render",
        "required_options": ["--recipe", "--output"],
        "optional_options": ["--width", "--height", "--scale", "--json"],
        "default_geometry": {"width": 1366, "height": 768, "scale": 1.0},
        "width_range": [640, 4096],
        "height_range": [480, 2160],
        "max_pixels": 16_777_216,
        "scales": [1.0, 1.25, 1.5, 2.0],
        "requires_binaries": ["labwc", "wlr-randr", "grim", "riceplate-native", "swaybg"],
        "requires_running_wayland_session": False,
        "requires_unprivileged_user": True,
        "source": "validated bundled/imported/owner-private recipe",
        "backend": "headless-labwc-native-riceplate",
        "output": "new owner-private PNG, never overwrite",
        "creates_temporary_compositor": True,
        "keeps_processes_after_exit": False,
        "mutates_active_desktop": False,
        "functional_or_perceptual_fidelity": "not_measured",
        "error_codes": ["invalid_render_request", "render_unavailable", "render_failed"],
        "error_exit_code": 2,
    }


def describe_render_matrix() -> dict[str, object]:
    """Fixed, reviewable multi-resolution captures from real nested labwc."""
    return {
        "contract_version": 1,
        "command": "de render-matrix",
        "required_options": ["--recipe", "--output"],
        "optional_options": ["--json"],
        "inspect_command": "de render-matrix-inspect --matrix FILE.zip --json",
        "scenarios": [
            {"id": "compact", "width": 1024, "height": 768, "scale": 1.0},
            {"id": "laptop", "width": 1366, "height": 768, "scale": 1.0},
            {"id": "desktop", "width": 1920, "height": 1080, "scale": 1.0},
            {"id": "fractional", "width": 1366, "height": 768, "scale": 1.25},
        ],
        "output": "new private data-only .zip with four real captures and SHA-256 manifest",
        "publication": "only after all four renders and receipt verification; no overwrite",
        "requires_running_wayland_session": False,
        "requires_unprivileged_user": True,
        "mutates_active_desktop": False,
        "functional_or_perceptual_accuracy": "not_measured",
        "error_exit_code": 2,
        "error_codes": ["invalid_matrix_request", "render_unavailable", "render_failed",
                        "invalid_matrix_archive", "matrix_failed"],
    }


def describe_ricepack() -> dict[str, object]:
    """Portable v2/v3/v4 archives with verified private visual assets."""
    return {
        "pack_version": 4,
        "accepts_older_versions": [1, 2, 3],
        "format": "org.ricebowl.ricepack",
        "extension": ".ricepack",
        "entries": ["ricepack.json", "recipe.json", "assets/wallpaper.png (v3/v4)",
                    "assets/font.ttf (v4)", "assets/icons/{action}.png (v4)"],
        "maximum_archive_bytes": 6 * 1024 * 1024,
        "recipe_schema_versions": list(range(1, 13)),
        "asset_support": "SHA-256 PNG; one TTF; three 48px icons",
        "asset_manifest": {"since_version": 2, "version": 2,
                           "fields": ["id", "sha256", "provenance"],
                           "declared_provenance": ["author", "license", "origin", "source_reference"],
                           "installed_wallpaper_must_match_digest": True},
        "third_party_assets": "owner-private, hash-verified",
        "arbitrary_code_or_scripts": False,
        "deterministic_export": True,
        "provenance": {
            "metadata_version": "fields-v1",
            "fields": ["author", "license", "origin", "source_reference"],
            "licenses": ["unspecified", "CC0-1.0", "CC-BY-4.0", "MIT",
                         "OFL-1.1", "Apache-2.0", "custom"],
            "origins": ["unspecified", "original", "ai-assisted", "adapted"],
            "user_declared_not_verified": True,
            "import_receipt": "private receipt pinned to recipe hash",
            "roundtrip_preserves_attribution": True,
        },
        "commands": [
            {"command": "de asset-import", "required_options": ["--asset"],
             "optional_options": ["--json"], "installs_content_addressed_png": True},
            {"command": "de pack-export", "required_options": ["--recipe", "--output"],
             "optional_options": ["--metadata", "--json"], "creates_archive": True},
            {"command": "de pack-inspect", "required_options": ["--package"],
             "optional_options": ["--json"], "read_only": True},
            {"command": "de pack-import", "required_options": ["--package"],
             "optional_options": ["--json"], "installs_recipe_and_receipt": True},
            {"command": "de pack-recover", "required_options": [],
             "optional_options": ["--json"], "resumes_private_pending_import": True},
        ],
        "inspect_diagnostics": {
            "host_backends_checked": False,
            "native_required_for_desktop_layers": "schema-v5+",
            "embedded_assets": "verified archive paths",
            "missing_host_dependencies": "must be checked on destination",
            "activates_on_import": False,
        },
        "import": "private no-overwrite, never activates",
        "failure_exit_code": 2,
        "success_exit_code": 0,
        "mutates_active_desktop": False,
    }


def describe_staging() -> dict[str, object]:
    """Explicit, compare-and-swap next-login choice; current desktop untouched."""
    return {
        "stage_version": 1,
        "commands": [
            {"command": "de creator-status", "required_options": [],
             "optional_options": ["--json"], "read_only": True},
            {"command": "de creator-stage",
             "required_options": ["--recipe", "--expect-sha256"],
             "optional_options": ["--expect-active", "--json"]},
            {"command": "de creator-rollback", "required_options": [],
             "optional_options": ["--expect-active", "--json"]},
        ],
        "recipe_input": "existing installed/bundled ID; not an arbitrary path",
        "hash": "64 lowercase hex characters of de review summary.semantic_sha256",
        "expected_active": "optional existing next-login ID used as concurrency guard",
        "state": "owner-private selected recipe and one-level previous selection",
        "runtime": "takes effect only on next opt-in Wayland login",
        "mutates_current_session": False,
        "mutates_xfce": False,
        "user_invocation_required": True,
        "reviewed_hash_saved_in_selection": True,
        "recipe_file_immutable": False,
        "changed_recipe_behavior": "reject pinned mismatch and fall back to classic at next login",
        "success_exit_code": 0,
        "error_exit_code": 2,
    }


def describe_live() -> dict[str, object]:
    """Explicit activation contract for one supervised opt-in labwc session."""
    return {
        "live_version": 1,
        "commands": ["creator-live-status", "creator-live-apply", "creator-live-restore",
                     "creator-live-recovery", "display-refresh"],
        "transport": "owner-only UNIX socket in XDG_RUNTIME_DIR, per Wayland display",
        "required_review": "de review semantic SHA-256 before creator-live-apply",
        "components": ["RicePlate native or Waybar", "swaybg wallpaper", "labwc root menu",
                       "next-login selection"],
        "behavior": "preflight, start new clients, health check, reconfigure menu, "
                    "persist reviewed selection, stop old clients; rollback on failure",
        "scope": "current opt-in RiceBowl labwc session only; never XFCE/X11",
        "restore": "one prior live rice, using its recorded reviewed fingerprint",
        "crash_recovery": "private durable pre-switch journal; next full login uses CAS to undo a "
                          "pending selection, preserves concurrent stages, and falls back to classic if unsafe",
        "readiness_limit": "new clients survive initial grace period; no full pixel/input validation",
        "external_apps": "compatible RiceField/Taskotto appearance files use guarded preflight and rollback; client frames are eventually consistent",
        "success_exit_code": 0,
        "error_exit_code": 2,
    }


def describe_creator_api() -> dict[str, object]:
    """Versioned, offline contract for a future human or AI Rice Creator UI.

    Side-effect classifications are generated from one bounded allowlist; an
    agent may discover functionality but can never acquire new executable
    privileges from recipe contents or this read-only description.
    """
    from . import creator_mapping, creator_regions

    contract = {
        "api_version": 3,
        "scope": "experimental-wayland-shell-authoring",
        "transport": "CLI JSON; session-local socket only for explicit live Rice changes",
        "discovery": "ricebowl de creator-api --json",
        "feature_negotiation": {
            "mode": "read-only-discovery-before-use",
            "recipe_schema_versions": list(range(1, 13)),
            "recommended_authoring_schema": 11,
            "catalog_version": 14,
            "features": [
                {"id": "shared-status-action-bindings", "supported": True,
                 "since_schema": 9, "runtime": "native; Waybar actions disabled when unverifiable"},
                {"id": "desktop-static-text", "supported": True,
                 "since_schema": 9, "runtime": "native-only-read-only"},
                {"id": "cross-surface-design-tokens", "supported": True,
                 "since_schema": 10, "runtime": "native; Waybar appearance and per-output layout"},
                {"id": "private-native-font-and-icon-assets", "supported": True,
                 "since_schema": 11, "runtime": "native-only; owner-private TTF and 48px RGBA icons"},
                {"id": "installed-truetype-font-picker", "supported": True,
                 "since_schema": 11, "runtime": "read-only Fontconfig catalog; explicit private licensed import"},
                {"id": "reference-mapping-review", "supported": True,
                 "runtime": "offline-PNG-panel-hints; optional external JSON proposals; explicit GTK review"},
                {"id": "manual-region-pixel-qa", "supported": True,
                 "runtime": "GTK-on-demand; owner-annotated rectangles; native-capture real pixels"},
                {"id": "interactive-region-correction-qa", "supported": True,
                 "runtime": "GTK-on-demand; mouse or keyboard regions; bounded private cross-revision pixel journal"},
                {"id": "private-drafts-and-packaging", "supported": True,
                 "runtime": "offline-CLI"},
                {"id": "read-only-draft-preflight-and-fingerprint-guards", "supported": True,
                 "runtime": "full-recipe-parser; semantic diff and pinned private draft publication"},
                {"id": "private-creator-version-lineage", "supported": True,
                 "runtime": "owner-only no-overwrite receipts; GTK history and read-only CLI"},
                {"id": "recipe-versioned-edit-json-schema", "supported": True,
                 "runtime": "standalone offline JSON Schema 2020-12; full parser validates cross-property rules"},
                {"id": "content-addressed-source-snapshots", "supported": True,
                 "runtime": "owner-private 0400 canonical copies, exact byte hash checked on every recipe load"},
                {"id": "crash-safe-creator-draft-recovery", "supported": True,
                 "runtime": "durable receipt-before-recipe publication; inspect verified parents and recover to new draft"},
                {"id": "crash-safe-wayland-live-selection-recovery", "supported": True,
                 "runtime": "owner-private journal, process identity guard and CAS recovery on next full Wayland login"},
                {"id": "isolated-native-multisize-preview", "supported": True,
                 "runtime": "four verified PNG captures in one private offline matrix archive; "
                            "requires-external-labwc-and-capture-binaries"},
                {"id": "review-gated-live-rice-switch", "supported": True,
                 "runtime": "supervised-opt-in-wayland-only"},
                {"id": "interactive-desktop-widgets", "supported": True,
                 "since_schema": 9,
                 "runtime": "bounded native action components with pointer/keyboard/AT-SPI; physical QA open"},
                {"id": "arbitrary-screenshot-one-click-conversion", "supported": False,
                 "reason": "Mapping references to supported primitives remains an authoring step"},
                {"id": "window-decoration-control-across-all-apps", "supported": False,
                 "reason": "labwc and third-party client-side decorations are independent"},
            ],
        },
        "authoring_workflow": [
            {"step": "discover", "commands": ["creator-api", "catalog", "creator-schema"],
             "effect": "none"},
            {"step": "draft-and-review", "commands": ["creator-snapshot", "draft-check", "draft-edit", "review",
                                                   "creator-history", "creator-recovery", "creator-recover"],
             "effect": "owner-private-file-only"},
            {"step": "visual-qa", "commands": ["render", "render-matrix",
                                                "render-matrix-inspect", "visual-compare"],
             "effect": "isolated-native-preview"},
            {"step": "reference-mapping-review", "commands": [],
             "ui": "ricebowl creator (GTK; no de CLI command)",
             "effect": "none until explicit checked-hint transfer to unsaved private draft"},
            {"step": "manual-region-qa", "commands": [],
             "ui": "ricebowl creator (GTK; no de CLI command)",
             "effect": "owner-private read-only pixel diagnostics, version comparisons and optional JSON export"},
            {"step": "package", "commands": ["pack-export", "pack-inspect", "pack-import",
                                            "pack-recover"],
             "effect": "owner-private-file-only"},
            {"step": "explicit-activate-or-recover", "commands": [
                "creator-stage", "creator-rollback", "creator-live-apply", "creator-live-restore"],
             "effect": "requires-reviewed-hash-and-explicit-user-invocation"},
        ],
        "mutation_scope_values": ["none", "private-file", "private-file-optional",
                                  "next-login", "active-wayland-session", "active-user-session"],
        "reference_mapping": creator_mapping.contract(),
        "manual_region_qa": creator_regions.contract(),
        "success_exit_code": 0,
        "invalid_options_exit_code": 1,
        "operation_error_exit_code": 2,
        "active_session_mutation": "Creator authoring stays offline; creator-live-apply/restore, notification-dismiss, notification-invoke, notification-dnd and audio-default require explicit user invocation",
        "next_login_selection_mutation": "creator-stage/rollback only; requires explicit invocation",
        "commands": [
            {"command": "catalog", "effect": "read-only component discovery",
             "cli": "de catalog --json", "contract_version": 14},
            {"command": "fonts", "effect": "read-only installed importable TrueType font inventory",
             "cli": "de fonts --json", "contract_version": 1},
            {"command": "review", "effect": "validate recipe and compare semantic diffs",
             "cli": "de review --recipe ID [--compare ID] --json", "contract_version": 1},
            {"command": "draft-check", "effect": "read-only edit validation and semantic diff",
             "cli": "de draft-check --recipe ID --edit FILE --json",
             "contract_version": EDIT_VERSION},
            {"command": "creator-history", "effect": "read verified private Creator draft ancestry",
             "cli": "de creator-history --recipe /absolute/draft.json --json",
             "contract_version": 1},
            {"command": "creator-schema", "effect": "read per-recipe JSON Schema for bounded edits",
             "cli": "de creator-schema --recipe ID --json", "contract_version": 1},
            {"command": "creator-snapshot", "effect": "publish or reuse an exact private source copy without selection",
             "cli": "de creator-snapshot --recipe ID --json", "contract_version": 1},
            {"command": "creator-recovery", "effect": "list incomplete versions or inspect a verified recovery ancestor",
             "cli": "de creator-recovery [--recipe /absolute/draft.json] --json", "contract_version": 1},
            {"command": "creator-recover", "effect": "publish a new private copy of the verified parent; no in-place repair",
             "cli": "de creator-recover --recipe /absolute/draft.json --expect-sha256 PARENT_HASH --json",
             "contract_version": 1},
            {"command": "draft-edit", "effect": "create private reviewed JSON draft",
             "cli": "de draft-edit --recipe ID --edit FILE --output NEW.json "
                    "--expect-sha256 SOURCE_HASH --expect-draft-sha256 DRAFT_HASH --json",
             "contract_version": EDIT_VERSION},
            {"command": "render", "effect": "isolated real native headless screenshot",
             "cli": "de render --recipe ID --output NEW.png --json", "contract_version": 1},
            {"command": "render-matrix", "effect": "four real native headless captures with immutable archive receipts",
             "cli": "de render-matrix --recipe ID --output NEW.zip --json", "contract_version": 1},
            {"command": "render-matrix-inspect", "effect": "read-only integrity check of a capture matrix archive",
             "cli": "de render-matrix-inspect --matrix FILE.zip --json", "contract_version": 1},
            {"command": "visual-compare", "effect": "read-only screenshot analysis; optional new artifacts",
             "cli": "de visual-compare --reference FILE --actual FILE --json",
             "contract_version": 2},
            {"command": "visual-baseline", "effect": "pin reviewed reference",
             "cli": "de visual-baseline --reference PNG --recipe ID --output NEW.json "
                    "--approve-reference",
             "contract_version": 2},
            {"command": "capture", "effect": "explicit live Wayland screen capture (private data)",
             "cli": "de capture --output NEW.png --json", "contract_version": 1},
            {"command": "notifications", "effect": "read live Mako alerts and prior history without replaying actions",
             "cli": "de notifications --json", "contract_version": 1},
            {"command": "notification-dismiss", "effect": "explicitly dismiss one currently active Mako alert; never invoke its actions",
             "cli": "de notification-dismiss --notification-id UINT32 --json", "contract_version": 1,
             "mutates_active_session": True},
            {"command": "notification-invoke", "effect": "explicitly invoke one freshly verified action advertised by an active Mako alert; never replay history or execute recipe commands",
             "cli": "de notification-invoke --notification-id UINT32 --action-key KEY --json",
             "contract_version": 1, "mutates_active_session": True},
            {"command": "notification-dnd", "effect": "inspect or compare-and-set Do Not Disturb only for the verified full RiceBowl Mako owner",
             "cli": "de notification-dnd [--dnd on|off --expect-dnd on|off] --json",
             "contract_version": 1, "mutates_active_session": True},
            {"command": "audio-devices", "effect": "read real playback and recording devices from the existing audio server",
             "cli": "de audio-devices --json", "contract_version": 1},
            {"command": "audio-default", "effect": "explicitly choose one reviewed default playback/recording device",
             "cli": "de audio-default --device-kind sink|source --device-name NAME --json",
             "contract_version": 1, "mutates_active_session": True},
            {"command": "pack-export", "effect": "create portable validated recipe archive",
             "cli": "de pack-export --recipe ID --output NEW.ricepack --json",
             "contract_version": 4},
            {"command": "pack-inspect", "effect": "verify archive, schema and fingerprints",
             "cli": "de pack-inspect --package FILE.ricepack --json", "contract_version": 4},
            {"command": "pack-import", "effect": "install private recipe without selecting it",
             "cli": "de pack-import --package FILE.ricepack --json", "contract_version": 4},
            {"command": "pack-recover", "effect": "resume a pinned interrupted private archive, no desktop switch",
             "cli": "de pack-recover --json", "contract_version": 1},
            {"command": "asset-import", "effect": "store a reviewed PNG as a private SHA256 asset; no apply",
             "cli": "de asset-import --asset /absolute/image.png --json", "contract_version": 1},
            {"command": "creator-status", "effect": "read next Wayland login choice and fingerprint",
             "cli": "de creator-status --json", "contract_version": 1},
            {"command": "creator-stage", "effect": "review-gated next Wayland login choice",
             "cli": "de creator-stage --recipe ID --expect-sha256 HASH --json",
             "contract_version": 1},
            {"command": "creator-rollback", "effect": "restore preceding next-login choice",
             "cli": "de creator-rollback --json", "contract_version": 1},
            {"command": "creator-live-status", "effect": "read active supervised Wayland rice",
             "cli": "de creator-live-status --json", "contract_version": 1},
            {"command": "creator-live-recovery", "effect": "read pending live switch journal without modifying the selection",
             "cli": "de creator-live-recovery --json", "contract_version": 1},
            {"command": "creator-live-apply", "effect": "review-gated live shell switch with recovery",
             "cli": "de creator-live-apply --recipe ID --expect-sha256 HASH --json",
             "contract_version": 1, "mutates_active_session": True},
            {"command": "creator-live-restore", "effect": "restore previous live shell rice",
             "cli": "de creator-live-restore --json", "contract_version": 1,
             "mutates_active_session": True},
            {"command": "display-refresh", "effect": "refresh output-aware Waybar after external mode changes",
             "cli": "de display-refresh --json", "contract_version": 1,
             "mutates_active_session": True},
        ],
        "ricepack": describe_ricepack(),
        "staging": describe_staging(),
        "live": describe_live(),
        "limitations": [
            "Not an automatic screenshot-to-rice converter",
            "Schema-v1..v12 shell preview; v12 adds bounded launcher/menu styling; v11 adds private native fonts/icons; v6+ supports bounded wallpaper PNG",
            "Live apply is explicit and supervised; Wayland session remains experimental",
            "Native tray, complete settings, notification center and physical multi-monitor acceptance remain open",
        ],
    }
    private_writes = {"draft-edit", "creator-snapshot", "creator-recover", "render", "render-matrix", "visual-baseline", "capture",
                      "pack-export", "pack-import", "pack-recover", "asset-import"}
    next_login = {"creator-stage", "creator-rollback"}
    active_wayland = {"creator-live-apply", "creator-live-restore", "display-refresh"}
    active_user = {"notification-dismiss", "notification-invoke", "notification-dnd", "audio-default"}
    for command in contract["commands"]:
        name = command["command"]
        command["mutation_scope"] = (
            "active-wayland-session" if name in active_wayland else
            "active-user-session" if name in active_user else
            "next-login" if name in next_login else
            "private-file-optional" if name == "visual-compare" else
            "private-file" if name in private_writes else "none")
        command["requires_explicit_user_invocation"] = (
            name in active_wayland | active_user | next_login | {"capture", "creator-recover"})
        command["executes_recipe_commands"] = False
    return contract


EDITABLE_PATHS = frozenset((
    "/name", "/panel/position", "/panel/height",
    *(f"/panel/sections/{name}" for name in recipes.SECTIONS),
    *(f"/panel/layout/{name}" for name in recipes.SECTIONS),
    "/menu/title", "/menu/groups", "/menu/presentation", "/desktop/wallpaper",
    "/desktop/icons",
    "/composition/widgets", "/composition/window_region", "/composition/compact_hide_widgets",
    "/components",
    "/artwork/font", "/artwork/icons",
    "/artwork/icons/applications", "/artwork/icons/terminal", "/artwork/icons/lock",
    "/panel/launcher", "/menu/colors",
    *(f"/panel/launcher/{name}" for name in
      ("label", "background", "foreground", "radius")),
    *(f"/menu/colors/{name}" for name in
      ("background", "foreground", "header", "header_foreground", "selection")),
    *(f"/appearance/{name}" for name in
      ("font_scale", "font_weight", "item_spacing", "hover", "focus", "disabled")),
    "/tokens/label_padding", "/tokens/task_radius",
    "/responsive/compact_max_width",
    *(f"/responsive/compact_layout/{name}" for name in recipes.SECTIONS),
    *(f"/panel/metrics/{name}" for name in recipes.METRIC_FIELDS),
    *(f"/colors/{name}" for name in recipes.COLORS),
))


def describe() -> dict[str, object]:
    """Tool-neutral JSON guidance derived from one allowlisted vocabulary."""
    return {
        "edit_version": EDIT_VERSION,
        "shell_action_contract": describe_shell_actions(),
        "command": "de draft-edit",
        "scope": "wayland-shell-preview",
        "operation": "set",
        "editable_paths": sorted(EDITABLE_PATHS),
        "max_edit_bytes": MAX_EDIT_BYTES,
        "max_operations": MAX_OPERATIONS,
        "source": "bundled/imported recipe ID or private absolute .json path",
        "edit_input": "owner-controlled absolute .json file",
        "output": "new owner-private absolute .json file, never overwrite",
        "mutates_active_desktop": False,
        "mutates_next_session_selection": False,
        "edits_id_or_schema_version": False,
        "arbitrary_actions_or_scripts": False,
        "read_only_preflight": {
            "command": "de draft-check --recipe ID --edit FILE --json",
            "writes_files": False,
            "same_full_recipe_parser_as_draft_edit": True,
            "returns": ["changes", "source_semantic_sha256", "draft_semantic_sha256"],
        },
        "guarded_create": {
            "optional_source_hash": "--expect-sha256",
            "optional_proposed_hash": "--expect-draft-sha256",
            "hash_format": "64 lowercase hex; same semantic hash as de review",
            "on_mismatch": "refuse creation; no active or private output changes",
        },
        "schema_discovery": {
            "command": "de creator-schema --recipe ID --json",
            "draft": "JSON Schema 2020-12; version-filtered property constraints",
            "source_fingerprint": "semantic SHA-256 for --expect-sha256",
            "schema_fingerprint": "stable canonical SHA-256 for reproducible schema discovery",
            "cross_property_rules": "always use de draft-check for complete recipe validation",
        },
        "source_snapshot": {
            "command": "de creator-snapshot --recipe ID --json",
            "output": "content-addressed 0400 private recipe, never overwritten",
            "validation": "exact SHA-256 of recipe bytes checked on every recipes.load()",
            "reusable_as": "de draft-check/draft-edit --recipe /absolute/snapshot-<hash>.json",
            "limits": "same 64 KiB recipe and full parser; assets retain their own content IDs",
            "filesystem_immutable": False,
        },
        "draft_recovery": {
            "inspect": "de creator-recovery [--recipe /absolute/draft.json] --json",
            "recover": "de creator-recover --recipe /absolute/draft.json --expect-sha256 PARENT_HASH --json",
            "policy": "durable version receipt published before recipe; no overwrite, never auto-activate",
            "outcome": "new private version from the last verified parent; source left untouched",
            "limits": "requires authentic prior receipt and readable parent; not live Wayland crash recovery",
        },
        "example_source_recipe": "classic",
        "example": {
            "edit_version": EDIT_VERSION,
            "operations": [
                {"op": "set", "path": "/panel/height", "value": 44},
                {"op": "set", "path": "/panel/sections/start", "value": ["launcher"]},
                {"op": "set", "path": "/panel/sections/center", "value": ["tasks"]},
            ],
        },
    }
