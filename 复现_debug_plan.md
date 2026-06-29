# Holo-3.1-4B @ OSWorld-Verified 复现 Debug 规划（Opus 制定，交 Sonnet 执行）

> 配套：人类版 [`复现.md`](复现.md)、LLM 操作手册 [`复现_LLM.md`](复现_LLM.md)、任务说明 [`current_goal.md`](current_goal.md)。
> 本文件只讲「为什么分数偏低、怎么严谨地排查并修复」，不重复环境搭建步骤。

## 0. 现状与三条已查实的事实（先读，别跳过）

当前结果（`osworld_results.csv`，369 全跑完）：**总均分 0.4550**，**199/369 = 54% 是硬 0 分**。
按域（mean / zero%）：

| domain | n | mean | zero% |
|---|---|---|---|
| multi_apps | 101 | 0.329 | **66%** |
| libreoffice_calc | 47 | 0.404 | 60% |
| vs_code | 23 | 0.435 | 57% |
| gimp | 26 | 0.462 | 54% |
| libreoffice_impress | 47 | 0.445 | 53% |
| chrome | 46 | 0.499 | 50% |
| libreoffice_writer | 23 | 0.522 | 48% |
| os | 24 | 0.625 | 38% |
| vlc | 17 | 0.694 | 29% |
| thunderbird | 15 | 0.733 | 27% |

**已查实的事实：**

1. **目标值已确定 = 75.8%，我们差了 ~30 个点（最重要）。** 官方博客 `hcompany.ai/holo3.1` 原始结果表（COMPUTER USE → OSWorld 行）按尺寸列出：

   | | 0.8B | **4B** | 9B | 35B-A3B | Qwen3.5-397B |
   |---|---|---|---|---|---|
   | **OSWorld** | 34.6% | **75.8%** | 71.5% | 80.0% | 62.1% |
   | Overall | 47.5% | 72.6% | 73.0% | 78.3% | 70.9% |

   - **Holo3.1-4B 官方 OSWorld = 75.8%**（比 9B 的 71.5% 还高）。我们现在 0.4550 → **差 ~30 点**。
   - sonnet 的"4B 该四十多"是**确凿幻觉**，作废。
   - ⚠️ **30 点的差距太大，不可能只靠修网络/环境补回（那顶多 10–15 点）。几乎必然还有 harness/口径层面的系统性问题**——这是头号矛盾，Phase 0/1 必须查清官方评测口径并逐项对齐。
   - 注意别混淆：表里 H CORPORATE 下的 "Multi-Apps" 是 H 公司内部基准，**不是** OSWorld 的 multi_apps 域。

2. **代码严谨性：scoring 与 agent 决策逻辑没被私自改动。** 当前未提交 diff 全是网络/环境管线（见 §1），agent loop 与官方 `agent-loop.md` 规范一致。唯一有运行时影响的是 `run_holo.py` 的 `enable_proxy=True`，须 A/B 验证。

3. **官方不可行（infeasible）任务 = 29 个 / 369。** 分布：gimp 10、os 5、vs_code 5、chrome 3、vlc 2、calc/writer/multi_apps/thunderbird 各 1。
   → 这 29 个任务，**正确行为 = 模型声明不可行**（评测器 `func` 含 `infeasible`，动作历史以 `FAIL` 结尾即得分），**无需修环境**。其余 340 个**都是可完成任务**：0 分只能是「模型失败」或「环境坏了」，环境坏了**必须修**，不能当能力问题。

---

## 诊断结果（轨迹归因已完成，2026-06-25 by Opus）

读 `meta.json`+`traj.jsonl`+截图，对全 369 任务归因。**核心结论：30 点差距的主体是 Agent 行为，不是环境故障。**

**全 369 分桶**：WIN 151 / PARTIAL 11 / INF_ok 12 / **INF_miss 17** / **ZERO_feasible 178**。明细见 `holo_repro/zero_triage.csv`。

1. **环境崩溃可忽略**：178 个「可完成却 0 分」里，空轨迹=0、中途停=7。**不存在大批"网络/崩溃假 0"**。之前"54% 0 分像环境问题"的猜测被证伪。
2. **infeasible 管线正确**：29 个官方不可行任务，模型声明不可行的 12 个**全部满分**、没声明的 17 个**全部 0**，零错配。→ 那 17 个是**模型没识别出任务不可能**（能力/提示词），修好上限 +17/369≈**+4.6 点**。
3. **主因＝模型"自认完成却没真完成"**：178 个 0 分里 **120 个是模型主动 `answer` 说做完了**（51 个耗光 100 步瞎转，7 个中途停）。
4. **「漏保存」是已坐实的最大单一可修因**：libreoffice 三域 **有 Ctrl+S 均分 0.637 / 无 Ctrl+S 均分 0.365**（115 个里 82 个根本没存盘）。自认完成的 51 个 libreoffice 0 分里 **40 个没保存**。截图实证（calc `1273e544`）：Sheet2 数据**已正确复制到位、UI 全对，但没存盘→评测器读磁盘旧文件→0**。底层点击/坐标/grounding **是好的**（选列/建表/粘贴全精准生效），差距在持久化与精度，不在执行保真度。
5. **其余**：51 个耗光步数＝长程任务（multi_apps 占 30）grounding/导航走死胡同；自认完成里还有一类是**差精度**（存错文件名/路径/单元格、"别动其它区域"没遵守）。

**关键待答（决定上述是"可忠实修复"还是"4B 真实上限"）**：官方 4B 也是 75.8%，它显然能存盘、能识别不可行。所以要么**官方 system prompt/工具集/参数比我们更有效**，要么我们哪里没对齐。→ **下一步最高价值＝Phase 0 + Phase 1.2：拿到官方 OSWorld harness/prompt 并对齐**；对齐后仍漏存，才算 4B 真实限制。⚠️ 在确认官方做法前，**不要**私自加"自动存盘 hack"或"记得保存"提示注入——那是不忠实的改动。

---

## 深挖更新（轨迹查实，2026-06-25 第二轮）—— 推翻部分早期结论

用 v1/v2 A/B 的实测轨迹逐条核对（不再靠聚合猜测），有三个硬发现：

1. **原始结果有 ~23% 被多-episode 污染**：`85/369` 个 orig 任务的 `traj.jsonl` 里塞着 2–4 段重复 episode（step_num 多次重置）＝孤儿 worker / 中断续跑重复写入（干净的 A/B 重跑 0 个）。→ **基于 orig 逐任务轨迹的分析（含上一节的 has_save / 自认完成统计）对这 85 个任务不可信**；result.txt 的分多半取自最后一次完整尝试、聚合 0.4550 大致仍可用，但**逐任务不可信**。**已修**：`recorder.py` 每次运行先清空旧 traj/截图，保证单 episode。
2. **单样本方差极大（temp=0.8）**：同一 v1 基线 prompt 重跑，大量 orig=0 任务翻成 1.0、orig=1 翻成 0.0，呈典型**回归均值**。按 orig 分数选的子集（G1 选 0、G3 选 1）会放大这种假象。→ **单样本 27 任务的 A/B 无法把"prompt 真效应"从噪声里分出来。**
3. **v1/v2 的分差＝挑剔操作的运气，不是 prompt 系统性好坏**（逐轨迹证）：
   - `calc/4de54231`：**v2 的"保存"规则确实生效（存了盘）**，失败在复杂拼接公式写错；v1 只是多调试几步蒙对。
   - `writer/0b17a146`：v1/v2 都做"选 2→下标"，差异只在"单字符 drag 选择"不稳——v1 这次发现失败并纠正、v2 假设成功就收工。
   - 注意：**v2 的"答完前先自检"指令并未可靠改变 4B 行为**（仍假设成功）→ 小模型对提示词指令的遵循度有限，"靠 prompt 修行为"杠杆可能不大。

**结论修正**：① 30 点差距里，模型真实失败模式是**不稳的精细 grounding（单字符/精确区域选择）、精度（公式/格式）、不自检、漏保存**；② 但"漏保存占多大""v2 好不好"**当前数据都答不了**——基线被污染、单样本噪声盖过效应。**要得到可信结论必须：(a) 用修好的 recorder 重跑得干净基线；(b) 多采样（每任务跑 k 次取均值）压噪声后再比 prompt，且子集要随机不按分数选。**

---

## Phase 0 — 先把「目标值」和「官方口径」钉死（最便宜、最先做）

目标已定死 = **75.8%**（见 §0 事实 1）。Phase 0 现在的唯一任务，是查清**官方是用什么口径/脚手架跑出 75.8 的**——因为 30 点的差距强烈指向口径不一致，这比修单个任务重要得多。

- [ ] **0.1 取官方 OSWorld 评测协议（重中之重）。** 抓 HuggingFace 模型卡 `Hcompany/Holo-3.1-4B`、collection `Hcompany/holo31`、博客 `hcompany.ai/holo3.1`、以及 H 官方是否放出 OSWorld 评测代码/agent harness（GitHub）。要回答：
  - 这个 "OSWorld" 是不是 **OSWorld-Verified（369）**？（35B 同表 80.0 vs 旧 Holo3 榜 82.6，基本就是 Verified）。
  - **是 Holo 单模型端到端当 agent，还是 grounding+planner？** Holo 是纯截图模型、被定位成"autonomous agent 的大脑"，**大概率是单模型端到端**（与我们一致）——但必须坐实。
  - `max_steps`、截图分辨率、`temperature`、动作集（官方训练时的工具箱）、是否带 a11y tree、是否有重试/多次采样取最好。
  - 有没有官方的 system prompt / chat 模板细节。
- [ ] **0.2 逐项对齐表**：把官方口径的每一项与我们的实现（`run_holo.py` 参数 + `agent.py` + `tools.py` + `osworld_computer_env.py`）列成对照表，标出每一处不一致——这些就是 30 点差距的候选来源，按影响排序。
- [ ] **0.3 结论写回**：更新本文件与记忆 `osworld-holo-repro`。

**产出**：官方口径 vs 我们实现的逐项 diff 表 + 分差候选优先级。

---

## Phase 1 — 冻结并审计 harness（保证后续重跑可信）

目的：回答用户的"我担心 sonnet 私自改动代码使结果不可信"。**在重跑前先把 harness 钉成可信、可复现的状态。**

- [ ] **1.1 scoring 路径零改动核验。** 把 vendored OSWorld 的评测相关文件与上游 `xlangai/OSWorld`（对应 commit）对比，确认**未被改动**：
  - `desktop_env/evaluators/`（getters / metrics / 各 `func`）
  - `desktop_env/desktop_env.py` 的 `evaluate()` 路径
  方法：`git log -p --follow <file>`，或另 clone 一份上游 diff。**只要这些被改过，结果一律不可信，先回滚再说。**
- [ ] **1.2 agent loop 对账官方规范**（`Agent/docs/holo_official/agent-loop.md`）。已核对一致的项：结构化输出 `{note,thought,tool_call}`、schema 同时进 `structured_outputs` 和 system prompt 的 `<output_format>`、`enable_thinking=True`、reasoning 不回填、坐标 [0,1000]→像素、最近 3 张图、`tool_output` 用 user 消息、`answer` 终止、temperature=0.8。**仍需查的两个偏差候选**：
  - **system prompt 非官方原版**：我们用的是自写 prompt（`agent.py:_SYSTEM_PROMPT`）。官方 loop 引用 `render_prompt(tools=...)` 但文档未给全文。小模型（4B）对 prompt 更敏感——去 `quickstart.md`/`api-reference.md`/`element-localization.md` 找官方推荐 system prompt，若存在则对齐。
  - **工具集 `tools.py`**：官方只示范 click/write/answer，"更宽工具箱按同模式扩展"。核对我们 `TOOLS` 的命名/语义/字段是否贴合官方动作语义；4B grounding 对工具描述敏感。
- [ ] **1.3 处置当前未提交 diff**（逐条判定，验证后再 commit）：
  - `agent.py` reasoning 提取兜底 → **保留**（纯日志，reasoning 永不回填，对分数零影响）。
  - `setup.py` tinyproxy upstream 无 username 兜底 + gdrive httplib2 走代理；`settings.yml` 加 `oauth_scope: drive` → **保留**（gdrive/web 需要）。
  - `run_holo.py` `enable_proxy=True` → **必须 A/B 验证**：取 3–5 个 chrome 实网任务（航班/酒店/购物搜索），分别在 `enable_proxy=True/False` 下跑，确认它让 VM 能经 clash 触网（而不是反而破坏）。**验证有益后才提交。**
- [ ] **1.4 复现性核验**：固定随机性来源（temperature=0.8 是官方值，保留；注意 0 分里有多少是采样波动——见 Phase 3 重试）。

**产出**：一次「harness 忠实且已冻结」的签字，commit 落定，后续重跑基于此。

---

## Phase 2 — 给 199 个 0 分做归因分类（先诊断，再动手）

**核心纪律（直接针对 sonnet 的两个风险行为）：**
> 一个 0 分**只有在** report.html 显示「环境健康 ∧ 任务可完成 ∧ 模型确实做错」时，才算**模型能力**问题。
> 网络 / 权限 / setup / gdrive 导致的 0 **不是能力问题**——必须归桶、修复、重跑，**不准当模型弱**。

- [ ] **2.1 分层抽样**：每域至少看 6–8 个 0 分任务 + 全部 8 个 gdrive 任务 + 全部 29 个 infeasible 任务里得 0 的。逐个开 `report.html` + `traj.jsonl` + `full_eval.log` 对应段落。
- [ ] **2.2 归桶**（产出 `zero_triage.csv`：task_id, domain, bucket, 证据一行）：
  - **E1 网络/触网**：HF setup 下载失败 / VM 上不了网（chrome 实网任务）/ ProxyError / VM never ready。
  - **E2 gdrive 鉴权**：8 个 google_drive=yes 任务。
  - **E3 infeasible 处理错**：属于那 29 个，但模型没声明不可行、或声明了但 `_INFEASIBLE_RE` 没匹配上（`run_holo.py:67`）。
  - **E4 setup 静默劣化**：输入文件没下全 → 任务从一开始就不可能完成，评测器给真 0。
  - **M 真·模型失败**：环境正常、任务可完成，模型误点/计划错/放弃/死循环。
- [ ] **2.3 算"天花板"**：E1+E2+E3+E4 占多少。这决定修完环境后分数能回到哪。
- [ ] 特别关注：**multi_apps（66% 0，101 任务，占总量 27%）是头号拖累**；**gimp 26 个里 10 个是 infeasible**——优先核这两块。

**产出**：`zero_triage.csv` + 各桶计数 + 可恢复分数估计。

---

## Phase 3 — 按桶修环境，只重跑「可恢复」的任务

修复用 §1 已冻结的 harness。**确认 M 桶的 0 保持不动**（那是真实能力信号）。

- [ ] **E1 触网**：核实 VM→宿主 NAT→clash 真能到外网（记忆note：clash 在宿主回环、VM 默认够不到；`enable_proxy`/tinyproxy 正是桥接手段——用 §1.3 的 A/B 坐实）。跑前预取全部 setup 文件并核对缓存命中；**跑前加网络健康门**：HF/clash 不通就暂停而不是让任务批量失败误判 0。
- [ ] **E2 gdrive**：完成 diff 里的 gdrive 修复，端到端验证至少 1 个 gdrive 任务能过；再批量重跑 8 个。
- [ ] **E3 infeasible**：对那 29 个任务，确认模型声明不可行时能被正确判分；必要时拓宽 `_INFEASIBLE_RE` 或核对 answer 文本。**反向保护**：可完成但环境坏的任务**不准**被误判成 infeasible 而"假装得分"。
- [ ] **E4**：预取修好后重跑。
- [ ] **重跑范围**：只删除并重跑 E1–E4 的 result.txt（断点续跑机制会重算）；M 桶保留。flaky 可疑的（如疑似采样波动）可同种子重试 1 次确认。

**产出**：修复后的新一轮结果。

---

## Phase 4 — 终账与对比

- [ ] 重算各域 + 总均分。
- [ ] **对比 Phase 0 的证据化 4B 目标区间**（不是 74）。说明差距还剩多少、归因到哪。
- [ ] 残留的 M 桶 0 = 4B 的真实能力上限信号，单列归档。
- [ ] 更新 `osworld_results.csv`、本文件 §0、记忆 `osworld-holo-repro`（含纠正后的目标、最终分、infeasible 处理结论）。

---

## 给 Sonnet 的硬性护栏（务必遵守）

1. **锚点纪律**：目标只锚到 Phase 0 的证据。既不假设"4B 该低"，也不假设"必须 74"。
2. **0 分归因纪律**：网络/权限/gdrive/setup 失败的 0 **绝不**当模型能力，必须归桶→修→重跑。每个判为"模型能力"的 0 都要有 report.html 证据。
3. **改动纪律**：**不准**改评测器/getters/metrics/`evaluate()`/agent 决策逻辑。若觉得非改不可——**停下，问人类**。
4. **提交纪律**：任何改动小步、可审、commit message 写清"为什么"。**禁止静默改代码**。改前先 `git diff` 给人类看。
5. **可行性判定纪律**：纠结"修环境还是接受不可行"时，**读该任务 config 的 evaluator `func`**：含 `infeasible`（这 29 个）→ 正确行为是模型声明不可行，不修环境；否则任务可完成 → 0 分要么修环境要么是真失败，**不准**用"不可行"搪塞。
6. **进程纪律**：停评测必须杀干净 spawn worker（见 `复现_LLM.md` STEP 7），否则孤儿污染结果；换配置后清空对应 result.txt 再跑。
