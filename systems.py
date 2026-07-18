#!/usr/bin/env python3
"""Game-system adapter boundary for foundryvtt-char2pdf.

This module is the *framework* side of the boundary. It knows how to detect
which Foundry game system an actor export came from and how to look up the
adapter that understands that system's schema — but it contains no knowledge of
any specific system (no D&D, no Pathfinder, ...). System-specific code lives in
its own adapter (today only ``dnd5e``, implemented in
``generate_character_sheet.py``) and registers itself here.

A ``SystemAdapter`` is responsible only for turning a system's actor schema into
a render-ready context and rendering that context into a themed sheet. Everything
else — the theme registry and palettes, the light/dark/mono color modes, the A4
and US Letter paper profiles, PDF export, browser detection, the local web UI,
and the browser ``localStorage`` trackers — is shared framework that every
adapter inherits for free.

Adding a new system means writing an object that satisfies :class:`SystemAdapter`
and calling :func:`register` with it. See the "Adding a new game system" section
of the README.

Stdlib-only, like the rest of the runtime.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SystemAdapter(Protocol):
    """The contract every game-system adapter must satisfy.

    Attributes
    ----------
    system_id:
        The Foundry ``systemId`` this adapter handles (e.g. ``"dnd5e"``). Used
        both for auto-detection (matched against an export's ``_stats.systemId``)
        and for the ``--system`` force flag, so it must equal the real Foundry id.
    display_name:
        Human-readable system name for messages and docs.
    """

    system_id: str
    display_name: str

    def matches(self, actor: dict[str, Any]) -> bool:
        """Return True if this adapter recognizes ``actor``'s schema shape.

        Called only when an export carries no usable ``_stats.systemId`` hint,
        so it should sniff the actor's structure rather than trust a label.
        """
        ...

    def build_context(self, actor: dict[str, Any]) -> dict[str, Any]:
        """Parse a raw actor export into the render-ready context dict."""
        ...

    def default_theme(self, actor: dict[str, Any]) -> str | None:
        """The theme to use when the caller did not request one (or None)."""
        ...

    def render(
        self,
        context: dict[str, Any],
        sheet_id: str,
        *,
        style: str,
        initial_theme: str | None,
        theme_palette: dict[str, str] | None,
        palette_decoration: str | None,
        include_footer: bool,
        paper: str,
    ) -> str:
        """Render one themed sheet (full HTML document) for ``context``.

        The palette, color mode, footer toggle, and paper profile are supplied
        by the shared framework; the adapter decides how to lay them onto its own
        system-specific sheet.
        """
        ...


class UnsupportedSystemError(Exception):
    """Raised when no registered adapter can handle an actor export.

    Carries the offending/ detected ``system_id`` (or None when nothing could be
    detected) plus the list of ``known_ids`` so callers — the CLI and the web UI —
    can surface a clear, actionable message instead of a stack trace.
    """

    def __init__(
        self,
        system_id: str | None,
        known_ids: list[str],
        *,
        forced: bool = False,
    ) -> None:
        self.system_id = system_id
        self.known_ids = list(known_ids)
        supported = ", ".join(self.known_ids) if self.known_ids else "(none registered)"
        if forced:
            message = (
                f"Unknown game system {system_id!r}. "
                f"char2pdf supports: {supported}."
            )
        elif system_id:
            message = (
                f"This looks like a Foundry {system_id!r} actor, which char2pdf "
                f"does not support yet. Supported systems: {supported}. "
                f"If it is actually a supported export, force it with --system."
            )
        else:
            message = (
                "Could not recognize this actor's game system. "
                f"char2pdf supports: {supported}. "
                "Force one with --system if you are sure it is supported."
            )
        super().__init__(message)


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
_REGISTRY: dict[str, SystemAdapter] = {}


def register(adapter: SystemAdapter) -> SystemAdapter:
    """Register ``adapter`` under its ``system_id``. Returns it for convenience."""
    if not getattr(adapter, "system_id", None):
        raise ValueError("A system adapter must define a non-empty system_id.")
    _REGISTRY[adapter.system_id] = adapter
    return adapter


def get(system_id: str) -> SystemAdapter | None:
    """Look up a registered adapter by system id, or None."""
    return _REGISTRY.get(system_id)


def registered() -> list[SystemAdapter]:
    """All registered adapters, in registration order."""
    return list(_REGISTRY.values())


def known_ids() -> list[str]:
    """Sorted list of registered system ids (for help text and errors)."""
    return sorted(_REGISTRY)


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #
def foundry_system_hint(actor: dict[str, Any]) -> str | None:
    """Read the game-system id a Foundry export declares about itself, if any.

    Foundry's "Export Data" writes a ``_stats.systemId`` field; some exports also
    namespace their ``flags`` by system id. Both are generic to Foundry (not to
    any one system), so reading them belongs to the framework. Returns None when
    the export carries no usable hint — detection then falls back to schema
    sniffing via each adapter's ``matches``.
    """
    stats = actor.get("_stats")
    if isinstance(stats, dict):
        system_id = stats.get("systemId")
        if isinstance(system_id, str) and system_id.strip():
            return system_id.strip()
    flags = actor.get("flags")
    if isinstance(flags, dict):
        for key in flags:
            if isinstance(key, str) and key in _REGISTRY:
                return key
    return None


def detect_adapter(
    actor: dict[str, Any],
    forced: str | None = None,
) -> SystemAdapter:
    """Return the adapter that should handle ``actor``.

    Resolution order:
      1. If ``forced`` is given, use that system id (error if unregistered).
      2. Else, if the export declares a system id, use it (error if that named
         system is unregistered — an unsupported system we can name precisely).
      3. Else, ask each registered adapter whether it recognizes the schema.
      4. Else, give up with an :class:`UnsupportedSystemError`.

    Raises :class:`UnsupportedSystemError` when no adapter can handle the actor.
    """
    if forced is not None:
        adapter = get(forced)
        if adapter is None:
            raise UnsupportedSystemError(forced, known_ids(), forced=True)
        return adapter

    hint = foundry_system_hint(actor)
    if hint is not None:
        adapter = get(hint)
        if adapter is not None:
            return adapter
        # The export names a system we don't support — a definitive answer.
        raise UnsupportedSystemError(hint, known_ids())

    for adapter in registered():
        if adapter.matches(actor):
            return adapter

    raise UnsupportedSystemError(None, known_ids())
