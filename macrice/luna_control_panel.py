"""Windows XP-inspired category Control Panel with real XFCE actions.

The panel intentionally uses installed Linux utilities instead of pretending
that an unavailable Windows applet exists. No settings are changed on open.
"""

from __future__ import annotations

import shutil


LUNA_CATEGORIES = (
    ("Appearance and Themes", "ricehub-luna-cp-appearance",
     ("xfce4-appearance-settings",), "Colors, fonts and window appearance"),
    ("Network and Internet Connections", "ricehub-luna-cp-network",
     ("nm-connection-editor", "nm-applet"), "Configure network connections"),
    ("Add or Remove Programs", "ricehub-luna-cp-programs",
     ("mintinstall", "gnome-software", "synaptic"), "Install or remove applications"),
    ("Sounds, Speech, and Audio Devices", "ricehub-luna-cp-audio",
     ("pavucontrol", "xfce4-mixer"), "Playback and input devices"),
    ("Performance and Maintenance", "ricehub-luna-cp-performance",
     ("xfce4-taskmanager", "gnome-system-monitor"), "Inspect running processes"),
    ("Printers and Other Hardware", "ricehub-luna-cp-hardware",
     ("system-config-printer",), "Set up printers"),
    ("User Accounts", "ricehub-luna-cp-accounts",
     ("users-admin", "gnome-control-center"), "Manage local accounts"),
    ("Date, Time, Language, and Regional Options", "ricehub-luna-cp-regional",
     ("time-admin", "xfce4-settings-manager"), "Open regional and time settings"),
    ("Accessibility Options", "ricehub-luna-cp-accessibility",
     ("xfce4-accessibility-settings",), "Make input and display easier to use"),
)

LUNA_CATEGORY_ICONS = {name: icon for name, icon, _tools, _hint in LUNA_CATEGORIES}


def task_art(category, icon):
    """A bespoke XP category glyph always exists; generic missing-icon squares do not."""
    from .installer import project_root

    themed_name = "ricehub-luna-task-" + icon
    themed = (project_root() / "assets/icons/RiceHub-Luna-Icons/scalable/apps" /
              (themed_name + ".svg"))
    return themed_name if themed.is_file() else LUNA_CATEGORY_ICONS[category]

# Windows XP's categories lead to task pages; only leaf actions launch Linux
# settings utilities. This is also the source for Classic View and search.
LUNA_TASKS = {
    "Appearance and Themes": (
        ("Change the desktop theme", "preferences-desktop-theme", ("xfce4-appearance-settings",),
         "Colors, fonts and widget styles"),
        ("Change the desktop background", "preferences-desktop-wallpaper", ("xfdesktop-settings",),
         "Wallpaper and desktop icons"),
        ("Change window borders", "preferences-system-windows", ("xfwm4-settings",),
         "Window frames and title bars"),
    ),
    "Network and Internet Connections": (
        ("View network connections", "network-workgroup", ("nm-connection-editor",),
         "Edit saved Wi-Fi and wired connections"),
        ("Configure Bluetooth devices", "bluetooth", ("blueman-manager",),
         "Pair and manage Bluetooth devices"),
    ),
    "Add or Remove Programs": (
        ("Install or remove programs", "system-software-install",
         ("mintinstall", "gnome-software", "synaptic"), "Open the installed software manager"),
        ("Browse installed applications", "system-search", ("xfce4-appfinder",),
         "Find and launch desktop programs"),
        ("Set preferred applications", "preferences-desktop-default-applications",
         ("exo-preferred-applications",), "Choose default browser and mail apps"),
    ),
    "Sounds, Speech, and Audio Devices": (
        ("Adjust audio devices", "audio-card", ("pavucontrol", "xfce4-mixer"),
         "Input, output and playback levels"),
        ("Configure notification sounds", "preferences-desktop-notification",
         ("xfce4-notifyd-config",), "Desktop notification preferences"),
    ),
    "Performance and Maintenance": (
        ("View running processes", "utilities-system-monitor",
         ("xfce4-taskmanager", "gnome-system-monitor"), "CPU, memory and applications"),
        ("Adjust power options", "battery", ("xfce4-power-manager-settings",),
         "Battery, brightness and sleep settings"),
        ("Open system settings", "preferences-system", ("xfce4-settings-manager",),
         "Other installed XFCE settings"),
    ),
    "Printers and Other Hardware": (
        ("View printers", "printer", ("system-config-printer",),
         "Printer queues and device setup"),
        ("Change display settings", "video-display", ("xfce4-display-settings",),
         "Monitor layout and resolution"),
        ("Configure mouse and touchpad", "input-mouse", ("xfce4-mouse-settings",),
         "Pointer and button settings"),
    ),
    "User Accounts": (
        ("Manage user accounts", "system-users", ("users-admin", "mate-user-admin"),
         "Available local account manager"),
        ("Change session and startup", "system-log-out", ("xfce4-session-settings",),
         "Autostart programs and saved sessions"),
    ),
    "Date, Time, Language, and Regional Options": (
        ("Set date and time", "preferences-system-time", ("time-admin", "gnome-control-center"),
         "Available date and time utility"),
        ("Keyboard and language settings", "input-keyboard", ("xfce4-keyboard-settings",),
         "Keyboard layouts and shortcuts"),
    ),
    "Accessibility Options": (
        ("Accessibility settings", "preferences-desktop-accessibility",
         ("xfce4-accessibility-settings",), "Keyboard, contrast and assistive options"),
        ("Mouse and pointer accessibility", "input-mouse", ("xfce4-mouse-settings",),
         "Pointer size, speed and button configuration"),
    ),
}


def matching_tasks(query):
    """Return category/task pairs matching the Control Panel's visible search."""
    needle = query.casefold().strip()
    return tuple((category, task) for category, tasks in LUNA_TASKS.items()
                 for task in tasks if not needle or needle in category.casefold()
                 or needle in task[0].casefold() or needle in task[3].casefold())


def available_program(candidates, which=shutil.which):
    """Select the first *available* real tool; never fake a working applet."""
    return next((command for command in candidates if which(command)), None)


def build(shell, Gtk, Gdk):
    """Create a lightweight 2001-style category view; return its GTK window."""
    window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    window.set_title("Control Panel")
    window.set_decorated(False)
    from gi.repository import GLib, Pango
    from .rice_windows import configure_settings_window, draggable_caption
    from .window_geometry import restore_and_track

    configure_settings_window(window, Gdk, role="ricebowl-xp-control-panel")
    window.set_default_size(746, 592)
    shell._luna_settings_positioned = restore_and_track(
        window, "ricebowl-xp-control-panel", Gdk, GLib)

    frame = shell._class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0),
                         "luna-control-window")
    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.add(frame)
    window.add(scroll)

    caption = shell._class(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8),
                           "luna-control-caption")
    title = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    title.pack_start(shell._icon("preferences-system", Gtk.IconSize.MENU),
                     False, False, 3)
    title.pack_start(Gtk.Label(label="Control Panel", xalign=0), True, True, 0)
    # Gtk.Box has no input GdkWindow: events on the caption's label/icon are
    # unreliable. Use the shared EventBox drag handle, excluding Close.
    caption.pack_start(draggable_caption(window, title, Gtk, Gdk), True, True, 0)
    close = shell._class(Gtk.Button(label="×"), "luna-control-close")
    close.get_accessible().set_name("Close Control Panel")
    close.connect("clicked", lambda _button: shell._hide_actions())
    caption.pack_end(close, False, False, 0)

    frame.pack_start(caption, False, False, 0)

    # XP's Explorer-era command/address chrome, with genuine GTK destinations.
    # These controls operate on this Control Panel only, never XFCE settings.
    toolbar = shell._class(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5),
                           "luna-control-toolbar")
    back_tool = shell._class(Gtk.Button(label="◂ Back"), "luna-control-tool")
    back_tool.set_sensitive(False)
    back_tool.get_accessible().set_name("Back to Control Panel categories")
    back_tool.connect("clicked", lambda _button: navigate(-1))
    toolbar.pack_start(back_tool, False, False, 0)
    forward_tool = shell._class(Gtk.Button(label="Forward ▸"), "luna-control-tool")
    forward_tool.set_sensitive(False)
    forward_tool.get_accessible().set_name("Forward to next Control Panel view")
    forward_tool.connect("clicked", lambda _button: navigate(1))
    toolbar.pack_start(forward_tool, False, False, 0)
    home_tool = shell._class(Gtk.Button(label="⌂ Home"), "luna-control-tool")
    home_tool.get_accessible().set_name("Control Panel home")
    home_tool.connect("clicked", lambda _button: show_home())
    toolbar.pack_start(home_tool, False, False, 0)
    toolbar.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 3)
    search_tool = shell._class(Gtk.Button(label="⌕ Search"), "luna-control-tool")
    search_tool.get_accessible().set_name("Search Control Panel settings")
    search_tool.connect("clicked", lambda _button: search.grab_focus())
    toolbar.pack_start(search_tool, False, False, 0)
    toolbar.pack_start(Gtk.Box(), True, True, 0)
    frame.pack_start(toolbar, False, False, 0)

    address_bar = shell._class(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6),
                               "luna-control-address")
    address_bar.pack_start(Gtk.Label(label="Address", xalign=0), False, False, 0)
    current_location = shell._class(Gtk.Label(label="Control Panel", xalign=0),
                                    "luna-control-location")
    current_location.set_ellipsize(Pango.EllipsizeMode.END)
    address_bar.pack_start(current_location, True, True, 0)
    frame.pack_start(address_bar, False, False, 0)

    body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
    frame.pack_start(body, True, True, 0)
    compact_layout = shell._desktop_rect().width < 700
    sidebar = shell._class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8),
                           "luna-control-sidebar")
    sidebar.set_size_request(165 if compact_layout else 232, -1)
    body.pack_start(sidebar, False, False, 0)
    main = shell._class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10),
                        "luna-control-main")
    body.pack_start(main, True, True, 0)

    heading = shell._class(Gtk.Label(label="Pick a category", xalign=0),
                           "luna-control-heading")
    main.pack_start(heading, False, False, 0)
    description = shell._class(Gtk.Label(
        label="Choose a task to configure your computer", xalign=0),
        "luna-control-intro")
    description.set_line_wrap(True)
    main.pack_start(description, False, False, 0)
    search = shell._class(Gtk.SearchEntry(), "luna-control-search")
    search.set_placeholder_text("Search Control Panel tasks")
    search.get_accessible().set_name("Search Control Panel tasks")
    main.pack_start(search, False, False, 2)

    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.NONE)
    stack.set_homogeneous(False)
    category_grid = Gtk.Grid(row_spacing=7, column_spacing=9)
    category_grid.set_column_homogeneous(True)
    classic_grid = Gtk.Grid(row_spacing=3, column_spacing=6)
    classic_grid.set_column_homogeneous(True)
    details = shell._class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5),
                           "luna-control-details")
    matches = shell._class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4),
                           "luna-control-results")
    for name, child in (("categories", category_grid), ("classic", classic_grid),
                        ("detail", details), ("search", matches)):
        stack.add_named(child, name)
    main.pack_start(stack, True, True, 2)
    home_view = ["categories"]
    history = [("home", "categories")]
    history_index = [0]
    replaying = [False]
    suppress_search = [False]

    def remember(kind, detail):
        if replaying[0]:
            return
        route = (kind, detail)
        previous = history[history_index[0]]
        if previous == route:
            return
        if kind == "search" and previous[0] == "search":
            history[history_index[0]] = route
        else:
            del history[history_index[0] + 1:]
            history.append(route)
            if len(history) > 32:
                history.pop(0)
            history_index[0] = len(history) - 1
        back_tool.set_sensitive(history_index[0] > 0)
        forward_tool.set_sensitive(history_index[0] < len(history) - 1)

    def clear_search():
        if not search.get_text():
            return
        suppress_search[0] = True
        try:
            search.set_text("")
        finally:
            suppress_search[0] = False

    def navigate(direction):
        next_index = history_index[0] + direction
        if not 0 <= next_index < len(history):
            return
        kind, detail = history[next_index]
        replaying[0] = True
        try:
            if kind == "home":
                show_home(detail)
            elif kind == "category":
                show_category(detail)
            elif kind == "search":
                suppress_search[0] = True
                try:
                    search.set_text(detail)
                finally:
                    suppress_search[0] = False
                on_search(search)
            else:
                return
            history_index[0] = next_index
        finally:
            replaying[0] = False
            back_tool.set_sensitive(history_index[0] > 0)
            forward_tool.set_sensitive(history_index[0] < len(history) - 1)

    def task_button(category, task, *, compact=False):
        name, icon, commands, explanation = task
        program = available_program(commands)
        button = shell._class(Gtk.Button(),
                              "luna-control-applet" if compact else "luna-control-task")
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
        image = shell._icon(task_art(category, icon), Gtk.IconSize.LARGE_TOOLBAR)
        line.pack_start(image, False, False, 0)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = shell._class(Gtk.Label(label=name, xalign=0), "luna-control-link")
        title.set_line_wrap(True)
        title.set_max_width_chars(23 if compact else 31)
        labels.pack_start(title, False, False, 0)
        summary = explanation if program else "Unavailable — install " + " or ".join(commands)
        if not compact or not program:
            subtitle = shell._class(Gtk.Label(
                label="Not installed" if compact else summary, xalign=0),
                "luna-control-explanation")
            subtitle.set_line_wrap(True)
            subtitle.set_max_width_chars(24 if compact else 44)
            labels.pack_start(subtitle, False, False, 0)
        line.pack_start(labels, True, True, 0)
        button.add(line)
        button.set_sensitive(program is not None)
        button.set_tooltip_text("Open " + name if program else summary)
        button.get_accessible().set_name("Open " + name if program else name + " (not installed)")
        if program:
            button.connect("clicked", lambda _button, cmd=program: shell._open_tool(cmd))
        return button

    def show_home(view=None):
        if view in ("categories", "classic"):
            home_view[0] = view
        clear_search()
        remember("home", home_view[0])
        stack.set_visible_child_name(home_view[0])
        heading.set_text("Classic View" if home_view[0] == "classic" else "Pick a category")
        description.set_text("Open an installed Control Panel tool" if home_view[0] == "classic"
                             else "Choose a task to configure your computer")
        toggle.set_label("Switch to Category View" if home_view[0] == "classic"
                         else "Switch to Classic View")
        back.hide()
        current_location.set_text("Control Panel" if home_view[0] == "categories"
                                  else "Control Panel / Classic View")

    def show_category(category):
        if category not in LUNA_TASKS:
            return
        clear_search()
        remember("category", category)
        for child in details.get_children():
            details.remove(child)
        title = next((row for row in LUNA_CATEGORIES if row[0] == category), None)
        if title:
            icon = shell._icon(title[1], Gtk.IconSize.DIALOG)
            header = shell._class(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=11),
                                  "luna-control-detail-header")
            header.pack_start(icon, False, False, 0)
            header.pack_start(shell._class(Gtk.Label(label=title[3], xalign=0),
                                           "luna-control-intro"), True, True, 0)
            details.pack_start(header, False, False, 6)
        for task in LUNA_TASKS[category]:
            details.pack_start(task_button(category, task), False, False, 0)
        details.show_all()
        stack.set_visible_child_name("detail")
        heading.set_text(category)
        description.set_text("Pick a task")
        back.show()
        current_location.set_text("Control Panel / " + category)

    for index, (name, icon, _commands, explanation) in enumerate(LUNA_CATEGORIES):
        button = shell._class(Gtk.Button(), "luna-control-category")
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
        line.pack_start(shell._icon(icon, Gtk.IconSize.DIALOG), False, False, 0)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        category_label = shell._class(Gtk.Label(label=name, xalign=0), "luna-control-link")
        category_label.set_line_wrap(True)
        category_label.set_max_width_chars(23)
        labels.pack_start(category_label, False, False, 0)
        summary = shell._class(Gtk.Label(label=explanation, xalign=0),
                               "luna-control-explanation")
        summary.set_line_wrap(True)
        summary.set_max_width_chars(24)
        labels.pack_start(summary, False, False, 0)
        line.pack_start(labels, True, True, 0)
        button.add(line)
        button.get_accessible().set_name("Show " + name + " tasks")
        button.connect("clicked", lambda _button, chosen=name: show_category(chosen))
        columns = 1 if compact_layout else 2
        category_grid.attach(button, index % columns, index // columns, 1, 1)

    # Classic View lists real individual applets, not duplicate category cards.
    distinct = {task[0]: (category, task) for category, group in LUNA_TASKS.items()
                for task in group}
    for index, (category, task) in enumerate(distinct.values()):
        columns = 1 if compact_layout else 2
        classic_grid.attach(task_button(category, task, compact=True), index % columns,
                            index // columns, 1, 1)

    def on_search(entry):
        if suppress_search[0]:
            return
        needle = entry.get_text().strip()
        if not needle:
            show_home()
            return
        remember("search", needle)
        for child in matches.get_children():
            matches.remove(child)
        found = matching_tasks(needle)
        if not found:
            matches.pack_start(shell._class(Gtk.Label(label="No matching settings", xalign=0),
                                            "luna-control-empty"), False, False, 10)
        else:
            last_category = None
            for category, task in found:
                if category != last_category:
                    matches.pack_start(shell._class(Gtk.Label(label=category, xalign=0),
                                                    "luna-control-result-heading"), False, False, 4)
                    last_category = category
                matches.pack_start(task_button(category, task), False, False, 0)
        matches.show_all()
        stack.set_visible_child_name("search")
        heading.set_text("Search results")
        description.set_text(str(len(found)) + " matching task" + ("" if len(found) == 1 else "s"))
        back.show()
        current_location.set_text("Control Panel / Search results")

    search.connect("search-changed", on_search)

    nav_group = shell._class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4),
                             "luna-control-side-group")
    sidebar.pack_start(nav_group, False, False, 0)
    nav_group.pack_start(shell._class(Gtk.Label(label="Control Panel", xalign=0),
                                       "luna-control-side-heading"), False, False, 0)
    back = shell._class(Gtk.Button(label="‹  Back to Control Panel"), "luna-control-nav")
    back.set_no_show_all(True)
    back.get_accessible().set_name("Back to Control Panel home")
    back.connect("clicked", lambda _button: navigate(-1) if history_index[0] > 0
                 else show_home())
    nav_group.pack_start(back, False, False, 0)
    toggle = shell._class(Gtk.Button(label="Switch to Classic View"), "luna-control-nav")
    toggle.get_accessible().set_name("Switch Control Panel view")

    def switch_view(_button):
        show_home("classic" if home_view[0] == "categories" else "categories")

    toggle.connect("clicked", switch_view)
    nav_group.pack_start(toggle, False, False, 0)
    shell.luna_control_stack = stack
    shell.luna_control_switch = toggle
    shell.luna_control_back = back
    shell.luna_control_search = search
    shell.luna_control_show_home = show_home
    shell.luna_control_show_category = show_category
    shell.luna_control_back_tool = back_tool
    shell.luna_control_forward_tool = forward_tool
    shell.luna_control_history = history

    hardware = shell._class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5),
                            "luna-control-side-group")
    sidebar.pack_start(hardware, False, False, 0)
    hardware.pack_start(shell._class(Gtk.Label(label="System status", xalign=0),
                                     "luna-control-side-heading"), False, False, 0)
    shell.control_network_label = shell._class(
        Gtk.Label(label="Network: reading…", xalign=0), "rice-control-detail")
    shell.control_network_label.set_line_wrap(True)
    hardware.pack_start(shell.control_network_label, False, False, 0)
    shell.control_battery_label = shell._class(
        Gtk.Label(label="Battery: reading…", xalign=0), "rice-control-detail")
    shell.control_battery_label.set_line_wrap(True)
    hardware.pack_start(shell.control_battery_label, False, False, 0)
    shell.control_battery_level = Gtk.LevelBar.new_for_interval(0, 100)
    shell.control_battery_level.set_no_show_all(True)
    hardware.pack_start(shell.control_battery_level, False, False, 0)
    shell.volume_status_label = shell._class(
        Gtk.Label(label="Volume: reading…", xalign=0), "rice-control-detail")
    shell.volume_status_label.set_line_wrap(True)
    hardware.pack_start(shell.volume_status_label, False, False, 0)
    shell.volume_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
    shell.volume_scale.set_draw_value(False)
    shell.volume_scale.set_sensitive(False)
    shell.volume_scale.get_accessible().set_name("System output volume")
    shell.volume_scale.connect("value-changed", shell._queue_volume_change)
    hardware.pack_start(shell.volume_scale, False, False, 0)
    shell.mute_button = shell._class(Gtk.ToggleButton(label="Mute output"), "rice-mute")
    shell.mute_button.set_sensitive(False)
    shell.mute_button.get_accessible().set_name("Mute or unmute output")
    shell.mute_button.connect("clicked", shell._toggle_output_mute)
    hardware.pack_start(shell.mute_button, False, False, 0)
    shell.status_summary = shell._class(
        Gtk.Label(label="Reading hardware status…", xalign=0), "luna-control-summary")
    shell.status_summary.set_line_wrap(True)
    sidebar.pack_end(shell.status_summary, False, False, 0)

    window.connect("delete-event", lambda *_args: shell._hide_actions() or True)
    def on_key(_widget, event):
        if event.state & Gdk.ModifierType.MOD1_MASK:
            if event.keyval == Gdk.KEY_Left:
                navigate(-1)
                return True
            if event.keyval == Gdk.KEY_Right:
                navigate(1)
                return True
        return shell._action_key(event)

    window.connect("key-press-event", on_key)
    show_home()
    return window
