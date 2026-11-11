# r80 · 验收报告：线程记忆（长线程早期上下文不丢）

> 结论：PRD 中 7 条验收标准全部满足。纯增量：1 张新表、2 个 repository 函数、1 个净化函数、
> 提示词加 1 段、模型输出加 1 个字段，**无新端点、无新依赖、无额外模型调用**。
> r75–r80 六轮仍未提交。

## 1. 交付内容

| 文件 | 改动 |
| --- | --- |
| `backend/app/core/db.py` | `R80_SCHEMA`（`taifu_threads` 单行表）+ `init_db()` 第 19 步 |
| `backend/app/core/repository.py` | `get_taifu_memory()` / `save_taifu_memory()`（单行 upsert）；`delete_taifu_messages()` 顺带清记忆 |
| `backend/app/services/taifu/policy.py` | `MEMORY_MAX=240` / `MEMORY_MIN=4` / `MEMORY_NONE` / `MEMORY_TASK`；`sanitize_memory()`；`TaifuDraftReply.memory`；提示词加 `【早期对话摘要】` 段与回写指令；系统提示词加第 6 条 |
| `backend/app/services/taifu/taifu.py` | 多取一条判断溢出；只在溢出时要求压缩、只在非空时落库；`memory_used` 标记 |
| `backend/app/schemas.py` | `TaifuReply.memory_used: bool`（可观测，前端不消费） |
| `backend/tests/test_r77_taifu.py` | +7 条（文件内 28 条） |

前端零改动：记忆对用户不可见，`TaifuReply` 多出的字段 TS 侧不读（不做无用类型字段）。

## 2. 验收标准

| AC | 结果 | 证据 |
| --- | --- | --- |
| AC-1 溢出才压缩 | 通过 | 6 条消息时 `overflow = False`（提示词含 `MEMORY_TASK[False]`、不含 `MEMORY_TASK[True]`），8 条时反转；短线程模型给了记忆也不落库 |
| AC-2 记忆进提示词 | 通过 | 有记忆：`【早期对话摘要】目标是 AI 应用工程师；…` 出现在档案段之后；无记忆：`【早期对话摘要】（无：…）`，不留空段头 |
| AC-3 记忆不是依据 | 通过 | `citations: ["/history"]`（只在记忆里出现）→ `citations == []`、`dropped_citations == 1` |
| AC-4 空值不覆盖 | 通过 | `无` / `（无）` / `N/A` / `没有` / 空白 → `sanitize_memory` 返回空串，调用方据此跳过写入 |
| AC-5 先成功再写 | 通过 | 空回答：消息数不变、`get_taifu_memory() == ""`（模型虽然回了 memory 也不写） |
| AC-6 清空即清空 | 通过 | `DELETE /api/taifu/thread` 后 `get_taifu_memory() == ""` |
| AC-7 不回归 | 通过 | 后端 804 passed / 1 skipped（805，0 失败）；r77/r78/r79 的 28 条用例全绿；前端未改，沿 r79 的 36 文件 464 测试 / typecheck / lint / build |

## 3. 验证命令与结果

```text
backend: ruff check app tests                → All checks passed
backend: pytest tests/test_r77_taifu.py -q    → 28 passed，exit 0
backend: pytest -q                            → 804 passed / 1 skipped（805 条，0 失败）
frontend: typecheck / lint / build            → 未改前端，沿用 r79 结果（464 测试、0 warning、构建通过）
```

存量库迁移（不跑迁移脚本，只重启）：

```text
sqlite> SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'taifu%';
taifu_messages | taifu_threads
PRAGMA table_info(taifu_threads) → ['user_id', 'memory', 'updated_at']
taifu_threads 行数 = 0（旧对话不伪造记忆）
```

## 4. 验收中发现并修复的问题

1. **`MEMORY_MIN = 8` 把合法短摘要当占位丢掉**。中文摘要「第一句 第二句」只有 7 字，
   初版阈值会返回空串 → 这条摘要永远存不进去，而且失败是静默的（只会表现为「记忆怎么没生效」）。
   降到 4：`无`(1) / `（无）`(3) / `N/A`(3) / `没有`(2) 仍被挡住，7 字摘要能过。
2. **溢出判定的测试数据少一轮**。初版测试塞 6 条消息就断言「要求压缩」，但那 6 条全在窗口里、
   根本没东西被挤出去 —— 是**用例错**而不是实现错。改为 8 条（4 轮）才是真正的溢出起点，
   同时把这层语义写进注释与 TECHNICAL §2（`6 条不溢出、8 条起溢出`）。
3. **前端 `TaifuReply` 是否需要加 `memory_used`**：决定不加。它是给测试与排障看的可观测标记，
   界面不展示；加一个没人读的字段只会让契约看起来比实际能力多。

## 5. 与前面几轮的关系

- 记忆是 r77「材料由服务端组装」的补面：档案每轮全量重读，**只有对话会衰减**，本轮补的就是这一半。
- 与 r78 页面上下文同一条边界：**模型自己写的东西不是依据**。页面与记忆都进提示词、都不进白名单，
  区别只是页面由前端给、记忆由模型给。
- r79 的锚点白名单不受影响：`sanitize_reply` 的 `allowed` 仍只由档案段（含锚点）构成。

## 6. 已知限制

- 滚动重写不可逆：某一轮摘要写得潦草，被覆盖的旧要点就没了（无版本、无回滚）。
- 单段记忆不分话题，跨话题对话会混在一起。
- 240 字硬上限：很长的背景（例如完整转岗经历）只能留要点。
- 摘要是否「忠于原文」无法程序校验，只能靠系统提示词「以档案为准」+ 引用白名单挡「拿记忆当出处」。
