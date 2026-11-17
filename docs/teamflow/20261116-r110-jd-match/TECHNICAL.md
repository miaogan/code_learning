# r110 技术方案

## 1. 契约（snake_case，两侧逐字段镜像）

`backend/app/schemas.py` 末尾新增：`JdMatchRequest` / `JdKeywordItem` / `JdGapItem` /
`JdInterviewPreset` / `JdMatchResult`；`frontend/src/api/types.ts` 逐字段镜像。

缺口来源字段命名为 `origin`（`jd` / `role_model`），**不是 `source`**：`test_r12_source_not_in_http_contract` 明令题库导入期字段 `source` 不得进 HTTP 契约，r110 首版踩过这个门禁并已改名。

`POST /api/jd-match` → `JdMatchResult`，带 `Depends(current_user)`。路由层只校验与转发，所有业务在 `services/jd_match.py`。

## 2. 服务端匹配（零 AI / 零新表）

`backend/app/services/jd_match.py` 的流程：

1. **岗位识别**：显式 `target_role` 优先；否则内置岗位模型名包含匹配 → `rules` 常见简称 → 画像岗位 → 最近报告岗位。识别不到就 `role_fit=None` 并给中文提示。
2. **岗位对标**：`role_fit_service.build_role_fit(profile, role)` 是报告页同一个纯函数；这是「本次 JD 现场对标」，不写回报告、不改医案。
3. **关键词召回**：从 `load_role_models()` 的全部技能名生成术语表；`_ALIAS_OVERRIDES` 只补 `React/js/ts/redis/docker/k8s/CI-CD/RAG/LLM/Agent` 等常见缩写。短 ASCII 别名（≤4）加单词边界，`go` 不命中 `golang`。
4. **消歧**：先全量召回，再按「起点靠前 → 覆盖更长 → 名称稳定」取不重叠区间；避免 `Python` 抢走 `Python 后端服务` 的更长命中。
5. **画像证据**：`user_level_of()` 沿用 r26 四档规则；只取非 historical 技能的 `source_quotes`（及旧 `source_quote` 回填）。`evidence` / `mentioned` / `missing` 三态区分「有原句证据 / 只在技术栈出现 / 没找到证据」。
6. **缺口与预设**：`origin=jd` 来自 JD 命中但无证据；`origin=role_model` 来自 `role_fit.first_fix` 且 JD 未直接写。预设方向取 `role_fit.model.direction` 或命中提示的多数方向，二级方向必须过 `rules.is_valid_sub_direction()`。

上限：`MAX_KEYWORDS=24` / `MAX_GAPS=12` / `MAX_EVIDENCE_PER_KEYWORD=3` / `MAX_SOURCE_QUOTE=90`。响应没有 `score` / `match_rate`，`notice` 明说「字面对照不是能力评分」。

## 3. 前端

- `lib/jdMatch.ts`：纯函数 `keywordGroups` / `gapGroups` / `jdSummary` / `interviewHref` / `isJdEmpty`；页面零二次匹配。
- `pages/JdPage.tsx`：受控 textarea + 可选岗位输入 + 示例 JD；`api.matchJd` 是唯一 HTTP 出口；命中词按证据状态分组展示，缺口按 `origin` 分组展示；复用 `RoleFitCard`。
- `App.tsx`：`/jd` 路由与「对岗」工具入口；桌面和移动同一份 `TOOL_ITEMS`。
- `InterviewPage.tsx` + `setupModel.ts`：新增 `presetFromParams()`，只收 `target_role` / `direction` / `sub_direction`，按前端闭集收敛；`jdPresetAppliedRef` 保证同 URL 只应用一次；preset 存在时跳过「自动接回旧会话」，否则新配置会被旧 run 覆盖。
- `base.css` 末尾 append `sc-jd-*`，全部 `var(--*)`；≤640 单列、按钮保持既有 44px 触控规则。

## 4. 测试

- `backend/tests/test_r110_jd_match.py`（9 条）：空白 JD、无画像、证据引用、岗位识别 / 显式覆盖、缺口来源分离、预设闭集、短别名边界、无能力分字段、账号隔离。
- `frontend/src/test/jdMatch.test.ts`（4 组）：分组、摘要、链接闭集、空态。
- `frontend/src/test/interviewSettings.test.ts` 追加 3 条 `presetFromParams` 用例。
- 门禁：`test_r12_source_not_in_http_contract`、`test_style_baseline_append_only`、`test_r7_contract_mirror` 均需保持通过。
