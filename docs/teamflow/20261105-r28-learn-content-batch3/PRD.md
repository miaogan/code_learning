# r28 — 学习模块第三批内容扩充（24 → 32 章）

## 背景

r24 将教程扩到 8 方向 × 3 档 = 24 章后，用户反馈「学习模块里的数据太少」，要求继续补充内容。本需求为纯内容扩充：每个方向新增 1 章，共 8 章，不改动任何页面逻辑与筛选机制。

## 新增章节

| 方向 | 章节 id | 难度 | 主题 |
|---|---|---|---|
| 前端 | `fe-typescript` | 进阶 | TypeScript 类型系统实战（联合类型与收窄、判别联合、穷尽性检查） |
| 后端 | `be-auth-session` | 进阶 | 认证与会话管理（Session vs JWT、bcrypt 密码存储、refresh token） |
| SQL 与数据库 | `sql-schema-design` | 基础 | 表结构设计：范式与反范式（订单项引用 vs 快照） |
| 中间件与运维 | `mw-docker` | 基础 | 容器化与 Docker 基础（镜像分层、多阶段构建、dockerignore） |
| 算法与数据结构 | `algo-binary-tree` | 基础 | 二叉树与递归（四种遍历、递归三问、BFS/DFS 选择） |
| 计算机基础 | `cs-io-model` | 进阶 | IO 模型与零拷贝（五模型、select→epoll、sendfile、ET/LT） |
| AI 工程 | `ai-agent-tools` | 进阶 | Agent 与工具调用（循环骨架、工具设计四规则、步数上限） |
| 研发工程实践 | `eng-refactoring` | 进阶 | 重构与代码坏味道（坏味道清单、小步节奏、提炼函数示例） |

结构沿用既有约定：每章 4 节（概念 → 规则/对比 → 可运行示例 → 常见坑与自测），末节必带 `qa` 折叠自测。排序交给 r24 的「方向 × 难度」排序视图，内容文件内追加位置无关。

## 档位分布

全库 32 章：基础 11 / 进阶 13 / 高级 8。每个方向 4 章、三档齐全不变。

## AC

1. `typecheck / lint / test / build` 全绿；既有教程测试（ID 唯一、表格列数、末节自测、每方向三档、目录排序单调）对新章节自动生效并通过。
2. 新章节与题库方向名严格一致（复用 `TUTORIAL_DIRECTIONS` 闭集）。
3. 代码块语言标注真实（sql / dockerfile / python / ts / javascript）。

## 改动清单

- `frontend/src/content/tutorials/{frontend,backend,sql,middleware,algorithms,cs,ai,engineering}.ts`：各追加 1 章，头注释同步。
- `docs/teamflow/20261105-r28-learn-content-batch3/`：本任务夹。
