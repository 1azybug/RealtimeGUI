"""Unified input layer for RealtimeGym GUI / computer-use mode.

This module is the single entry point shared by *both* the AI agent and a
human player. Everyone produces low-level **keyboard / mouse events**; this
layer translates them into the game's discrete action characters
(U / D / L / R / S / I) that the environments actually consume.

Design goals:
  * One translation function (`resolve_event`) used by the agent runner and
    the human play loop alike, so both go through identical logic.
  * Keyboard mapping follows the traditional game convention requested by the
    user: W/A/S/D = up/left/down/right, F = interact, Space = stop.
  * Mouse clicks land on an on-screen action-button panel whose geometry is
    defined here (`button_layout`) and reused by the renderer, so buttons and
    hit-testing never drift apart.
  * Default action on unparseable / illegal input follows the paper
    (arXiv:2511.04898): Freeway & Snake repeat the *previous* action; Overcooked
    stays idle (S).
"""

from __future__ import annotations

import re
from typing import Any, Optional

# Legal discrete action set per game (from the paper / env code).
GAME_ACTION_SET: dict[str, str] = {
    "freeway": "UDS",
    "snake": "UDLR",
    "overcooked": "UDLRIS",
}

# Initial "previous action" used for the default-action fallback on turn 1.
# Freeway: move up toward the goal. Snake: env starts heading Left.
# Overcooked: idle.
INITIAL_ACTION: dict[str, str] = {
    "freeway": "U",
    "snake": "L",
    "overcooked": "S",
}

# Whether a game has an explicit "stay" action that Space maps to.
_HAS_STAY: dict[str, bool] = {
    "freeway": True,
    "snake": False,  # Snake has no stay; Space is ignored.
    "overcooked": True,
}

# Canonical key name -> direction/action intent (before per-game filtering).
# Accept both WASD (requested convention) and arrow keys (human habit).
_KEY_TO_INTENT: dict[str, str] = {
    # WASD
    "W": "U",
    "A": "L",
    "S": "D",
    "D": "R",
    # Arrow keys (equivalent)
    "UP": "U",
    "LEFT": "L",
    "DOWN": "D",
    "RIGHT": "R",
    # Interact / stop
    "F": "I",
    "SPACE": "S",
    " ": "S",
}


def _normalize_key(value: str) -> str:
    v = value.strip()
    if v == " ":
        return "SPACE"
    return v.upper()


# --- Action button panel geometry --------------------------------------------

# Order of buttons shown in the control bar, per game, with display labels.
_BUTTON_SPECS: dict[str, list[tuple[str, str]]] = {
    # (action_char, label)
    "freeway": [("U", "W  Up"), ("S", "Space  Stay"), ("D", "S  Down")],
    "snake": [
        ("U", "W  Up"),
        ("L", "A  Left"),
        ("D", "S  Down"),
        ("R", "D  Right"),
    ],
    "overcooked": [
        ("U", "W  Up"),
        ("L", "A  Left"),
        ("D", "S  Down"),
        ("R", "D  Right"),
        ("I", "F  Interact"),
        ("S", "Space  Stay"),
    ],
}

PANEL_HEIGHT = 90  # pixels of control bar appended below the game image
_BUTTON_MARGIN = 8


def button_specs(game: str) -> list[tuple[str, str]]:
    return _BUTTON_SPECS[game]


def button_layout(game: str, screen_w: int, game_h: int) -> dict[str, tuple[int, int, int, int]]:
    """Return {action_char: (x, y, w, h)} rectangles for the control bar.

    Buttons are laid out in a single row spanning ``screen_w``, sitting in the
    panel strip directly below the game image (which has height ``game_h``).
    The same geometry is used by the renderer to draw buttons and by
    ``resolve_event`` to hit-test clicks.
    """
    specs = _BUTTON_SPECS[game]
    n = len(specs)
    total_margin = _BUTTON_MARGIN * (n + 1)
    bw = (screen_w - total_margin) // n
    bh = PANEL_HEIGHT - 2 * _BUTTON_MARGIN
    y = game_h + _BUTTON_MARGIN
    layout: dict[str, tuple[int, int, int, int]] = {}
    x = _BUTTON_MARGIN
    for action_char, _label in specs:
        layout[action_char] = (x, y, bw, bh)
        x += bw + _BUTTON_MARGIN
    return layout


# --- Agent output parsing -----------------------------------------------------

_KEY_RE = re.compile(r'Key\(\s*["\']?([^"\')]+)["\']?\s*\)', re.IGNORECASE)
_CLICK_RE = re.compile(r"Click\(\s*(\d+)\s*,\s*(\d+)\s*\)", re.IGNORECASE)


def parse_agent_output(text: str) -> Optional[dict[str, Any]]:
    """Extract the last Key(...) or Click(...) event from a model reply.

    Returns an event dict ``{"type": "key", "value": "W"}`` or
    ``{"type": "click", "x": int, "y": int}``, or ``None`` if neither found.
    Whichever appears *last* in the text wins (the model's final decision).
    """
    if not text:
        return None
    key_matches = list(_KEY_RE.finditer(text))
    click_matches = list(_CLICK_RE.finditer(text))

    last_key = key_matches[-1] if key_matches else None
    last_click = click_matches[-1] if click_matches else None

    if last_key and last_click:
        chosen_key = last_key.end() >= last_click.end()
    elif last_key:
        chosen_key = True
    elif last_click:
        chosen_key = False
    else:
        return None

    if chosen_key:
        return {"type": "key", "value": last_key.group(1).strip()}
    return {
        "type": "click",
        "x": int(last_click.group(1)),
        "y": int(last_click.group(2)),
    }


# --- Core translation: event -> discrete action -------------------------------


class InputController:
    """Translates keyboard/mouse events into discrete game actions.

    Holds ``last_action`` to implement the paper's default-action rule.
    Construct one per episode. Used identically by the agent runner and the
    human play loop.
    """

    def __init__(self, game: str, screen_w: int, game_h: int) -> None:
        if game not in GAME_ACTION_SET:
            raise ValueError(f"Unknown game: {game}")
        self.game = game
        self.action_set = GAME_ACTION_SET[game]
        self.screen_w = screen_w
        self.game_h = game_h
        self.layout = button_layout(game, screen_w, game_h)
        self.last_action = INITIAL_ACTION[game]

    def default_action(self) -> str:
        """Paper-defined fallback when no valid action is produced."""
        if self.game == "overcooked":
            return "S"
        # Freeway & Snake: repeat previous action/direction.
        return self.last_action

    def _key_to_action(self, value: str) -> Optional[str]:
        key = _normalize_key(value)
        intent = _KEY_TO_INTENT.get(key)
        if intent is None:
            return None
        # Space -> stay only if the game has a stay action.
        if intent == "S" and not _HAS_STAY[self.game]:
            return None
        # Interact only legal where present.
        if intent == "I" and "I" not in self.action_set:
            return None
        if intent in self.action_set:
            return intent
        return None

    def _click_to_action(self, x: int, y: int) -> Optional[str]:
        for action_char, (bx, by, bw, bh) in self.layout.items():
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return action_char
        return None

    def resolve_event(self, event: Optional[dict[str, Any]]) -> str:
        """Map a parsed event to a discrete action, applying defaults.

        Always returns a legal action character. Updates ``last_action``.
        """
        action: Optional[str] = None
        if event is not None:
            if event.get("type") == "key":
                action = self._key_to_action(event.get("value", ""))
            elif event.get("type") == "click":
                action = self._click_to_action(
                    int(event.get("x", -1)), int(event.get("y", -1))
                )
        if action is None:
            action = self.default_action()
        self.last_action = action
        return action

    def resolve_agent_text(self, text: str) -> tuple[str, Optional[dict[str, Any]]]:
        """Convenience: parse model text then resolve. Returns (action, event)."""
        event = parse_agent_output(text)
        action = self.resolve_event(event)
        return action, event
