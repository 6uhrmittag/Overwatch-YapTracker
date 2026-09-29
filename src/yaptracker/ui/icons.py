"""Inline SVG icons, copied from docs/ui/mockup. No emoji anywhere in the UI."""

LOGO = (
    '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#12151c" '
    'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M4 5h16v11H9l-5 4z"/><path d="M9 9l3 3 3-3"/><path d="M12 12v2"/></svg>'
)

_OPEN = (
    '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
)

LIVE = (
    _OPEN.format(w="2.2") + '<circle cx="12" cy="12" r="2.5"/>'
    '<path d="M7.8 7.8a6 6 0 0 0 0 8.4M16.2 7.8a6 6 0 0 1 0 8.4'
    'M5 5a10 10 0 0 0 0 14M19 5a10 10 0 0 1 0 14"/></svg>'
)

YAPPERS = (
    _OPEN.format(w="2") + '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/>'
    '<path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14.5a6.5 6.5 0 0 1 3.5 5.5"/></svg>'
)

SESSIONS = _OPEN.format(w="2") + '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>'

SEARCH = _OPEN.format(w="2") + '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/></svg>'

SETTINGS = (
    _OPEN.format(w="2") + '<circle cx="12" cy="12" r="3"/>'
    '<path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 '
    "1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1"
    "a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1"
    "a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 "
    "1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3"
    "l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4"
    'h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>'
)
