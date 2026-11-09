"""Pure, versioned AI/human authoring contract for real panel components.

Kept separate from file IO, live Wayland state and the renderer. Agents can
discover the exact vocabulary before producing any draft edit data.
"""

from __future__ import annotations

from . import recipes

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
        "recipe_schema_versions": list(range(1, 12)),
        "asset_support": "content-addressed wallpaper, up to one TrueType font and three 48px RGBA icons",
        "asset_manifest": {"since_version": 2, "version": 2,
                           "fields": ["id", "sha256", "provenance"],
                           "declared_provenance": ["author", "license", "origin", "source_reference"],
                           "installed_wallpaper_must_match_digest": True},
        "third_party_assets": "owner-controlled-PNG-wallpaper-and-verified-private-v4-font-and-icons",
        "arbitrary_code_or_scripts": False,
        "deterministic_export": True,
        "provenance": {
            "metadata_version": "fields-v1",
            "fields": ["author", "license", "origin", "source_reference"],
            "licenses": ["unspecified", "CC0-1.0", "CC-BY-4.0", "MIT", "custom"],
            "origins": ["unspecified", "original", "ai-assisted", "adapted"],
            "user_declared_not_verified": True,
            "import_receipt": "owner-private data-only sidecar bound to recipe semantic hash",
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
        ],
        "import": "no-overwrite private user recipe collection; never activates",
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
                     "display-refresh"],
        "transport": "owner-only UNIX socket in XDG_RUNTIME_DIR, per Wayland display",
        "required_review": "de review semantic SHA-256 before creator-live-apply",
        "components": ["RicePlate native or Waybar", "swaybg wallpaper", "labwc root menu",
                       "next-login selection"],
        "behavior": "preflight, start new clients, health check, reconfigure menu, "
                    "persist reviewed selection, stop old clients; rollback on failure",
        "scope": "current opt-in RiceBowl labwc session only; never XFCE/X11",
        "restore": "one prior live rice, using its recorded reviewed fingerprint",
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
        "api_version": 2,
        "scope": "experimental-wayland-shell-authoring",
        "transport": "CLI JSON; session-local socket only for explicit live Rice changes",
        "discovery": "ricebowl de creator-api --json",
        "feature_negotiation": {
            "mode": "read-only-discovery-before-use",
            "recipe_schema_versions": list(range(1, 12)),
            "recommended_authoring_schema": 11,
            "catalog_version": 12,
            "features": [
                {"id": "shared-status-action-bindings", "supported": True,
                 "since_schema": 9, "runtime": "native; Waybar actions disabled when unverifiable"},
                {"id": "desktop-static-text", "supported": True,
                 "since_schema": 9, "runtime": "native-only-read-only"},
                {"id": "cross-surface-design-tokens", "supported": True,
                 "since_schema": 10, "runtime": "native; Waybar appearance and per-output layout"},
                {"id": "private-native-font-and-icon-assets", "supported": True,
                 "since_schema": 11, "runtime": "native-only; owner-private TTF and 48px RGBA icons"},
                {"id": "reference-mapping-review", "supported": True,
                 "runtime": "offline-PNG-panel-hints; optional external JSON proposals; explicit GTK review"},
                {"id": "manual-region-pixel-qa", "supported": True,
                 "runtime": "GTK-on-demand; owner-annotated rectangles; native-capture real pixels"},
                {"id": "interactive-region-correction-qa", "supported": True,
                 "runtime": "GTK-on-demand; mouse or keyboard regions; bounded private cross-revision pixel journal"},
                {"id": "private-drafts-and-packaging", "supported": True,
                 "runtime": "offline-CLI"},
                {"id": "isolated-native-multisize-preview", "supported": True,
                 "runtime": "requires-external-labwc-and-capture-binaries"},
                {"id": "review-gated-live-rice-switch", "supported": True,
                 "runtime": "supervised-opt-in-wayland-only"},
                {"id": "interactive-desktop-widgets", "supported": False,
                 "reason": "Only panel action bindings and read-only desktop widgets exist"},
                {"id": "arbitrary-screenshot-one-click-conversion", "supported": False,
                 "reason": "Mapping references to supported primitives remains an authoring step"},
                {"id": "window-decoration-control-across-all-apps", "supported": False,
                 "reason": "labwc and third-party client-side decorations are independent"},
            ],
        },
        "authoring_workflow": [
            {"step": "discover", "commands": ["creator-api", "catalog"], "effect": "none"},
            {"step": "draft-and-review", "commands": ["draft-edit", "review"],
             "effect": "owner-private-file-only"},
            {"step": "visual-qa", "commands": ["render", "visual-compare"],
             "effect": "isolated-native-preview"},
            {"step": "reference-mapping-review", "commands": [],
             "ui": "ricebowl creator (GTK; no de CLI command)",
             "effect": "none until explicit checked-hint transfer to unsaved private draft"},
            {"step": "manual-region-qa", "commands": [],
             "ui": "ricebowl creator (GTK; no de CLI command)",
             "effect": "owner-private read-only pixel diagnostics, version comparisons and optional JSON export"},
            {"step": "package", "commands": ["pack-export", "pack-inspect", "pack-import"],
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
        "active_session_mutation": "Creator authoring stays offline; creator-live-apply/restore, notification-dismiss, notification-invoke and audio-default require explicit user invocation",
        "next_login_selection_mutation": "creator-stage/rollback only; requires explicit invocation",
        "commands": [
            {"command": "catalog", "effect": "read-only component discovery",
             "cli": "de catalog --json", "contract_version": 12},
            {"command": "review", "effect": "validate recipe and compare semantic diffs",
             "cli": "de review --recipe ID [--compare ID] --json", "contract_version": 1},
            {"command": "draft-edit", "effect": "create private reviewed JSON draft",
             "cli": "de draft-edit --recipe ID --edit FILE --output NEW.json --json",
             "contract_version": EDIT_VERSION},
            {"command": "render", "effect": "isolated real native headless screenshot",
             "cli": "de render --recipe ID --output NEW.png --json", "contract_version": 1},
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
            "Schema-v1..v11 shell preview; v11 adds private native TTF and 48px RGBA icons; v6+ supports bounded wallpaper PNG",
            "Live apply is explicit and supervised; Wayland session remains experimental",
            "Native tray, complete settings, notification center and physical multi-monitor acceptance remain open",
        ],
    }
    private_writes = {"draft-edit", "render", "visual-baseline", "capture",
                      "pack-export", "pack-import", "asset-import"}
    next_login = {"creator-stage", "creator-rollback"}
    active_wayland = {"creator-live-apply", "creator-live-restore", "display-refresh"}
    active_user = {"notification-dismiss", "notification-invoke", "audio-default"}
    for command in contract["commands"]:
        name = command["command"]
        command["mutation_scope"] = (
            "active-wayland-session" if name in active_wayland else
            "active-user-session" if name in active_user else
            "next-login" if name in next_login else
            "private-file-optional" if name == "visual-compare" else
            "private-file" if name in private_writes else "none")
        command["requires_explicit_user_invocation"] = (
            name in active_wayland | active_user | next_login | {"capture"})
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
