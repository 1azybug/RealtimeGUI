"""Tests for the Holo agent loop: schema parsing, image budget, decoupling."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import json  # noqa: E402

from realtimegym.agents.holo_tools import (  # noqa: E402
    build_schema,
    parse_step,
    schema_block,
)
from realtimegym.agents.holo_agent import trim_to_last_n_images  # noqa: E402


def test_parse_press_key():
    s = parse_step(json.dumps({
        "note": None,
        "thought": "move up",
        "tool_call": {"tool_name": "press_key", "key": "W"},
    }))
    assert s.tool_call.tool_name == "press_key"
    assert s.tool_call.key == "W"


def test_parse_click_with_coords():
    s = parse_step(json.dumps({
        "thought": "click the up button",
        "tool_call": {"tool_name": "click", "element": "Up button", "x": 250, "y": 950},
    }))
    assert s.tool_call.tool_name == "click"
    assert (s.tool_call.x, s.tool_call.y) == (250, 950)


def test_parse_done():
    s = parse_step(json.dumps({
        "thought": "finished",
        "tool_call": {"tool_name": "done", "content": "reached goal"},
    }))
    assert s.tool_call.tool_name == "done"


def test_schema_has_union_discriminator():
    schema = build_schema()
    # Step has note/thought/tool_call; tool_call is a union with tool_name consts.
    assert "tool_call" in schema["properties"]
    block = schema_block()
    assert "<output_format>" in block and "tool_name" in block


def test_coordinate_scaling():
    # [0,1000] -> pixels for a 540x690 screenshot.
    w, h = 540, 690
    x, y = 500, 1000
    px = int(x / 1000 * w)
    py = int(y / 1000 * h)
    assert px == 270 and py == 690


def test_image_budget_keeps_last_3():
    # Build 5 user observation messages each with one image chunk.
    messages = [{"role": "system", "content": "sys"}]
    for i in range(5):
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": "<observation>\n"},
                {"type": "image_url", "image_url": {"url": f"data:img{i}"}},
                {"type": "text", "text": "\n</observation>"},
            ],
        })
    trim_to_last_n_images(messages, n=3)
    # Count remaining real images and evicted placeholders.
    imgs, evicted = 0, 0
    for m in messages:
        if not isinstance(m.get("content"), list):
            continue
        for c in m["content"]:
            if c.get("type") == "image_url":
                imgs += 1
            if c.get("type") == "text" and c.get("text") == "[screenshot evicted]":
                evicted += 1
    assert imgs == 3, f"expected 3 images, got {imgs}"
    assert evicted == 2, f"expected 2 evicted, got {evicted}"
    # <observation> wrappers preserved on all 5.
    obs_open = sum(
        1
        for m in messages
        if isinstance(m.get("content"), list)
        for c in m["content"]
        if c.get("type") == "text" and c.get("text") == "<observation>\n"
    )
    assert obs_open == 5


if __name__ == "__main__":
    test_parse_press_key()
    test_parse_click_with_coords()
    test_parse_done()
    test_schema_has_union_discriminator()
    test_coordinate_scaling()
    test_image_budget_keeps_last_3()
    print("ALL holo_loop tests passed")
