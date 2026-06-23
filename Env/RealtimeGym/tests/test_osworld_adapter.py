"""Unit tests for the OSWorld adapter's action translation (no docker needed)."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import json  # noqa: E402

from realtimegym.agents.holo_tools import DESKTOP_TOOLS, make_step_model, parse_step  # noqa: E402
from realtimegym.computer_env import InputEvent  # noqa: E402
from realtimegym.osworld_computer_env import _pyautogui_for  # noqa: E402

M = make_step_model(DESKTOP_TOOLS)


def test_click_command():
    e = InputEvent(tool_name="click", params={"x": 960, "y": 540, "element": "btn"})
    assert _pyautogui_for(e) == "import pyautogui; pyautogui.click(960, 540)"


def test_type_with_enter():
    e = InputEvent(tool_name="type", params={"text": "hello", "press_enter": True})
    cmd = _pyautogui_for(e)
    assert "typewrite('hello'" in cmd and "press('enter')" in cmd


def test_hotkey():
    e = InputEvent(tool_name="hotkey", params={"keys": ["ctrl", "c"]})
    assert _pyautogui_for(e) == "import pyautogui; pyautogui.hotkey('ctrl', 'c')"


def test_scroll_down_negative():
    e = InputEvent(tool_name="scroll", params={"x": 100, "y": 200, "direction": "down", "amount": 3})
    cmd = _pyautogui_for(e)
    assert "moveTo(100, 200)" in cmd and "scroll(-3)" in cmd


def test_drag():
    e = InputEvent(tool_name="drag", params={"x": 10, "y": 20, "to_x": 30, "to_y": 40})
    cmd = _pyautogui_for(e)
    assert "moveTo(10, 20)" in cmd and "dragTo(30, 40" in cmd


def test_wait_maps_to_WAIT():
    assert _pyautogui_for(InputEvent(tool_name="wait", params={"seconds": 2})) == "WAIT"


def test_coordinate_scaling_via_agent_convention():
    # The agent scales [0,1000] -> pixels before building InputEvent.
    # Here we simulate: model said x=500,y=500 on a 1920x1080 screen.
    w, h = 1920, 1080
    x, y = int(500 / 1000 * w), int(500 / 1000 * h)
    e = InputEvent(tool_name="click", params={"x": x, "y": y, "element": "center"})
    assert _pyautogui_for(e) == f"import pyautogui; pyautogui.click({x}, {y})"
    assert (x, y) == (960, 540)


def test_desktop_schema_parses_all_tools():
    # Each desktop tool variant parses under the desktop Step model.
    for payload in [
        {"tool_name": "click", "element": "x", "x": 1, "y": 2},
        {"tool_name": "double_click", "element": "x", "x": 1, "y": 2},
        {"tool_name": "right_click", "element": "x", "x": 1, "y": 2},
        {"tool_name": "type", "text": "hi"},
        {"tool_name": "press_key", "key": "Enter"},
        {"tool_name": "hotkey", "keys": ["ctrl", "s"]},
        {"tool_name": "scroll", "x": 1, "y": 2, "direction": "down"},
        {"tool_name": "drag", "x": 1, "y": 2, "to_x": 3, "to_y": 4},
        {"tool_name": "wait"},
        {"tool_name": "done", "content": "ok"},
        {"tool_name": "fail", "content": "no"},
    ]:
        s = parse_step(json.dumps({"thought": "t", "tool_call": payload}), M)
        assert s.tool_call.tool_name == payload["tool_name"]


if __name__ == "__main__":
    for fn in list(globals().values()):
        if callable(fn) and getattr(fn, "__name__", "").startswith("test_"):
            fn()
    print("ALL osworld_adapter tests passed")
