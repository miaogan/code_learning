# 题库合并导入报表（r15 · 工具生成，勿手改）

命令：`cd backend && python -X utf8 -m app.services.question_merge --write`
（重算 → 写 `backend/app/seed/questions.json` → 本报表；`--check` 用它做逐字节幂等比对）

## 1 总量

- 合并前存量：260 条（无 `source` 键，运行时缺省 `seed`，逐字节不变）
- 本批新增：519 条
- 合并后总量：779 条
- 读入素材：519 条 → 越界丢弃 0 条、字面重复 0 条、近重复 0 条

## 2 每来源计数

| 来源 | 读入 | 字面重复 | 近重复 | 越界 | 纠正 | 方向推断 | 新增 |
|---|---|---|---|---|---|---|---|
| `tiji` | 20 | 0 | 0 | 0 | 0 | 0 | 20 |
| `local100` | 100 | 0 | 0 | 0 | 8 | 0 | 100 |
| `iq380` | 379 | 0 | 0 | 0 | 1 | 0 | 379 |
| `fe-interview` | 20 | 0 | 0 | 0 | 0 | 20 | 20 |

口径：`纠正` = 素材声明的方向与 language 归属冲突、以 language 为准被纠正的条数（不丢题）；`方向推断` = 素材缺 `direction`、由 `rules.direction_of_language()` 推断出来的条数（`04-fe-interview20.json` 全缺）。两者都不改语言、不丢题。
归一化动作：判断题选项重建 120 条、答案字符串切分为列表 399 条。

## 3 分布

- 总数：779
- 来源：fe-interview 20 / iq380 379 / local100 100 / seed 260 / tiji 20
- 题型：judge 156 / multiple 60 / single 551 / text 12
- 语言：(空) 294 / css 40 / go 74 / html 36 / java 84 / js 46 / python 86 / react 45 / ts 32 / vue3 42
- 方向：前端 267 / 后端 423 / 算法与数据结构 56 / 计算机基础 33
- 难度：basic 283 / challenge 137 / intermediate 359
- 必备度：advanced 167 / must_know 499 / nice_to_know 113

## 4 质量口径

- 解析长度：最短 38 字符 / 平均 109.2 字符；不足 10 字符 0 条
- 客观题选项合规率：767/767（100.0%，口径 = 选项 2–6 个、key 唯一、答案 ⊆ 选项）
- `language` 空白（通用 / 算法题）占比：294/779 = 37.7%
- 通用方向（算法与数据结构 / 计算机基础）带语言的行数：0

## 5 方向纠正与推断

- 素材缺 `direction`、按 language 推断：20 条（fei-001 … fei-020；前端 20）

方向冲突纠正：9 条
- `l100-028`（local100，language=java）：计算机基础 → 后端
- `l100-040`（local100，language=css）：后端 → 前端
- `l100-060`（local100，language=react）：算法与数据结构 → 前端
- `l100-064`（local100，language=css）：算法与数据结构 → 前端
- `l100-080`（local100，language=css）：后端 → 前端
- `l100-084`（local100，language=css）：后端 → 前端
- `l100-096`（local100，language=css）：后端 → 前端
- `l100-100`（local100，language=css）：后端 → 前端
- `iq380-094`（iq380，language=java）：计算机基础 → 后端

## 6 人工抽检（每来源 3 道，首 / 中 / 尾）

- `tiji-001` [single/js/basic] 答案 `D`：在 JavaScript 中，以下哪个表达式的 typeof 结果为 "number"？…
- `tiji-011` [single/go/intermediate] 答案 `B`：Go 语言中，短变量声明 `:=` 的使用前提是？…
- `tiji-020` [judge/vue3/challenge] 答案 `B`：Vue3 中 ref 用于基本类型、reactive 用于对象，二者在模板中访问时都需要手动…
- `l100-001` [single/vue3/basic] 答案 `A`：关于 Vue3 的 reactivity 与 React 的 state/re-render…
- `l100-051` [single/通用/basic] 答案 `B`：关于 Embedding 及相似度度量，以下说法正确的是？…
- `l100-100` [single/css/challenge] 答案 `C`：在设计可观测的故障定位系统时，以下哪项做法符合要求？…
- `iq380-001` [single/vue3/intermediate] 答案 `B`：Vue3 中 reactive 实现依赖收集与派发的底层机制是什么？…
- `iq380-190` [single/go/intermediate] 答案 `C`：关于 Go 接口底层结构及值接收者与指针接收者对接口实现的影响，以下说法正确的是？…
- `iq380-379` [judge/通用/intermediate] 答案 `B`：技术选型时，应优先考虑自研所有组件以保持完全控制，避免使用成熟开源或云服务。…
- `fei-001` [single/html/basic] 答案 `A`：关于 cookies、sessionStorage 和 localStorage 的区别，以…
- `fei-011` [single/css/basic] 答案 `A`：关于 CSS 中相邻兄弟选择器（+）、后代选择器（空格）和子选择器（>）的区别，以下说法正确…
- `fei-020` [single/js/basic] 答案 `B`：关于散列函数（哈希函数）的特征，下列哪项描述是正确的？…

## 7 断言改造清单

- r11 的题库质量断言在 r12 **0 处需要改基数**：题量类断言已收敛为前缀子集（`fe-/be-/al-/cs-` 存量 + 九个 r11 语言前缀）或按 `len(_seed_rows())` 动态推导，本批新前缀（`tiji-` / `l100-` / `iq380-` / `fei-`）不在任何前缀集合里。
- `test_question_bank_quality.py` 只**追加** r12 三条断言（source 枚举与计数、总量 779、通用方向恒空 language），r11 断言一字未改。
- `test_engineering_gates.py` 追加 `R12_TOUCHED` + 三条门禁（改动面可解析、合并工具不被运行时导入、`source` 不进 HTTP 契约）。

## 8 回滚

代码回退后**必须**再跑数据回滚（数据只增不删，只回退代码不会清理已导入的 519 行）：

```bash
cd backend && python -X utf8 -m app.services.question_merge --rollback
# 只删 source ∈ tiji/local100/iq380/fe-interview 的行，存量 260 行（source='seed'）不受影响
# 幂等：再跑一次删 0 行
```
