# 技术方案与变更记录 · r107

## 来源与合规

- 官方来源：`https://atomgit.com/alibabaclouddocs/aliyun_acp_learning`，仓库根 `LICENSE` 为 Apache-2.0，
  允许再分发；中文教程位于 `大模型ACP认证教程/`。
- 抓取方式：`git clone --depth 1`（仅一次性中间产物，落在 gitignore 的 `.tmp/`，不提交）。
- 题目定位：各 notebook markdown cell 末尾「🔥 课后小测验」下的 `<details>` 折叠块，
  四段结构固定：`<b>` 题干 / `- A.` 选项 / `✅ 参考答案` / `📝 解析`。
- 解析脚本 `.tmp/parse_acp_quiz.py`（不入仓）用正则抽四段，HTML 标签与 md 强调符清理；
  注意原文写的是 `解析**：`（冒号前有两个星号），正则需允许 `解析\*{0,2}\s*[:：]`。
- 转录只清理标记，不改写技术结论；来源与许可证登记在 `PROVENANCE.md` §10。

## 字段归属

- 官方题：`source=acp-official`、`id=acpof-%03d`；原创题：`source=acp-ext`、`id=acpext-%03d`。
- 全部 `direction="AI 工程"`、`language=""`，显式合法 `sub_direction`：
  - 官方 32：Agent 14 / 通用 AI 7 / LLM 与 RAG 6 / Prompt 工程 3 / 部署与推理 2。
  - 原创 18：Agent 9 / 通用 AI 4 / LLM 与 RAG 3 / 部署与推理 2。
- 题型：官方 29 单选 + 3 多选；原创 18 单选。难度 / 必备度逐题标注，无越界值。

## 原创题的取材纪律

- 事实依据只取教程**正文明确陈述**的知识点（如 3.4 三种记忆策略、3.5 Skills-as-Code 与
  按需加载、3.8 Harness/Loop 闭环、4.1 数据合成蒸馏三步、4.3 TTFT/TPOT 与上下文缓存、
  4.4 纵深防御与黑名单局限），不凭常识扩写。
- 初稿 34 道中 16 道与官方小测验同考点换问法（Ragas Precision、句子窗口、MCP、
  部署选型等），主动剔除，避免题库同一考点复现两遍；最终保留 18 道独立考点。
- 4 道正确项长度比 >3 的题，通过压缩正确项 + 加长干扰项修正（`OPTION_REWRITES`），
  不动知识点与答案，最终全库 length>3x = 0。

## 合并与门禁

- `question_merge.py` 的 `SOURCES` / `STAGING_FILES` / `ID_PREFIX` 同步登记两个新来源，
  `SOURCE_PRIORITY` 仍直接引用 `SOURCES`，优先级语义不变。
- 沿用 `normalize_record()`、字面查重、字符 2-gram Jaccard 0.62 近重复门禁、
  `question_shuffle.apply()`、`question_bank.load_seed()` 复核与 `ensure_seeded()` 启动导入。
- 选项数不写死：`question_merge._OPTION_KEYS` 与 `question_shuffle.ALL_KEYS` 同为 `A–F`，
  每题按自身选项数取前缀重编 key；2 道 5 选项多选题（acpof-008 / acpof-031）正常重排，
  解析字母引用按同一映射同步改写。配套扩展判角正则支持 `B.D.E.` 点分隔清单与 `A. 是错误的`
  句式（此前这两处会把字母判为「无法判角」而跳过整题）。单选题位置轮转仍限 A–D，
  故存量 260 行的分布与基线哈希不受影响。
- 题面 / 契约零改动：`source` 不进 HTTP 契约；无 SQL、无运行时 import 离线工具。

## 实际改动

- 新增 `docs/question-bank-staging/14-acp-official-quizzes.json`（32 道）与
  `15-acp-v24-extension.json`（18 道）。
- 修改 `backend/app/services/assessment/question_merge.py`：登记两个来源 / 素材 / 前缀。
- 重算落盘 `backend/app/seed/questions.json`：1284 → 1334 道。
- 测试随题库基数更新：`test_question_bank_quality.py`（来源枚举 / 计数 / 总量 + 两批分布用例）、
  `test_r12_question_merge.py`（EXPECTED_TOTAL 1334、来源计数、added/read 1074、回滚文案、
  `R13_SEED_SHA256` 因通用桶选项轮转刷新为 `c3254c31…69b977`，字节数仍 199377）、
  `test_r11_practice_service.py`（真实 seed 导入 1334）、
  `test_r13_question_shuffle.py`（选项 key 改为按 `ALL_KEYS` 前缀断言；新增
  `test_shuffle_keys_align_with_merge_schema` 钉住两处 key 全集对齐、
  `test_five_option_questions_are_shuffled_not_skipped` 防「选项数写死」回归）。
- `docs/question-bank-staging/PROVENANCE.md` 追加 §10 / §11。

## 存量数据不变性核对

对比 `git show HEAD:backend/app/seed/questions.json` 与新 seed 的前 260 行：
题干变化 0、选项文本集合变化 0；25 道题的选项 key 发生确定性轮转（正确答案文本仅换字母位），
1 道解析同步改写字母引用。属通用桶新增触发的全局均衡等长改写，与 r47/r48/r55 同类，
非历史数据篡改。

## 回滚

```bash
cd backend && python -X utf8 -m app.services.assessment.question_merge --rollback
# 删除全部 15 个登记来源（含 acpof- / acpext-），保留存量 260 行；幂等，再跑删 0 行
```
