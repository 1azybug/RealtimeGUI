"""Human play entry point for RealtimeGym GUI / computer-use mode.

Lets a human play the same games through the SAME input layer the AI agent
uses: keyboard (W/A/S/D, F, Space) or clicking the on-screen action buttons.
Every key press / click goes through ``io_layer.InputController.resolve_event``
— identical to the agent path — so this both proves the environment is a real
computer-use environment and produces human reference trajectories.

Records the episode to MP4 + CSV (source = "human"), just like the agent runner.

Requires a display (X11). On a headless server (``DISPLAY`` unset) it exits with
an explanatory message. To smoke-test the human code path without a display,
use ``--simulate`` which feeds a scripted list of events through the exact same
resolve/step pipeline.

Usage (with a display):
    python -m realtimegym.play_human --game freeway --cognitive_load E --seed 0

Headless self-check:
    python -m realtimegym.play_human --game freeway --simulate W W Space S
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime
from typing import Any, Optional

import pandas as pd

import realtimegym
from realtimegym.environments.render.control_panel import compose_frame
from realtimegym.io_layer import InputController
from realtimegym.recorder import TrajectoryRecorder

_LOAD_TO_VERSION = {"E": "0", "M": "1", "H": "2"}

# pygame key code -> canonical key name fed to the input layer.
def _pygame_keymap() -> dict[int, str]:
    import pygame

    return {
        pygame.K_w: "W",
        pygame.K_a: "A",
        pygame.K_s: "S",
        pygame.K_d: "D",
        pygame.K_f: "F",
        pygame.K_SPACE: "Space",
        pygame.K_UP: "Up",
        pygame.K_DOWN: "Down",
        pygame.K_LEFT: "Left",
        pygame.K_RIGHT: "Right",
    }


def _make(game: str, cognitive_load: str, seed: int):
    version = _LOAD_TO_VERSION[cognitive_load]
    return realtimegym.make(f"{game.capitalize()}-v{version}", seed=seed, render=True)


def play_interactive(
    game: str, cognitive_load: str, seed: int, file: str, max_turns: int, fps: int
) -> dict[str, Any]:
    """Real-window interactive play. Requires a display."""
    import pygame

    pygame.init()
    pygame.font.init()
    env, real_seed, render = _make(game, cognitive_load, seed)
    obs, done = env.reset()
    game_surf = render.render(env)
    game_w, game_h = game_surf.get_size()
    controller = InputController(game, screen_w=game_w, game_h=game_h)
    composite = compose_frame(game_surf, game)
    screen = pygame.display.set_mode(composite.get_size())
    pygame.display.set_caption(f"RealtimeGym - {game} {cognitive_load} (human)")
    keymap = _pygame_keymap()

    recorder = TrajectoryRecorder(file.replace(".csv", ".mp4"), fps=fps)
    recorder.add(composite, env.game_turn, action="(start)", source="human")
    logs: dict[str, list[Any]] = {
        "game_turn": [],
        "raw_event": [],
        "action": [],
        "reward": [],
    }

    def render_to_screen() -> None:
        screen.blit(composite, (0, 0))
        pygame.display.flip()

    render_to_screen()
    turn = 0
    while not done and turn < max_turns:
        event_dict: Optional[dict[str, Any]] = None
        # Block until the player provides an input (or quits).
        waiting = True
        while waiting:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    recorder.close()
                    pygame.quit()
                    return {"aborted": True}
                if ev.type == pygame.KEYDOWN and ev.key in keymap:
                    event_dict = {"type": "key", "value": keymap[ev.key]}
                    waiting = False
                    break
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    event_dict = {"type": "click", "x": ev.pos[0], "y": ev.pos[1]}
                    waiting = False
                    break
            time.sleep(0.01)

        action = controller.resolve_event(event_dict)
        raw = (
            f'Key("{event_dict["value"]}")'
            if event_dict and event_dict["type"] == "key"
            else f'Click({event_dict["x"]},{event_dict["y"]})'
        )
        obs, done, reward, reset_flag = env.step(action)
        env.summary()
        game_surf = render.render(env)
        composite = compose_frame(game_surf, game)
        render_to_screen()

        logs["game_turn"].append(env.game_turn)
        logs["raw_event"].append(raw)
        logs["action"].append(action)
        logs["reward"].append(reward)
        pd.DataFrame(logs).to_csv(file)
        recorder.add(composite, env.game_turn, action=action, source="human", raw_event=raw)
        turn += 1

    recorder.close()
    pygame.quit()
    return {
        "game": game,
        "seed": seed,
        "real_seed": real_seed,
        "reward": env.reward,
        "turns": env.game_turn,
    }


def play_simulated(
    game: str, cognitive_load: str, seed: int, events: list[str], file: str, fps: int
) -> dict[str, Any]:
    """Headless self-check: feed scripted key names through the same pipeline.

    Proves the human path (resolve_event -> env.step) works without a display,
    and exercises the identical translation logic the agent uses.
    """
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame

    pygame.init()
    pygame.font.init()
    env, real_seed, render = _make(game, cognitive_load, seed)
    obs, done = env.reset()
    game_surf = render.render(env)
    game_w, game_h = game_surf.get_size()
    controller = InputController(game, screen_w=game_w, game_h=game_h)
    composite = compose_frame(game_surf, game)

    recorder = TrajectoryRecorder(file.replace(".csv", ".mp4"), fps=fps)
    recorder.add(composite, env.game_turn, action="(start)", source="human")
    logs: dict[str, list[Any]] = {"game_turn": [], "raw_event": [], "action": [], "reward": []}

    for key in events:
        if done:
            break
        event_dict = {"type": "key", "value": key}
        action = controller.resolve_event(event_dict)
        obs, done, reward, reset_flag = env.step(action)
        env.summary()
        game_surf = render.render(env)
        composite = compose_frame(game_surf, game)
        logs["game_turn"].append(env.game_turn)
        logs["raw_event"].append(f'Key("{key}")')
        logs["action"].append(action)
        logs["reward"].append(reward)
        pd.DataFrame(logs).to_csv(file)
        recorder.add(composite, env.game_turn, action=action, source="human", raw_event=f'Key("{key}")')

    recorder.close()
    return {
        "game": game,
        "seed": seed,
        "real_seed": real_seed,
        "reward": env.reward,
        "turns": env.game_turn,
        "actions": logs["action"],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Human play for RealtimeGym GUI mode.")
    ap.add_argument("--game", choices=["freeway", "snake", "overcooked"], default="freeway")
    ap.add_argument("--cognitive_load", choices=["E", "M", "H"], default="E")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--log_dir", default="logs_human")
    ap.add_argument("--max-turns", type=int, default=200)
    ap.add_argument("--fps", type=int, default=2)
    ap.add_argument(
        "--simulate",
        nargs="*",
        default=None,
        help="Headless self-check: scripted key names (e.g. W W Space S).",
    )
    args = ap.parse_args()

    run_dir = os.path.join(
        args.log_dir, f"{args.game}_{args.cognitive_load}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    os.makedirs(run_dir, exist_ok=True)
    file = os.path.join(run_dir, f"{args.game}_{args.cognitive_load}_{args.seed}.csv")

    if args.simulate is not None:
        res = play_simulated(args.game, args.cognitive_load, args.seed, args.simulate, file, args.fps)
        print(f"[simulated human] result: {res}")
        return

    if not os.environ.get("DISPLAY"):
        print(
            "No DISPLAY found — interactive human play needs an X11 display.\n"
            "On a headless server, use --simulate to self-check the human code path, e.g.:\n"
            "  python -m realtimegym.play_human --game freeway --simulate W W Space S"
        )
        return

    res = play_interactive(
        args.game, args.cognitive_load, args.seed, file, args.max_turns, args.fps
    )
    print(f"[human] result: {res}")


if __name__ == "__main__":
    main()
