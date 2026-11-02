# r18 · B 组代码小改（技术变更单）

> 本轮只做 3 处小改，均为历史验收里的 P3 观察项：2 条前端 UI 补齐 + 1 条后端死分支清理。
> 零契约改动、零数据迁移、零新增依赖、零新增 CSS 类。

## 1 背景与范围

来源（历史任务夹不可改，原文只读）：

- r5 `ACCEPTANCE.md` §5 `O-1`：配置态无「本场尚未开始」一类会话状态行（`InterviewPage.tsx:288` 仅在 chat/ended 渲染）。
- r5 `ACCEPTANCE.md` §5 `O-2`：`Composer.tsx:73` 仅 `maxLength`，接近 800 字无计数、超出静默截断。
- r4 `ACCEPTANCE.md`（r3 收口夹）P3①：`backend/app/services/profile.py:150` 的
  `if "merge_summary" in getattr(ProfileWithMerge, "model_fields", {})` 是恒真历史防御分支，可删或补注释。

本轮**不含**（按用户口径留在待办）：

- r5 `O-4`：`--max-warnings 28` 未在 r5 技术方案改动面声明 —— 历史夹不可改，属文档/流程留痕，不动代码。
- r6 `D-7/D-8/D-9`（熟练度说明文案）与 r8 ①（9 题卷追问额度 3→4）—— 涉及产品口径，需另立需求。

## 2 改动面

| 文件 | 改动 | 行为影响 |
| --- | --- | --- |
| `frontend/src/pages/InterviewPage.tsx` | 配置态（`else` 分支）在表单上方补一行 `.sc-iq-meta`：`本场尚未开始 · 配置后开始对话` | 仅多一行文案，与 chat 态 `已提出 N 题 · 已答 M 题` 形成三态一致 |
| `frontend/src/components/interview/Composer.tsx` | `metaText` 追加 `${chars}/${MAX_ANSWER_CHARS} 字`，达到上限追加 `（已达上限）` | 输入区提示行多一段计数；`maxLength` 与提交判定不变 |
| `backend/app/services/profile.py` | `_with_summary()` 删掉恒真 `model_fields` 判断，直接写 `merge_summary` | 响应结构逐字段等价（该字段在 `ProfileWithMerge` 恒存在） |
| `docs/teamflow/20261102-r18-p3-code-closure/**` | 新增本任务夹 | — |
| `docs/teamflow/memory.md` | r5 三条 P3 / r3 P3① 待办收口 | — |

契约（`backend/app/schemas.py` / `frontend/src/api/types.ts`）、seed、依赖、CSS token：**零改动**。

## 3 方案

### 3.1 r5 O-1：配置态状态行

配置态的卡内原本直接从表单开始，用户看不出「还没开始」。补一行复用既有 `.sc-iq-meta`（与 chat 态同一类），
不新增 CSS 类、不新增 token。文案只描述状态与下一步，不复述表单字段。

### 3.2 r5 O-2：字数计数与上限提示

- 计数取 `value.length`（与 `maxLength={MAX_ANSWER_CHARS}` 同一计量口径，不做 trim 归一，避免「显示的数和能输入的数不一样」）。
- 达到 800 时在提示行追加「（已达上限）」，解释「再输入没反应」不是卡死，而是上限。
- 只读态保持原文案「本场面试已结束 · 仅供回看」，不叠计数（此时不可输入，计数没有意义）。
- 不新增 `is-warn` 着色：现有 `is-warn` 语义是「本轮计时 ≥13s」，混入字数会破坏该状态的唯一含义。

### 3.3 r3 P3①：删除恒真分支

`ProfileWithMerge` 在 `backend/app/schemas.py:635-638` 恒声明 `merge_summary: ProfileMergeSummary | None = None`，
因此 `"merge_summary" in model_fields` 永远为真。删除后 `_with_summary()` 变成三行线性写入，响应结构不变；
`_summary_payload()`（含 `model_dump` / `asdict` 兼容）保持原样，不在本轮扩大改动面。

## 4 验证计划

- 前端：`npm run typecheck` / `npm run lint` / `npm test -- --run`。
- 后端：`python -m pytest -p no:cacheprovider`（全量，确认删分支不回归画像合并链路），
  定向重点 `tests/test_profile_merge.py`（`merge_summary` 计数与重复上传断言）。
- 文档自查：`memory.md` 对应待办已标关闭；`git status` 只含预期文件。

## 5 风险与回滚

- 风险极低：三处均为展示/死代码，无状态机、无契约、无落库变化。
- 回滚：单文件 `git checkout -- <file>` 即可；无数据副作用。

## 6 取舍

1. **计数不做「剩余字数」**：`800/800` 比「剩余 0 字」更直观，且与 `maxLength` 语义一致。
2. **不给计数加警示色**：避免与 13s 计时警示共用 `is-warn` 而语义漂移；上限提示用文字后缀表达。
3. **不顺手清理 `_summary_payload()` 的 `asdict` 兜底**：r3 P3① 只点了外层恒真判断；内层兼容函数虽也可简化，
   但不在本轮授权范围，避免「小改变大改」。
4. **不补前端单测**：现有 vitest 只测纯函数（无 DOM 环境），两处改动均为组件内文案拼装；
   编译期（typecheck/lint）与复跑既有 133 条用例已覆盖不回归，渲染事实在验收里人工核对源码。
5. **不回写 r5 `DESIGN.md`**：其 §2.3 输入区标尺只写「Ctrl/Cmd + Enter 提交 · 已用 6s」，本轮按 O-2 追加字数段，
   属验收建议的增量；历史任务夹不可改，口径以本变更单与 `ACCEPTANCE.md` 为准。
