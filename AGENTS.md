# AGENTS.md — 团队协作守则与文档索引（dev-skill-coach 产品线）

> 任何新加入本产品的 Agent（团队成员）必须先通读本文件，再按 §2 文档索引读取相关文档与任务卡片，不要自行全量探索项目。
> 维护者：团队本身 + TeamFlow 研发流水线（TeamFlow 仅维护文末 <!-- teamflow --> 托管区，其余内容为团队资产，不得改写）。

## 1. 产品是什么

- 产品：帮助编程开发者提升实力的 Web 应用 —— AI 读简历建可溯源画像 → 模拟面试/笔试定位带证据的短板 → 诊断报告直连精选基础课程，首版跑通四步闭环。
- 产品根：本仓库根目录（当前工作区，仓库名 `code_learning`）；`products/<product>/` 是本工作区的产品线命名约定，本产品独占该仓库。
- 当前版本：0.1.0（2026-10-31 交付，脚手架阶段）。

## 2. 文档索引（按职责）

| 职责 | 位置 | 说明 |
|---|---|---|
| 产品入口 | README.md | 玩法/操作/运行/验收速览 |
| 任务产物 | docs/teamflow/<yyyyMMdd-rN-slug>/ | 一需求一自包含任务夹：PRD/设计/技术方案/QA 报告/验收报告 |
| 架构总览 | docs/teamflow/architecture/ARCHITECTURE.md | 技术选型与权衡、目录树、模块契约、依赖、构建/测试/CI、落地清单 |
| 产品记忆 | docs/teamflow/memory.md | 跨需求约定/技术栈/已知待办（低频更新） |
| 运行日志 | logs/teamflow/<runId>/ → $DSH_HOME/teamflow/<workspace>/logs/<runId>/ | 只放**要留存**的东西（一次性检查脚本、结论笔记）；**不制造命令输出 dump**；run 期间在项目内暂存，run 结束由 host 归档并从项目删除 |

## 3. 团队角色与标准流程

**角色**：产品经理 / UI/UX 设计师 / 架构师 / 高级全栈工程师 / QA 测试工程师。

**标准流程**：需求 → PRD →（UI 改造时）UI/UX 设计 →（新项目时）架构规划 → 技术方案 → 并行开发 → QA 测试 → 产品验收。

**产出物落盘约定**：每个需求的所有产物写入该需求的任务夹 `docs/teamflow/<任务夹>/`；`ARCHITECTURE.md` 与 `memory.md` 是产品级长期文档。**除实际产品代码改造与 AGENTS.md 托管区外，TeamFlow 只在 `docs/teamflow/` 与 `logs/teamflow/` 下写文件**，绝不写入宿主 `docs/<职责>/` 或项目根。

**完成度自查**：每个环节交付前对照职责清单自查，未完成不得流转；架构师对新项目必须实际初始化脚手架文件与 AGENTS.md。

## 4. 工程约定

- **代码形态**：`frontend/`（React 18 + Vite 5 + TypeScript strict，手写 CSS + token）+ `backend/`（FastAPI + SQLite，标准库 `sqlite3` 直连）。两侧无共享代码，契约只有 HTTP JSON 一种。
- **契约同步（硬约束）**：任何字段变更必须同时改 `backend/app/schemas.py` 与 `frontend/src/api/types.ts`；JSON 字段名一律 snake_case（Python 侧零转换）。
- **错误形态**：全部经 `{ "error": { "code", "message", "retryable" } }`，`message` 中文、不含路径/堆栈/端点/Key；错误码闭集见 ARCHITECTURE §3.3。
- **样式**：只用 `frontend/src/styles/tokens.css` 的变量，禁止裸色值与裸尺寸；改 DESIGN §0.7 任一尺寸必须重算推导并回写设计文档。
- **验证命令**：前端 `npm run typecheck` / `npm run lint` / `npm test` / `npm run build`；后端 `python -m pytest -q` / `python -m ruff check app tests`；探活 `GET /health`。
- **测试放置**：前端 `frontend/src/**/*.test.ts`（vitest）；后端 `backend/tests/`（pytest，`pythonpath=["."]`）。
- **不提交**：`node_modules/`、`dist/`、`.venv/`、`*.db`、`.env`（`.env.example` 可提交）。
- **隐私**：上传文件不落原文件，只存抽取正文；模型 Key 只在 `backend/.env`。

## 5. 变更记录

- 2026-10-31：创建本文件（TeamFlow 脚手架，含架构与工程约定初版）。
- 2026-11-05：学习模块补齐题库缺失的 3 个方向（中间件与运维 / SQL 与数据库 / 研发工程实践），章节增加「基础 / 进阶 / 高级」难度档位，目录页支持方向 → 难度两级筛选；内容扩到 8 方向 × 3 档 = 24 章（产物见 `docs/teamflow/20261105-r24-learn-directions-levels/`）。
- 2026-11-05：学习模块新增阅读进度（r25）：小节级已读记录（`sc.learn.<userId>` 按账号隔离的 localStorage）、目录页进度条与「继续学习」入口、文章页 `#tutorial-<sectionId>` 断点续读；进度只记「读过」不记「掌握」，不进后端、不计成绩（产物见 `docs/teamflow/20261105-r25-learn-progress/`）。
- 2026-11-05：文章页新增章内目录（r26）：`TutorialToc` 在宽屏常驻右栏、窄屏折叠，当前小节由第二条 IntersectionObserver 观察带（视口上部 40%）推导并高亮，已读小节打 ✓ 且与进度条同源；报告页方向卡的「站内教程」入口显示已读完章数（产物见 `docs/teamflow/20261105-r26-learn-toc/`）。
- 2026-11-05：无简历引导修复（r27）：「未上传简历」弹框会话标记迁 `sessionStorage`（修 StrictMode 双跑不弹 / 整页刷新重弹），登出清理只认「已登录 → null」跳变；上传页与成绩趋势空态加免简历出口（练习 / 教程），门禁旁路扩为练习 + 教程（产物见 `docs/teamflow/20261105-r27-noprofile-guidance/`）。
- 2026-11-05：学习模块第三批内容扩充（r28）：8 方向各增 1 章（TypeScript 类型系统、认证与会话、范式与反范式、Docker 基础、二叉树与递归、IO 模型与零拷贝、Agent 与工具调用、重构与坏味道），教程扩到 32 章（基础 11 / 进阶 13 / 高级 8），纯内容不改逻辑（产物见 `docs/teamflow/20261105-r28-learn-content-batch3/`）。
- 2026-11-05：上传页中途离开保护（r29）：上传/生成中刷新或关闭走浏览器原生提示、站内链接先确认再跳，卸载兜底中止在途请求（r30 异步化后拦截收窄到文件上传窗口）（产物见 `docs/teamflow/20261105-r29-upload-leave-guard/`）。
- 2026-11-05：画像生成异步化（r30）：新增 `profile_jobs` 表与 `POST /api/resumes/{id}/profile/async`（`asyncio.create_task` 后台跑 `generate_profile`，终态落库可见）、`GET /api/profile-jobs/{job_id}`（轮询）与 `GET /api/profile-jobs/latest`（回上传页自动接上）；同步 POST 契约不变。上传页生成阶段改为 2 秒轮询，离开页面任务照跑、回来自动接上，离开保护收窄到文件上传窗口；一次性 `merge_summary` 随任务落库不因异步丢失（产物见 `docs/teamflow/20261105-r30-profile-async-job/`）。
- 2026-11-05：上传失败可见性（r32）：用户反馈「上传失败没有报错提示」——真实复验确认同步错误路径本就正常，洞在异步化之后：回上传页时 failed 的 latest 任务被静默忽略、服务重启留下永远 running 的僵尸任务行。修复：任务读路径惰性清扫（running 超过 10 分钟按 failed 落库中文原因），重接入时 failed 任务明示原因 + 重试（产物见 `docs/teamflow/20261105-r32-upload-failure-visibility/`）。
- 2026-11-05：失败提示语义与时效（r33）：用户反馈「后台接口只有 200 但还是失败」——异步任务端点 200 仅代表受理/查询成功，成败在 body.status；r32 的 failed 提示无时效导致历史失败永久常驻。修复：`shouldSurfaceFailure` 加 24 小时窗口（过期旧失败不打扰、时间不可解仍提示），失败文案改为「简历已上传成功，但画像生成失败：<原因>」（产物见 `docs/teamflow/20261105-r33-failure-notice-window/`）。
- 2026-11-05：画像生成超时治理（r34）：用户实测「AI 服务响应超时」——画像生成输出大 JSON，吃全局 20s 超时（实测 1048 字简历已需 11s），且超时不在重试范围。修复：`generate_profile` 用专用 `PROFILE_TIMEOUT_S=120s` 并开启 `retry_unavailable`（超时/5xx/429 自动重试一次；鉴权/额度不重试；前台交互调用默认不重试）（产物见 `docs/teamflow/20261105-r34-profile-timeout/`）。
- 2026-11-05：上传页进度卡左右布局（r35）：用户反馈进度条展示仍有 bug——`.sc-upload-summary` 是 column flex，环形进度作为直接子项独占一行贴左上角，文字全部竖挤在下、卡片右半边空白（上传中/生成中/重接入三态皆然）。修复：新增 `.sc-upload-progress`（环在左垂直居中、阶段文字在右），两处进度卡包裹；同时修重接入「已用秒数」从 0 重计——新增 `jobElapsedSec`（按任务行 `created_at` 起算，不可解/未来时间戳按 0）（产物见 `docs/teamflow/20261105-r35-upload-progress-layout/`）。
- 2026-11-05：进度环偏心修复 + 润色专用超时（r36）：用户再报进度条有问题且润色超时——截图放大确认 indeterminate 环的旋转弧**甩出轨道**：Chrome 对 SVG 子元素的 CSS transform 动画，`transform-origin` 无论 view-box 还是 fill-box 解析枢轴都不在圆心。修复：动画移到 `<svg>` 根元素（常规盒模型，origin=center 严格为自身中心），circle 的 `rotate(-90 28 28)` 属性保留（determinate 弧不受影响）；`resume_polish.build_suggestions` 加 `POLISH_TIMEOUT_S=120s` + `retry_unavailable`（与 r34 同策略，实测 8.6s 返回 200）（产物见 `docs/teamflow/20261105-r36-ring-pivot-and-polish-timeout/`）。
- 2026-11-08：图片简历上传 + 报告转 7 天计划（r41）：①新增 `POST /api/resumes/images`（1–3 张 JPG/PNG/WebP，按真实字节嗅探格式），复用主档 DeepSeek 账号的视觉能力（`AI_VISION_MODEL=deepseek-flash`，端点/Key/超时留空继承主档），逐页转写后拼成一份简历共用一个 `resume_id`，汇总 `<60` 字判识别不足给重拍指引，视觉未开通明确报「图片识别未开通，请改用 PDF 上传」；图片字节只在内存流转、只入库正文，旧 `POST /api/resumes` 契约零变化（仅 `ResumeMeta` 补 `source_type` / `image_count` 缺省字段）。②报告页「7 天学习计划」换 `studyPlan.ts` 确定性排程（短板权重 → 教程小节/练习映射 → 15/30/60 分钟装箱 + 通用任务补位），任务粒度打卡与计划快照分两个 localStorage key，**界面明示计划不跨设备、打卡不计入熟练度与成绩**，`reportPlan.ts` 退役；新增 `--thumb-size` / `--plan-task-min-h` 两个 token，推导回写 DESIGN-MOBILE §6（产物见 `docs/teamflow/20261108-r41-image-resume-study-plan/`）。
- 2026-11-08：任务化与断连恢复 + HEIC 兜底（r42）：①图片识别异步化 —— 新表 `resume_jobs` + `POST /api/resumes/images/async`、`GET /api/resume-jobs/{job_id}`、`/latest`，r41 同步端点与 r30 同步画像端点原样保留；幂等靠部分唯一索引（画像 `(user_id, document_id)`、图片 `(user_id, sha256)`，只约束 running），存量重复 running 由 `init_db()` 先收敛再建索引。②卡死治理：r32 惰性清扫阈值 10→30 分钟（统一 AI 超时 600s + 重试一次，合法耗时可到 20 分钟），新增任务级 `asyncio.wait_for` 硬上限（画像 25 分钟、图片 `3×600s+300s`），图片任务每识别一页写心跳、按「无进展 10 分钟」判死；r33 24h 失败窗口与 r34 重试策略未改。③前端新增 `recognizing` 阶段与本地会话 `sc.upload.<userId>`（24h 失效）：重入先读本地会话（running 接上 / completed 30 分钟内回放 / failed 24h 内提示），再回落服务端 `latest`；断网给中文提示 + 「重试接上」，轮询不停止、不误判任务失败；`uploading` 的离开保护不变，后台阶段给出口不拦截。④HEIC：前端读文件头 `ftyp` 品牌提前拦截并给「设置 → 相机 → 格式 → 兼容性最佳 / 导出 JPG」路径；后端 `sniff_or_raise` 识别 HEIC → `UNSUPPORTED_TYPE` + 专用文案（无新增错误码）。实测桌面 Chromium 142 对真实 HEIC 样本 `decode-error`、后端嗅探判 HEIC；iOS Safari 相册转码行为无真机、标注测不了（产物见 `docs/teamflow/20261108-r42-task-recovery-heic/`）。
- 2026-11-08：自检迭代（r43）：①熟练度说明合并成一处 —— `ExamRun` 新增 `reintroduced_count`（= `|熟练 ∩ 本卷|`，与 `filtered_count` 互补；两侧同步且默认 0），卷面首行同时给「过滤事实 + 默认 30 天 / 答对 2 次的回流规则 + 另有 N 道因保持卷面结构被重新纳入」，结果面板复显同一事实；L2 把熟练题全部放回（净过滤 0）时也会提示，这是 r19「N=0 不解释」的真实缺口。②上传上限判断收敛到 `services/resume/parser.py::ensure_upload_size()`，文档 / 单张图片 / 图片合计共用，错误码仍 `FILE_TOO_LARGE`；前端 `10MB` 由 `MAX_UPLOAD_MB` 单点派生。③面试 `Composer` 字数计数与 405 中文化核对为 r5 O-2 / 2026-11-03 已交付，本轮不改。④`ARCHITECTURE.md` §7.2 删除过期条目（`pypdf`/`python-docx`/`ruff` 已装可实跑），测试文件数 31→38；CI 实跑与 iOS 真机 HEIC 仍留「未落盘」（产物见 `docs/teamflow/20261108-r43-self-audit/`）。
- 2026-11-09：题库粒度细化（r44）：用户要求「模拟面试 / 模拟笔试 / 学习」三处都能选到更细粒度。①闭集单源仍是 `rules.py::SUBDIRECTIONS`（8 方向 × 子方向），前端新增 `lib/questionDirections.ts` 逐字同源，笔试页不再内联字面量。②面试设定扩为 6 键，新增可选 `direction` / `sub_direction`（空串 = 不限，老 payload 缺键仍合法）；`settings_or_none` 越界一律 `None`，`fill_settings` 只清非法子方向，三层提示词注入（`calibration.focus` 三档措辞互不相同 + SYSTEM 硬性规则 + 每轮 settings）；开局表单新增「方向聚焦 / 二级方向」两组 chip，切换方向清空子方向。③学习 32 章全部补 `sub_direction`，目录页改为方向 → 子方向 → 难度三级筛选（换方向清子方向与难度、换子方向重置难度），URL `?sub=` 越界回落 `all`（产物见 `docs/teamflow/20261109-r44-question-granularity/`）。
- 2026-11-09：AI 工程教程内容扩充（r45）：用户要求补「模型基本原理 / 微调 / 蒸馏 / LangChain / LangGraph / AI 名词解释」。纯内容扩充、契约与筛选零改动：AI 工程 4 → 8 章（全库 32 → 36），新增 `ai-model-basics`（预训练 next-token、前向/反向/更新、手写梯度下降，基础）、`ai-finetune-distill`（全量微调 vs LoRA/QLoRA、SFT→RLHF/DPO、灾难性遗忘、知识蒸馏/数据蒸馏/量化，高级）、`ai-langchain-langgraph`（LCEL 流水线、StateGraph + 条件边 + checkpointer，进阶）、`ai-glossary`（训练/推理/工程三组名词 + 常见误解 + 易混辨析，基础）。**刻意不新增子方向**：闭集加项会让笔试/练习出现必空入口，新章按语义落进 `LLM 与 RAG` / `Agent` / `通用 AI`；三档仍有内容（基础 2 / 进阶 2 / 高级 2）（产物见 `docs/teamflow/20261109-r45-ai-tutorial-expansion/`）。
- 2026-11-09：模拟笔试子方向聚焦可用性修复（r46）：r44 的子方向筛选是**硬过滤**，导致 12 个子方向（图 1、链表 2、复杂度 4、排序 9、消息队列 7、索引 9 等）与 3 个零题子方向（组成原理 / NoSQL / 架构设计）在模拟笔试里必 400，且方向覆盖 ≥2 恒不可满足使任何聚焦卷永远落 L5、熟练度过滤失效。修复：①方向 / 难度仍是硬过滤，子方向改为**聚焦优先、不足补位** —— 先跑子方向窄池，凑不出结构达标的卷才退化到同方向宽池并计数；②方向聚焦时基线方向覆盖 2/1/0 降为 1/1/0（不传筛选时逐字节等价）；③`Paper` / `ExamRun` 双侧新增 `sub_direction` / `sub_direction_backfill`（默认 `""` / `0`），payload 同步落键；④前端新增 `subDirectionNotice` 纯函数（与 `filteredNotice` 同静默口径），作答中独立一行 + 结果面板 join 进透明度说明，明示「暂无可用题目已改按同方向出题」/「已补充 N 道同方向题」。已知限制：方向 + 难度组合题量不足时仍 400（刻意保留）（产物见 `docs/teamflow/20261109-r46-exam-sub-direction-focus/`）。

- 2026-11-09：AI 工程方向高阶题库扩充（r47）：用户目标「高级 AI 应用工程师」，新增 40 道生产实战题（挑战 30 / 进阶 10，单选 24 / 多选 11 / 判断 5），重点补最薄的「部署与推理」子方向（4 → 16）：连续批处理 / PagedAttention / 前缀缓存 / 投机解码 / 显存估算 / 多 LoRA 服务等，另覆盖 RAG 融合与索引迁移、约束解码与提示词版本化、Agent 幂等与审批、评测集泄漏与供应商切换回归。素材落 `docs/question-bank-staging/10-ai-engineering-advanced.json`（新来源 `ai-adv`、id 前缀 `aiadv-`），`question_merge` 支持素材显式声明 `sub_direction`（合法值随行落盘、老素材键序不变）；经 `--write` 重算，题库 1088 → 1128、AI 工程 157 → 197，`--check` 逐字节 0 差异。按 r18 先例刷新存量 260 行 sha256 基线（字节数仍 199377，仅选项位置序确定性轮转），并同步总量 / 来源计数门禁与两份工具报表；`pytest` 622 passed / 1 skipped，`ruff check app tests` 全过。

- 2026-11-09：AI 工程方向再补高难系统工程题（r48）：用户要求「多 Agent 编排 / RAG 评审 / harness 工程」等更高难度主题，新增 36 道**全 challenge** 题（单选 18 / 多选 14 / 判断 4），三组各 12 道，子方向 Agent 12 / LLM 与 RAG 12 / 通用 AI 12：多 Agent 侧重自由交接的循环转派、共享状态单写者与事件日志、全局预算与终止判据、同源自评偏差、并行归集尾延迟、追踪树与交接边、结构化输出契约、副作用幂等；RAG 评审侧重金标上下文对照实验做检索/生成归因、逐句蕴含与引用正确性拆分、裁判校准与位置偏差、拒答率权衡、配对比较与区间估计；harness 工程侧重可复现的版本锁定、被测与评分系统隔离、轨迹回放、工具沙箱、重试口径、并发限流误判、持续集成门禁波动带、评分器自检、多次采样通过率、失败分类体系。素材落 `docs/question-bank-staging/11-ai-engineering-systems.json`（新来源 `ai-sys`、id 前缀 `aisys-`），沿用 r47 已支持的显式 `sub_direction`；经 `--write` 重算，题库 1128 → 1164、AI 工程 197 → 233，`--check` 逐字节 0 差异。按 r18/r47 先例刷新存量 260 行 sha256 基线（字节数仍 199377，仅选项位置序确定性轮转），同步总量 / 来源计数门禁与两份工具报表。

- 2026-11-09：学习模块补 AI 工程高阶教程 + 计划按子方向选章（r49）：承接 r47/r48 的题库扩充，站内教程从 36 → **40 章**（AI 工程 8 → 12），新增 `ai-inference-serving`（部署与推理·高级：连续批处理 / 分页 KV 与前缀缓存 / TTFT 与 TPOT / 显存估算 / 多 LoRA 服务化 / 流式断连）、`ai-multi-agent`（Agent·高级：编排拓扑与显式状态机 / 共享状态单写者 / 全局预算与终止判据 / 幂等与权限隔离 / 追踪树）、`ai-eval-harness`（通用 AI·高级：金标上下文上界归因 / 裁判校准与位置偏差 / 评测集防泄漏与显著性 / 轨迹回放与沙箱 / 重试与并发口径 / 持续集成门禁）、`ai-prompt-engineering`（Prompt 工程·进阶：模板与前缀缓存 / 版本化灰度 / 约束解码边界 / 注入防护）；AI 工程 5 个子方向**首次全覆盖**，全库难度 基础 13 / 进阶 15 / 高级 12。②7 天计划改造：报告 `WeaknessItem` 新增**纯附加**字段 `sub_direction`（后端 `weakness.py` 取组内题目众数、越界留空、平局按 `rules.SUBDIRECTIONS` 顺序保证可复算；前端 `types.ts` 为可选字段兼容旧报告），`studyPlan.ts::pickChapter` 先在该方向同子方向章节里按「目标档位 → 就近低档 → 任意章」挑选，挑不到**静默回落**方向级（旧行为逐字等价）。分组 key、条数、排序、任务 id 形态与 `PLAN_VERSION` 均不变；报告页方向卡入口仍按方向跳转。契约同步硬约束已双侧落地，前后端各补 4 / 3 条新测试。

- 2026-11-09：练习子方向闭环 + 报告子方向可视化（r50）：承接 r47/r48/r49，把「题库 → 诊断 → 教程 → 练习」最后一处粒度断点接上。①**后端**：`PracticePaperRequest` / `PracticePaper` 双侧契约加 `sub_direction` / `sub_direction_backfill`（默认 `""` / `0`，老请求体逐字可用）；`practice.py` 新增 `_resolve_focus()`（空串/脏值静默忽略、direction=all 时自动锁定子方向父方向、与显式方向冲突则忽略），`_matches` / `_filtered` / `build_paper` / `stats` 支持二级方向，沿用 r46 的**聚焦优先、不足补位**：先取窄池，`limit` 不足时用**同方向**宽池补齐并计数，`hit_count` 仍是窄池命中数（与 `/stats.hit` 同源），补位事实由服务端中文 `notice` 单点产出。不聚焦时整条主路径逐字节等价，`/answer` 与 `/wrong-book` 不涉及筛选、零改动。②**前端**：练习页加第 6 组「二级方向」chip（未选方向给提示、换方向清空子方向），URL 增 `?sub=`（与学习目录页同名，越界静默回落），0 命中放宽建议、完成态筛选描述同步；作答态与完成态复显同一份服务端补位 `notice`。③**跳转**：`practiceHref` 支持 `sub_direction`，教程页底部、7 天计划练习任务、报告方向卡的练习链接都带上子方向。④**报告可视化**：`WeaknessMap` 每行用 `coach.ts::weaknessSubDirectionLabel()` 显示「方向 · 二级方向」chip（旧报告缺字段零占位）；`guidance.ts` 从 `weakness_map` 取该方向第一条非空子方向，`LearningDirectionCard` 的教程入口只在**该方向确有这一章**时才按子方向筛选，否则静默回落方向级。测试：后端练习服务 +5 / API +2，前端 practice +4 / coach +1 / guidance +2 / studyPlan +2；`PracticePaperRequest` 默认值与题单字段集合两处门禁基线同步刷新。题库种子与素材零改动。

<!-- teamflow:begin -->
## TeamFlow 托管区（本块由 TeamFlow 自动维护，团队请勿手改）

- 团队文档根：docs/teamflow/（每需求一个任务夹 + memory.md + architecture/）
- 运行日志：logs/teamflow/<runId>/（run 期间的项目内暂存；run 结束由 host 归档到 $DSH_HOME/teamflow/<workspace>/logs/<runId>/，项目内不留存）
- 需求/任务/缺陷 backlog：持久化镜像位于 $DSH_HOME/teamflow/<workspace>/（按工作区/项目隔离）
- 规则：TeamFlow 只维护本块、docs/teamflow/ 与 logs/teamflow/；本文件其余内容为团队资产。
<!-- teamflow:end -->
