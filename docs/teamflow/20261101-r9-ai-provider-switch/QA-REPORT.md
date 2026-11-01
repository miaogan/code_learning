# QA 复验报告 · r9 AI 供应商可切换（本地 LM Studio ⇄ 云端 DeepSeek）

- 轮次：**修复后复验轮**（round 2）。上一轮 QA 报出 D-1 P1 / D-2 P2 / D-3 P3，dev 修复轮已交付 `FIX-NOTE.md`。
- 需求类型：tech-driven rework（无功能 PRD），契约＝`docs/teamflow/20261101-r9-ai-provider-switch/TECH-CHANGE.md`，r8 的 20 条 AC 继续有效。
- 分支 `feat/dev-skill-coach`（原地，未提交）；QA 只改自己的检查器，未改任何产品源码（本轮唯一改动＝`check_qa_r9_switch_live.py` 的 D-2 观察项 + `check_t1_config_resolution.py` 新增 3 条探针，均在 `logs/teamflow/tf-mvxni5sd-xruqfw/scripts/`）。

## 0 结论

**可以验收**：round-1 的 3 条缺陷全部关闭，本轮未发现新缺陷（P0/P1/P2/P3 均为 0）。

- **D-1（P1）已关闭**：交付默认 `AI_LMSTUDIO_TIMEOUT_S` 由 180s 抬到 **600s**（`config.py` 字段默认 + `.env.example` + 门禁互锁三处同步）。用**上一轮原文检测命令**（不覆盖任何 timeout env，即用交付默认）复跑：`RESULT: PASS (16 passed, 0 failed)`，`POST /api/resumes/{id}/profile → 200`、**232.53s**（上一轮 180s 被截断的同一链路）。
- **D-2（P2）已关闭（按该行允许的口径）**：上一轮的通过判据写了两条分支——「`target_role` 有值」或「产品判定本地小模型允许 null ⇒ 断言降级为观察项 + 任务夹书面记录 + 下游默认值有测试覆盖」。dev 取第二条并留下三项证据，本 QA 已按判据执行：`FIX-NOTE.md §2` 书面口径、`test_target_role_null_is_accepted_and_downstream_defaults_hold` 钉住下游出口、检查器仅对 **lmstudio 档**把该断言降级为 `OBS`（云端/legacy 仍严格）。
- **D-3（P3）已关闭**：`.env.example:11` 增加「provider 取值必须【小写】且逐字」。
- 其余全部通过：pytest **348 passed / 1 skipped × 三种 AI 环境**、门禁 **30**（r9 4 条）、门禁反向注入 **11/11** 拦下、真实三档 `/health` 200、legacy/deepseek 真实画像链 **17/0 · 2.7s · 溯源 18/18**、前端 typecheck 0 error / lint 0 error·28 warn / vitest 109 / build OK、零 Key 泄露、git 卫生 OK、架构与接口一致性符合蓝图。

## 1 范围与环境

- 被测面：`backend/app/config.py`（`resolve_ai` 单出口）、`services/ai.py`（唯一出网口）、`main.py`+`schemas.py`（`/health` 存活契约）、`frontend/src/api/types.ts`（契约镜像）、`tests/conftest.py`（环境中性化）、`tests/test_engineering_gates.py`（4 条 r9 门禁）、`tests/test_ai_provider.py`（新增）、`.env.example`。
- 环境：Windows + Python 3.13；`backend/.env` 为 legacy 全局（`AI_BASE_URL=api.deepseek.com/v1`、Key 已配置、`deepseek-chat`）；**本机 LM Studio 真实在线**（`localhost:1234`，`qwen3.5-9b`）；Node/npm 可用。
- 本轮所有「本地档」证据＝**真实模型实跑**（上一轮 D-2 的真机取证脚本亦复跑确认：模型**原始 JSON** 就是 `"target_role": null`，解析层零改写）。

## 2 回归契约：上一轮留在 `scripts/` 的检查器全量复跑

| 检查器 | 本轮结果（verbatim） | 备注 |
|---|---|---|
| `check_t1_config_resolution.py` | `ALL PASS`（54 条 ok / 0 FAIL） | 51 原有 + 本轮新增 3 条（见 §6） |
| `check_t2_ai_transport.py` | `== T2 ai transport: 13 passed, 0 failed ==` | 含 none 档重试提示、双重短路 |
| `check_t3_health_live.py` | `[T3] ALL PASS` | 同一 app 实例上 live 切档证据 |
| `check_t6_env_example.py` | `ALL CHECKS PASSED` | 17 个 `ai_*` 字段覆盖、3 个 Key 全空、示例 timeout=600 已生效 |
| `check_r9_json_mode_matrix.py` | `RESULT: PASS (9/9 断言通过)` | json_object 发键 / none 整键不发 / 闭集外零出网 503 |
| `check_r9_provider_live.py` | `RESULT: PASS (71/71 断言通过)` | 离线 provider 矩阵 + 响应体键集 |
| `check_qa_r9_interface.py` | `RESULT: PASS (12 passed, 0 failed)` | 契约镜像 + 投影表键集 == 闭集 |
| `check_r9_gate_sensitivity.py` | `PASS：11 条注入全部被对应门禁拦下` | 含新增 2 条超时互锁注入；在临时副本树上跑，工作区未改动 |
| `check_r9_local_target_role.py` | `RESULT: PASS (samples=1, failures=0)` | 原始 JSON `target_role: null`，`ProfileDraft.target_role = None` |
| `check_qa_r9_switch_live.py --provider legacy` | `RESULT: PASS (17 passed, 0 failed)  total=2.7s` | 溯源 18/18，**target_role 严格断言仍生效** |
| `check_qa_r9_switch_live.py --provider deepseek` | `RESULT: PASS (17 passed, 0 failed)  total=2.7s` | 同上（云端档未被降级波及） |

## 3 D-1 / D-2 / D-3 逐条复验（按上一轮原文命令执行，未替换等价物）

| 编号 | round-1 级 | 本轮结论 | 复验证据 |
|---|---|---|---|
| D-1 | P1 | **已关闭** | 原文命令 `cd backend && AI_PROVIDER=lmstudio AI_LMSTUDIO_MODEL=qwen3.5-9b AI_LMSTUDIO_API_KEY= QA_MAX_ATTEMPTS=1 python -X utf8 ../logs/teamflow/tf-mvxni5sd-xruqfw/scripts/check_qa_r9_switch_live.py --provider lmstudio` → exit 0，`RESULT: PASS (16 passed, 0 failed)  total=233.0s`，`[S4] POST /api/resumes/{id}/profile → 200  232.53s`，`skills=6 projects=3 tech_stack=6`、`溯源 18/18` |
| D-2 | P2 | **已关闭（按该行第二条判据）** | 原文命令（带 `AI_LMSTUDIO_TIMEOUT_S=600`）→ exit 0，`RESULT: PASS (16 passed, 0 failed)  total=180.7s`，`OBS target_role 有值（本地档观察项，非判定项）`；口径见 `FIX-NOTE.md §2`；钉住用例 `pytest tests/test_profile_null_contract.py::test_target_role_null_is_accepted_and_downstream_defaults_hold` 通过 |
| D-3 | P3 | **已关闭** | `.env.example:11`「provider 取值必须【小写】且逐字：deepseek / lmstudio（写 LMStudio 会被判未识别 → 请求侧 503）」 |

**类级扫描一致性**（与 dev 修复摘要对账，须一致，不一致本身即缺陷）

| 扫描 | dev 声称 | QA 实测 | 结论 |
|---|---|---|---|
| `grep -rn "\b180\b" backend/app backend/tests backend/.env.example` | 11 处 → 0 处 | **ZERO_180**（0 处） | 一致 |
| 门禁反向注入条数 | 9 → 11 条全拦 | **11/11 拦下** | 一致 |
| 回归地板 | 348 passed / 1 skipped | **348 passed / 1 skipped**（三环境同） | 一致 |

## 4 缺陷表（仅列本轮仍未关闭者）

**未发现缺陷**（P0/P1/P2/P3 均 0；round-1 的 D-1/D-2/D-3 已按 §3 关闭）。

> 非缺陷说明（可追溯性观察，无需修复）：`TECH-CHANGE.md §5-1` 正文仍写 `timeout=180`，实际交付 600；任务夹创建后不可变，dev 以 `FIX-NOTE.md` 首部「**取代**」显式声明——符合本产品「历史文档不回改、以书面取代」的既有约定。

## 5 架构核验（M3）与接口一致性（0a）

**蓝图符合（本轮重新实测）**
- 单一解析出口：`Settings.resolve_ai() -> AiRuntime`（9 字段，`api_key` 带 `repr=False`），永不 raise，配置错＝`ready=False` + 中文 reason（未知 provider / 缺 `AI_LMSTUDIO_MODEL` / 闭集外 `json_mode` 三种仍为中文 503，`/health` 仍 200）。
- 无重复实现：`grep -rnE "settings\.ai_|get_settings\(\)\.ai_" app/ | grep -v config.py` → **NONE**；`grep -rn "json_object" app/` 源码命中仅 `config.py` 与 `services/ai.py`（其余为 `__pycache__` 二进制，非源码）；`grep` provider 字面量（`"lmstudio"`/`"deepseek"`）在 `config.py` 外 → **NONE**。
- 无「该抽未抽」：档位遍历只有一张 `_PROFILE_FIELDS`，`resolve_ai` 只有一处实现（`app/config.py:166`），新增供应商＝5 字段 + 1 行仍成立；`AI_PROVIDER_NAMES == tuple(_PROFILE_FIELDS)` 实测 True。
- 就绪语义单源：`.ready` 全仓仅 `config.py`（property 委托）、`main.py`（透传）、`ai.py`（双重短路）三处，无第二处判 key 逻辑。
- 探活去闭包：`health()` 请求内 `get_settings().resolve_ai()`；真实 uvicorn 三档 `/health` 全 200（§7）。
- 依赖方向 `config → ai/main → schemas`：`ai.py` 只 import `AiRuntime/Settings/get_settings`；`main.py` 只透传字段，不拼文案。

**接口一致性（静态可复跑，0a）**：`check_qa_r9_interface.py` 12/12；另手工核对本轮修复触达的调用：`role_fit.resolve_target_role(*, interview_settings, profile)` 为 keyword-only，`test_profile_null_contract.py:383` 的调用形状与之逐字匹配；`interview._role_text(str | None)` 存在；`main.py` 构造 `HealthResponse` 的 7 个关键字与 `schemas.py` 7 字段一一对应、无遗漏。

## 6 本轮新增探针（上一轮未覆盖的面）

| 新增面 | 为什么上一轮漏了 | 探针 | 结果 |
|---|---|---|---|
| 数值型档位 env 写成空串（`AI_LMSTUDIO_TIMEOUT_S=`） | D-1 修复恰好改的是数值默认值，上一轮只验证了「值够不够大」，从未验证「运维清空该行」的回落路径（`config.py` 的 `model_validator` 兜底是蓝图外的超集） | `check_t1_config_resolution.py` 新增 `case_blank_numeric_env()`（3 条断言） | `ok 空串 timeout 不打挂解析`、`ok 空串 -> 回落字段默认 600（不是全局 20）`、`ok 显式 0 仍表示继承全局 20` |
| D-2 降级是否误伤云端档 | 上一轮判据没有要求「降级后云端仍严格」 | 同一检查器 legacy / deepseek 两条真链路复跑 | 两档均 `17 passed / 0 failed`，且 `ok target_role 有值` 仍为**判定项** |
| 降级是否会掩盖其它失败 | — | 反向证据：round-1 用 180s 跑同一脚本时，失败点是 `画像生成 200`（不是被降级的那条） | 降级未削弱主判定 |

## 7 真实探活与主路径证据

| 项 | 命令 | 结果 |
|---|---|---|
| `/health` legacy | uvicorn:8166 + `curl -sS /health` | 200 `{"status":"ok","version":"0.1.0","ai_configured":true,"db":"sqlite","ai_provider":"legacy","ai_model":"deepseek-chat","ai_json_mode":"json_object"}` |
| `/health` lmstudio | uvicorn:8226 | 200 `{...,"ai_provider":"lmstudio","ai_model":"qwen3.5-9b","ai_json_mode":"none"}` |
| `/health` deepseek | uvicorn:8204 | 200 `{...,"ai_provider":"deepseek","ai_model":"deepseek-chat","ai_json_mode":"json_object"}` |
| 本地档主路径 | §3 D-1 命令 | 上传 200（0.01s）→ 画像 200（232.53s）→ 溯源 18/18 |
| 云端/legacy 主路径 | §3 两档 | 画像 200 / 2.7s / 溯源 18/18 / target_role=前端开发工程师 |

## 8 用例与执行结果（门禁地板）

| 编号 | 检查 | 命令（`backend/` 或 `frontend/`） | 结果 |
|---|---|---|---|
| C-1 | 后端全量（未设 `AI_PROVIDER`） | `python -m pytest -p no:cacheprovider --tb=no` | **348 passed, 1 skipped**（33.35s，exit 0） |
| C-2 | 环境确定性 | `AI_PROVIDER=lmstudio` / `AI_PROVIDER=deepseek` 各一次 | 均 **348 passed, 1 skipped**（33.5s / 33.7s，exit 0） |
| C-3 | 工程门禁 | `python -m pytest tests/test_engineering_gates.py` | **30 passed**；`-k r9` **4 passed** |
| C-4 | r9 用例集 | `pytest tests/test_ai_provider.py tests/test_health.py` | **21 passed, 1 skipped**（skip＝`AI_LIVE` 门控） |
| C-5 | 前端 typecheck / lint | `npm run typecheck` / `npm run lint` | 0 error；lint **0 error / 28 warnings**（=基线，未增） |
| C-6 | 前端单测 / 构建 | `npx vitest run` / `npm run build` | **109 passed（8 文件）**；build OK（`dist 267.81 kB`） |
| C-7 | 零 Key 泄露 | `grep -riE "sk-\|api_key\|AI_API_KEY" frontend/dist/ frontend/src/` | `NO_KEY_LEAK` |
| C-8 | 版本控制卫生 | `git status --porcelain=v1 -uall` + `git check-ignore -v` | 12 M + 1 新增测试 + 5 任务夹文件；`.env`/`tests/.tmp/`/`node_modules/`/`dist/`/`__pycache__/`/`logs/teamflow/` 全部命中 `.gitignore`，无依赖/构建产物/密钥入库 |
| C-9 | ruff | `python -m ruff check app tests` | **未执行（环境限制）**：`No module named ruff`，按策略不重试（历史轮次同因） |

## 9 人工补测清单（环境/机器相关，非交付缺陷）

| 项 | 验收判据 | 方法 / 工具 |
|---|---|---|
| 其它机器/模型的超时标定 | 交付默认 600s ≥ 该机实测 ×1.5（本机实测 180–233s） | 目标机跑 `check_qa_r9_switch_live.py --provider lmstudio`，读 `[S4]` 耗时 |
| 本地小模型 `target_role` 非空率 | 与产品确认可接受口径 | 同一简历重复 3 次画像，统计非空率（本轮确认现象为模型原生产出 null） |
| 长等待期的用户观感 | 232s 等待期间前端不出现「无响应」误解 | 真实浏览器手动跑一次本地档画像（本沙箱不可启动浏览器） |
| `/health` 三字段前端不渲染 | 页面任何位置不出现 provider/model/json_mode | 浏览器人工逐屏检查（r9 无 UI 改动，`types.ts` 仅可选类型） |

## 10 环境限制

- `python -m ruff check app tests` → `No module named ruff`（环境限制，未重试）。等价替代：`py_compile` 全量通过、pytest 348 例、前端 lint 0 error。
- 浏览器不可启动（宿主沙箱限制），r9 无 UI 渲染改动，DOM/构建级证据已覆盖（typecheck/vitest/build），视觉项已列入 §9。
- 真实 LM Studio 的 `qwen3.5-9b` 为 reasoning 模型，单次画像耗时波动 180–233s（本轮实测两次：232.53s / 180.27s），D-1 的 600s 默认对应 2.6–3.3 倍余量。

## 11 交付面与边界

- 改动树 13 个文件：12 改（`config.py`、`services/ai.py`、`schemas.py`、`main.py`、`conftest.py`、`test_health.py`、`test_resume_hints.py`、`test_engineering_gates.py`、`test_profile_null_contract.py`、`.env.example`、`types.ts`、`memory.md`）+ 1 新增（`tests/test_ai_provider.py`）。与 `TECH-CHANGE.md §2` 白名单一致，**零新依赖**（`httpx` 既有）；修复轮只多改 `test_profile_null_contract.py`（D-2 口径用例）。
- 文档边界：本报告只在 `docs/teamflow/20261101-r9-ai-provider-switch/`；检查器与证据在 `logs/teamflow/tf-mvxni5sd-xruqfw/scripts/`，项目根零散落。
