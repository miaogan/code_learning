# TECH-PLAN · r41 图片简历入口 + 报告转 7 天学习计划

> 配套：同目录 `PRD.md`。本文件回答三个问题：**视觉能力到底有没有、要花多少钱（§1）**、**A 怎么接进现有链路（§2）**、**B 用什么方案排程（§3）**。
> 原则：先给结论与代价，未拍板不动代码。

---

## 1. 决策点 1：图片识别用什么（需拍板）

### 1.1 现状核实（读代码得出的事实）

| 事实 | 位置 | 结论 |
|---|---|---|
| AI 调用只发纯文本：`messages` 的 `content` 是 `str`，只有 `system` + `user` | `backend/app/services/ai/ai.py` L84–L98、L152–L174 | 当前代码**没有**多模态请求能力 |
| 配置档只有 `legacy` / `deepseek` / `lmstudio`，字段是 `base_url / model / api_key / json_mode / timeout_s` | `backend/app/core/config.py` L137–L150、`resolve_ai()` L192–L240 | **没有**视觉模型配置项 |
| 本机 `.env` 指向 `https://api.deepseek.com/v1` + `deepseek-chat` | `backend/.env` | 当前跑的是文本模型 |
| 简历抽取只支持 `pdf/docx/txt`，PDF 读文本层、DOCX 读段落 | `backend/app/services/resume/parser.py` L20–L68、L92–L127 | **没有**图片分支、也没有 OCR |
| 依赖清单里无 Pillow / OCR 库 | `backend/requirements.txt` | 无图像处理能力 |

### 1.2 外部核实（DeepSeek 官方文档，2026-11 现状）

- Chat Completions 的 `content` 支持块数组，图片用 `image_url`（base64 data URL 或公网 URL）。
- **`deepseek-flash` 支持图像理解**；同名价位表明确 **`deepseek-v4-pro` 不支持图像理解**。旧名 `deepseek-v4-flash-vision-exp` 已下线，请求由最新 Flash 承接。
- 支持格式：JPEG / PNG / GIF / WebP（**按文件真实内容判断**，不看后缀/MIME）。
- 图片只能出现在 `user` 消息里；`system/assistant` 带图会 400。
- 每张图在进入模型前会被缩放：小图放大、大图缩到约 1300×1300；**每图 token 上限 1024**，多图各自独立计。
- 限制：单图 inline / URL ≤32 MiB，请求体 ≤48 MiB，单请求 ≤600 张；`detail` 可选 `low(512×512) / high / original / auto`。

### 1.3 结论

> **不需要引入第三方视觉供应商或云 OCR。现有 DeepSeek 账号本身就是视觉供应商**：同一个 `base_url`、同一把 `api_key`，只把模型名换成 `deepseek-flash` 即可。代价是「一个配置项 + 请求体支持内容块数组」，不是「接一个新系统」。

注意两点差异，避免踩坑：

1. `.env` 的 base_url 带 `/v1`，官方示例是不带 `/v1` 的 `https://api.deepseek.com`。两条路径在 DeepSeek 上都可用，但**实施时必须先用一条最小请求实测**（`/v1/chat/completions` + `deepseek-flash` + 1 张小图），失败再切不带 `/v1`。不要假设。
2. 现有 `deepseek-chat` 是不是已经别名到 Flash（若已别名，可能直接就能吃图）**不确定**。方案不依赖这个猜测：视觉请求**显式指定** `AI_VISION_MODEL=deepseek-flash`。

### 1.4 成本核算（按官方价位表换算）

| 项 | 单价（元 / 百万 tokens） | 一次上传（2 张图）用量 | 单次成本 |
|---|---|---|---|
| 输入（缓存未命中） | 空闲 1 / 高峰 2 | 2 × ≤1024 = 2048 tokens | 0.002 / 0.004 元 |
| 输出 | 空闲 4 / 高峰 8 | 约 1000–1500 tokens | 0.004–0.012 元 |
| **合计** | — | — | **≈0.007 元（空闲）/ 0.014 元（高峰）** |

- 单张图 ≈ 0.004–0.008 元；**1 万次上传 ≈ 70–140 元**，相对画像生成（大 JSON 输出）可忽略。
- 成本可控的三个闸门：单批 ≤3 张、总量 ≤10MB、前端把最长边压到 1600px（超过 1300 也会被服务端再缩，压图只为省流量与失败率）。
- **不做** `detail: low`：512×512 会让密集排版的简历文字糊掉，省下的钱不值一次失败重试。

### 1.5 若部署环境没有视觉模型（分支方案，不静默降级）

| 路径 | 做法 | 代价 | 评价 |
|---|---|---|---|
| **A1（推荐）** | 复用 DeepSeek + `AI_VISION_MODEL=deepseek-flash` | 1 个配置项 + 多模态请求体 + 1 个 service | 成本近零、无新供应商、隐私口径不变 |
| A2 | 自建/内网 OpenAI 兼容网关的视觉模型（`AI_VISION_BASE_URL/API_KEY/MODEL` 独立可配） | 网关需具备视觉模型；配置多 3 项 | 适合私有化部署，代码同一套 |
| A3 | 第三方云 OCR（百度/腾讯/阿里） | 新供应商合同 + 图片**外发第三方**（隐私口径要重新评估）+ 按次计费 + 返回纯文本无版式 | 仅在 A1/A2 都不可用时兜底 |
| A4 | 本地 OCR（PaddleOCR/Tesseract） | 依赖重（模型包百 MB 级）、中文简历双栏/表格识别质量不可控 | **否决**（正是需求里说的「别硬塞 OCR 草草了事」） |
| — | 视觉未配置时 | 返回 `AI_UNAVAILABLE` + 中文「图片识别未开通，请改用 PDF 上传」，**前端明确提示、不静默降级** | 必做分支 |

---

## 2. 功能 A 技术方案

### 2.1 数据流

```
手机相册/相机
  → <input type=file accept="image/*">（拍照带 capture，选图带 multiple）
  → 前端 canvas 预处理：EXIF 方向校正 → 最长边 1600 → JPEG(0.85)
  → POST /api/resumes/images   （multipart，字段 files: UploadFile[]，1–3 张）
  → routers/resume.py：只做「数量/大小/格式」校验 + 调 service + 错误映射
  → services/resume/image_resume.py：逐张 → AI 视觉抽取 → 拼接（【第 n 页】）→ 质量判定
  → repository.insert_document(meta, text, mime)   ← 只存正文，图片字节丢弃
  → 返回 ResumeMeta（source_type=image, image_count=n）
  → 前端沿用现有流程：生成画像（r30 异步任务）→ 后续面试/笔试/报告
```

### 2.2 后端改动

| 文件 | 改动 | 说明 |
|---|---|---|
| `core/config.py` | `AiRuntime` 增 `vision_model / vision_base_url / vision_api_key / vision_timeout_s`；`resolve_ai()` 读 `AI_VISION_*`，缺省回落到主配置 | `vision_model` 非空才启用图片入口 |
| `services/ai/ai.py` | 抽 `_post_chat(payload)`；`complete_model` 保持原签名（零迁移）；新增 `complete_vision(system, user_text, image_data_urls, timeout_s, retry_unavailable)` 组装内容块数组 | 不改既有调用方 |
| `services/resume/image_resume.py`（新） | `extract_resume_text(images: list[bytes], ai) -> ParsedResume`：逐张调用、拼接、`chars < 60` 判不足 | 提示词要求「逐字转写、保留换行、无法辨认标 `[无法辨认]`、**禁止补写/猜测**」 |
| `services/resume/parser.py` | 增 `IMAGE_SUFFIXES` 与 `is_image_name()`；`parse_resume` 对图片 suffix 抛「请走图片入口」（保持纯函数） | 不改原有 PDF/DOCX/TXT 行为 |
| `routers/resume.py` | 新端点 `POST /api/resumes/images`（`files: list[UploadFile]`），校验 1–3 张、单张/总量 ≤ 现有 `max_upload_bytes()`；错误映射到既有码 | **新增端点而不是改旧端点**：旧 `POST /api/resumes` 契约零变化，避免破坏存量客户端与测试 |
| `services/ai/usage.py`（若存在） | 视觉调用同样记 `ai_usage`（model / tokens / 耗时） | 便于核算成本 |

错误映射（**全部复用既有闭集码**）：

| 分支 | code | message（示意） | retryable |
|---|---|---|---|
| 视觉未配置 | `AI_UNAVAILABLE` | 图片识别暂未开通，请改用 PDF 上传 | false |
| 张数 >3 / 0 张 | `VALIDATION_ERROR` | 一次最多上传 3 张图片 | false |
| 格式不支持（非 JPEG/PNG/WebP） | `UNSUPPORTED_TYPE` | 仅支持 JPG / PNG / WebP 图片 | false |
| 超限 | `FILE_TOO_LARGE` | 图片超过 10MB，请压缩后重试 | false |
| 抽取字数 < 60 | `VALIDATION_ERROR` | 识别到的文字太少，请重拍（正对、光线充足）或改用 PDF | false |
| 模型超时/5xx | `AI_UNAVAILABLE` | 图片识别超时，请稍后重试 | **true** |
| 图片解码失败 | `PARSE_FAILED` | 这张图片打不开，请重新拍照或改用 PDF | false |

### 2.3 契约变更（两侧同步）

`schema.py`：
```python
# ResumeMeta 追加（带缺省值，存量响应不变）
source_type: Literal["pdf", "docx", "txt", "image"] = "pdf"
image_count: int = 1          # 仅 source_type=image 时有意义
```
`frontend/src/api/types.ts`：
```ts
export interface ResumeMeta {
  resume_id: string
  file_name: string
  chars: number
  sections: number
  source_type: 'pdf' | 'docx' | 'txt' | 'image'
  image_count: number
}
```
`api/client.ts` 增 `uploadResumeImages(files: File[])`：`FormData.append('files', f)` 逐个追加。
JSON 全 snake_case；错误 envelope 不变。

### 2.4 前端改动（`UploadPage.tsx`）

1. **两个隐藏 input**：`captureImageRef`（`accept="image/*"` + `capture="environment"`，单选）与 `pickImageRef`（`accept="image/*"` + `multiple`，最多 3）。入口按钮沿用 `.sc-btn`，r40 已保证移动端 ≥44。
2. **预处理**：`<img>` 解码（浏览器默认按 EXIF 方向渲染）→ `canvas` 等比缩到最长边 1600 → `toBlob('image/jpeg', 0.85)`；解码失败（HEIC/损坏）→ `VALIDATION_ERROR` 文案「这张图片打不开，请重新拍照或改用 PDF」。
3. **缩略图列表**：每个 56×56（新 token `--thumb-size`），右上删除按钮视觉 20、**命中 44**（用透明 padding 外扩），最多 3 个，超限禁用「+ 添加」。
4. **提交**：走新的 `uploadResumeImages`；进度卡沿用 `.sc-upload-progress`（环在左、文字在右），阶段文案加「识别图片中」；完成后沿用 r30 异步画像。
5. **失败**：`InlineError` + 「重试识别」（整批重试）；错误文案原样来自 envelope，不含路径/Key。
6. **布局**：窄屏图片入口与文档入口同一列，图片入口不把主 CTA 挤出首屏；≤430 与 r40 的 `.sc-lab-drop-cta` 独占行规则共存。

### 2.5 尺寸推导（遵守 AGENTS §4：新增尺寸必须算清）

| 新 token | 值 | 推导 |
|---|---|---|
| `--thumb-size` | 56 | 360 宽内容区 328（r40：360 − 16×2）；3 张 + 2 间隙 = 3×56 + 2×8 = 184 ≤ 328，留出删除命中区与「添加」位；56 = 7×8，落在 4 基准网格 |
| `--plan-task-min-h` | 56 | padding 8×2 + 标题 --lh-small 20 + gap 4 + meta 16 = 56，且 ≥ `--touch-min` 44（整行为可点区） |
| 时长选择 | 复用 `--lab-chip-h` 28（桌面）/ r40 的 44（移动） | 不新增第三档高度 |
| 计划进度轨 | 复用 `--qa-track-h` 6 | 不新增 |

> 这两个 token 是**新增**，不改 `--btn-h / --iq-composer-h / --iq-scroll-pad` 等既有推导链；后续实施时把推导回写 DESIGN-MOBILE 增补节。

### 2.6 隐私与安全

- 图片字节只在请求内存中存在：`await file.read()` → base64 → 调模型 → 丢弃；**不写临时文件**。
- `documents` 表只存 `text / file_name / mime`（既有表结构不动）。
- 日志只记 `image_count / bytes / chars / model`，不打印正文与 data URL。
- 单账号无频率限制（现状），成本闸门靠 3 张 + 10MB；若担心滥用，在 `routers/resume.py` 加「同一 user 每分钟 N 次」需另开需求（本轮不做，列风险）。

---

## 3. 功能 B 技术方案

### 3.1 三个可选方案

| 方案 | 做法 | 优点 | 代价 | 结论 |
|---|---|---|---|---|
| **B1** | 纯前端确定性排程：`report` + 教程目录（`frontend/src/content/tutorials`）+ 时长偏好 → 计划；打卡与偏好存 localStorage | 零后端改动、零契约变更、离线可用、无 AI 成本 | 换设备不同步 | **推荐本轮** |
| B2 | 后端持久化：新表 `study_plans` + `POST/GET/PATCH` 端点 | 跨设备同步 | 教程目录在前端，服务端只能存「前端算出的 JSON」黑盒；+1 表 +3 端点 +双向契约；校验弱 | 需要跨设备时再做 |
| B3 | 后端 AI 生成计划 | 文案更像「教练」 | 不稳定、可能编造章节、每次生成有成本与延迟，且报告页要等 AI | 否决 |

> 选择 B1 的硬理由：**「对应到具体教程章节/小节」的目录只存在于前端**（`frontend/src/content/tutorials/*.ts`）。把计划搬到后端，等于把目录复制一份到服务端 seed 或让前端上传目录，两个方向都是新增同步负担。本轮先用 B1 把闭环补上；若之后确需跨设备，按 §3.6 的 B2 迁移路径做。

### 3.2 现有实现与差距

- 现有 `frontend/src/lib/reportPlan.ts` 的 `buildWeekPlan(report)`：7 天固定骨架，前 3 天用薄弱分组给「专项练习 + 最多 2 门课程（外链）」，后 4 天是固定通用任务；**无时长、无章节映射、无依赖、无时长偏好**。
- 现有 `WeekPlan.tsx`：按天打卡（`weekplan:<userId>:<reportId>`），已有进度显示。
- **本轮不是重写，是升级**：保留 `WeekPlan` 的卡片与打卡壳，替换数据源为 `studyPlan.ts`。

### 3.3 数据模型（纯前端，`frontend/src/lib/studyPlan.ts` 新建）

```ts
export type TaskKind = 'tutorial' | 'practice' | 'review'

export interface StudyTask {
  id: string          // `tutorial:<chapterId>:<sectionId>` | `practice:<direction>` | `review:<reportId>`
  kind: TaskKind
  title: string
  est_min: number     // 15/20/25/30/45/60
  direction: string | null
  chapter_id: string | null
  section_id: string | null
  href: string        // 站内路由；教程为 /learn/<chapterId>#tutorial-<sectionId>
  reason: string      // 「短板：xxx（高）」「前置：先补基础」
  shortfall: string | null
}

export interface StudyDay { day: 1..7; minutes: number; tasks: StudyTask[] }

export interface StudyPlan {
  version: 1
  report_id: string
  daily_minutes: 15 | 30 | 60
  days: StudyDay[]
  updated_at: string
}

export interface PlanState {           // 与计划分开存，避免重算丢打卡
  version: 1
  daily_minutes: 15 | 30 | 60
  done: Record<string, true>           // 按 task.id
}
```

存储：
- 计划快照 `sc.plan.<userId>.<reportId>`（`StudyPlan`）
- 打卡与偏好 `sc.planState.<userId>.<reportId>`（`PlanState`）

为什么拆两个 key：改时长会重算 `days`，但**已完成的 task.id 要保住**；合并存会导致每次重算覆盖打卡。

### 3.4 排程算法（确定性，可单测）

**输入**：`report`（`weakness_map` 优先，`shortfalls` 兜底）、教程目录、`daily_minutes`、已读小节（`sc.learn.<userId>`）。

1. **候选池**：`weakness_map` 每条 → 一个短板候选，权重
   `w = severity(direction 最高)` + `essentiality` + `(1 − rate)`；无 `weakness_map` 时用 `shortfalls.severity` 映射。
2. **方向归一**：复用 `services/report/courses.py` 的思路（`DIRECTION_HINTS`），前端维护一份同口径映射表；匹配不到 → 该短板只产 `practice` 任务。
3. **依赖代理**：教程章有 `direction + level`（基础/进阶/高级）但**没有显式前置字段** → 用「同方向 level 递进」作为前置代理：若计划里选了进阶章且该方向基础章未读，先插一条「先读基础章」任务（`reason` 写明是前置）。**在 PRD/UI 上不宣称这是「真实课程依赖」**。
4. **任务生成**：每个短板最多 2 个任务（1 个教程 + 1 个练题）；教程指向该章**第一个未读小节**（已读则下一节；整章读完则跳过教程任务、只留练题）。
5. **时长门槛**：
   - 15 分钟档：只排 1 个任务/天，只取「练题 15」或「读一节 15」；
   - 30 分钟档：1–2 个任务/天（15 + 15，或 30）；
   - 60 分钟档：2–3 个任务/天（30 + 30，或 20 + 20 + 20）。
6. **装箱**：按权重降序，贪心塞入当天预算；塞不下顺延次日；7 天排不完的任务截断（不跨周），并在末日卡片显示「本周排不完，下周继续」。
7. **补位**：若高权重任务不足 7 天，用「回看诊断（10–15 min）」「重做错题（15 min）」补位，且 `reason` 标注「通用建议」——**绝不编造短板名**。

### 3.5 降级与边界

| 情形 | 行为 |
|---|---|
| 报告有 `weakness_map` | 正常排程 |
| 只有 `shortfalls` | 用 severity 排序，练题为主，教程按方向匹配 |
| 两者都空 | 显示「本次数据不足以定位短板」，给 3 个**标注为通用建议**的任务 |
| 方向无对口章节 | 保留练题，章节位显示「暂无对口章节」 |
| 教程目录里章 id 失效 | 任务降级为练题，不生成坏链接（单测兜住） |
| 报告未生成 | 不渲染计划模块（保持现有空态） |

### 3.6 打卡与「不影响成绩」的落实

- 打卡只写 `sc.planState.*`，**不调用任何 API**；`profile / report / runs` 表零写入。
- 页面固定一行说明：**「打卡只记录学习动作，不改变诊断分数与熟练度」**（口径与 r25「只记读过不记掌握」一致）。
- 与 `sc.learn.<userId>` 的关系：**只读**已读小节用于「跳过/标记已读」，不反写阅读进度（文章页仍是唯一写入方）。
- 若选 B2 迁移：新增 `study_plan_tasks(user_id, report_id, task_id, done_at)`，仍**不**进入评分链路。

### 3.7 尺寸与样式

- 计划卡沿用 `.sc-card`；任务行 `min-height: var(--plan-task-min-h)`（新 token 56，推导见 §2.5）。
- 时长选择复用 `.sc-chip.is-clickable` 的 44 触控规则。
- 窄屏单列；任务行整行可点；`href` 用站内路由，不新开窗。
- 新增类名沿用 `.sc-` 前缀（`sc-plan-*`），颜色/间距只取 tokens。

---

## 4. 实施拆分（不含工期，按依赖排序）

**A**
1. 配置与 AI 客户端：`AI_VISION_*` + `complete_vision`（先跑 1 张图的最小实测，确认 `/v1` 路径与 `deepseek-flash`）。
2. `image_resume.py` + `POST /api/resumes/images` + 错误映射 + 后端 pytest。
3. `ResumeMeta` 两侧契约同步。
4. 前端图片入口 + canvas 预处理 + 缩略图 + 上传/重试 + 进度阶段。
5. 窄屏验收（360/390/430）。

**B**
1. `studyPlan.ts`：类型 + 排程 + 补位 + 降级（纯函数，先写单测）。
2. `reportPlan.ts` 退役或收薄（保留旧导出避免断裂，标记 deprecated 后删）。
3. `WeekPlan.tsx` 改数据源 + 时长选择 + 任务粒度打卡 + 进度 + 口径声明。
4. 单测：预算不超、7 天非空、排序、依赖代理、降级、id 稳定（重算保留打卡）。
5. 窄屏验收。

**收尾**：`TECH-CHANGE.md`、`QA-REPORT.md`、更新 `AGENTS.md` 变更记录。

---

## 5. 验证方案

| 层 | 命令 / 方法 | 通过标准 |
|---|---|---|
| 后端 | `python -m pytest -q`、`python -m ruff check app tests` | 全绿；新增图片分支有用例（张数/超限/字数不足/未配置视觉） |
| 契约 | 对照 `schemas.py` 与 `types.ts` | 字段名、缺省值、snake_case 一致 |
| 前端 | `npm run typecheck` / `npm run lint` / `npm test` / `npm run build` | typecheck 0、lint `--max-warnings 0`、vitest 全通过、build 成功 |
| 接口手测 | 1 张清晰截图 / 2 张正反 / 空白图 / 11MB 图 / HEIC / 关掉 `AI_VISION_MODEL` | 分别命中 A-4/A-5/A-6/A-3/A-3/A-7 |
| 真机窄屏 | 复用 `docs/teamflow/20261108-r40-mobile-usable/REAL-DEVICE-CHECKLIST.md` 的片段 ②③④ | 无越界、触控 ≥44、键盘不遮挡 |
| 成本 | 看 `ai_usage` 里 vision 调用的 token 记数 | 单次 2 张 ≤ 0.02 元（按峰值价回算） |

---

## 6. 风险与未决

| 风险 | 影响 | 缓解 |
|---|---|---|
| `deepseek-chat` 与 `deepseek-flash` 的调用路径差异（`/v1` vs 无 `/v1`） | 实施后第一枪可能 404/400 | 先做最小实测再写 service |
| 视觉模型对「密集排版/双栏/表格」的识别质量未知 | 用户拿到残缺正文 | 3 组真实样本实测；字数阈值 + 重拍指引；不承诺结构完整 |
| HEIC（iPhone 相册原图） | 前端解码失败 | canvas 兜底文案 + 引导用 PDF；真机验证 iOS |
| 无频率限制 | 被刷成本 | 3 张 + 10MB 闸门；如需限流另开需求 |
| 「前置依赖」没有真实数据 | 排序解释不严谨 | 明确以「难度递进」为代理，UI 不宣称真实依赖 |
| B1 不跨设备 | 用户换手机丢计划 | 页面不承诺「多设备同步」；需要时按 §3.6 迁 B2 |
| 计划任务过多导致 7 天排满仍学不完 | 挫败感 | 15/30/60 三档 + 末日提示「下周继续」 |

## 7. 待拍板（三件）

1. **D1 视觉供应商**：是否确认走 A1（复用 DeepSeek `deepseek-flash`，单次约 0.7–1.4 分钱）？
2. **D2 图片上限**：3 张（含「正面 + 项目页」场景）是否可接受？
3. **B 方案**：本轮 B1（纯前端 + 本地持久化，**不跨设备**）是否可接受，还是必须一次做到 B2 后端持久化？

---

## Sources

- [DeepSeek 图像理解文档](https://api-docs.deepseek.com/zh-cn/guides/vision/)
- [DeepSeek 模型与价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)
- [DeepSeek Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)
