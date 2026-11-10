"""Compile opt-in, recipe-derived labwc server-side window decorations.

Only a bounded, validated recipe palette is used. The returned text is written
to an owner-private compositor config directory, never to the global theme.
"""

from __future__ import annotations

from .recipes import PanelRecipe


def labwc_chrome(recipe: PanelRecipe) -> str | None:
    """Use matching compositor chrome for explicit two-column menu rices.

    Existing tabs/sidebar recipes retain labwc's usual theme. The palette has
    already been validated as six-digit hexadecimal colors by recipe parsing.
    Client-side decorated GTK/Qt windows remain outside labwc's control.
    """
    palette = recipe.menu_palette
    if recipe.menu_presentation != "columns" or palette is None:
        return None
    active_bg, foreground, active_border = recipe.colors
    return ("# RiceBowl private labwc chrome: recipe palette; no system theme writes.\n"
            "border.width: 2\n"
            "window.titlebar.padding.width: 3\n"
            "window.titlebar.padding.height: 2\n"
            "window.active.title.bg: Gradient Vertical\n"
            f"window.active.title.bg.color: {palette.header}\n"
            f"window.active.title.bg.colorTo: {active_bg}\n"
            "window.inactive.title.bg: Gradient Vertical\n"
            f"window.inactive.title.bg.color: {palette.selection}\n"
            f"window.inactive.title.bg.colorTo: {palette.background}\n"
            f"window.active.border.color: {active_border}\n"
            f"window.inactive.border.color: {palette.selection}\n"
            f"window.active.label.text.color: {palette.header_foreground}\n"
            f"window.inactive.label.text.color: {palette.foreground}\n"
            "window.label.text.justify: Left\n"
            "window.button.width: 26\n"
            "window.button.height: 26\n"
            "window.button.spacing: 2\n"
            f"window.active.button.unpressed.image.color: {foreground}\n"
            f"window.inactive.button.unpressed.image.color: {palette.foreground}\n")
