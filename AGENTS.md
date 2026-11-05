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

<!-- teamflow:begin -->
## TeamFlow 托管区（本块由 TeamFlow 自动维护，团队请勿手改）

- 团队文档根：docs/teamflow/（每需求一个任务夹 + memory.md + architecture/）
- 运行日志：logs/teamflow/<runId>/（run 期间的项目内暂存；run 结束由 host 归档到 $DSH_HOME/teamflow/<workspace>/logs/<runId>/，项目内不留存）
- 需求/任务/缺陷 backlog：持久化镜像位于 $DSH_HOME/teamflow/<workspace>/（按工作区/项目隔离）
- 规则：TeamFlow 只维护本块、docs/teamflow/ 与 logs/teamflow/；本文件其余内容为团队资产。
<!-- teamflow:end -->
