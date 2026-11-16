# r111 技术方案

## 数据流

```
/jd 对位结果 preset.focus_gaps（最多 3）
  → interviewHref: ?focus=A&focus=B&focus=C（重复参数）
  → presetFromParams: 解析为 SetupDraft.focus_gaps（隐藏字段）
  → draftToPatch: 非空才下发 InterviewSettingsPatch.focus_gaps
  → fill_settings: _focus_gaps_of 清洗（trim / 去重 / 40 字 / 3 项）落 runs.payload.settings
  → 出题提示词: technical 前几题围绕缺口；追问沿缺口深挖
  → 跃迁档案 _expression: 按场次 settings 回读 + term_in_text 对照回答文本
  → LeapPage: gapCompareText 渲染「提到 X · 未提到 Y」
```

## 后端

### 契约（schemas.py）

- `InterviewSettings.focus_gaps: list[str] = []`；`InterviewSettingsPatch.focus_gaps: list[str] | None = None`。
- `JdInterviewPreset.focus_gaps: list[str] = []`（`max_length=3`）。
- `LeapExpressionItem.focus_gaps / gap_hits / gap_misses: list[str] = []`。

### 服务层

- `services/interview/interview.py`：
  - `_focus_gaps_of(raw)`：清洗唯一入口（开局与 calibration 同口径）。
  - `_focus_gaps_calibration(settings)`：空缺口返回空串（提示词不出现缺口段）；非空时给出「前 min(3, N) 道 technical 必须分别围绕缺口技能展开」的指令。
  - 出题与追问的提示词模板各加一条 focus_gaps 段。
- `services/jd_match.py`：
  - `_preset` 的缺口来源：`origin=jd` 的缺口优先，没有才回退 `fit.first_fix`。
  - 新增 `term_in_text(text, term)`：复用 `_aliases_of` + `_alias_pattern`（短 ASCII 别名词边界），供跃迁档案做「回答里是否提到」对照。
- `services/leap.py`：
  - `_run_focus_gaps(payload)`：从 `runs.payload.settings.focus_gaps` 回读（存量 run 缺键 → 空列表）。
  - `_expression()` 逐条计算 `gap_hits` / `gap_misses`（`term_in_text` 对照 answer）。

### 老数据兼容

- 存量 run 的 `settings` 无 `focus_gaps` 键：读取侧补空列表；面试恢复 / 报告生成路径不读该字段，零影响。
- `InterviewSettings` 校验：非 list 或超 3 项由 pydantic / 清洗层兜住；`max_length=3` 只约束 preset，settings 侧靠 `_focus_gaps_of`。

## 前端

- `types.ts`：三个接口逐字段镜像（settings / patch / preset / expression item）。
- `setupModel.ts`：
  - `SetupDraft.focus_gaps`（隐藏字段，不进表单 UI）；
  - `presetFromParams`：`params.getAll('focus')` 解析，trim / 截 40 / 去重 / 最多 3；
  - `draftToPatch`：非空才带键；`previewLine` 追加「缺口：A / B / C」。
- `jdMatch.ts`：`interviewHref` 用 `params.append('focus', gap)`。
- `leapArchive.ts`：`gapCompareText(item)`——`focus_gaps` 为空返回 null；非空拼「提到 X · 未提到 Y（仅关键词对照，不是掌握度结论）」。
- `LeapPage.tsx`：`ExpressionRow` 在 chips 与 hint 之间渲染对照行（`sc-leap-expr-gap`）。
- `JdPage.tsx`：预设卡显示「将优先追问：A / B / C（仍不虚构候选人经历）」。
- `base.css`：append-only 追加 `.sc-leap-expr-gap`。

## 测试

- 后端 `test_interview_chat.py`：缺口进提示词、清洗口径（空白/超长/去重/上限）、空缺口不出现提示段。
- 后端 `test_r108_leap_archive.py`（r111 节）：按场次对照（命中/未提到/存量空）、`term_in_text` 词边界。
- 后端 `test_r110_jd_match.py`：preset.focus_gaps 来源（JD 缺口优先、回退 first_fix、最多 3）。
- 前端 `interviewSettings.test.ts`：URL focus 参数解析、draftToPatch 空键不下发、previewLine。
- 前端 `jdMatch.test.ts`：interviewHref 带 focus 参数、脏值收敛。
- 前端 `leapArchive.test.ts`：gapCompareText 三态（无缺口 null / 命中与未提到 / 全未提到）。
