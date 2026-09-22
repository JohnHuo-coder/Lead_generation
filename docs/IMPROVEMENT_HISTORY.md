# Research Pipeline 改进历史

记录每次 batch test 前后改了什么，方便对比报告、回溯决策。  
**当前 main 已 push 到：** `66d6c4f` · **本地还有未 commit 改动**（见阶段 8–10 与文末「进行中」）。

---

## 怎么读这份文档

| 列 | 含义 |
|---|---|
| **阶段** | 按时间顺序的改进批次 |
| **来源** | git commit、Engine PR、或本地手改 |
| **状态** | `merged` / `local-only` / `in-progress` |
| **主要文件** | 动刀最多的模块 |
| **测试** | 当时用的 batch 规模与报告（如有） |

---

## 阶段 0：Pipeline 基线（9/16–9/17）

> 还没有 LangSmith Engine PR，主要是把 research graph 搭起来。

### 0.1 初始 LangGraph pipeline — `8184e20` ✅ merged

- 引入 `src/` 结构：`search → fit_score` graph、batch HTML report、`test.ipynb`
- Tavily `web_search`，agent 自己抽 evidence 并返回 `ResearchResult`
- 模型：`gpt-5-nano`

### 0.2 多阶段 evidence verification — `870ebf1` ✅ merged

- Verify 拆阶段：excerpt 校验 → claim verification LLM
- Excerpt 归一化匹配；非 verbatim 时走 **excerpt derivation LLM**
- Verify 返回 `unclear_ownership` 时，用 **Tavily Extract 拉 full page** 再验一次（`src/services/tavily_extract.py`）
- Report 增加 failure stage 标签

### 0.3 按 search batch 抽 evidence — `fcca950` ✅ merged

- Extract 从 agent 里拆到 `search_evidence_extractor.py`，**每次 search 单独抽一批**
- LLM 常给错 `result_id` → 用 excerpt 在 batch 内 **自动纠偏**
- Report 增加 **average tool call count**
- 删除旧 `pipeline.py` / `fit_scoring.py` 脚本

---

## 阶段 1：Verify 内嵌到 search — `6a2d78d` ✅ merged（9/18）

**动机：** agent 应在 **已 verified 的事实** 上判断 sufficient，而不是自己编 evidence。

**改动：**

- `web_search` 内：extract → verify → 合并进 state
- Graph 简化为 **search 单节点**（去掉独立 verify node）
- `ResearchResult` 只返回 `sufficient` + `additional_evidence_needed`（不再让 agent 返回 evidence 列表）
- `control_web_search` middleware：**4 次 search 上限**，用尽后强制调 `ResearchResult`
- Agent prompt：每次 search 后看 verified 再决定是否继续

**主要文件：** `tools.py`, `nodes.py`, `evidence_verification.py`, `state.py`, `research_report.py`

---

## 阶段 2：Off-target 公司过滤（Engine PR #1）— `6497eea` ✅ merged（9/18）

**来源：** LangSmith Engine 自动 PR  
[PR #1: fix(evidence): reject off-target company sources](https://github.com/JohnHuo-coder/Lead_generation/pull/1)  
分支：`issues-agent/26d9dc28-348b-4edf-ab35-67b279c93308`

**问题：** 搜 A 酒店时，Tavily 返回 B 酒店页面；excerpt 对、verify 也可能过，competitor claim 进 verified。

**改动：**

1. **确定性 token 匹配**（`search_evidence_extractor.py`）
   - 从公司名拆 token，去掉 `hotel` / `bangkok` / `the` 等泛词
   - 要求 token **全部出现** 在 document 的 `title + url + content`
   - 位置：**extract 之后、verify 之前**（`_resolve_evidence_to_batch` 里）
2. **Prompt 收紧**
   - Extract：claim 主语必须是 target company
   - Verify：**FIRST check subject identity**
3. **统计：** `off_target_company_rejections` 进 state + batch report
4. ToolMessage 里提示 agent 换 query / 用 `site:`

**LangSmith eval：** dataset 4 条 regression；Studio Ekkamai / Nine Place 40 曾 fail（verified 里混进别家酒店）。

---

## 阶段 3：Eval + Insufficient 报告 — `b4f48c5` ✅ merged（9/18）

**改动：**

- 新增 `scripts/eval_research.py`（对接 `b2b-leadgen-engine-dataset`，依赖 LangSmith UI 的 Assertions evaluator）
- HTML report 增加 **Insufficient Runs** 表格（公司、sufficient=false、缺什么 evidence）
- Eval 默认 `--verbose` 可关；输出 slim 为 verified / failed / sufficient

**主要文件：** `scripts/eval_research.py`, `research_report.py`

---

## 阶段 4：跳过重复搜索（Engine PR #2）— `3570f5e` ❌ 未 merge

**来源：** LangSmith Engine 第二个 PR  
分支：`origin/issues-agent/52581ac4-3381-43f5-bc00-6c119ac7efa3`  
commit：`3570f5e`（**只在远端分支，未进 main**）

**问题：** 重复 search 重复处理同一 URL，浪费 extract/verify，verified 里堆重复 corroboration。

**PR 原方案：**

- 过滤 state 里已有 URL + 同 response 内重复 URL
- Verified dedupe：**normalized claim + URL**
- 抽 `constants.py` 共享 `MAX_SEARCH_CALLS`
- Agent prompt：引导换 source family

**为何没 merge：** 本地按同样思路 **手改了一版**，细节与 PR 不完全相同（见阶段 5）。

---

## 阶段 5：Extract 要事实 + 去重 + Tavily 10 条按需取 — `66d6c4f` ✅ merged（9/20）

**动机：** verify 成功率已经 ~95%+，但 agent 仍常 insufficient；发现 extract 会 **改数字贴 requirement**、重复抽 existence claim、primary batch 经常 0 verified。

### 5.1 Extract prompt：忠实事实，禁止「贴 requirement」

- 只写 source 里有的数字/容量，**禁止**把 25–95 改写成 20–60
- 支持 **contrary evidence**（反证也要抽）
- 禁止 generic marketing / amenity list（除非含 focus 要的硬事实）

**文件：** `src/prompts/system_prompts.py`（`SEARCH_BATCH_EVIDENCE_PROMPT`）

### 5.2 跳过重复

| 类型 | 实现 | 与 PR #2 差异 |
|---|---|---|
| 重复 search result | 同 URL **且** content 相同则 skip | PR 只按 URL |
| 重复 verified claim | 按 **normalized claim** dedupe（跨 URL 同 claim 只留一条） | PR 用 url+claim |

**文件：** `tools.py`, `evidence_verification.py`（`merge_verification_updates`）

### 5.3 Tavily 10 条，按需取用

- `TAVILY_MAX_RESULTS = 10`（一次拉 10 条）
- `MAX_RESULTS_PER_SEARCH = 5`：**primary batch 5 条**进 extract
- 余下最多 5 条进 **reserve batch**
- Primary 有页面但 **0 verified** → 自动对 reserve 再 extract+verify（**fallback**）
- 新增统计：`duplicate_search_result_skips`, `duplicate_claim_skips`, `empty_evidence_tool_calls`, `fallback_extract_attempts`, `fallback_verified_hits`

**文件：** `constants.py`（新建）, `tools.py`, `state.py`, `research_report.py`

### 5.4 Off-target 拦截前移

- **Merged PR** 在 extract **之后**（per evidence item）筛
- **本地版** 在 **document 级别、extract 之前**筛（`document_mentions_company` 在 `_collect_search_batches`）
- 减少无效 extract LLM 调用

**文件：** `tools.py`, `search_evidence_extractor.py`（导出 `document_mentions_company`）

### 5.5 ToolMessage 瘦身

- Agent 只看：`Searches used X/4` + 本 search **新增** verified claims
- 去掉：query 回显、rejected 列表、累计 verified 总数、skip 统计（统计仍进 report）

**文件：** `tools.py`

---

## 阶段 6：search_focus + requirement 维度对齐 — `66d6c4f` ✅ merged（9/20）

**动机：** Sora Resort trace 里 `search_focus` 要 capacity，extract 仍抽「has conference room」类 existence claim。

### 6.1 `web_search(query, search_focus)`（后于阶段 9 改为仅 `search_focus`）

- `query`：给 Tavily 检索
- `search_focus`：给 extract **PRIMARY** 指南（比 query 优先）
- `SearchDocument` schema 增加 `search_focus` 字段

### 6.2 Agent prompt：research focus 工作流（阶段 9 前版本）

- 每次 search 必须传 **query + search_focus**
- 流程：合并 verified → 判 sufficient → 否则选下一 focus → 再搜
- 同一 focus 可以换 query angle；focus 只在当前维度 satisfied 后切换

**文件：** `system_prompts.py`, `tools.py`, `research_schemas.py`, `nodes.py`

### 6.3 Extract 看 prior verified，避免重复抽

- HumanMessage 传入 **already verified claims**
- Prompt：不要 re-extract 已有 claim 或其弱化版

### 6.4 Requirement 维度规则 + 确定性 filter

- Prompt 按 focus 类型分规则（existence / capacity / catering）
- Capacity focus 的 YES/NO 示例写进 prompt
- 代码层 `_claim_addresses_search_focus`：focus 含 capacity 时，drop 纯 existence claim（「has conference room」等）

**文件：** `search_evidence_extractor.py`, `system_prompts.py`

---

## 阶段 7：换模型 — `66d6c4f` ✅ merged（9/20）

**动机：** extract 仍 ignore search_focus，怀疑 nano 跟不上。

**改动：**

- `RESEARCH_LLM_MODEL` 默认 `gpt-5-mini`（agent + extract + verify + fit score）
- `RESEARCH_DERIVATION_LLM_MODEL` 仍 `gpt-5-nano`（excerpt derivation）
- 支持 `.env` 覆盖
- `test.ipynb` 报告文件名读 `RESEARCH_LLM_MODEL`

**文件：** `src/llm/models.py`, `test.ipynb`

**batch 结论（v3/v4）：** nano → mini 对 sufficient 提升不明显；瓶颈在检索与判定，不在 verify IQ。

---

## 阶段 7.1：Agent 输出 sufficient 理由 — `66d6c4f` ✅ merged（9/20）

**动机：** sufficient 时要知道 agent **为什么**认为够评估，便于人工审 quality。

**改动：**

- `ResearchResult` 增加 `reason`；sufficient=true 时必填，false 时留空
- State / report 字段 `sufficient_reason`；HTML **Why Sufficient** 区块
- Agent / final prompt 同步要求

**文件：** `research_schemas.py`, `system_prompts.py`, `nodes.py`, `state.py`, `research_report.py`, `eval_research.py`

---

## 阶段 8：URL Selector 全文抽取 — `local-only`（9/21）

**动机：** Tavily snippet 常缺 capacity / 会议详情；一次 search 拉 10 条，但 extract 只用 5 条，希望 **智能选 1–2 页拉全文**。

**改动：**

1. **流程：** 去重 + off-target 后 → 对全部 eligible 结果跑 **URL Selector LLM** → 选 1–2 URL → **Tavily Extract** → 替换 `document.content`，`full_page=True`
2. **优先级 prompt：** 官网 meeting/events、PDF/MICE 目录、Cvent/Northstar、OTA 等（5→1）
3. **选中 URL 优先进 primary batch**（排在 primary 5 条前面）
4. **去重升级：** 已 `full_page` 的 URL → **仅按 URL 去重**（不再要求 content 相同）
5. **统计：** `url_selector_extract_attempts`, `url_selector_full_page_extracts`, `url_selector_extract_failures`

**文件：** `services/url_selector.py`, `tools.py`, `system_prompts.py`（`URL_SELECTOR_SYSTEM_PROMPT`）, `research_schemas.py`, `llm/models.py`, `constants.py`, `state.py`, `nodes.py`, `research_report.py`

**v5 量化：** 71 次 full-page extract；fallback verified hits 从 v3 的 2 次 → **0**；sufficient +3.3 pp。

---

## 阶段 9：Planner / Executor 拆分 — `research_search` + Query Generator — `local-only`（9/21）

**动机：** agent 同时写 query + focus 负担大；query 应是检索工程，focus 才是 planning。

**改动：**

1. **工具改名：** `web_search` → **`research_search`**，只收 **`search_focus`**
2. **Agent（Planner）：** 只看 verified → 判 sufficient / 选下一 **search_focus** → 调 `research_search`；**不再写 query**
3. **Query Generator LLM（tool 内）：** 输入 company、requirement、search_focus、已有 verified claims、**本 run 已用 queries**、**已见 source URLs**（供 LLM 推断 `site:官网`）→ 输出 Tavily query
4. **State：** `search_queries_used` 累计本 run 生成过的 query
5. **Middleware：** `control_web_search` → `control_research_search`

**文件：** `services/query_generator.py`, `tools.py`, `system_prompts.py`（`RESEARCH_AGENT_*`, `QUERY_GENERATOR_*`）, `nodes.py`, `state.py`, `research_schemas.py`（`QueryGeneratorResult`）, `llm/models.py`

**说明：** prior URLs → `site:` **无确定性解析**，仅把 URL 列表交给 Query Generator prompt。

---

## 阶段 10：Verify 复用已全文页面 — `local-only`（9/21）

**动机：** URL Selector 已拉全文的 URL，在 verify 的 `unclear_ownership` 路径不应再调 Tavily Extract。

**改动：**

- `verify_evidence_item`：`document.full_page=True` 时，ownership retry **直接复用** `document.content`
- 仅非 full_page 才 `extract_page_content()` 并计入 `evidence_full_page_extracts`

**文件：** `evidence_verification.py`

---

## Batch 测试记录（30 家 Bangkok 酒店）

Requirement（固定）：
> 20–60 人 private meeting/event space + group catering/banquet

| 报告 | 模型 | Sufficient | Verify 成功率 | Evidence | Avg searches | 备注 |
|---|---|---:|---:|---:|---:|---|
| v3（nano） | gpt-5-nano | **36.7%** | 97.0% | 100 | 3.3 | 阶段 5–6 本地改动 |
| v4（mini） | gpt-5-mini | **33.3%** | 95.1% | 122 | 3.5 | 阶段 7；evidence 更多但 sufficient 未升 |
| **v5（mini）** | gpt-5-mini | **40.0%** | 100.0% | 78 | 3.5 | 阶段 8–10；`model_gpt-5-mini_research_report_v5.html`（2026-09-21） |

> **注：** 阶段 10 改完后跑 **test v5**（2026-09-21 20:58 UTC）。

### v5 vs v3 对比（同 30 家 Bangkok 酒店）

| 指标 | v3（nano） | v5（mini + 8–10） | 变化 |
|---|---:|---:|---|
| Sufficient rate | 36.7% | **40.0%** | **+3.3 pp**（11/30 → 12/30） |
| Verify 成功率 | 97.0% | **100.0%** | +3 pp（78/78，零失败） |
| Evidence total | 100 | 78 | −22（更精、少噪音） |
| Avg searches | 3.3 | 3.5 | +0.2 |
| Empty primary batch | 0.87 / search | **0.57 / search** | ↓ 34% |
| Fallback 尝试 | 0.87 / search | **0.57 / search** | ↓ 34% |
| Fallback verified hits | 2（0.07 / 公司） | **0** | reserve 路径基本被 URL Selector 取代 |
| Off-target rejections | 12.57 / 公司 | 20.97 / 公司 | ↑（更多页被扫 + 全文替换后 filter 更严） |
| URL selector full-page | — | **71 次**（2.70 attempts / 公司） | 新能力 |
| Full-page extract（evidence） | 4 | 1 | verify 复用 selector 全文，少重复 Extract |

**解读：** sufficient 从 36.7% → 40% 是本轮最直观收益；verify 100% 说明 evidence 质量更干净。URL Selector 每家公司平均拉 ~2.4 页全文（71/30），primary batch 空跑和 fallback 依赖都明显下降——信息在 **search 阶段** 就进了 pipeline，而不是靠 reserve 碰运气。Evidence 总数下降但 sufficient 上升，符合「少而准」方向。

**v3/v4 遗留现象（v5 部分缓解）：**

- Off-target 仍高（v5 更高，因扫描面扩大）
- Fallback 命中率问题 → v5 几乎不再靠 fallback 产出 verified
- **结论更新：** URL Selector + Query Generator 对 **信息可得性** 有效；下一步可看 sufficient 子集 claim 质量、以及 off-target 是否需调 filter 阈值

---

## 进行中 / 未 commit（截至 2026-09-21）

**已 push（`66d6c4f`）：** 阶段 5–7 + sufficient `reason`

**本地未 push（阶段 8–10）：**

```
src/components/constants.py
src/components/tools.py
src/components/evidence_verification.py
src/components/nodes.py
src/components/state.py
src/llm/models.py
src/prompts/system_prompts.py
src/reporting/research_report.py
src/schemas/research_schemas.py
src/services/query_generator.py    (new)
src/services/url_selector.py         (new)
```

---

## 已知问题 & 待做（讨论过、未实现）

1. **Deterministic sufficiency** — requirement 拆 checklist，用 verified claims 规则匹配，不让 agent 主观拍板
2. **Query Generator 域名启发式** — prior URLs 目前纯 LLM 推断 `site:`，可加规则
3. **Selector 用 search `raw_content`** — 对比 Tavily Extract，省 API / 降延迟（讨论过，未改）
4. **Engine PR #2** — 未 merge；本地 dedupe 逻辑已覆盖部分意图，但未 1:1 对齐 PR
5. **Sufficient 子集分析** — 不只看 overall rate，看 sufficient runs 的 tool calls 与 claim 质量

---

## Commit / PR 速查

| ID | 说明 | 状态 |
|---|---|---|
| `8184e20` | 初始 LangGraph + batch report | merged |
| `870ebf1` | 多阶段 verify + full-page retry | merged |
| `fcca950` | 按 batch extract + result_id 纠偏 | merged |
| `6a2d78d` | Verify 内嵌 web_search；4 次 search 预算 | merged |
| `6497eea` | Off-target company filter（Engine PR #1） | merged |
| `b4f48c5` | Eval script + insufficient runs 报告 | merged |
| `3570f5e` | Skip duplicate sources（Engine PR #2） | **未 merge** |
| `66d6c4f` | search_focus、Tavily 10、fallback、fact extract、mini、 sufficient reason | merged |
| 本地 | URL Selector、research_search + Query Generator、verify 全文复用 | **未 commit** |

---

## 更新约定

每次跑 batch 后在此文档 **Batch 测试记录** 加一行，并在对应阶段补：

1. 改了什么（一句话）
2. 主要文件
3. 报告路径（如 `reports/30_companies/model_gpt-5-mini_research_report_v5.html`）
4. 关键指标变化
