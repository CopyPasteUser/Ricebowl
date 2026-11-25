//! Bounded Wayland text-input-v3 double-buffered IME events for Luna editors.
//! The compositor may send preedit, deletion and commit in any order before
//! Done; editor mutations happen only at Done as one validated transaction.
//! This module owns neither a Wayland proxy nor any persisted user text.

use std::time::{Duration, Instant};

/// Suppress at most the matching keyboard echo of an IME commit, within a
/// short interval. Never consume a different, genuine next printable key.
/// Return can be an echo of the key used to accept a candidate, so retain
/// that guard; Escape and non-text editing keys always remain responsive.
const IME_ECHO_WINDOW: Duration = Duration::from_millis(80);

#[derive(Clone, Debug)]
pub(crate) struct RecentCommit {
    pub(crate) at: Instant,
    pub(crate) text: String,
}

pub(crate) fn suppress_keyboard_echo(
    composing: bool,
    recent_commit: &mut Option<RecentCommit>,
    now: Instant,
    text: Option<&str>,
    return_key: bool,
) -> bool {
    if composing {
        return text.is_some() || return_key;
    }
    if text.is_none() && !return_key {
        return false;
    }
    let Some(committed) = recent_commit.take() else {
        return false;
    };
    now.checked_duration_since(committed.at)
        .is_some_and(|elapsed| elapsed <= IME_ECHO_WINDOW)
        && (return_key || text == Some(committed.text.as_str()))
}

/// A preedit owns the editing keys of the current Run/Rename field. Outside
/// composition, only the matching text echo or candidate-confirming Return
/// may be suppressed. Other characters must never vanish after IME Done.
pub(crate) fn owns_keyboard_edit(
    composing: bool,
    recent_commit: &mut Option<RecentCommit>,
    now: Instant,
    text: Option<&str>,
    return_key: bool,
    editor_control: bool,
    escape: bool,
) -> bool {
    if composing {
        return text.is_some() || editor_control;
    }
    if escape {
        return false;
    }
    suppress_keyboard_echo(false, recent_commit, now, text, return_key)
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct Preedit {
    pub(crate) text: String,
    /// UTF-8 byte offset inside the preedit, or None when the IME hides it.
    pub(crate) cursor: Option<usize>,
    pub(crate) anchor: Option<usize>,
}

impl Preedit {
    pub(crate) fn parse(text: &str, begin: i32, end: i32) -> Option<Self> {
        // Protocol indices are byte offsets, not Unicode scalar counts.
        // A Unicode scalar occupies at most four UTF-8 bytes. Reject an
        // oversized compositor-provided preedit in O(1) before two full
        // Unicode scans (as the commit_string path already does).
        let limit = crate::luna_dialog::MAX_INPUT;
        if text.len() > limit * 4
            || text.chars().take(limit + 1).count() > limit
            || text.chars().any(char::is_control)
        {
            return None;
        }
        let (cursor, anchor) = match (begin, end) {
            (-1, -1) => (None, None),
            (a, b) if a >= 0 && b >= 0 => {
                let a = usize::try_from(a).ok()?;
                let b = usize::try_from(b).ok()?;
                if !text.is_char_boundary(a)
                    || !text.is_char_boundary(b)
                    || a > text.len()
                    || b > text.len()
                {
                    return None;
                }
                // text-input-v3 specifies UTF-8 *byte* offsets, not
                // extended-grapheme indices. A valid IME may put its cursor
                // between a base and combining mark (or inside a ZWJ
                // sequence). Preserve that protocol offset here: the editor
                // projects it onto a whole-grapheme painted caret. Reject
                // offsets inside a UTF-8 scalar or outside the preedit.
                (Some(a), Some(b))
            }
            _ => return None,
        };
        Some(Self {
            text: text.to_owned(),
            cursor,
            anchor,
        })
    }
}
#[derive(Default, Clone, Debug)]
pub(crate) struct Pending {
    pub(crate) preedit: Option<Result<Preedit, ()>>,
    pub(crate) commit: Option<String>,
    // Never keep a maliciously large or invalid compositor-provided commit
    // alive until Done. If another commit_string event arrives, its *latest*
    // value replaces the old one, preserving existing v3 buffering semantics.
    pub(crate) invalid_commit: bool,
    pub(crate) delete: Option<(u32, u32)>,
}

impl Pending {
    pub(crate) fn reset(&mut self) {
        *self = Self::default();
    }

    pub(crate) fn preedit(&mut self, text: Option<String>, start: i32, end: i32) {
        self.preedit = Some(Preedit::parse(text.as_deref().unwrap_or(""), start, end).ok_or(()));
    }
    pub(crate) fn commit(&mut self, text: Option<String>) {
        let content = text.unwrap_or_default();
        // A valid single-line editor cannot accept more than MAX_INPUT
        // Unicode scalars (at most 4 UTF-8 bytes each). Check byte size first
        // to avoid decoding an oversized Wayland payload a second time.
        let limit = crate::luna_dialog::MAX_INPUT;
        if content.len() > limit * 4
            || content.chars().take(limit + 1).count() > limit
            || content.chars().any(char::is_control)
        {
            self.commit = None;
            self.invalid_commit = true;
            return;
        }
        // A later commit_string is permitted to replace a previous invalid
        // value before Done, just as the existing editor tests require.
        self.invalid_commit = false;
        self.commit = Some(content);
    }
    pub(crate) fn delete(&mut self, before: u32, after: u32) {
        self.delete = Some((before, after));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn committed(text: &str, at: Instant) -> Option<RecentCommit> {
        Some(RecentCommit {
            at,
            text: text.to_owned(),
        })
    }

    #[test]
    fn ime_echo_only_matches_actual_commit_not_first_new_character() {
        let now = Instant::now();
        let mut last = committed("あ", now);
        // Navigation, Backspace and modifiers neither block nor consume.
        assert!(!suppress_keyboard_echo(false, &mut last, now, None, false));
        assert!(last.is_some());
        // This is a new character typed immediately after the IME commit.
        // The old any-key guard incorrectly lost it.
        assert!(!suppress_keyboard_echo(
            false,
            &mut last,
            now + Duration::from_millis(4),
            Some("b"),
            false
        ));
        assert!(last.is_none(), "unmatched text must disarm the old echo");
        assert!(!suppress_keyboard_echo(
            false,
            &mut last,
            now + Duration::from_millis(5),
            Some("あ"),
            false
        ));

        let mut duplicate = committed("é", now);
        assert!(suppress_keyboard_echo(
            false,
            &mut duplicate,
            now + Duration::from_millis(3),
            Some("é"),
            false
        ));
        assert!(duplicate.is_none());
        assert!(!suppress_keyboard_echo(
            false,
            &mut duplicate,
            now + Duration::from_millis(4),
            Some("é"),
            false
        ));
        // A candidate-confirming Return may be mirrored by wl_keyboard.
        let mut accept = committed("日本語", now);
        assert!(suppress_keyboard_echo(
            false,
            &mut accept,
            now + Duration::from_millis(6),
            None,
            true
        ));
        assert!(accept.is_none());
        let mut expired = committed("x", now);
        assert!(!suppress_keyboard_echo(
            false,
            &mut expired,
            now + IME_ECHO_WINDOW + Duration::from_millis(1),
            Some("x"),
            false
        ));
        assert!(expired.is_none());
        let mut out_of_order = committed("x", now);
        assert!(!suppress_keyboard_echo(
            false,
            &mut out_of_order,
            now - Duration::from_millis(1),
            Some("x"),
            false
        ));
        assert!(out_of_order.is_none());
    }

    #[test]
    fn preedit_owns_editing_and_escape_recovers_without_eating_next_text() {
        let now = Instant::now();
        let mut marker = committed("字", now);
        // Active preedit defers printable text and all destructive/nav keys.
        assert!(owns_keyboard_edit(
            true,
            &mut marker,
            now,
            Some("a"),
            false,
            false,
            false
        ));
        assert!(owns_keyboard_edit(
            true,
            &mut marker,
            now,
            None,
            false,
            true,
            false
        ));
        assert!(owns_keyboard_edit(
            true,
            &mut marker,
            now,
            None,
            true,
            true,
            false
        ));
        assert!(!owns_keyboard_edit(
            true,
            &mut marker,
            now,
            None,
            false,
            false,
            false
        ));
        assert!(marker.is_some());
        // Done releases Escape immediately even within the guard window.
        assert!(!owns_keyboard_edit(
            false,
            &mut marker,
            now + Duration::from_millis(1),
            None,
            false,
            true,
            true
        ));
        assert!(marker.is_some());
        assert!(!owns_keyboard_edit(
            false,
            &mut marker,
            now + Duration::from_millis(2),
            None,
            false,
            true,
            false
        ));
        assert!(marker.is_some());
        assert!(!owns_keyboard_edit(
            false,
            &mut marker,
            now + Duration::from_millis(3),
            Some("x"),
            false,
            false,
            false
        ));
        assert!(marker.is_none());
    }

    use crate::luna_dialog::{Kind, State};

    #[test]
    fn oversized_commit_rejects_done_but_later_valid_commit_can_supersede_it() {
        let max = crate::luna_dialog::MAX_INPUT;
        let mut pending = Pending::default();
        pending.delete(3, 0);
        pending.commit(Some("あ".repeat(max + 1)));
        assert!(pending.invalid_commit);
        assert!(
            pending.commit.is_none(),
            "never retain the attacker-sized string"
        );
        let mut state = State::new(Kind::Run);
        assert!(state.commit_text("old"));
        assert!(!state.apply_ime(&pending));
        assert_eq!(
            state.input, "old",
            "delete must roll back as part of invalid Done"
        );

        // Later valid buffered commit overrides the invalid one, mirroring
        // text-input-v3 and the pre-existing Luna editor contract.
        pending.commit(Some("safe".to_owned()));
        assert!(!pending.invalid_commit);
        assert_eq!(pending.commit.as_deref(), Some("safe"));
        assert!(state.apply_ime(&pending));
        assert_eq!(state.input, "safe");

        pending.reset();
        pending.commit(Some("new".to_owned()));
        assert!(state.apply_ime(&pending));
        assert_eq!(state.input, "safenew");

        pending.reset();
        pending.commit(Some("x\n".to_owned()));
        assert!(pending.invalid_commit);
        assert!(pending.commit.is_none());
        pending.reset();
        pending.commit(None);
        assert_eq!(pending.commit.as_deref(), Some(""));
        assert!(!pending.invalid_commit);
    }

    #[test]
    fn preedit_requires_utf8_scalar_boundaries_but_allows_intra_grapheme_carets() {
        let valid = Preedit::parse("a\u{301}👩‍💻", 3, 14).unwrap();
        assert_eq!(valid.cursor, Some(3));
        assert_eq!(valid.anchor, Some(14));
        // A protocol-valid cursor can be between the base and its accent.
        // Rejecting this whole batch would lose legitimate IME commits.
        let inside = Preedit::parse("a\u{301}", 1, 3).unwrap();
        assert_eq!(inside.cursor, Some(1));
        assert_eq!(inside.anchor, Some(3));
        let joined = Preedit::parse("👩‍💻", 4, 7).unwrap();
        assert_eq!((joined.cursor, joined.anchor), (Some(4), Some(7)));
        // UTF-8 continuation bytes remain invalid.
        assert!(Preedit::parse("a\u{301}", 2, 3).is_none());
        assert!(Preedit::parse("é", 1, 2).is_none());
        assert!(Preedit::parse("a", -1, 0).is_none());
        assert!(Preedit::parse("x\n", 0, 0).is_none());
        assert_eq!(Preedit::parse("é", -1, -1).unwrap().cursor, None);
    }

    #[test]
    fn intra_cluster_caret_is_accepted_without_changing_committed_text() {
        let mut state = State::new(Kind::Run);
        assert!(state.commit_text("e"));
        let mut batch = Pending::default();
        batch.preedit(Some("\u{301}".to_owned()), 0, 0);
        assert!(state.apply_ime(&batch));
        assert_eq!(state.input, "e");
        assert_eq!(state.preedit.as_ref().unwrap().cursor, Some(0));

        batch.reset();
        // Combined commit and preedit with a valid *scalar* boundary inside
        // a multi-scalar grapheme must not drop the committed Japanese text.
        batch.commit(Some("日本".to_owned()));
        batch.preedit(Some("a\u{301}".to_owned()), 1, 1);
        assert!(state.apply_ime(&batch));
        assert_eq!(state.input, "e日本");
        assert_eq!(state.preedit.as_ref().unwrap().cursor, Some(1));
    }

    #[test]
    fn oversized_preedit_is_rejected_before_unicode_scans() {
        let limit = crate::luna_dialog::MAX_INPUT;
        let max_cjk = "漢".repeat(limit);
        assert!(Preedit::parse(&max_cjk, -1, -1).is_some());
        assert!(Preedit::parse(&"漢".repeat(limit + 1), -1, -1).is_none());
        assert!(Preedit::parse(&"🦀".repeat(limit + 1), -1, -1).is_none());
        // Even an ASCII-only hostile preedit above the maximum possible
        // UTF-8 byte size must fail before an unbounded character traversal.
        assert!(Preedit::parse(&"x".repeat(limit * 4 + 1), -1, -1).is_none());
        // The bound must not alter valid byte-offset/grapheme IME caret data.
        assert_eq!(Preedit::parse("a\u{301}👩‍💻", 3, 14).unwrap().cursor, Some(3));
    }

    #[test]
    fn done_transaction_is_atomic_on_invalid_delete_or_commit() {
        let mut state = State::new(Kind::FileRename);
        assert!(state.commit_text("a\u{301}🦀.txt"));
        assert!(state.move_cursor(crate::luna_dialog::CursorMove::Home));
        assert!(state.move_cursor(crate::luna_dialog::CursorMove::Right));
        let before = (state.input.clone(), state.cursor);
        let mut pending = Pending::default();
        pending.delete(1, 0); // one byte inside a multi-byte grapheme
        pending.commit(Some("Z".into()));
        assert!(!state.apply_ime(&pending));
        assert_eq!((state.input.clone(), state.cursor), before);
        pending.reset();
        pending.delete(0, 2); // splitting the next multi-byte emoji
        assert!(!state.apply_ime(&pending));
        assert_eq!((state.input.clone(), state.cursor), before);
        pending.reset();
        pending.preedit(Some("a\u{301}".into()), 2, 3);
        assert!(!state.apply_ime(&pending));
        assert_eq!((state.input.clone(), state.cursor), before);
    }

    #[test]
    fn combined_delete_commit_and_preedit_are_applied_in_done_order() {
        let mut state = State::new(Kind::Run);
        assert!(state.commit_text("hello.txt"));
        assert!(state.move_cursor(crate::luna_dialog::CursorMove::Home));
        let mut p = Pending::default();
        p.delete(0, 5);
        p.commit(Some("日本語".into()));
        p.preedit(Some("あ".into()), 3, 3);
        assert!(state.apply_ime(&p));
        assert_eq!(state.input, "日本語.txt");
        assert_eq!(state.cursor, 3);
        assert_eq!(state.preedit.as_ref().unwrap().text, "あ");
        assert_eq!(state.surrounding_text().1, "日本語".len() as i32);
        assert!(state.input.chars().count() < crate::luna_dialog::MAX_INPUT);
    }

    #[test]
    fn delete_requires_whole_graphemes_and_preserves_notice_on_failure() {
        let mut state = State::new(Kind::FileRename);
        assert!(state.commit_text("🇩🇪.txt"));
        assert!(state.move_cursor(crate::luna_dialog::CursorMove::Home));
        let mut p = Pending::default();
        p.delete(0, 4);
        state.notice = Some("Keep error");
        assert!(!state.apply_ime(&p));
        assert_eq!(state.notice, Some("Keep error"));
        p.delete(0, "🇩🇪".len() as u32);
        assert!(state.apply_ime(&p));
        assert_eq!(state.input, ".txt");
    }

    #[test]
    fn preedit_is_preview_only_not_shell_command_storage() {
        let mut state = State::new(Kind::Run);
        assert!(state.commit_text("foot"));
        let mut p = Pending::default();
        p.preedit(Some(" あ".into()), 4, 4);
        assert!(state.apply_ime(&p));
        assert_eq!(state.argv().unwrap(), ["foot"]);
        assert!(state.preedit.is_some());
        state.commit_text("x");
        assert!(
            state.preedit.is_none(),
            "direct keyboard input cancels stale composition"
        );
    }
}
