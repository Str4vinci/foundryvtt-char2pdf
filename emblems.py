"""Class emblems: one small line-art SVG symbol per D&D class.

Each emblem is the inner markup of a 24x24 SVG drawn with ``currentColor``
strokes, so it picks up whatever color the surrounding CSS gives it (the theme
accent on screen, black in mono). Characters without a known class get the
d20 fallback.
"""

from __future__ import annotations

EMBLEMS: dict[str, str] = {
    # Gear
    "artificer": (
        '<path d="M18.02 10.53 L20.53 10.89 L20.53 13.11 L18.02 13.47 L17.30 15.22 L18.82 17.24 '
        'L17.24 18.82 L15.22 17.30 L13.47 18.02 L13.11 20.53 L10.89 20.53 L10.53 18.02 L8.78 17.30 '
        'L6.76 18.82 L5.18 17.24 L6.70 15.22 L5.98 13.47 L3.47 13.11 L3.47 10.89 L5.98 10.53 '
        'L6.70 8.78 L5.18 6.76 L6.76 5.18 L8.78 6.70 L10.53 5.98 L10.89 3.47 L13.11 3.47 '
        'L13.47 5.98 L15.22 6.70 L17.24 5.18 L18.82 6.76 L17.30 8.78 Z"/>'
        '<circle cx="12" cy="12" r="2.6"/>'
    ),
    # Double-bitted axe
    "barbarian": (
        '<path d="M12 2.5 V21.5"/>'
        '<path d="M12 5 C9 5 6 3.8 4.2 2.8 C3 6 3 10 4.2 13.2 C6 12.2 9 11 12 11"/>'
        '<path d="M12 5 C15 5 18 3.8 19.8 2.8 C21 6 21 10 19.8 13.2 C18 12.2 15 11 12 11"/>'
    ),
    # Lyre
    "bard": (
        '<path d="M7 21 H17"/>'
        '<path d="M8 21 C5 17 4.5 11 7 7 C8 5.4 7.5 4 6 3.5"/>'
        '<path d="M16 21 C19 17 19.5 11 17 7 C16 5.4 16.5 4 18 3.5"/>'
        '<path d="M6.6 8 H17.4"/>'
        '<path d="M10 8 V21 M12 8 V21 M14 8 V21"/>'
    ),
    # Radiant sun
    "cleric": (
        '<circle cx="12" cy="12" r="4"/>'
        '<path d="M12 2.5 V5.5 M12 18.5 V21.5 M2.5 12 H5.5 M18.5 12 H21.5 '
        'M5.3 5.3 L7.4 7.4 M16.6 16.6 L18.7 18.7 M5.3 18.7 L7.4 16.6 M16.6 7.4 L18.7 5.3"/>'
    ),
    # Leaf
    "druid": (
        '<path d="M4.5 19.5 C4 11 9.5 4.5 20 4 C19.5 14.5 13 20 4.5 19.5 Z"/>'
        '<path d="M4.5 19.5 L15.5 8.5 M8.5 15.5 V12 M8.5 15.5 H12 M12 12 V8.8 M12 12 H15.2"/>'
    ),
    # Crossed swords
    "fighter": (
        '<path d="M4 4 L15.5 15.5 M20 4 L8.5 15.5"/>'
        '<path d="M13 18 L18 13 M11 18 L6 13"/>'
        '<path d="M16.5 16.5 L19 19 M7.5 16.5 L5 19"/>'
        '<circle cx="20" cy="20" r="1.2"/><circle cx="4" cy="20" r="1.2"/>'
    ),
    # Ensō brush circle
    "monk": (
        '<path d="M15.5 4.2 A8.5 8.5 0 1 1 6.2 6.2" stroke-width="2.2"/>'
        '<circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none"/>'
    ),
    # Shield with cross
    "paladin": (
        '<path d="M12 2.8 L19.5 5.6 V11 C19.5 15.8 16.3 19.4 12 21.2 C7.7 19.4 4.5 15.8 4.5 11 V5.6 Z"/>'
        '<path d="M12 7 V17 M8.5 10.5 H15.5"/>'
    ),
    # Bow and arrow
    "ranger": (
        '<path d="M13 2.5 C7.5 4.5 5 8 5 12 C5 16 7.5 19.5 13 21.5"/>'
        '<path d="M13 2.5 L19 12 L13 21.5" stroke-width="1"/>'
        '<path d="M19 12 H2.5 M5.5 9 L2.5 12 L5.5 15 M19 12 L21.5 9.5 M19 12 L21.5 14.5"/>'
    ),
    # Dagger
    "rogue": (
        '<path d="M12 2.5 L14.2 6 V14.5 H9.8 V6 Z"/>'
        '<path d="M7 14.5 H17"/>'
        '<path d="M12 14.5 V19.2"/>'
        '<circle cx="12" cy="20.5" r="1.3"/>'
    ),
    # Flame
    "sorcerer": (
        '<path d="M12 2.5 C13 6.5 18.5 9 18.5 14.5 A6.5 6.5 0 0 1 5.5 14.5 C5.5 11.5 7.3 9.6 8.5 8 '
        'C9 10 10 11.2 11.2 11.5 C10.6 8.5 10.8 5.2 12 2.5 Z"/>'
        '<path d="M12 21 A3 3 0 0 1 9 18 C9 16 10.5 15 12 13.5 C13.5 15 15 16 15 18 A3 3 0 0 1 12 21 Z"/>'
    ),
    # Slit-pupil eye
    "warlock": (
        '<path d="M2.5 12 C6 6.2 18 6.2 21.5 12 C18 17.8 6 17.8 2.5 12 Z"/>'
        '<path d="M12 8.2 C13.4 9.6 13.4 14.4 12 15.8 C10.6 14.4 10.6 9.6 12 8.2 Z" fill="currentColor"/>'
    ),
    # Pointed hat with a star
    "wizard": (
        '<path d="M3 19.5 C7 21 17 21 21 19.5 C17 18 7 18 3 19.5 Z"/>'
        '<path d="M6.5 18.6 L11.2 4.2 C11.5 3.3 12.6 3.4 12.9 4.2 L17.5 18.6"/>'
        '<path d="M12 10 L12.7 11.6 L14.4 11.8 L13.1 12.9 L13.5 14.6 L12 13.7 L10.5 14.6 '
        'L10.9 12.9 L9.6 11.8 L11.3 11.6 Z" fill="currentColor" stroke-width="0.8"/>'
    ),
}

# d20 outline, used when the actor has no class or a homebrew one.
FALLBACK_EMBLEM = (
    '<path d="M12 2.5 L20.2 7.2 V16.8 L12 21.5 L3.8 16.8 V7.2 Z"/>'
    '<path d="M12 7.5 L16.5 15 H7.5 Z"/>'
    '<path d="M12 2.5 V7.5 M20.2 7.2 L16.5 15 M3.8 7.2 L7.5 15 M7.5 15 L3.8 16.8 '
    'M16.5 15 L20.2 16.8 M7.5 15 L12 21.5 L16.5 15"/>'
)


def emblem_svg(class_slug: str | None, css_class: str = "") -> str:
    """Inline SVG markup for the class emblem (d20 fallback for unknown classes)."""
    inner = EMBLEMS.get(class_slug or "", FALLBACK_EMBLEM)
    class_attr = f' class="{css_class}"' if css_class else ""
    return (
        f'<svg{class_attr} viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        f"{inner}</svg>"
    )
