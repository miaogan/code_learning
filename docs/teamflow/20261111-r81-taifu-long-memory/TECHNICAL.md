# r81 · 技术方案：长期记忆（跨对话、可审计、可忘掉）

> 依据 PRD `docs/teamflow/20261111-r81-taifu-long-memory/PRD.md`。
> 纯增量：1 张新表 + 3 个端点；无新依赖、无额外模型调用（仍复用回答的那一次 JSON 输出）。

## 1. 先解决命名：`summary` 与 `memories`

r80 让模型输出 `memory`（一段文字摘要）。r81 要再加 `memories`（一组事实），**只差一个字母**：

```json
{"reply": "...", "memory": "...", "memories": ["..."]}
```

模型极容易把数组塞进 `memory`、或把字符串塞进 `memories`。而 `TaifuDraftReply.memory: str`
收到 list 会直接校验失败 → 整次回答失败（用户看到的是报错，不是回答）。

所以先把 r80 的字段改名：

| r80 | r81 | 含义 |
| --- | --- | --- |
| `memory: str` | `summary: str` | 线程摘要（本次对话的压缩） |
| — | `memories: list` | 长期记忆候选（跨对话的事实） |

**数据库列名保留 `memory`**（`taifu_threads.memory`）：列名不参与模型交互，为它做一次迁移不值得。
代码里统一叫 summary，`db.py` 里留一行注释说明这处历史命名。

## 2. 存储：为什么是「多条」而不是再一个单行

```sql
CREATE TABLE IF NOT EXISTS taifu_memories (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL DEFAULT 'default',
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_taifu_memories_user ON taifu_memories (user_id, created_at);
```

- 摘要必须**单行**（滚动重写、整体替换）；
- 长期记忆必须**多条**：一条记「时间约束」，一条记「已排除的方向」，它们是并列的，混成一段就没法单条删。

`TAIFU_MEMORY_LIMIT = 20` 是**存储层**护栏：即使调用方忘了裁剪，写入后也会按
`created_at DESC` 保留最近 20 条。上限存在的理由不是省钱，而是 20 条之后提示词里那一段会
从「我记得你是谁」变成「又一份档案」，反而稀释档案本身。

## 3. 去重：字面包含即同一件事

```python
def _memory_key(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]", "", text).lower()

def sanitize_memories(raw, existing) -> list[str]:
    keys = [key for key in (_memory_key(item) for item in existing) if key]
    ...
    if any(key == old or key in old or old in key for old in keys):   # 与已有重复
        continue
    if any(key == new or key in new or new in key for new in kept_keys):  # 同批重复
        continue
```

- 归一化只去空格标点、ASCII 大小写：**故意不做语义相似**（没有 embedding，也不想为一个 20 条的表引依赖）；
- 「互相包含」比「相等」重要得多：模型每次重述同一件事都会换措辞，
  「只能周末学习」与「用户只能周末学习，工作日要上班」如果都记，后面的条目就会挤掉别的；
- 每条夹到 80 字、短于 6 字丢弃（`好的`/`是的` 没有信息量）、每轮最多 2 条。

**每轮 2 条**是个产品判断：一次说十件事是自述，不是对话；限量会逼模型只挑最值得记的。

## 4. 提示词：四个「理解用」的段，只有档案是依据

```
【档案】
[1] 最近诊断（href: /report）
- 薄弱：AI 工程 · 部署与推理 · 错误率 60%（3/5）→ /report#weakness-1

【长期记忆】（用户口头说过、档案里没有的背景与偏好；不是依据，不能当引用出处）
1. 只能周末学习，工作日要上班
2. 已排除算法岗，只找应用开发

【早期对话摘要】用户目标是 AI 应用工程师；已建议先补部署与推理。
【当前页面】医案（诊断报告）（/report）—— 短板、薄弱分组…
【最近对话】
...
【问题】那这周怎么排

长期记忆：只有当用户这一轮**明确说出一条跨对话仍然成立、且【档案】与【长期记忆】里都没有的**
事实或偏好时…才用 memories 字段输出…
另外：把【早期对话摘要】与【最近对话】…用 summary 字段输出更新后的摘要…
```

系统提示词第 6/7 条分别约束摘要与长期记忆，措辞一致：**「不是依据」「冲突时以档案为准」**。
第 7 条还写了「不能从里面挑引用」——与 r78 页面上下文同一句话的变体。

空记忆时写 `MEMORIES_NONE = "（无）"`，不留空段头：空段头会让模型以为「有记忆但没读到」。

## 5. 记忆不是依据（程序层，不靠提示词）

`sanitize_reply` 的 `allowed` 仍然只由档案段（含 r79 锚点）构建，`memories` / `summary` / `page`
都没有参与。测试 `test_memories_are_never_a_citation_source` 锁的是：
模型在 `citations` 里给一个只在记忆里出现的 `/history` → `citations == []`、`dropped_citations == 1`。

## 6. 写入时序与两种清空的区别

```python
payload["summary_used"] = bool(summary)
payload["memories_used"] = len(memories)
if not payload["reply"]:
    return TaifuReply(**payload)           # 空回答：消息、摘要、记忆都不写
insert_taifu_message(...)                   # user
insert_taifu_message(...)                   # assistant
if overflow:                                # r80：摘要只在窗口溢出时更新
    ...save_taifu_summary(...)
new_memories = policy.sanitize_memories(draft.memories, [item["content"] for item in memories])
for content in new_memories:
    repository.insert_taifu_memory(content)  # r81：与线程长度无关
```

清空语义（刻意不对称）：

| 操作 | 对话 | 线程摘要 | 长期记忆 |
| --- | --- | --- | --- |
| `DELETE /api/taifu/thread`（清空对话） | 清 | 清 | **留** |
| `DELETE /api/taifu/memories`（忘掉全部） | 留 | 留 | 清 |
| `DELETE /api/taifu/memories/{id}`（忘掉一条） | 留 | 留 | 删这一条 |

「清空对话」是「忘掉我们聊过什么」，「忘掉记忆」是「忘掉我是谁」——混在一起会让用户
一次手滑丢掉两类不同价值的东西。

## 7. 界面：可审计是硬要求

一个「会记住你」的功能，如果不给查看与删除，就是不诚实的。所以面板里必须有入口：

- 入口文案 `记忆` / `记忆 · N 条` / `记忆 · 空`。**没读过时不报数字**（不猜条数）；
- **展开才读**（与线程同一口径：收起态零请求）；
- 每条右侧「忘掉」；底部「全部忘掉」，两步确认（与「清空对话」同一交互语言）；
- 本轮 `memories_added > 0` 时，在 meta 行追加「记住 N 条新事实」——记忆是**用户该被告知的事**；
- 记住后把列表缓存置空，展开态立刻重拉（不能让旧数组冒充最新条数）。

布局上记忆块放在**消息流末尾**（随内容滚动），不放 footer：footer 展开一个列表会把输入框
顶出固定高度的面板。初版还给列表加了 `max-height` + 内部滚动，实测两个滚动条导致
「第 3 条被自己的滚动条藏住、『全部忘掉』被挤出面板」——已去掉内滚动，改由面板主体统一滚，
并让展开动作也触发滚到底（`memoriesOpen` / `memories.length` 进 scroll effect 依赖）。

## 8. 测试

后端（`tests/test_r77_taifu.py`，+12 条，文件内 40 条）：

| 用例 | 锁什么 |
| --- | --- |
| `sanitize_memories_clamps_dedupes_and_caps_per_turn` | 与已有/同批互相包含去重、每轮上限 2 条 |
| `sanitize_memories_rejects_too_short_and_clamps_long` | 短句丢弃、长句截到 80+`…` |
| `prompt_carries_long_term_memories_as_a_numbered_list` | 编号清单 + 空记忆占位 |
| `memories_are_never_a_citation_source` | 只在记忆里的 href 被丢弃并计数 |
| `chat_stores_long_term_memory_even_on_a_short_thread` | 第一轮就记（与溢出无关） |
| `next_turn_carries_memories_into_the_prompt` | 下一轮 `memories_used = 1` 且提示词含清单 |
| `duplicate_memory_is_not_stored_twice` | 同一句第二次说不多一条 |
| `memory_list_is_capped_and_drops_the_oldest` | 23 条写入后只剩 20 条、最旧被淘汰 |
| `forget_one_memory_keeps_the_rest` | 单条删除 + 重复删幂等返回 0 |
| `forget_all_memories_keeps_thread` | 忘掉记忆不动对话 |
| `memory_is_isolated_per_account` | 换账号读不到；拿别人的 id 删不掉（`id + user_id` 双条件） |
| `memories_require_login` | 401 |

前端：无新增纯函数（`memoriesLabel` 在组件内，靠浏览器脚本覆盖）；`lib/taifuChat.test.ts` 不变。

真实浏览器（`logs/teamflow/r77-taifu-chat/scripts/check.cjs`，+4 组，共 14 组）：
展开才读、列出事实 → 新回答记住 1 条并当场告知 + 列表刷新到 3 条 → 单条忘掉只剩 2 条 →
「全部忘掉」两步确认后回到空记忆。

## 9. 已知限制

- 记忆质量靠模型自觉：漏记与记错程序都发现不了（只能靠用户看列表时自己删）。
- 去重是字面包含，不做语义：「我只有周末有空」与「工作日完全没时间」会存成两条。
- 20 条按时间淘汰，不按重要性：早期的重要约束可能被后来的琐事挤掉。
- 不可编辑，只能忘掉重记。
