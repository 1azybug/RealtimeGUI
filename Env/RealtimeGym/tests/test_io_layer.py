"""Unit tests for the unified input layer (no model / no display needed)."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from realtimegym.io_layer import (  # noqa: E402
    InputController,
    parse_agent_output,
)


def test_parse_key_and_click():
    assert parse_agent_output('I will go up. Key("W")') == {"type": "key", "value": "W"}
    assert parse_agent_output("Click(120, 560)") == {"type": "click", "x": 120, "y": 560}
    # Last event wins.
    ev = parse_agent_output('first Key("A") then finally Click(10, 20)')
    assert ev == {"type": "click", "x": 10, "y": 20}
    assert parse_agent_output("no action here") is None
    assert parse_agent_output("") is None


def test_freeway_keys():
    c = InputController("freeway", screen_w=540, game_h=600)
    assert c.resolve_event({"type": "key", "value": "W"}) == "U"
    assert c.resolve_event({"type": "key", "value": "S"}) == "D"
    assert c.resolve_event({"type": "key", "value": "Space"}) == "S"
    # Arrow-key equivalents.
    assert c.resolve_event({"type": "key", "value": "Up"}) == "U"
    # 'A'/'D' (left/right) are not legal in freeway -> default (= last action).
    c.last_action = "U"
    assert c.resolve_event({"type": "key", "value": "A"}) == "U"


def test_snake_space_invalid_and_default_repeats():
    c = InputController("snake", screen_w=390, game_h=390)
    assert c.resolve_event({"type": "key", "value": "D"}) == "R"
    # Space has no mapping in snake -> falls back to repeating last action (R).
    assert c.resolve_event({"type": "key", "value": "Space"}) == "R"
    # Unparseable -> repeat last action again.
    assert c.resolve_event(None) == "R"


def test_snake_initial_default_is_left():
    c = InputController("snake", screen_w=390, game_h=390)
    # First turn with no valid event -> initial direction L (matches env).
    assert c.resolve_event(None) == "L"


def test_overcooked_interact_and_idle_default():
    c = InputController("overcooked", screen_w=375, game_h=375)
    assert c.resolve_event({"type": "key", "value": "F"}) == "I"
    assert c.resolve_event({"type": "key", "value": "Space"}) == "S"
    # Overcooked default is always idle S, regardless of last action.
    c.last_action = "U"
    assert c.resolve_event(None) == "S"


def test_click_hits_button():
    c = InputController("freeway", screen_w=540, game_h=600)
    # Click inside the 'U' button rectangle -> action U.
    bx, by, bw, bh = c.layout["U"]
    assert c.resolve_event({"type": "click", "x": bx + bw // 2, "y": by + bh // 2}) == "U"
    # Click far outside any button -> default (= last action).
    c.last_action = "U"
    assert c.resolve_event({"type": "click", "x": 5, "y": 5}) == "U"


if __name__ == "__main__":
    test_parse_key_and_click()
    test_freeway_keys()
    test_snake_space_invalid_and_default_repeats()
    test_snake_initial_default_is_left()
    test_overcooked_interact_and_idle_default()
    test_click_hits_button()
    print("ALL io_layer tests passed")
