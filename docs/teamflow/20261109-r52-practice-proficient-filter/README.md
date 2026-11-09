# r52 · 练习默认跳过已熟练题（复用笔试题熟练度判定）

## 1. 需求来源

用户反馈：「练习中的『答对之后短时间内不再出现』这个机制似乎没有生效」。

复验结论：**机制此前并不存在，不是失效** —— `practice.py` 全文件无 `proficiency` 引用，
`proficient_ids()` 只在 `exam.py`（笔试卷）调用。练习的三个范围都不满足该体验：

| 范围 | 现状 | 问题 |
| --- | --- | --- |
| `all` | 不筛 | 已熟练题反复出现，且第二次答对后仍出现 |
| `unseen` | 无任何作答事件 | 做过一次即永久消失，无法「短期后回流」 |
| `wrong` | 最近一次答错 | 与「熟练」无关，答对即移出 |

文档原口径（`ARCHITECTURE §3.4` 抽样行、r11 PRD）写的是「练习可重复练同一题」，因此
**这是产品口径变更，不是 bug 修复**。用户确认按方案 A 执行。

## 2. 方案 A（已实施）

练习组卷与 `/stats.hit` **复用笔试同一份** `proficiency.proficient_ids()`：

- 判定口径零复制：30 天内答对 ≥2 次且最近一次答对 → 熟练；超 30 天或最近一次答错自动回流。
  阈值只在 `config.Settings`，练习侧不写第二套数字。
- 「全部」语义变为「**除熟练题外的全部**」；`unseen` / `wrong` 语义不变（熟练题本就不会命中
  这两个范围）。
- 过滤事实由服务端算：题单新增 `filtered_count`（本次真正被跳过的熟练题数），前端沿用
  `lib/examNotice.ts::filteredNotice()` 一行文案，不自行重算（AC-12）。
- 池子被过滤到 0 命中时，notice 换成专用中文（「该组合下的题目都已熟练掌握，可切到
  『只看错题』回顾，或换个筛选继续练」），不再误报「试试放宽难度或必备度」。

被否决的方案：B（新增「跳过已熟练」chip，改动小但默认体验不变）；C（新增短期冷却阈值，
需要独立口径与配置，且与既有熟练度语义重复）。

## 3. 改动清单

后端：

- `backend/app/services/assessment/practice.py`
  - `_compose_paper()` / `build_paper`：粗筛 `wide` 后剔除熟练题（`wide_available`），
    返回新增 `filtered_count`（题库空、0 命中、正常三种出口都带，缺省语义为 0）。
  - r50 聚焦路径：窄池与补位宽池都跳过熟练题；`filtered_count` = 窄池被跳过数 +
    （发生补位时）宽池中**不属于该子方向**且被跳过的题数（窄池已数过的不重复）。
  - `stats()`：`hit` 与题单 `hit_count` 同源同值地排除熟练题；`total` / `practiced` /
    `wrong_total` 仍是全库事实，不缩水。
- `backend/app/schemas.py`：`PracticePaper` 增加 `filtered_count: int = 0`。

前端：

- `frontend/src/api/types.ts`：`PracticePaper` 同步 `filtered_count`。
- `frontend/src/pages/PracticePage.tsx`：作答态与完成态挂 `filteredNotice(paper.filtered_count)`
  （0 / 非法值由该函数返回 `null`，不挂节点）；页面副标题改为说明默认跳过熟练题。
- `frontend/src/components/practice/PracticeFilters.tsx`：「范围」组下加一行说明
  （30 天 / 答对 2 次 / 超期或答错回流）。

## 4. 测试

后端 `backend/tests/test_r11_practice_service.py`（新增 4 条）：

- 答对 2 次 → 该题不进题单、`filtered_count` 增加、`stats.hit` 与 `hit_count` 同值、
  `stats.total` 不缩水；
- 30 天窗口外两次答对 / 最近一次答错 → 回流，题目重新出现；
- 全库熟练 → 空题单 + 专用 notice + `filtered_count = 全库`；
- 聚焦池全熟练 → 同方向宽池补位，`filtered_count` 只数窄池被跳过的题。

并按契约变更同步更新：

- `test_r11_practice_service.py` 的题单键集合基线加入 `filtered_count`；
- `test_r11_practice_api.py` 两处响应断言补 `filtered_count`；
- `test_engineering_gates.py::test_frontend_filtered_notice_single_source` 扩到
  `PracticePage.tsx`（继续钉住「文案唯一出处 + 前端不重算」）。

## 5. 验证结果

- 后端：`python -m pytest -q` 全绿（1 skipped 为既有跳过项）、`python -m ruff check app tests` 通过。
- 前端：`npm run typecheck` / `npm run lint` / `npm test`（250 用例）/ `npm run build` 全通过。

## 6. 已知限制（刻意保留）

1. 熟练阈值是**答对 2 次**：只答对 1 次不会消失（与笔试口径一致，不新增「答对 1 次冷却」）。
2. 池子会变小：某语言 / 方向全部熟练时可能 0 命中，已给专用提示与「只看错题」出口，
   **不提供**「强制显示熟练题」开关。
3. `/stats` 只回 `hit`（已排除熟练题），不再单独披露 `filtered_count`；筛选页用一行说明
   解释默认行为，题单页才给精确条数。
4. 熟练度按账号共享一份账本（练习与笔试共用 `question_attempts`）：笔试答对 2 次后，练习
   同样不会再出该题 —— 这是「共享熟练度」的既有设计，非本轮新增。
