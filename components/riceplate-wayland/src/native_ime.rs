//! Bounded Wayland text-input-v3 double-buffered IME events for Luna editors.
//! The compositor may send preedit, deletion and commit in any order before
//! Done; editor mutations happen only at Done as one validated transaction.
//! This module owns neither a Wayland proxy nor any persisted user text.

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
        if text.chars().count() > crate::luna_dialog::MAX_INPUT
            || text.chars().any(char::is_control) { return None; }
        let (cursor, anchor) = match (begin, end) {
            (-1, -1) => (None, None),
            (a, b) if a >= 0 && b >= 0 => {
                let a = usize::try_from(a).ok()?;
                let b = usize::try_from(b).ok()?;
                if !text.is_char_boundary(a) || !text.is_char_boundary(b)
                    || a > text.len() || b > text.len() { return None; }
                // A caret inside a combining sequence must not be painted
                // between the base and its diacritic.
                if !text.grapheme_indices(true).map(|(i, _)| i)
                    .chain(std::iter::once(text.len())).any(|i| i == a)
                    || !text.grapheme_indices(true).map(|(i, _)| i)
                    .chain(std::iter::once(text.len())).any(|i| i == b) {
                    return None;
                }
                (Some(a), Some(b))
            }
            _ => return None,
        };
        Some(Self { text: text.to_owned(), cursor, anchor })
    }
}
use unicode_segmentation::UnicodeSegmentation;

#[derive(Default, Clone, Debug)]
pub(crate) struct Pending {
    pub(crate) preedit: Option<Result<Preedit, ()>>,
    pub(crate) commit: Option<String>,
    pub(crate) delete: Option<(u32, u32)>,
}

impl Pending {
    pub(crate) fn reset(&mut self) { *self = Self::default(); }

    pub(crate) fn preedit(&mut self, text: Option<String>, start: i32, end: i32) {
        self.preedit = Some(Preedit::parse(text.as_deref().unwrap_or(""), start, end).ok_or(()));
    }
    pub(crate) fn commit(&mut self, text: Option<String>) {
        self.commit = Some(text.unwrap_or_default());
    }
    pub(crate) fn delete(&mut self, before: u32, after: u32) {
        self.delete = Some((before, after));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::luna_dialog::{Kind, State};

    #[test]
    fn preedit_requires_valid_utf8_and_grapheme_boundaries() {
        let valid = Preedit::parse("a\u{301}👩‍💻", 3, 14).unwrap();
        assert_eq!(valid.cursor, Some(3));
        assert_eq!(valid.anchor, Some(14));
        assert!(Preedit::parse("a\u{301}", 1, 3).is_none());
        assert!(Preedit::parse("é", 1, 2).is_none());
        assert!(Preedit::parse("a", -1, 0).is_none());
        assert!(Preedit::parse("x\n", 0, 0).is_none());
        assert_eq!(Preedit::parse("é", -1, -1).unwrap().cursor, None);
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
        pending.preedit(Some("a\u{301}".into()), 1, 3);
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
        assert!(state.preedit.is_none(), "direct keyboard input cancels stale composition");
    }
}
