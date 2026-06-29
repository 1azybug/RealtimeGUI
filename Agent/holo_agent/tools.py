"""Holo3.1 structured-output tool schema (the agent's action vocabulary).

Follows the official H Company agent-loop spec (see ``Agent/docs/holo_official/
agent-loop.md``): each step the model emits ONE JSON object
``{note, thought, tool_call}`` where ``tool_call`` is a flat object discriminated
by a ``Literal[tool_name]`` field, with the arguments as siblings (not nested).
Coordinates are integers in ``[0, 1000]`` normalized to the screenshot; the agent
loop scales them to pixels before handing them to the environment.

This module lives entirely on the Agent side — it IS the Holo action vocabulary.
The environment never imports it; the only thing that crosses the Agent/Env
boundary is ``computer_env.InputEvent(tool_name, params)``.

`click`, `write`, and `answer` are taken verbatim from the official docs; the
remaining desktop tools (double_click / right_click / press_key / hotkey /
scroll / drag / wait) are reasonable extensions following the same documented
pattern, since the docs state "real agents register a wider toolbox following
the same pattern".
"""

from __future__ import annotations

import json
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field


class ClickArgs(BaseModel):
    """Click at (x, y) coordinates."""

    tool_name: Literal["click"]
    element: str = Field(description="Detailed description of the target UI element to click on")
    x: int = Field(description="X coordinate as integer in [0, 1000]")
    y: int = Field(description="Y coordinate as integer in [0, 1000]")


class WriteArgs(BaseModel):
    """Type text into the currently focused element without clicking first."""

    tool_name: Literal["write"]
    content: str = Field(description="Content to write")
    press_enter: bool = Field(default=False, description="Whether to press Enter after typing")


class AnswerArgs(BaseModel):
    """Provide a final answer / declare the task finished. Terminates the loop.

    For state-based tasks, set ``content`` to a short summary of what was
    achieved. If the task is genuinely impossible, say so explicitly (e.g.
    "the task is infeasible …") and the harness will record a failure.
    """

    tool_name: Literal["answer"]
    content: str = Field(description="The final answer, or a summary of what was achieved")


class DoubleClickArgs(BaseModel):
    """Double-click at (x, y) coordinates."""

    tool_name: Literal["double_click"]
    element: str = Field(description="Detailed description of the target UI element")
    x: int = Field(description="X coordinate as integer in [0, 1000]")
    y: int = Field(description="Y coordinate as integer in [0, 1000]")


class RightClickArgs(BaseModel):
    """Right-click (open the context menu) at (x, y) coordinates."""

    tool_name: Literal["right_click"]
    element: str = Field(description="Detailed description of the target UI element")
    x: int = Field(description="X coordinate as integer in [0, 1000]")
    y: int = Field(description="Y coordinate as integer in [0, 1000]")


class PressKeyArgs(BaseModel):
    """Press a single keyboard key."""

    tool_name: Literal["press_key"]
    key: str = Field(
        description="A key name such as 'Enter', 'Tab', 'Escape', 'Backspace', "
        "'ArrowUp', 'PageDown', or a single character like 'a'."
    )


class HotkeyArgs(BaseModel):
    """Press a key combination together, e.g. ctrl+c or alt+Tab."""

    tool_name: Literal["hotkey"]
    keys: list[str] = Field(description="Keys pressed together, e.g. ['ctrl','c'] or ['ctrl','shift','s']")


class ScrollArgs(BaseModel):
    """Scroll the wheel at (x, y)."""

    tool_name: Literal["scroll"]
    x: int = Field(description="X coordinate as integer in [0, 1000]")
    y: int = Field(description="Y coordinate as integer in [0, 1000]")
    direction: Literal["up", "down", "left", "right"] = Field(description="Scroll direction")
    amount: int = Field(default=3, description="Number of scroll clicks (1-10)")


class DragArgs(BaseModel):
    """Drag from (x, y) to (to_x, to_y) with the left button held."""

    tool_name: Literal["drag"]
    x: int = Field(description="Start X in [0, 1000]")
    y: int = Field(description="Start Y in [0, 1000]")
    to_x: int = Field(description="End X in [0, 1000]")
    to_y: int = Field(description="End Y in [0, 1000]")


class WaitArgs(BaseModel):
    """Wait for the screen to settle / a slow operation to finish."""

    tool_name: Literal["wait"]
    seconds: float = Field(
        default=3.0,
        description="How long to wait, in seconds. Use a few seconds for a quick "
        "settle, or more (e.g. 10-30) while a slow page or operation finishes, so you "
        "don't waste steps issuing wait repeatedly.",
    )


#: The single, unified Holo computer-use toolbox. No game/desktop split — every
#: environment accepts the same vocabulary and tolerates actions it cannot
#: perform (e.g. a game maps unknown tools to its default action).
TOOLS = (
    ClickArgs,
    WriteArgs,
    AnswerArgs,
    DoubleClickArgs,
    RightClickArgs,
    PressKeyArgs,
    HotkeyArgs,
    ScrollArgs,
    DragArgs,
    WaitArgs,
)

#: Tools that terminate the agent loop.
TERMINAL_TOOLS = ("answer",)


def make_step_model(tools: tuple = TOOLS) -> type[BaseModel]:
    """Build a ``Step`` pydantic model whose ``tool_call`` is a union of ``tools``."""
    union = Union[tools] if len(tools) > 1 else tools[0]

    class _Step(BaseModel):
        note: Optional[str] = Field(
            default=None,
            description="Task-relevant information from the current screen to remember "
            "(it persists across steps). Null if nothing new is worth keeping.",
        )
        thought: str = Field(description="One-line reasoning about the next action")
        tool_call: union = Field(description="The single action to take this step")

    return _Step


#: Default Step model over the full toolbox.
Step = make_step_model(TOOLS)


def build_schema(step_model: type = Step) -> dict:
    """Return the JSON Schema for the structured-output decoder + prompt block."""
    return step_model.model_json_schema()


def schema_block(step_model: type = Step) -> str:
    """Return the ``<output_format>`` block to embed in the system prompt."""
    return "<output_format>\n```json\n" + json.dumps(build_schema(step_model)) + "\n```\n</output_format>"


def parse_step(content: str, step_model: type = Step):
    """Parse the model's JSON content into a validated Step."""
    return step_model.model_validate_json(content)
