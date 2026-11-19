# r133：先锋页易用性 + 中文简介入库前翻译

- 日期：2026-11-19
- 发起：用户反馈「先锋页面的易用性需要调整一下，把翻页按钮当到调整页面大小的旁边；还有英文翻译为啥是在前端触发的，不应该是在数据录入的时候就是翻译完再入库的吗」。
- 主题：**把 AI 副作用从渲染路径移回写入路径**——前端只读已经翻好的数据；翻不动时如实降级，不靠浏览器补刀。

## 1. 调查结论（为什么前端曾经会翻）

代码里并非「从来没在后端翻」：r74 起 `run_round` / `ingest_manual` 结束时会调 `_translate_round`。让它看起来像前端触发的是四个洞：

1. **顺序错位**：先 `store.upsert_tech(item)` 落英文，再批量回填 `summary_zh`，清单里存在可观察的中间态；
2. **批量上限**：每轮只翻 `RADAR_TRANSLATE_BATCH`（默认 20）条，本轮条目多时根本翻不完；
3. **定时轮缺口**：`_scheduled_round` 调 `run_round(user=None)`，`_translate_round` 见 `user is None` 直接返回 0；
4. **失败降级**：无 Key / 上游失败保留英文原文——合理，但把欠账永久留给了界面。

于是 r88 加了前端自动补翻（进页 / 翻页 / 改筛选各试一次），用户看到的就是「一进页面前端在翻」。**补翻是历史欠账的兜底，不该是主路径**。

## 2. 本轮改动

### 2.1 分页器与每页条数同处筛选条

- `PioneerPage.tsx`：`Pagination` 从清单列表下方移到 `.sc-radar-filterright` 内、每页条数 `Select` 右侧；只有一页时组件仍返回 `null`，筛选条不会多出一行。
- `base.css`：append `.sc-radar-filterright .sc-pager { margin-top: 0; }`（原 `.sc-pager` 的 `margin-top` 是给列表底部独立一行用的）。

### 2.2 翻译前移到入库前（写入路径）

- `repository.radar_upsert_tech`：`item["summary_zh"]` 存在时直接写该译文（与本次原文同批产生）；缺省仍走 r74 旧口径——原文变化清空旧译文、原文不变保留。
- `radar_translation_states(slugs)`：一次 IN 查询读回本轮旧原文 / 旧译文，供「原文没变且旧译文含中文」时直接复用，不重复烧 token。
- `translate.prepare_for_storage(items, client, states)`：纯函数式地为本轮条目备好译文，**不写库**：
  - 真英文 → 一次批量请求翻完（没有 20 条上限，覆盖本轮全部新条目）；
  - 本来就是中文 → 回填自身；
  - 旧原文相同且旧译文可用 → 复用；
  - 「标题即简介」（HN）→ 跳过，继续留给 r89 抓正文汇总，避免翻标题占掉汇总队列。
- `radar.run_round` / `ingest_manual`：先 `_translate_for_storage`，再把 `summary_zh` 随条目一起 `upsert_tech`；评估 / 快照 / 提示词指纹口径不变（`input_sha256` 不读译文）。
- `_ClientGate`：一轮只建一个 AI 客户端，翻译、模型细化、历史欠账清队列共用——共享 Key 不再因多调一次 `client_for` 多扣一次配额。
- 定时轮（`user=None`）改用服务端配置的 AI runtime；服务端 Key 不记到任何用户配额，端点仍走统一 `AIClient`，**不新增出网面**（r115 登记制守卫覆盖）。

### 2.3 前端只保留手动兜底

- 删除 r88 自动补翻 effect 与 `lib/radar.ts` 的 `autoTranslateKey`（及其单测）：进页 / 翻页不再触发翻译请求。
- 保留「翻译英文简介」按钮，仅在当前页存在历史欠账时显示；无 Key 时明确 503，由用户自己决定何时补。

### 2.4 顺手修掉一条既有门禁红

`base.css` 的 `.sc-delete-error` 是 r129 留下的 `var(--danger, #b42318)` 裸色值回退，违反 `test_no_raw_colors_outside_tokens`（`--danger` 在 `tokens.css` 中始终有定义）。改为 `var(--danger)`；与本轮样式 append 一并提交后，append-only 门禁看的是提交后的基线，因此不会把这条必要修正误判为「改了既有声明」。

## 3. 边界与未决

- **不是所有条目都能翻**：没配任何模型 Key、上游失败、模型回吐英文 / 漏条目时，`summary_zh` 留空并显示原文——这是 `translate.py` 从 r74 沿袭的「宁缺毋滥」，不为了覆盖率编造译文。
- **历史欠账仍在**：改造只保证「本轮之后入库的条目」已翻完；存量英文条目保留手动补翻按钮，不写一次性全库回填脚本（会烧一大笔 token 且无法回滚）。
- **服务端 Key 的双刃**：定时轮用管理员 Key 翻译会消耗服务端配额；若管理员不希望如此，留空 `AI_*` 即退回英文原文，不影响采集主流程。
- 「翻完再入库」是**同批写入**，不是「翻译成功后才允许采集成功」：翻译失败仍保留条目与规则结论，不能让英文摘要拖垮整轮采集。

## 4. 验证

- 后端专项：`test_r74_radar_translate.py` 新增 4 例（入库前译文随 upsert 落库 / 旧译文复用不调模型 / 定时轮走服务端客户端 / `_ingest_client(None)` 返回系统客户端）；雷达 r67/r89 与新增用例共 46 passed。
- 前端：`typecheck` / `lint` / `vitest` 600 passed（较 r132 少 1 例 = 删除 autoTranslateKey 单测）。
- 后端 ruff 全绿；全量 pytest 无 failed（工程门禁在提交后复跑，见 AGENTS 变更记录）。
