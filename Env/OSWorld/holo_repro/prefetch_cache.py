"""Pre-download all OSWorld setup input files into the local cache.

Many tasks' setup steps download input files (gimp images, libreoffice xlsx, …)
from the HuggingFace ``ubuntu_osworld_file_cache`` dataset. HF is unreachable on
the campus network, so we fetch everything ahead of time (via the clash proxy)
into the exact cache path OSWorld expects — after which the run finds a cache hit
and needs no network for these setup downloads.

Cache path replicates desktop_env/controllers/setup.py::_download_setup:
    cache/{task_id}/{uuid5(NAMESPACE_URL, url)}_{basename(vm_path)}
We write each file under BOTH the original-URL key and the hf-mirror-URL key, so
the cache hits whether or not OSWORLD_HF_MIRROR is set at run time.

Only the SETUP "download" files are pre-cached here (their cache key is
deterministic). Evaluator/getter reference files are fetched at scoring time via
clash and are not pre-cached (their cache schemes vary).

Run from Env/OSWorld (clash must be up):
    python holo_repro/prefetch_cache.py
"""

from __future__ import annotations

import glob
import json
import os
import sys
import uuid

os.environ.setdefault("http_proxy", "http://127.0.0.1:7897")
os.environ.setdefault("https_proxy", "http://127.0.0.1:7897")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

import requests  # noqa: E402

CACHE = "cache"
MIRROR = "hf-mirror.com"
EXAMPLES = "evaluation_examples/examples"


def cache_path(task_id: str, url: str, vm_path: str) -> str:
    return os.path.join(
        CACHE, task_id, "{:}_{:}".format(uuid.uuid5(uuid.NAMESPACE_URL, url), os.path.basename(vm_path))
    )


def main() -> None:
    cfgs = sorted(glob.glob(os.path.join(EXAMPLES, "*", "*.json")))
    downloaded = skipped = errors = 0
    total_files = 0
    for c in cfgs:
        d = json.load(open(c, encoding="utf-8"))
        tid = d.get("id") or os.path.basename(c)[:-5]
        for step in d.get("config", []):
            if step.get("type") != "download":
                continue
            for f in step.get("parameters", {}).get("files", []):
                orig = f.get("url", "")
                vm_path = f.get("path", "")
                if "huggingface.co" not in orig and "hf-mirror" not in orig:
                    continue
                total_files += 1
                mir = orig.replace("huggingface.co", MIRROR)
                keys = {cache_path(tid, orig, vm_path), cache_path(tid, mir, vm_path)}
                if all(os.path.exists(k) for k in keys):
                    skipped += 1
                    continue
                fetch_url = mir if "huggingface.co" in orig else orig
                try:
                    r = requests.get(fetch_url, timeout=90)
                    r.raise_for_status()
                    content = r.content
                    for k in keys:
                        os.makedirs(os.path.dirname(k), exist_ok=True)
                        with open(k, "wb") as fh:
                            fh.write(content)
                    downloaded += 1
                    if downloaded % 25 == 0:
                        print(f"... {downloaded} downloaded ({skipped} cached) [{total_files} seen]", flush=True)
                except Exception as e:  # noqa: BLE001
                    errors += 1
                    print(f"ERR {tid} {fetch_url[:80]}: {str(e)[:80]}", flush=True)
    print(f"DONE. setup files seen={total_files}  downloaded={downloaded}  skipped(cached)={skipped}  errors={errors}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
