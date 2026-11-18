# r125 · 验收报告（镜试 / 反向面试）

## 1. 功能验收

| 项 | 判据 | 结果 |
|---|---|---|
| AI 推荐题 | quote 过不了简历原文闸门的整条剔除并计数 | `test_suggestions_drop_unsourced_quotes` ✅ |
| 自拟问题复盘 | 四块内容完整落库，刷新后从列表恢复 | `test_ask_custom_question_persists_and_recovers` ✅ |
| AI 出题复盘 | 复用 AI 推荐的题目，`origin=recommended` | `test_ask_recommended_uses_ai_question_and_marks_source` ✅ |
| 数字闸门 | 简历查不到的多位数降级〈待补充〉，真实年份不误杀 | `test_ask_sanitizes_fabricated_numbers` ✅ |
| 证据闸门 | 无出处引用整条剔除，`dropped_evidence_count` 如实披露 | `test_ask_drops_unsourced_evidence` ✅ |
| 简历缺失 | 未知 id / 空正文一律 404 NOT_FOUND（中文 envelope） | `test_missing_resume_is_404` ✅ |
| AI 失败 | 失败在入库前抛错，不留半条记录 | `test_ai_failure_leaves_no_card` ✅ |
| 输入护栏 | 祈使式注入问题 422 GUARDRAIL_BLOCKED，且不落记录 | `test_injection_question_is_blocked` ✅ |
| 账号隔离 | 跨用户列表为空；他人 resume_id 提问 404 | `test_cards_are_isolated_across_accounts` ✅ |

## 2. 门禁执行结果

| 命令 | 结果 |
|---|---|
| `ruff check app tests` | All checks passed |
| `pytest -q`（全量） | 1262 collected，0 failed（junit：full-junit2.xml；首轮 1 failed 为 `source` 字段撞 r12 门禁，已改名 `origin` 修复） |
| `npx tsc --noEmit` | 通过 |
| `npm run lint` | 通过（0 warning） |
| `npm test -- --run` | 43 文件 / 551 passed（2 errors 为本机 fs shim 噪音，非测试失败） |
| `npm run build` | 通过（chunk 体积警告为既有） |

注：本机 esbuild 清理系统临时目录会被沙箱拦（`Access is denied`），构建需把 `TMP/TEMP/TMPDIR` 指向项目内 `logs/tmp`——纯环境问题，CI / 服务器不受影响。

## 3. 契约要点

- `POST /api/mirror/suggestions` → `MirrorSuggestions{resume_id, items[], dropped_count}`
- `POST /api/mirror/ask` → `MirrorCard{id, resume_id, file_name, question, answer, rationale[], assessment, follow_ups[], evidence[], missing_info[], origin, dropped_evidence_count, answer_sanitized, created_at}`
- `GET /api/mirror/cards?limit=` → `MirrorCardList{items[]}`
- 字段名纪律：**`origin` 而非 `source`**——r12 工程门禁钉住「`source` 只住在库里不进契约」，镜试沿用（`test_r12_source_not_in_http_contract` 全绿）。
- 存储：`mirror_cards`（JSON payload，双库幂等 DDL，进 `_STANDALONE_PROBE_TABLES`）。

## 4. 与既有模块的边界

- 不写 `runs` / `question_attempts` / `reports` / `timeline_events`，不进战绩、医案、成长时间线。
- 不复用 interview 状态机；只复用画像读取、heavy AI 出口、输入/输出护栏与账号隔离。
- 零遥测不变：唯一 AI 出口仍是服务端 / 用户自带 LLM（`user_ai.client_for(user, "heavy")`），无新增外部请求。
