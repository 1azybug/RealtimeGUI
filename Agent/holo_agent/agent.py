"""Generic Holo3.1 computer-use agent loop (task-agnostic, environment-agnostic).

Implements the official H Company agent loop (``Agent/docs/holo_official/
agent-loop.md``) against the generic ``computer_env.ComputerEnv`` interface. This
module contains NO environment-specific knowledge — it never names or branches
on any particular environment. It drives any ``ComputerEnv`` by reading
screenshots and emitting actions from its fixed Holo toolbox.

Official conventions implemented here:
  * Structured output: one ``{note, thought, tool_call}`` JSON per step,
    constrained via ``extra_body.structured_outputs.json`` AND the same schema
    embedded in the system prompt's ``<output_format>`` block.
  * Reasoning on (``enable_thinking=True``), read from ``reasoning_content``,
    never fed back into the conversation. Cross-turn memory rides in ``note``.
  * Coordinates in [0,1000], scaled to pixels using the screenshot size.
  * Image budget: keep only the last 3 screenshots; older ones become a text
    placeholder while keeping the ``<observation>`` wrapper.
  * Chat layout: assistant gets the parsed JSON; tool results come back as a
    ``user`` message wrapped in ``<tool_output tool="...">``.
  * Termination: the ``answer`` tool ends the loop; its content is the final
    answer (infeasibility, if any, is conveyed in that text by convention).
"""

from __future__ import annotations

import base64
import logging
import time
from io import BytesIO
from typing import Any, Optional

from openai import OpenAI
from PIL import Image

from computer_env import ComputerEnv, InputEvent
from holo_agent.tools import TERMINAL_TOOLS, TOOLS, build_schema, make_step_model, parse_step, schema_block

logger = logging.getLogger("holo_agent")

# --- Baseline prompt (v1): the original minimal prompt, kept for A/B comparison. ---
_SYSTEM_PROMPT_BASELINE = """You are an autonomous computer-use agent. You operate a computer the way a human does: you look at a screenshot of the screen and act by clicking with the mouse, typing on the keyboard, and pressing keys.

Each step you receive the current screenshot inside an <observation> block. Decide the single best next action to make progress on the user's task, then respond with exactly ONE JSON object matching the schema below.

Guidelines:
- Look carefully at the screenshot. On-screen labels, controls, and text tell you what actions are available and what they do — infer the controls from what you see.
- Coordinates are integers in [0, 1000], normalized to the screenshot (origin top-left). Aim at the center of the target element.
- Put any information you must remember for later in the `note` field; your private reasoning is not carried across steps.
- Take exactly one action per step, chosen from the tools available in the schema below.
- When the task is fully complete (or if it is genuinely impossible), call `answer` with your final answer or a short summary.

{schema_block}"""


# --- v2 prompt: adds behavioral rules targeting observed failure modes (under-saving,
# premature "done"/no self-check, imprecision, flailing, under-declaring infeasible).
# Stays environment-agnostic — no OSWorld/game knowledge. This is the default. ---
_SYSTEM_PROMPT = """You are an autonomous computer-use agent. You operate a computer the way a human does: you look at a screenshot of the screen and act by moving and clicking the mouse, typing on the keyboard, and pressing keys.

Each step you receive the current screenshot inside an <observation> block. Decide the single best next action to make progress on the user's task, then respond with exactly ONE JSON object matching the schema below.

How to act:
- Look carefully at the screenshot. On-screen labels, menus, controls and text tell you what is available and what each control does — infer the interface from what you actually see, not from assumptions.
- Coordinates are integers in [0, 1000], normalized to the screenshot (origin top-left). Aim at the center of the target element.
- Take exactly one action per step, chosen from the tools in the schema below.
- Put anything you must remember for later (values, IDs, file paths, what you have already done) in the `note` field; your private reasoning is NOT carried forward.

Completing the task correctly:
- Follow the request precisely. Match every explicit detail — exact names, paths, locations, values and formatting — and do not change anything the task did not ask you to change.
- After each action, check the new screenshot to confirm it had the intended effect. If it did not work or a value was not entered, fix it before moving on; never assume success.
- Persist your work. If you edited a document, file or settings, save it (e.g. Ctrl+S, or confirm the dialog) so the change is written to disk — an unsaved change does not count as done.
- If an approach is not working after a couple of attempts, stop repeating it and try a different path (a menu, a keyboard shortcut, a different control).

Finishing:
- When the task is fully complete and you have verified the result on screen, call `answer` with a short summary.
- If the task is genuinely impossible (the required option does not exist, the request is contradictory, or it cannot be done in this environment), call `answer` and state clearly that it is infeasible instead of pretending it is done — but only after you have actually tried.

{schema_block}"""

# Registry so runners can select a variant by name (e.g. for A/B experiments).
SYSTEM_PROMPTS = {"v1": _SYSTEM_PROMPT_BASELINE, "v2": _SYSTEM_PROMPT}


def _image_to_data_url(image: Image.Image) -> str:
    buf = BytesIO()
    image.convert("RGB").save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def trim_to_last_n_images(messages: list[dict[str, Any]], n: int = 3) -> None:
    """Keep only the last ``n`` screenshots; evict older image chunks to text."""
    seen = 0
    for msg in reversed(messages):
        if msg.get("role") != "user" or not isinstance(msg.get("content"), list):
            continue
        for chunk in msg["content"]:
            if chunk.get("type") != "image_url":
                continue
            seen += 1
            if seen > n:
                chunk["type"] = "text"
                chunk["text"] = "[screenshot evicted]"
                chunk.pop("image_url", None)


class HoloComputerAgent:
    """Drives any ComputerEnv via the official Holo structured-output loop."""

    def __init__(
        self,
        client: OpenAI,
        model: str,
        env: ComputerEnv,
        max_steps: int = 100,
        temperature: float = 0.8,
        reasoning_effort: str = "medium",
        image_budget: int = 3,
        max_tokens: int = 3072,
        top_p: float = 0.9,
        on_step: Optional[Any] = None,
        system_prompt_template: Optional[str] = None,
    ) -> None:
        self.client = client
        self.model = model
        self.env = env
        self.max_steps = max_steps
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort
        self.image_budget = image_budget
        self.max_tokens = max_tokens
        self.top_p = top_p
        # System prompt template (must contain a ``{schema_block}`` placeholder).
        # Defaults to the current best prompt; override for A/B experiments.
        self._system_prompt_template = system_prompt_template or _SYSTEM_PROMPT
        # Optional callback(step_index, screenshot, step_obj, info_dict, reasoning).
        self.on_step = on_step
        # The agent owns its action vocabulary — a single fixed Holo toolbox.
        self.step_model = make_step_model(TOOLS)
        self.schema = build_schema(self.step_model)

    def _system_message(self) -> dict[str, Any]:
        content = self._system_prompt_template.format(schema_block=schema_block(self.step_model))
        content += f"\n\n<task>\n{self.env.task}\n</task>"
        return {"role": "system", "content": content}

    def system_prompt(self) -> str:
        """The exact system prompt the model is given (instructions + output schema + task).

        Public accessor for recording / inspection (see ``holo_agent.recorder``)."""
        return self._system_message()["content"]

    def _observation_message(self, image: Image.Image) -> dict[str, Any]:
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": "<observation>\n"},
                {"type": "image_url", "image_url": {"url": _image_to_data_url(image)}},
                {"type": "text", "text": "\n</observation>"},
            ],
        }

    def _call_model(self, messages: list[dict[str, Any]]) -> tuple[str, str]:
        """Return (content, reasoning_content). Retries on transient errors."""
        last_err = None
        for attempt in range(4):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    top_p=self.top_p,
                    max_tokens=self.max_tokens,
                    reasoning_effort=self.reasoning_effort,
                    extra_body={
                        "structured_outputs": {"json": self.schema},
                        "chat_template_kwargs": {"enable_thinking": True},
                    },
                )
                msg = resp.choices[0].message
                # vLLM with --reasoning-parser qwen3 returns thinking in msg.reasoning
                # (stored as model_extra); fall back to reasoning_content for other backends.
                reasoning = (
                    getattr(msg, "reasoning", None)
                    or (msg.model_extra or {}).get("reasoning", "")
                    or getattr(msg, "reasoning_content", None)
                    or ""
                )
                return (msg.content or ""), reasoning
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(2.0 * (attempt + 1))
        raise RuntimeError(f"model call failed after retries: {last_err}")

    # Coordinate fields that must be scaled from [0,1000] to pixels.
    _COORD_FIELDS = ("x", "y", "to_x", "to_y")

    def _tool_call_to_event(self, tool_call: Any) -> InputEvent:
        """Convert a parsed tool_call into a pixel-space InputEvent.

        Any coordinate fields are scaled from the model's [0,1000] space to
        pixels using the env's screen size; everything else passes through. The
        agent does not know how the env executes — it just emits the event.
        """
        params = tool_call.model_dump()
        name = params.pop("tool_name")
        if any(f in params for f in self._COORD_FIELDS):
            w, h = self.env.screen_size()
            for f in ("x", "to_x"):
                if params.get(f) is not None:
                    params[f] = int(params[f] / 1000 * w)
            for f in ("y", "to_y"):
                if params.get(f) is not None:
                    params[f] = int(params[f] / 1000 * h)
        return InputEvent(tool_name=name, params=params)

    def run(self) -> dict[str, Any]:
        """Run until the env is done, the agent answers, or max_steps is hit."""
        messages: list[dict[str, Any]] = [self._system_message()]
        steps = 0
        finished_by_agent = False
        final_answer: Optional[str] = None

        # A single transient failure (a truncated/invalid model output, a slow VM
        # screenshot, a flaky env.step) must NOT crash the whole episode — retry
        # the step and, only after several consecutive failures, end gracefully so
        # the runner still scores the task. This robustness is agent-side concern.
        consecutive_errors = 0
        while not self.env.is_done() and steps < self.max_steps:
            if consecutive_errors >= 4:
                logger.warning("too many consecutive errors; ending episode early")
                break

            try:
                image = self.env.screenshot()
            except Exception as e:  # noqa: BLE001
                logger.warning("screenshot failed: %s", e)
                consecutive_errors += 1
                time.sleep(2)
                continue
            messages.append(self._observation_message(image))
            trim_to_last_n_images(messages, self.image_budget)

            # Model call + structured parse, with retries (handles truncated/invalid JSON).
            step = reasoning = None
            for attempt in range(3):
                try:
                    content, reasoning = self._call_model(messages)
                    step = parse_step(content, self.step_model)
                    break
                except Exception as e:  # noqa: BLE001
                    logger.warning("model call/parse failed (attempt %d): %s", attempt + 1, e)
                    time.sleep(1.5)
            if step is None:
                # Drop the dangling observation we just appended and try a fresh step.
                if messages and messages[-1].get("role") == "user":
                    messages.pop()
                consecutive_errors += 1
                continue

            # Re-add ONLY the parsed output (never the reasoning).
            messages.append({"role": "assistant", "content": step.model_dump_json()})

            tc = step.tool_call
            if tc.tool_name in TERMINAL_TOOLS:
                finished_by_agent = True
                final_answer = getattr(tc, "content", "")
                if self.on_step:
                    self.on_step(steps, image, step, {"done": True}, reasoning)
                break

            try:
                event = self._tool_call_to_event(tc)
                result = self.env.step(event)
            except Exception as e:  # noqa: BLE001
                logger.warning("env.step failed: %s", e)
                consecutive_errors += 1
                time.sleep(1.5)
                continue

            consecutive_errors = 0
            tool_output = result.info.get("tool_output", "") if isinstance(result.info, dict) else str(result.info)
            messages.append(
                {
                    "role": "user",
                    "content": f'<tool_output tool="{tc.tool_name}">\n{tool_output}\n</tool_output>',
                }
            )
            if self.on_step:
                self.on_step(steps, image, step, result.info, reasoning)
            steps += 1
            if result.done:
                break

        return {
            "steps": steps,
            "finished_by_agent": finished_by_agent,
            "answer": final_answer,
        }
