# r18 验收报告：B 组代码小改（r5 O-1 / r5 O-2 / r3 P3①）

- 任务夹：`docs/teamflow/20261102-r18-p3-code-closure/`
- 验收对象（工作区未提交改动）：`frontend/src/pages/InterviewPage.tsx`、`frontend/src/components/interview/Composer.tsx`、
  `backend/app/services/profile.py`、本任务夹、`docs/teamflow/memory.md`。
- 验收口径：r5 `ACCEPTANCE.md` §5 的 O-1 / O-2 + r4 夹（r3 收口）P3①；用户本轮明确只做这三条，r6 / r8① / r5 O-4 / r3 P3② 不在范围内。

## 1 判据逐条核对

| # | 判据 | 实测结果 | 结论 |
|---|---|---|---|
| 1 | O-1：配置态出现会话状态行 | `InterviewPage.tsx:353` 在 `InterviewSetupForm` 上方渲染 `<p className="sc-iq-meta">本场尚未开始 · 配置后开始对话</p>`，与 chat 态同类复用既有样式类 | 通过 |
| 2 | O-1：不新增 CSS 类 / token | 只用既有 `.sc-iq-meta`；`git diff` 无 CSS 改动 | 通过 |
| 3 | O-2：输入区显示字数计数 | `Composer.tsx:59-64` 提示行追加 `${value.length}/${MAX_ANSWER_CHARS} 字`，与 `maxLength` 同一计量口径 | 通过 |
| 4 | O-2：达到上限有明确提示 | `chars >= MAX_ANSWER_CHARS` 时追加「（已达上限）」，解释静默截断 | 通过 |
| 5 | O-2：只读态不叠计数 | `readonly` 分支保持原文案「本场面试已结束 · 仅供回看」，计数只在可输入态拼装 | 通过 |
| 6 | P3①：恒真分支已移除 | `profile.py:147-151` 现为三行线性写入，无 `model_fields` 判断；响应字段 `merge_summary` 不变 | 通过 |
| 7 | 契约零改动 | `backend/app/schemas.py` / `frontend/src/api/types.ts` 在 `git status` 中零改动 | 通过 |
| 8 | 既有门禁不回归 | 前端 typecheck 0 error、lint 0 error / 28 warnings、vitest 10 文件 133 passed；后端 534 passed / 1 skipped（见 §3） | 通过 |
| 9 | 记忆收口准确 | `memory.md` 第 39 行 O-1/O-2 标已关闭、O-4 保留开放；第 47 行 P3① 标已关闭、P3② 保留开放 | 通过 |
| 10 | 任务夹自包含 | `meta.json` / `TECH-CHANGE.md` / `ACCEPTANCE.md` 齐备 | 通过 |

## 2 架构一致性

| 蓝图要求 | 实测 | 结论 |
|---|---|---|
| 组件文件只导出组件、纯函数进 `chatModel.ts` | 两处改动均为组件内文案拼装，未新增导出；lint `react-refresh` 维持 28 warnings 不变 | 符合 |
| 样式只用 token / 既有类 | 零 CSS 改动 | 符合 |
| 契约两侧同步 | 未触碰契约 | 符合 |
| 任务夹不可变 | r5 / r4（r3 收口）夹零改动；偏差口径写在本夹 + memory | 符合 |
| 单源实现 | 计数复用 `MAX_ANSWER_CHARS` 常量本身，不写第二份 800；`_with_summary` 不再双重判定模型字段 | 符合 |

## 3 复跑命令与实测

```powershell
cd frontend
npm run typecheck          # exit 0
npm run lint               # exit 0，0 error / 28 warnings
npm test -- --run          # 10 文件 / 133 passed
cd ..\backend
python -m pytest -p no:cacheprovider   # 结果见下方
```

- 后端全量：`534 passed, 1 skipped in 1204.43s (0:20:04)`，exit 0（用例数与 r17 基线一致，无新增失败、无跳过变化）。
- `ruff`：本机不可用（与 r9/r12–r15/r16 同口径，未记为通过）。

## 4 遗留（P3，均不阻断）

| 编号 | 内容 | 处置建议 |
|---|---|---|
| P3-a | `ruff` 本机不可用（`No module named ruff`，无 `backend/.venv`） | 与历史同口径；CI 或含 ruff 的环境补跑 |
| P3-b | 两处 UI 文案无 vitest 断言（项目无 DOM 测试库，纯函数才可测） | 渲染事实由源码评审 + 真机走查覆盖；如需门禁可另立需求引 DOM 测试 |
| P3-c | 配置态状态行的真实视觉（390px 换行、与表单间距）未做浏览器截图 | 并入 memory 第 38 行人眼/真机补测清单 |
| P3-d | r5 `DESIGN.md` §2.3 输入区标尺仍只写计时文案（历史夹不可改） | 口径以 `TECH-CHANGE.md` §6.5 与本报告为准 |

## 5 验收判定

三处改动与目标一致、契约与样式零改动、前端门禁全绿、后端全量不回归、记忆与任务夹已收口，
剩余 4 条 P3 为环境/工艺留痕，不构成返工条件。

验收结论：✅ 通过
