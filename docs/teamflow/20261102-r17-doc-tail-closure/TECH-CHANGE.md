# r17 · A 组文档回写收口（技术变更单）

> 本轮以**文档回写**为主：架构文档尾巴收干净、r11 三条验收收口落到产品级文档；仅两处代码侧最小对齐
> （`exam_selector.py` 模块 docstring 表述、`practice.ts` 方向闭集单一来源），**零行为改动、零契约改动**。

## 1 背景

三个产品级遗留全部指向「文档与实现不同步」，代码本身正确：

- **通用 · 架构文档尾巴**（`memory.md` 第 37 行）：`§7.2` 表格里的 r5 行、`§8` 交接段仍写「待落地 / 进行中」、
  `§8` 末尾重复了一条「统一约束」。
- **r8-②**（`memory.md` 第 41 行）：r5 `TECHNICAL.md:186,302` 记 `is_follow_up_allowed` 3 参旧签名
  （实现已 4 参），历史夹不可改，须由后续需求在架构文档补记。
- **r11 三条验收收口**（`memory.md` 第 42 行，判定「⚠️ 有条件通过」）：
  ① `QA-REPORT` 缺「练习 vs 笔试共用同一题库」说明段；② `exam_selector.py` docstring 与实现对不齐
  （「每种可用客观题型 ≥1」实为取题策略而非结构闸门校验项），且该步骤与 `PromptBody.tsx` 未记进技术方案；
  ③ `frontend/src/lib/practice.ts` 的 `directionChips()` 四个方向字面量应改由单一常量/类型派生或补门禁。

约束：任务夹 `docs/teamflow/<yyyyMMdd-rN-slug>/` **建后不可变**（`memory.md` 说明段），
r5 / r11 夹不得回改；历史文档错误只在产品级文档补记（先例：r16 的 `ARCHITECTURE.md` §3.4.2「历史笔误更正」）。

## 2 改动面

| 文件 | 改动 | 说明 |
| --- | --- | --- |
| `docs/teamflow/architecture/ARCHITECTURE.md` | §3.1 增两行 | `src/lib/practice.ts`（方向 chip 由 `DIRECTION_LABEL` 派生 + `satisfies` 门禁）、`src/components/exam/PromptBody.tsx`（题面围栏唯一出口） |
| 同上 | 新增 §3.4.3 | 「题库共享口径（练习 vs 笔试）」七层表 + 理由，关闭 r11 C-1 |
| 同上 | §7.1 增三行 + 更正一处 | 补 r5 面试对话流、`exam_selector` 组卷选池、r10 容器化交付；后端测试文件数 13 → 31（实测） |
| 同上 | §7.2 删两行 | 删除已交付的「r5 面试对话流仍待落地」「Docker 打包 / 一键启动脚本 未做」 |
| 同上 | §8 改写 + 新增 §8.1 | r5 条改「已交付（2026-11-01）」；删重复的「统一约束」第二条；新增「历史任务夹的偏差补记」表（r5 三参签名两处、r11 C-1/C-2、r12 `iq-NNN`） |
| `backend/app/services/exam_selector.py` | 模块 docstring 第 9–14 行 | 把「每种可用客观题型各 ≥1」明确为取题策略（`_prefer_kind_diversity()`），不再列进 `build_paper()` 结构闸门校验项；**零逻辑改动** |
| `frontend/src/lib/practice.ts` | 第 118–138 行 | 新增 `DIRECTION_LABEL`（`satisfies Record<Exclude<PracticeDirectionFilter,'all'>, string>`），`directionChips()` 由其派生；输出形状与顺序不变 |
| `docs/teamflow/20261102-r17-doc-tail-closure/**` | 新增 | 本任务夹（`meta.json` / 本变更单 / `ACCEPTANCE.md`） |
| `docs/teamflow/memory.md` | 更新 | 第 37 / 41 / 42 行三条标为已关闭并指向本夹 |
| `backend/app/schemas.py`、`frontend/src/api/types.ts`、seed、运行时行为 | **零改动** | 无字段变更、无数据变更 |

## 3 方案

### 3.1 架构文档尾巴（memory 第 37 行）

- **§7.2 的两条过时行**：待办只点名「r5 行」，核查时发现「Docker 打包 / 一键启动脚本 未做（README 为三步手动流程）」
  与 r10 已交付事实相反（`docker-compose.yml` / 两个 Dockerfile / `nginx.conf` / `docker.env.example` 五个文件均在库），
  属同类文档尾巴，一并移入 §7.1 并标注 r10 任务夹；§7.2 只保留真实未完成项（真实 PDF/DOCX、ruff、CI 实跑）。
- **§8 交接段**：r5 条由「待落地」改为「已交付（2026-11-01）」并给出模块 / 路由 / 页面落点；删掉逐字重复的第二条
  「统一约束」，保留一条。
- **§7.1 顺带更正**：「后端测试 13 文件」为脚手架期数字，实测 `backend/tests/*.py` 除 `conftest.py` 共 **31** 个。

### 3.2 r8-② 与 r11 C-2：偏差只补记、不回改历史夹

- **§8.1「历史任务夹的偏差补记」**：一张「来源 / 历史文档写法 / 实现真相」表，覆盖
  r5 `TECHNICAL.md:186,302`（3 参 → 4 参，`services/rules.py:226`；r8 起以「不挤占剩余正题轮次」替代「answered+1 ≤ 12」）、
  r11 `TECHNICAL.md`（缺 `_prefer_kind_diversity()` 与 `PromptBody.tsx`）、r11 `QA-REPORT.md`（缺共享口径段）、
  r12 §3.2（`iq-NNN` → `iq380-`，已由 §3.4.2 承载，此处只做索引）。
- **代码侧对齐**：`exam_selector.py` 模块 docstring 直接把「题型覆盖」写成取题策略并给出 r11 的成因
  （判断题全落 intermediate/challenge 档，旧取题顺序下 basic 额度先耗尽 → 卷面结构不可达），
  与 `_fit_structure()` 的四项校验（题量 / 客观 ≥8 / 挑战 ≤20% / 方向 ≥ `require_directions`）分列。
- **功能侧补记**：`PromptBody.tsx` 与 `practice.ts` 进 §3.1 模块表，标明约束（题面围栏唯一出口 / 方向闭集单源），
  避免后续需求再各自解析题面或再写一份方向字面量。

### 3.3 r11 C-1：共享口径落到 §3.4.3

- **为什么不写回 r11 `QA-REPORT.md`**：任务夹不可变；r11 的 QA 结论需保留原貌，口径更正必须落在产品级文档。
- **表结构**：七层（数据源 / 判分 / 作答记录 / 熟练度 / 取题池 / 卷面结构 / 抽样），每层先标「共享 / 刻意不同」再给事实，
  与 `memory.md` 第 20 行（r11 约定）逐条对齐，不引入新口径。
- **落点选择**：放在 §3.4（数据模型）内、紧跟 §3.4.2 题库前缀之后 —— 共享口径的本质是「同一张 `questions` 表 +
  同一判分函数 + 同一 `question_attempts`」，属数据层事实，不是页面行为。

### 3.4 r11 C-3：方向闭集单一来源 + 编译期门禁

- **形式选择**：`satisfies Record<Exclude<PracticeDirectionFilter,'all'>, string>` 同时保证「键合法」与「无漏项」；
  对比 `as const` 元组只保证元素合法、不保证完整，无法消除「契约新增方向但 chip 静默缺失」的风险。
- **顺序不变**：`Object.keys` 对字符串键保持插入序，chip 顺序仍为「全部 + 前端 / 后端 / 算法与数据结构 / 计算机基础」，
  与改动前逐项一致（现有 14 条 `src/test/practice.test.ts` 用例全绿）。
- **不改契约**：`PracticeDirectionFilter` 仍在 `src/api/types.ts`（后端 `rules.DIRECTIONS` 的镜像），本文件只消费。

## 4 验证计划（本轮实跑记录见 `ACCEPTANCE.md`）

1. 前端 `npm run typecheck` → 0 error（`satisfies` 门禁生效路径）。
2. 前端 `npm run lint` → 0 error（28 warnings 为既有基线，`--max-warnings 28`）。
3. 前端 `npm test -- --run` → 10 文件 / 133 passed。
4. 后端 `python -m pytest -p no:cacheprovider` → 全绿（仅 docstring 改动，断言行为不变）。
5. 文档自查：`ARCHITECTURE.md` 中 `待落地 / 进行中` 不再命中 r5 条；「统一约束」只出现一次；
   §7.2 只剩三项；§3.4.3 / §8.1 存在且指向的实现路径逐条可核实（`rules.py:226`、`exam_selector.py`、`practice.ts`、`types.ts:533`）。

## 5 风险与回滚

| 风险 | 处置 |
| --- | --- |
| `DIRECTION_LABEL` 的 `satisfies` 在 `tsconfig` 非 strict 时不生效 | `tsconfig.json` 为 strict（AGENTS §4），typecheck 实跑通过 |
| `Object.keys` 顺序被误认为不受控 | 字符串键按插入序，且 vitest 既有 chip 断言（若后续补）可兜住；本轮已实跑全绿 |
| 文档补记与实现再次漂移 | §8.1 每行都给出「来源行号 + 实现位置」，实现变动时可在同一表内更新 |
| 回滚 | `git revert` 本轮提交；两处代码改动为零行为变更，无需数据回滚 |

## 6 取舍

1. **不回改 r5 / r11 任务夹**：任务夹不可变是团队硬约定；§8.1 的补记表是长期生效的更正入口。
2. **§7.2 多删一条 Docker 行**：超出待办原文的「r5 行」，但同属「文档尾巴」且与 r10 交付事实相反，符合本轮意图；
   若团队认为应保留「README 三步手动流程」的历史记录，可在 §7.1 的 r10 行内读到。
3. **不为 `directionChips()` 补 vitest 用例**：本轮目标是消除第二份字面量并用编译期门禁兜住「漏项」；
   顺序回归已有页面渲染路径覆盖，新增用例属可选增强（如需要另立小需求）。
4. **不改业务提示词 / 不改契约**：r11 C-2 只对齐 docstring 表述，不改组卷取题顺序（行为在 r11 已定型并通过验收）。

## 7 交付物

- 文档：`ARCHITECTURE.md`（§3.1 / §3.4.3 / §7.1 / §7.2 / §8 / §8.1）、`memory.md`（三条待办收口）、
  本任务夹 `meta.json` / `TECH-CHANGE.md` / `ACCEPTANCE.md`。
- 代码：`backend/app/services/exam_selector.py`（docstring）、`frontend/src/lib/practice.ts`（方向闭集单源）。
- 数据与契约：无。
