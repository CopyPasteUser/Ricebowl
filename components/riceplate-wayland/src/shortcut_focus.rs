//! Pure XP Luna shortcut keyboard navigation, separate from Wayland focus ownership.
//!
//! Labels are supplied only for *visible same-output* shortcuts. No recipe
//! command is executed by this module. Bounded Unicode scalar prefix state
//! is kept by the short-lived, compositor-confirmed focus lease.
pub const MAX_PREFIX: usize = 48;

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

#[cfg(test)]
mod tests {
    use super::*;
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
    fn never_selects_out_of_bounds_hidden_and_malformed_prefixes() {
        assert_eq!(match_visible_prefix("Programs", [None, None, Some("Other")]), None);
        assert_eq!(match_visible_prefix("", [Some("A")]), None);
        assert_eq!(match_visible_prefix(&"x".repeat(MAX_PREFIX + 1), [Some("x")]), None);
        assert_eq!(match_visible_prefix("a\n", [Some("a")]), None);
    }
}
