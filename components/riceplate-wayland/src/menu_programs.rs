//! XDG Categories -> static XP-style folders. These are navigation tokens, not commands.

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Category {
    Accessories, Games, Graphics, Internet, Multimedia, Office, Development, System, Other,
}
impl Category {
    pub const ORDER: [Self; 9] = [Self::Accessories, Self::Games, Self::Graphics,
        Self::Internet, Self::Multimedia, Self::Office, Self::Development,
        Self::System, Self::Other];

    pub const fn action(self) -> &'static str {
        match self {
            Self::Accessories => "menu-category:accessories",
            Self::Games => "menu-category:games",
            Self::Graphics => "menu-category:graphics",
            Self::Internet => "menu-category:internet",
            Self::Multimedia => "menu-category:multimedia",
            Self::Office => "menu-category:office",
            Self::Development => "menu-category:development",
            Self::System => "menu-category:system",
            Self::Other => "menu-category:other",
        }
    }
    pub const fn title(self) -> &'static str {
        match self {
            Self::Accessories => "Accessories",
            Self::Games => "Games",
            Self::Graphics => "Graphics",
            Self::Internet => "Internet",
            Self::Multimedia => "Entertainment",
            Self::Office => "Office",
            Self::Development => "Development",
            Self::System => "System Tools",
            Self::Other => "Other Programs",
        }
    }
    pub fn from_action(action: &str) -> Option<Self> {
        Self::ORDER.into_iter().find(|category| category.action() == action)
    }
    /// Only read the recognized Categories key from the main Desktop Entry.
    /// Unknown values cannot become dynamic executable menu entries.
    pub fn from_desktop_data(data: &str) -> Self {
        let mut in_entry = false;
        for line in data.lines() {
            let line = line.trim();
            if line.starts_with('[') {
                in_entry = line == "[Desktop Entry]";
                continue;
            }
            if in_entry {
                if let Some(value) = line.strip_prefix("Categories=") {
                    return Self::from_categories(value);
                }
            }
        }
        Self::Other
    }
    fn from_categories(value: &str) -> Self {
        let tags: Vec<_> = value.split(';').collect();
        let has = |names: &[&str]| names.iter().any(|name| tags.contains(name));
        if has(&["Game"]) { Self::Games }
        else if has(&["Network", "WebBrowser", "Email", "InstantMessaging", "Chat"]) {
            Self::Internet
        } else if has(&["AudioVideo", "Audio", "Video", "Music", "Player", "Recorder"]) {
            Self::Multimedia
        } else if has(&["Graphics", "Photography", "2DGraphics", "3DGraphics"]) {
            Self::Graphics
        } else if has(&["Office", "WordProcessor", "Spreadsheet", "Presentation"]) {
            Self::Office
        } else if has(&["Development", "IDE", "GUIDesigner"]) {
            Self::Development
        } else if has(&["Settings", "System", "Monitor", "Security"]) {
            Self::System
        } else if has(&["Utility", "FileManager", "Archiving", "TextEditor"]) {
            Self::Accessories
        } else { Self::Other }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn categories_are_stable_and_scoped_to_main_desktop_group() {
        assert_eq!(Category::from_desktop_data(
            "[Desktop Entry]\nType=Application\nCategories=Network;WebBrowser;\n"),
            Category::Internet);
        assert_eq!(Category::from_desktop_data(
            "[Other]\nCategories=Game;\n[Desktop Entry]\nCategories=Office;\n"),
            Category::Office);
        assert_eq!(Category::from_desktop_data(
            "[Desktop Entry]\nCategories=Utility;AudioVideo;\n"),
            Category::Multimedia);
        assert_eq!(Category::from_desktop_data(
            "[Desktop Entry]\nCategories=UntrustedName;\n"), Category::Other);
        assert_eq!(Category::from_desktop_data("[Desktop Entry]\nName=Tool\n"),
                   Category::Other);
        assert!(Category::from_action("desktop:some-app.desktop").is_none());
        for category in Category::ORDER {
            assert_eq!(Category::from_action(category.action()), Some(category));
        }
    }
}
