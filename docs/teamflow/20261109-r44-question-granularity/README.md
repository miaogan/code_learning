# r44 题库粒度细化：笔试 / 面试 / 学习三处可选二级方向

## 1. 需求

用户原话：「可以 这样方便我在 模拟面试 模拟笔试 学习 这几个模块划分更细的粒度」。

现状：方向只有 8 个大类，选到「后端」后无法再区分 python / java / go，学习模块也只有「方向 + 难度」两级。
目标：保留 8 个大方向，新增**二级方向**字段（方案 A），三个模块都能选到子方向粒度。

## 2. 方案

- 闭集单源：`backend/app/services/report/rules.py::SUBDIRECTIONS`（8 方向 × 子方向，末项是「通用 XX」兜底），`is_valid_sub_direction()` / `generic_sub_direction_of()` 供各模块复用。
- 前端同源：`frontend/src/lib/questionDirections.ts` 与 `rules.py` 逐字一致；笔试 / 面试 / 学习都从这里取，不再各自内联字面量。
- 语义：`direction` / `sub_direction` 空串 = 不限；`sub_direction` 只能挂在合法 `direction` 上，越界一律清空而不是 422。

## 3. 三模块改动

### 3.1 模拟笔试（先前已随 `0846fe4` / `30746e5` 提交）

- `POST /api/exams` 支持 `direction` / `sub_direction` / `difficulty` / `question_count`；
- 卷面按方向（→ 子方向）取材，二级方向只在方向非空时生效。

### 3.2 模拟面试（本轮）

- `InterviewSettings` / `InterviewSettingsPatch` 扩为 6 键，新增可选 `direction` / `sub_direction`（`backend/app/schemas.py`），老 payload 缺这两键仍合法。
- `rules.settings_or_none()` 历史 / 报告 / 会话三方统一校验：方向越界、子方向不属该方向 → `None`（不把非法值装成合法设定）。
- `interview.fill_settings()` 归一化权威入口：非法方向清空方向，合法方向 + 不匹配子方向只清子方向。
- 三层提示词注入：`calibration.focus`（不限 / 只到方向 / 到子方向三档互不相同）、`INTERVIEW_SYSTEM` 硬性规则第 2 条、每轮 user JSON 自带 settings。
- 前端：`setupModel.ts` 的 `SetupDraft` / `prefillOf` / `draftToPatch` / `previewLine` 补两字段；`InterviewSetupForm` 新增「方向聚焦」与「二级方向」两组 chip（切换方向清空子方向）；`chatModel.ts::settingsLine` 仅在方向非空时追加「方向 · 子方向」。

### 3.3 学习（本轮）

- `TutorialChapter` 增 `sub_direction`，32 章全部打标，取值落在该方向闭集内。
- `lib/tutorials.ts`：新增 `subDirectionsInChapters()`（只列有内容的子方向、按闭集顺序）、`filterChaptersBySubDirection()`、`parseLearnSubDirection()`、`tutorialHref(direction, level, sub)`。
- `LearnPage`：方向 → 子方向 → 难度三级筛选；只有选定方向后才出现「子方向」行；换方向清空子方向与难度，换子方向重置难度；卡片在方向 chip 旁展示子方向 chip。
- URL：`/learn?direction=…&sub=…&level=…`，`sub` 不属于当前方向时回落 `all`。

## 4. 契约与兼容

- JSON 字段名 `snake_case`，前后端逐字同步（`schemas.py` ↔ `api/types.ts`）。
- 老数据：历史 run 的 `settings` 只有 4 键，读路径不补默认值也不报错；老 URL 无 `sub` 参数时按「全部」。
- 错误形态不变，未新增错误码。

## 5. 验证结果（2026-11-09）

| 命令 | 结果 |
|---|---|
| `python -m ruff check app tests` | 通过 |
| `python -m pytest -q` | 全绿（含新增 `test_focus_calibration_covers_three_levels` / `test_settings_or_none_rejects_out_of_closure_direction`） |
| `npm run lint` | 通过（`--max-warnings` 基线内） |
| `npm run typecheck` | 通过 |
| `npx vitest run` | 全绿（`interviewSettings.test.ts` 新增方向下发 / 预览行用例；`tutorials.test.ts` 新增子方向闭集 / 排序 / 三级组合用例） |
| `npm run build` | 通过 |

## 6. 已知限制

- 学习模块子方向的正确性靠「章节打标必须落在闭集内」的 vitest 门禁保证，没有在 UI 上做方向 × 子方向的交叉空态矩阵测试。
- 真实浏览器视觉（两组新 chip 在窄屏的换行表现）未做人工点检。
