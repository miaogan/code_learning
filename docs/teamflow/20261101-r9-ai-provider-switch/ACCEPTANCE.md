# 验收报告 · r9 AI 供应商可切换（本地 LM Studio ⇄ 云端 DeepSeek）

> 验收人：产品经理（验收负责人）· 分支 `feat/dev-skill-coach`（原地，未提交）· 契约＝`TECH-CHANGE.md`（tech-driven rework，无功能 PRD）· r8 的 20 条 AC 继续有效。
> 验收方式：**独立复跑 QA 留下的检查器与自己补的探针**（不复用 QA 的结论文字，只对标它给出的命令与期望）。

## 1 独立复跑证据（本人本轮实跑，非引用 QA 报告）

| # | 命令 | 实测结果 |
|---|---|---|
| A1 | `cd backend && AI_PROVIDER= python -m pytest -p no:cacheprovider` | **348 passed, 1 skipped / 39.07s**，exit 0 |
| A2 | 同命令 `AI_PROVIDER=lmstudio AI_LMSTUDIO_MODEL=qwen3.5-9b` / `AI_PROVIDER=deepseek` | 均 **348 passed, 1 skipped**（33.48s / 33.61s）→ 宿主 `.env` 不再左右用例 |
| A3 | `pytest tests/test_engineering_gates.py` / `-k r9` | **30 passed** / **4 passed**（r9 四条门禁齐备） |
| A4 | `pytest tests/test_ai_provider.py tests/test_health.py` | **21 passed, 1 skipped**（skip＝`AI_LIVE` 门控，零网络） |
| A5 | `check_t1_config_resolution.py` / `check_t2_ai_transport.py` / `check_t3_health_live.py` / `check_t6_env_example.py` | `ALL PASS`（54 断言）/ `13 passed, 0 failed` / `ALL PASS` / `ALL CHECKS PASSED` |
| A6 | `check_r9_json_mode_matrix.py` / `check_r9_provider_live.py --provider all` / `check_qa_r9_interface.py` | `PASS 9/9` / `PASS 71/71` / `PASS 12/12` |
| A7 | `check_r9_gate_sensitivity.py`（11 条反向注入，跑在临时副本树） | `PASS：11 条注入全部被对应门禁拦下` → 门禁非空壳 |
| A8 | 真 uvicorn：`/health`（交付 `.env` legacy） | **200** `ai_provider=legacy / ai_model=deepseek-chat / ai_json_mode=json_object`，15ms |
| A9 | 真 uvicorn：`AI_PROVIDER=lmstudio`（8401）/ `=deepseek`（8402）/ `=bogus`（8403） | 200 `{lmstudio, qwen3.5-9b, none}` / 200 `{deepseek, deepseek-chat, json_object}` / **200** `{bogus, "", json_object, ai_configured=false}`（配置错只降级不 500） |
| A10 | 真实本地链路 `check_qa_r9_switch_live.py --provider lmstudio`（**不覆盖任何 timeout env，用交付默认**） | **200，244.57s**，`skills=6 projects=3 tech_stack=6`，**溯源 18/18 逐字命中**，`RESULT: PASS (16 passed, 0 failed)` |
| A11 | 真实云端链路 `--provider deepseek`（`AI_PROVIDER=deepseek` 显式） | **200，2.31s**，`target_role='前端开发工程师'`，**溯源 18/18**，`PASS 17/17` |
| A12 | 真实 legacy 链路 `--provider legacy` | `PASS 17/17`，2.9s，溯源 18/18（切换不改变旧路径） |
| A13 | 前端 `npm run typecheck` / `npm run lint` / `npx vitest run` / `npm run build` | 0 error / **0 error · 28 warning**（＝基线）/ **109 passed（8 文件）** / build OK `dist 267.81 kB` |
| A14 | 依赖与密钥面 | `git diff` 无 `pyproject/requirements/package.json` 改动（**零新依赖**）；`grep sk-…` → 仅 `.env.example` 的空占位 `AI_*_API_KEY=`，**零 Key 泄露**；`.env`/`db`/`node_modules`/`dist` 全被 gitignore |

## 2 逐条对照验收判据

| 判据 | 来源 | 结论 | 证据 |
|---|---|---|---|
| R1 单一解析出口 `Settings.resolve_ai() -> AiRuntime`，永不 raise，配置错＝`ready=False`+中文 reason | 蓝图 T1 / TECH-CHANGE §3.1 | ✅ | `config.py:166-246`；A5（未知 provider / 缺 `AI_LMSTUDIO_MODEL` / 闭集外 json_mode 三种均中文 503、`/health` 仍 200） |
| R2 具名档 base_url/model/key **不回落全局**（防云端 Key 发往本地） | §3.1 硬规则 / F2 | ✅ | `config.py:187`；A5 实证（全局 Key 存在时 deepseek 档读到空 Key）；A10 本地档 `api_key=空` 仍 200 |
| R3 `ai_configured` 降级为 `resolve_ai().ready` 唯一委托，无第二处判 key | 蓝图风险项 | ✅ | `config.py:243-246`；`grep "ready"` 仅 config/main/ai 三处 |
| R4 传输层只认 `AiRuntime`，不读裸配置字段 | 蓝图 T2 | ✅ | `services/ai.py` 构造即快照；`grep -rnE "settings\.ai_\|get_settings\(\)\.ai_" app/ \| grep -v config.py` → **NONE** |
| R5 `json_mode` 三档：`json_object` 发键 / `none` 整键不发 / 闭集外零出网 | §3.2 / F1 | ✅ | `ai.py:25` 投影表；A6 矩阵 9/9；闭集只在 `config.JSON_MODES`（源码 `json_object` 字面量仅 config.py 缺省 + ai.py 投影表键） |
| R6 空 key 省略 `Authorization`，超时优先级「调用点 > 档内 > 全局」 | §3.2 / F3 | ✅ | `ai.py:99-104`；A5 T2 用例；`SCORING_TIMEOUT_S=14` 未动 |
| R7 探活 live 读取（去 import 期闭包）+ 三字段白名单 + `types.ts` 逐字镜像 | 蓝图 T3 | ✅ | `main.py:93-104`；A8/A9 三档 200；A6 契约镜像 12/12；`schemas.py`/`types.ts` 纯新增 |
| R8 测试环境中性化单出口，任何宿主 `.env` 下确定 | 蓝图 T4 | ✅ | `conftest.py:194-223`（`neutral_ai_env` → `tmp_db` → `client`）；A1/A2 三环境同 348/1 |
| R9 门禁只增不减且真能变红 | 蓝图 T5 | ✅ | A3（30/4）；A7（11/11 注入被拦，含 2 条超时互锁、示例带 key、`sk-` 残留） |
| R10 `.env.example` 覆盖全部档位键、无密钥、默认值与字段互锁 | 蓝图 T6 | ✅ | A5 `check_t6`（17 个 `ai_*` 覆盖、3 个 Key 全空、示例 timeout == 字段默认值且 ≥300s） |
| R11 本地档真实跑通（先本地后云端），并附 `/health`、状态、耗时 | §5 验收第 1-3 条 | ✅ | A10（244.57s/200/溯源 18/18）+ A11（2.31s/200）+ A8/A9 |
| R12 云端/legacy 零回退（请求体、错误码、超时、重试、提示词逐字不变） | §4 零变化保证 | ✅ | A11/A12 均 17/17、溯源 18/18；`git diff` 未触任何业务 service 提示词与响应模型 |
| R13 零 DDL / 零迁移 / 零新依赖 / 不改提示词 / 不改业务 routers 与前端页面 | §2 明确不改 | ✅ | A14；`git status` 13 文件（12 改 + 1 新增测试），无 `db.py`/`repository.py`/routers/页面改动 |
| R14 r8 的 20 条 AC 保持关闭 | 基线 | ✅ | `schemas.py`/`types.ts` 纯新增；`test_profile_null_contract.py` 仅 +24 行（新增 `target_role` 口径用例，无删改）；A1 全量含 r8 契约用例全绿 |
| R15 报告如实（含缺陷与取代口径，不伪造通过） | §5 第 3 条 | ✅ | FIX-NOTE 首部「取代 §5-1 timeout=180」；QA-REPORT §3 逐条复验；本轮 A10 复现「本地档 `target_role` 为 null」为 OBS 观察项而非静默放过 |

## 3 架构一致性（M3，强制项）

- **蓝图符合**：`config.resolve_ai → AiRuntime` 单出口、`ai.py` 唯一出网口、`main.health` 只透传、`schemas`↔`types.ts` 镜像、`conftest` 单 fixture、`test_engineering_gates.py` **就地扩展**（未新建门禁文件）——8 个蓝图任务全部落地，装配顺序 `config → ai / main → schemas` 无反向依赖。
- **无重复实现 / 无适配器漂移**：`resolve_ai` 全仓 1 处实现；供应商字面量仅 `config.py`；`json_object` 仅 config 缺省 + ai 投影表（键集由门禁与闭集互锁）；新增供应商仍是「5 字段 + 1 行 `_PROFILE_FIELDS`」。
- **该抽的都抽了**：`ai_configured` 委托 `ready`、`neutral_ai_env` 收敛两处散落、超时合并在 `resolve_ai` 唯一处；`_NUMERIC_ENV_FIELDS` 校验器是蓝图提示的「空串炸构造期」风险的落地修复（超集但不越界）。
- **结论**：无「偏离蓝图 / 重复实现 / 该抽未抽」，无需架构返工。

## 4 意见与遗留（均不阻断验收）

1. **P3 · 文档精度**：`TECH-CHANGE.md §5-1` 仍写 `timeout=180`，交付为 **600s**。任务夹建后不可变，dev 以 `FIX-NOTE.md` 首部「**取代**」声明，符合本产品「历史文档不回改、以书面取代」的既有约定；实测 180s 确会把本地档掐成 503（FIX-NOTE §1），600s 且有「示例值 == 字段默认值、≥300s」门禁互锁。**接受，不改**。
2. **P3 · 白名单表漏列**：`TECH-CHANGE.md §2` 的改动面表未列 `test_engineering_gates.py`/`test_resume_hints.py`/`test_profile_null_contract.py`，但三者均在架构蓝图的模块清单内（T4/T5 + D-2 口径用例），**不是越界**，只是表精度问题。
3. **P3 · 本地小模型产出**：`qwen3.5-9b` 原生把 `target_role` 判为 `null`（模型原始 JSON 即 null，非解析/落库丢值），已按 QA D-2 第二条判据落为「本地档观察项」+ 下游默认值用例固定。若要抬高本地档产出质量（改提示词）属新产品决策，**另开需求**，不在 r9 改动面内。
4. **P3 · `/health` 未知 provider 时 `ai_model` 为空串**：契约类型为 `str`、无 Key 泄露、前端不渲染，可接受；若日后要在运维面板展示，可考虑给「未识别」占位文案（本轮不做）。
5. **环境限制（非交付缺陷）**：`python -m ruff` → `No module named ruff`（本轮同样未装，按策略不重试）；浏览器不可启动，r9 无 UI 改动，视觉项由 typecheck/vitest/build 覆盖。
6. **人工补测（机器相关）**：交付默认 600s 对应本机实测 244.57s（≈2.5 倍余量）；换更慢的机器/模型时应重跑 `--provider lmstudio` 读 `[S4]` 耗时；长等待（~4 分钟）期间前端「无响应」观感建议真机手动确认一次。

## 5 验收判定

r9 的 15 条验收判据全部满足；r8 的 20 条 AC 保持关闭；架构与蓝图一致、无重复实现与结构性破坏；三档 `/health` 真实 200、本地/云端两条真实画像链路各自 200 且溯源 18/18；门禁 348+30、前端 109、build、零新依赖、零 Key 泄露。round-1 的 D-1/D-2/D-3 已关闭，本轮独立复跑未发现新缺陷。**准予验收。**

验收结论：✅ 通过
