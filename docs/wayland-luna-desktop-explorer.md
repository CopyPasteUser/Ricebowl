# RiceBowl XP Luna — XDG Desktop & RiceField integration 5.0

Status: **proposed in PR #355, stacked on PR #342**. It is not a merged
desktop feature and must not be advertised as stable before native compositor
focus and end-to-end filesystem tests pass.

## Integration boundaries

- `components/riceplate-wayland/src/desktop_files.rs` handles the **bounded,
  owned XDG Desktop directory snapshot** (not an entire Explorer/file manager).
  All paths stay as `OsString` / `PathBuf`; the lossy on-screen label is never
  used as the operation target. Up to 48 visible, sorted entries are sampled
  from a maximum of 512 directory records, with refresh at most once per four
  seconds or on the explicit root Refresh/New Folder request.
- `desktop_file_positions.rs` stores **file icon** coordinates separately
  from `icon_positions.rs`, keyed by device+inode and logical output name.
  Private file: `$XDG_CONFIG_HOME/ricebowl/native-file-icon-positions.json`,
  otherwise `~/.config/ricebowl/native-file-icon-positions.json`.
  Directory/file permissions, bounded JSON, symlinks, and invalid display
  identifiers fail closed. Renaming retains the inode identity; deleting and
  replacing an entry ordinarily does not. Hardlinks to the same inode currently
  share a position identity, and no multi-output independent file copies exist.
- The static recipe desktop icons and their per-output positions remain
  unchanged. Real Desktop entries are runtime-only icon layers, hosted **only
  on the primary output**. The chosen output can change with hotplug; saved
  positions use its advertised name where available.
- The app's existing labwc/layer-shell and `xdg_popup` focus implementation
  comes from PR #342. The popup never requests an invisible fullscreen layer
  or global keyboard grab. An active popup may accept compositor keyboard focus
  on the popup **or its already-focused parent icon**; a focus loss dismisses
  the transient menu. The exact headless-labwc 0.9.4 keyboard test is a
  mandatory acceptance gate, not a reason to claim success without evidence.
- Opt-in `xp-luna-columns` **standalone session only**. Nested Creator previews
  and other rices do not enumerate or operate on the user's files.

## Supported operations and current limits

| User action | Backend and current contract |
| --- | --- |
| Browse Desktop | Real XDG Desktop path validated, bounded 4s refresh; owner must match current UID |
| New Folder | Existing private desktop IPC creates actual directory; new native icon appears on refresh |
| File double-open | Gio MIME handling, guarded by live entry kind and device/inode |
| Folder double-open | RiceField `--theme xp-luna --separate-window <absolute path>` (verified in RiceField `src/main.rs`), Gio fallback if executable is absent |
| Desktop file menu | Genuine icon-parented XDG popup from #342, new file-specific Open/Rename/Move to Trash/Open in Explorer/Properties rows |
| F2 / rename | Unicode editor with visible errors, Linux `renameat2(RENAME_NOREPLACE)`, no implicit target overwrite |
| Delete / Trash | Explicit visible confirmation; `gio trash <path>`, **not** permanent delete. Gio exit/async completion is not mistaken for immediate success; directory snapshot subsequently reconciles |
| Rename/file drag positions | Separate owner-private saved map, per named output, does not mutate validated recipe |
| Recycle Bin | `Full` indicator only if `$XDG_DATA_HOME/Trash/files` (or default `~/.local/share/Trash/files`) actually contains an entry; **not a total across external volumes** |
| Copy/cut/paste, bulk move, archives, advanced properties | Delegate to RiceField's already implemented GUI; do not add competing filesystem operations to RicePlate |
| Symbolic links | Visible distinct `Link` label but file activation and mutating paths fail closed |
| Network locations | Existing GVfs/Gio discovery; RiceField supports optional SMB/SFTP/WebDAV navigation with its own guarded backend limitations |

No `sh -c`, arbitrary recipe script, untrusted `.desktop Exec` interpretation,
external dependency, background daemon, or session/login-manager mutation.

**Known limitations:** no real MIME-specific thumbnail renderer; file
properties view currently only categorizes a local file/folder/link and does
not provide byte size/mtime/permissions. External-volume Trash entries are not
aggregated. Four-second bounded sampling is not a filesystem notification
service; unusual I/O latency in the Desktop mount can still delay the
synchronous scan. No true independent duplicate file icon on each display.
A file renamed or deleted externally during an operation may still race the
subsequent Gio process launch; no guarantee of transactionality with external
applications is claimed.

## Verification checklist

- Rust unit tests: Unicode/non-UTF8, symlink root, stale inode replacement,
  no-replace rename, bounds, file/folder painter, user-private config file,
  per-display positions, corrupt and symlink state.
- Exact PR head: `cargo test --locked`, native release build, repository
  Python suite; **CI status must be inspected after the latest commit**.
- Real isolated labwc: mouse and keyboard in the #342 parented popup,
  F2/Enter/Escape/Delete, double-click live file and folder, URI/MIME
  association, refresh after external add/remove, two outputs + unplug.
- Physical Mint 22 acceptance: verify XFCE/X11 unchanged and opt-in Luna
  return path, desktop files, XDG user paths, international text input,
  RiceField installed or absent fallback, lock/suspend/restore and all
  file-action error states. Do not claim physical results from CI.


## Desktop filesystem event refresh (stacked follow-up)

- Linux **inotify** (directory watch, nonblocking CLOEXEC fd) now feeds the
  existing calloop event loop; no polling thread or additional daemon.
- New, removed, renamed and closed-for-write entries trigger a bounded model
  refresh after 125 ms, coalesced across bursts of events. The existing 4s
  scan remains as the recovery fallback if inotify setup fails, the watch is
  invalidated, or the kernel reports queue overflow.
- A disappearing entry between directory enumeration and lstat is skipped
  without destroying an otherwise valid snapshot; permission errors still
  surface instead of being silently ignored.
- Rust fixtures cover real create/rename/delete, non-UTF8 event names, lost
  directory watches and invalid directory paths. Exact-head CI and real
  labwc screenshot acceptance are still required.
- This is **not** file URI clipboard transfer, Wayland DnD or native bulk copy;
  those are separate protocol integrations and remain delegated to RiceField.
  No new global MIME associations or data-destructive actions are added.

### Rename path anchoring

Renames on Linux now open the verified Desktop directory with
`O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC` and use a directory-relative
`renameat2(RENAME_NOREPLACE)` after comparing directory and source
device/inode metadata. A replaced Desktop path cannot redirect the operation
to another directory. The kernel does not provide atomic
compare-source-inode-and-rename, so a same-UID process racing a single
source basename between `fstatat` and `renameat2` remains a known limitation.
The regression fixture explicitly replaces the Desktop root with a symlink and
verifies unrelated files are untouched.
