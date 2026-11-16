//! Pure XP Luna shortcut keyboard navigation, separate from Wayland focus ownership.
//!
//! Labels are supplied only for *visible same-output* shortcuts. No recipe
//! command is executed by this module. Bounded Unicode scalar prefix state
//! is kept by the short-lived, compositor-confirmed focus lease.
pub const MAX_PREFIX: usize = 48;

/// A Wayland keyboard event may deliver more than one Unicode scalar for a
/// *single* user-perceived character. Accept exactly one extended grapheme,
/// never arbitrary pasted words, control sequences or unbounded input.
/// This does not implement text-input-v3/IME preedit or normalization.
pub(crate) fn is_single_grapheme_input(input: &str) -> bool {
    use unicode_segmentation::UnicodeSegmentation;
    !input.is_empty()
        && input.chars().count() <= MAX_PREFIX
        && input.chars().all(|letter| !letter.is_control())
        && input.graphemes(true).count() == 1
}

/// Keep type-to-select bounded by Unicode scalar count, including a complete
/// multi-scalar grapheme. Overflow resets the old prefix before appending.
pub(crate) fn append_grapheme_input(prefix: &mut String, input: &str) -> bool {
    if !is_single_grapheme_input(input) { return false; }
    if prefix.chars().count().saturating_add(input.chars().count()) > MAX_PREFIX {
        prefix.clear();
    }
    prefix.push_str(input);
    true
}


/// A compositor output notification does not necessarily move a desktop icon.
/// Keep its existing, short-lived keyboard lease only if the selected icon
/// remains on the exact same output at the exact same logical coordinates.
/// Removed icons, output replacement and real placement changes still revoke.
pub(crate) fn preserves_focus_on_reflow<O: PartialEq>(
    before: Option<(O, (u32, u32))>,
    after: Option<(O, (u32, u32))>,
) -> bool {
    before.is_some() && before == after
}

/// Choose the first matching visible peer in recipe order, not a hidden icon
/// or a different output's mirrored shortcut. Unicode lowercasing is supported
/// without interpreting the label as a path or executable command.
pub fn match_visible_prefix<'a>(query: &str, peers: impl IntoIterator<Item = Option<&'a str>>)
                                -> Option<usize> {
    if query.is_empty() || query.chars().count() > MAX_PREFIX
        || query.chars().any(char::is_control) {
        return None;
    }
    let needle = query.to_lowercase();
    peers.into_iter().enumerate().find_map(|(index, label)|
        label.filter(|name| name.to_lowercase().starts_with(&needle)).map(|_| index))
}

/// Navigate only real placed peers on the active compositor output.
/// A removed/hidden current icon cannot be silently replaced with an
/// unrelated file. The caller revokes that stale focus lease instead.
pub(crate) fn next_visible_file<T: PartialEq + Clone>(
    visible: &[T], current: &T, backwards: bool,
) -> Option<T> {
    let at = visible.iter().position(|item| item == current)?;
    let len = visible.len();
    let next = if backwards { (at + len - 1) % len } else { (at + 1) % len };
    Some(visible[next].clone())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn composed_text_is_one_safe_keyboard_input_not_multiple_presses() {
        for character in ["a\u{301}", "👩‍💻", "👍🏽", "🇩🇪", "Ä", "A"] {
            assert!(is_single_grapheme_input(character), "{character:?}");
        }
        for invalid in ["", "ab", "a\n", "\u{0000}", "👩‍💻x", &"b".repeat(49)] {
            assert!(!is_single_grapheme_input(invalid), "{invalid:?}");
        }
        let mut input = "a".repeat(MAX_PREFIX - 1);
        assert!(append_grapheme_input(&mut input, "👩‍💻"));
        assert_eq!(input, "👩‍💻");
        assert!(append_grapheme_input(&mut input, "x"));
        assert_eq!(input, "👩‍💻x");
        assert!(!append_grapheme_input(&mut input, "xy"));
        assert_eq!(input, "👩‍💻x");
        assert_eq!(match_visible_prefix("a\u{301}",
                   [Some("a\u{301}pplications"), Some("programs")]), Some(0));
    }

    #[test]
    fn file_keyboard_navigation_skips_unplaced_peers_and_refuses_stale_target() {
        let same_output_visible = [1_u32, 4, 8];
        // Hidden icon 2 and other-output icon 5 are not present in peers.
        assert_eq!(next_visible_file(&same_output_visible, &1, false), Some(4));
        assert_eq!(next_visible_file(&same_output_visible, &4, false), Some(8));
        assert_eq!(next_visible_file(&same_output_visible, &8, false), Some(1));
        assert_eq!(next_visible_file(&same_output_visible, &1, true), Some(8));
        assert_eq!(next_visible_file(&same_output_visible, &8, true), Some(4));
        assert_eq!(next_visible_file(&same_output_visible, &2, false), None);
        assert_eq!(next_visible_file(&same_output_visible, &5, true), None);
        assert_eq!(next_visible_file::<u32>(&[], &1, true), None);
        assert_eq!(next_visible_file(&[8_u32], &8, false), Some(8));
    }

    #[test]
    fn unicode_prefix_matches_only_live_same_output_shortcuts() {
        let peers = [Some("Recycle Bin"), None, Some("Programs"),
                     Some("Änderungen"), None, Some("Pizza 🍚")];
        assert_eq!(match_visible_prefix("p", peers), Some(2));
        assert_eq!(match_visible_prefix("PRo", peers), Some(2));
        assert_eq!(match_visible_prefix("änd", peers), Some(3));
        assert_eq!(match_visible_prefix("pizza 🍚", peers), Some(5));
        assert_eq!(match_visible_prefix("x", peers), None);
    }
    #[test]
    fn noop_output_notification_must_not_drop_real_keyboard_focus() {
        assert!(preserves_focus_on_reflow(Some((1_u32, (128, 400))),
                                          Some((1_u32, (128, 400)))));
        assert!(!preserves_focus_on_reflow(Some((1_u32, (128, 400))),
                                           Some((1_u32, (129, 400)))));
        assert!(!preserves_focus_on_reflow(Some((1_u32, (128, 400))),
                                           Some((2_u32, (128, 400)))));
        assert!(!preserves_focus_on_reflow(Some((1_u32, (128, 400))), None));
        assert!(!preserves_focus_on_reflow(None::<(u32, (u32, u32))>, None));
    }

    #[test]
    fn never_selects_out_of_bounds_hidden_and_malformed_prefixes() {
        assert_eq!(match_visible_prefix("Programs", [None, None, Some("Other")]), None);
        assert_eq!(match_visible_prefix("", [Some("A")]), None);
        assert_eq!(match_visible_prefix(&"x".repeat(MAX_PREFIX + 1), [Some("x")]), None);
        assert_eq!(match_visible_prefix("a\n", [Some("a")]), None);
    }
}
