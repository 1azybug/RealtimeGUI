# 单任务调试手册 —— `debug_one.py`（只跑你指定的那一个）

传一个 `domain/example_id`，**只跑这一个任务**，控制台**实时打印** id / 指令 / 轨迹路径，
以及模型每一步的 `note / thought / action / 截图路径`；结束打印分数与 report.html 路径。
适合：盯上了某个失败任务，想反复重跑、逐步看模型到底卡在哪。

> 串行跑一批任务用 `[复现_debug_串行.md](复现_debug_串行.md)`；评测总流程见 `[复现.md](复现.md)`；
> 网络/geo 修复见 `[CLAUDE.md](CLAUDE.md)`。两个 debug 脚本共用同一套 run_holo 机制与产物格式。

---

## 0. 前置

```bash
cd /mnt/zhaorunsong/repo/CUA/Env/OSWorld
PYO=/mnt/zhaorunsong/anaconda3/envs/osworld/bin/python
```

**起 vLLM（端点 :8002）**、**docker/KVM 可用**、**家用 SSH 隧道已绑** `10.200.0.1:7897` ——
与串行手册一致，详见 `[复现_debug_串行.md](复现_debug_串行.md)` §0。最快验证 vLLM：

```bash
curl -s http://127.0.0.1:8002/v1/models | head -c 200
```

> ⚠️ **联网的 web 任务（chrome/multi_apps 等）必须带** `HOLO_VM_PROXY=http://10.200.0.1:7897`：本机宿主无直连外网，
> VM 唯一外网出口就是这个美国代理。不带它，页面加载不出来、卡在 `about:blank`（不是模型问题）。只有纯离线任务可省。

---



## 1. 怎么知道任务的 `domain/id`

`domain` = `evaluation_examples/examples/` 下的目录名；`id` = 该目录里 json 文件名（去掉 `.json`）。

```bash
# 列出某域所有任务 id 与指令（例：chrome）
$PYO - <<'PY'
import glob, json, os
for f in sorted(glob.glob("evaluation_examples/examples/chrome/*.json")):
    d = json.load(open(f))
    print(os.path.basename(f)[:-5], "::", d.get("instruction","")[:80])
PY
```

得到形如 `f79439ad-3ee8-4f99-a518-0eb60e5652b0 :: Search for a one way flight ...`，
则任务标识就是 `chrome/f79439ad-3ee8-4f99-a518-0eb60e5652b0`。

---



## 2. 跑

```bash
# 基本：跑这一个任务
$PYO holo_repro/debug_one.py chrome/f79439ad-3ee8-4f99-a518-0eb60e5652b0

# 地理敏感 web：让 VM 走美国代理
HOLO_VM_PROXY=http://10.200.0.1:7897 \
  $PYO holo_repro/debug_one.py chrome/f79439ad-3ee8-4f99-a518-0eb60e5652b0

# 换提示词变体 / 端点 / 加大步数
$PYO holo_repro/debug_one.py os/<id> --prompt v2 --base_url http://127.0.0.1:8003/v1 --max_steps 150
```

```bash
# 网络测试,这个任务需要网络
rm -rf results_debug/pyautogui/screenshot/Holo-3.1-4B/chrome/e1e75309-3ddb-4d09-92ec-de869c928143
curl -x http://10.200.0.1:7897 http://ip-api.com/json
HOLO_VM_PROXY=http://10.200.0.1:7897 $PYO holo_repro/debug_one.py chrome/e1e75309-3ddb-4d09-92ec-de869c928143

```

参数：


| 参数             | 默认              | 说明                                  |
| -------------- | --------------- | ----------------------------------- |
| `task`（位置参数）   | ——              | `domain/example_id`，必填              |
| `--prompt`     | `v1`            | `v1`=baseline（贴近官方），`v2`=behavioral |
| `--base_url`   | `:8002/v1`      | vLLM 端点                             |
| `--result_dir` | `results_debug` | 结果根目录（与串行脚本共用，互不冲突）                 |
| `--max_steps`  | `100`           | 最大步数                                |


可选环境变量：`HOLO_VM_PROXY`（VM 走美国代理）、`HOLO_NET_GATE=1`（断网暂停不计分），同串行手册。

---



## 3. 实时输出 & 产物

输出格式与串行手册 §2 完全一致（任务头 → 每步 note/thought/action/shot → RESULT 行 + report 路径）。
产物落在 `results_debug/pyautogui/screenshot/Holo-3.1-4B/<domain>/<id>/`：
`traj.jsonl`、`step_*.png`、`report.html`（可视化回放）、`result.txt`、`meta.json`、`system_prompt.txt`。
详见 `[复现_debug_串行.md](复现_debug_串行.md)` §3。

浏览器打开 `report.html` 看回放：橙色准星标出模型点击处，配合每步 thought 判断
**是模型问题（点错/计划错/死循环/没存盘）还是环境问题（页面没加载/代理报错/中国弹窗）**。

---



## 4. 反复重跑同一个任务

脚本看到 `result.txt` 会**跳过**。要再跑一次，先删该任务目录：

```bash
rm -rf results_debug/pyautogui/screenshot/Holo-3.1-4B/chrome/f79439ad-3ee8-4f99-a518-0eb60e5652b0
$PYO holo_repro/debug_one.py chrome/f79439ad-3ee8-4f99-a518-0eb60e5652b0
```

> 模型有温度（`--temperature` 默认 0.8），同一任务多跑几次可能不同结果——这正是调试时观察稳定性的方式。

