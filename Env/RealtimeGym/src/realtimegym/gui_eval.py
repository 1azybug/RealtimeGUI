"""GUI computer-use evaluation runner (thin assembly layer).

Wires together a generic ``HoloComputerAgent`` and a ``GameComputerEnv`` (the
RealtimeGym adapter), records each episode to MP4 + CSV, and reports scores.
All game knowledge lives in the env/io_layer; this file only assembles parts
and logs results. Scoring uses ``env.total_reward`` (same metric as the paper).

Usage:
    python -m realtimegym.gui_eval \
        --game freeway --cognitive_load E --seeds 0 1 \
        --base-url http://localhost:8001/v1 --model Holo-3.1-35B-A3B \
        --max-steps 60 --log_dir logs_gui
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from typing import Any

# Headless rendering for the game adapter.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pandas as pd  # noqa: E402
import pygame  # noqa: E402
from openai import OpenAI  # noqa: E402

from holo_agent import HoloComputerAgent  # noqa: E402
from holo_agent import TrajectoryRecorder as TrajRecorder  # noqa: E402
from holo_agent import report as holo_report  # noqa: E402
from realtimegym.game_computer_env import GameComputerEnv  # noqa: E402
from realtimegym.recorder import TrajectoryRecorder as VideoRecorder  # noqa: E402


def run_episode(
    client: OpenAI,
    model: str,
    game: str,
    cognitive_load: str,
    seed: int,
    file: str,
    max_steps: int,
    record_mp4: bool = True,
    fps: int = 2,
    temperature: float = 0.8,
) -> dict[str, Any]:
    env = GameComputerEnv(game=game, cognitive_load=cognitive_load, seed=seed)

    # Per-episode output dir (alongside the per-episode csv path passed in).
    ep_dir = file[:-4] if file.endswith(".csv") else file
    # Generic, env-agnostic step recording (traj.jsonl + observation PNGs +
    # system prompt) shared with every other runner; lives in the Agent package.
    traj_rec = TrajRecorder(ep_dir)
    # The annotated MP4 is a RealtimeGym-specific video artifact (not duplicate logging).
    video = VideoRecorder(os.path.join(ep_dir, "recording.mp4"), fps=fps) if record_mp4 else None

    # Record the initial frame before any action.
    if video is not None:
        video.add(
            pygame.image.frombuffer(
                env.screenshot().tobytes(), env.screenshot().size, "RGB"
            ),
            turn=0,
            action="(start)",
            source="agent",
        )

    def on_step(idx: int, image, step, info: dict[str, Any], reasoning: str) -> None:
        traj_rec.on_step(idx, image, step, info, reasoning)
        tc = step.tool_call
        if video is not None and not info.get("done"):
            surf = pygame.image.frombuffer(image.tobytes(), image.size, "RGB")
            # image is the PRE-action frame; annotate with the action just taken.
            video.add(
                surf,
                turn=info.get("game_turn", idx),
                action=str(info.get("action", "")),
                source="agent",
                raw_event=(
                    f"{tc.tool_name} ({tc.x},{tc.y})"
                    if tc.tool_name == "click"
                    else f'press_key("{tc.key}")'
                    if tc.tool_name == "press_key"
                    else tc.tool_name
                ),
            )

    agent = HoloComputerAgent(
        client=client,
        model=model,
        env=env,
        max_steps=max_steps,
        temperature=temperature,
        on_step=on_step,
    )
    traj_rec.dump_system_prompt(agent.system_prompt())

    start = time.time()
    loop_info = agent.run()
    if video is not None:
        video.close()
    # Self-contained HTML replay (observation + reticle + note/thought/action).
    try:
        with open(os.path.join(ep_dir, "report.html"), "w", encoding="utf-8") as f:
            f.write(holo_report.build_html(ep_dir))
    except Exception:  # noqa: BLE001
        pass

    return {
        "game": game,
        "cognitive_load": cognitive_load,
        "seed": seed,
        "real_seed": env.real_seed,
        "reward": env.total_reward,
        "turns": env.game_turn,
        "steps": loop_info["steps"],
        "finished_by_agent": loop_info["finished_by_agent"],
        "wall_time": round(time.time() - start, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="GUI computer-use eval (Holo agent loop).")
    ap.add_argument("--game", choices=["freeway", "snake", "overcooked"], default="freeway")
    ap.add_argument("--cognitive_load", choices=["E", "M", "H"], default="E")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0])
    ap.add_argument("--base-url", default="http://localhost:8001/v1")
    ap.add_argument("--api-key", default="EMPTY")
    ap.add_argument("--model", default="Holo-3.1-35B-A3B")
    ap.add_argument("--max-steps", type=int, default=100)
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--log_dir", default="logs_gui")
    ap.add_argument("--no_mp4", action="store_true", default=False)
    ap.add_argument("--fps", type=int, default=2)
    args = ap.parse_args()

    pygame.init()
    pygame.font.init()
    client = OpenAI(base_url=args.base_url, api_key=args.api_key)

    run_dir = os.path.join(
        args.log_dir,
        f"{args.game}_{args.cognitive_load}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
    )
    os.makedirs(run_dir, exist_ok=True)

    results = []
    for seed in args.seeds:
        file = os.path.join(run_dir, f"{args.game}_{args.cognitive_load}_{seed}.csv")
        print(f"\n=== {args.game}-{args.cognitive_load} seed={seed} ===")
        res = run_episode(
            client=client,
            model=args.model,
            game=args.game,
            cognitive_load=args.cognitive_load,
            seed=seed,
            file=file,
            max_steps=args.max_steps,
            record_mp4=not args.no_mp4,
            fps=args.fps,
            temperature=args.temperature,
        )
        print(f"--> {res}")
        results.append(res)

    df = pd.DataFrame(results)
    df.to_csv(os.path.join(run_dir, "summary.csv"), index=False)
    print("\n================ SUMMARY ================")
    print(df.to_string(index=False))
    print(f"\nMean reward: {df['reward'].mean():.2f}")
    with open(os.path.join(run_dir, "summary.json"), "w") as f:
        json.dump(
            {"args": vars(args), "results": results, "mean_reward": float(df["reward"].mean())},
            f,
            indent=2,
        )


if __name__ == "__main__":
    main()
