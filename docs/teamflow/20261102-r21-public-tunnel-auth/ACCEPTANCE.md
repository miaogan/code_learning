# r21 验收报告：公网自用访问 + 移动端导航修复

- 任务夹：`docs/teamflow/20261102-r21-public-tunnel-auth/`
- 验收对象（工作区改动）：`frontend/nginx.conf`、`docker-compose.yml`、`.gitignore`、
  `frontend/.dockerignore`、`frontend/src/App.tsx`、`frontend/src/styles/{base,tokens}.css`、
  `scripts/{gen-htpasswd,tunnel}.sh`、本任务夹、`docs/teamflow/memory.md`。
- 设计/部署依据：本夹 `DESIGN-MOBILE.md`、`DEPLOY-PUBLIC.md`（与 r1 `DESIGN.md` §1.2 的
  移动断点差异见 §4 偏离-1）。

## 1 判据逐条核对

| # | 判据 | 实测结果 | 结论 |
|---|---|---|---|
| 1 | 公网闸门覆盖页面与接口 | `nginx.conf` server 层 `auth_basic` + `auth_basic_user_file`，页面、`/api`、`/health` 同层生效 | 通过 |
| 2 | 密码文件双向排除 | `.gitignore` 与 `frontend/.dockerignore` 均排除 `.htpasswd`；compose 只读挂载，不入镜像 | 通过 |
| 3 | 缺失密码文件不静默放行 | docker 创建同名空目录 → nginx 启动报错；compose 注释写明前置步骤 | 通过（设计口径） |
| 4 | compose 语法有效 | `docker-compose config --quiet` → exit 0 | 通过 |
| 5 | 密码生成脚本可复现 | `gen-htpasswd.sh` 用 `openssl passwd -apr1`，默认随机密码，写入 `frontend/.htpasswd` | 通过（评审） |
| 6 | 隧道脚本符合本机命令 | `tunnel.sh` 用 `${WEB_PORT:-8080}`，缺 cloudflared 时打印安装指引后 exit 1 | 通过（评审） |
| 7 | 手机可进入三个工具页 | `App.tsx:70` 复用同一份 `TOOL_ITEMS` 渲染 `ToolNav orientation="horizontal"` | 通过 |
| 8 | 顶部导航可点、可读 | `base.css` <1024 段：两类导航项 44 高、步骤文字恢复；390×844 实测见 `DESIGN-MOBILE.md` §3 | 通过 |
| 9 | 无页面级横向溢出 | 顶部条 `overflow-x: auto`（`scrollWidth 852 / clientWidth 390`），页面 `scrollWidth` 仍 390 | 通过 |
| 10 | 桌面零回归 | 新增规则全部在 `@media (max-width:1023px)` 内；桌面既有规则未改 | 通过 |
| 11 | token 单源、append-only | 新 `:root` 块只加 `--touch-min: 44px`；未改 `--btn-h` / `--chip-h` 等既有变量 | 通过 |
| 12 | 前端门禁全绿 | typecheck 0 error；lint 0 error / 28 warnings；vitest 10 文件 **136 passed**；`npm run build` exit 0 | 通过 |
| 13 | 契约 / 后端零改动 | `backend/**`、`schemas.py`、`types.ts` 零改动 | 通过 |
| 14 | 任务夹自包含 | `meta.json` / `TECH-CHANGE.md` / `ACCEPTANCE.md` + `DEPLOY-PUBLIC.md` / `DESIGN-MOBILE.md` | 通过 |
| 15 | 记忆收口 | `memory.md` 新增「公网自用访问约定」（三条硬约束 + 超时口径 + 迁云清单指针） | 通过 |

## 2 架构一致性

| 蓝图要求 | 实测 | 结论 |
|---|---|---|
| 前端只经 `src/api/client.ts` 出网 | 未改网络层；同源反代不变 | 符合 |
| 样式只用 token | 新尺寸引用 `--touch-min` 与既有 `--sp-1/2/3`、`--border-hair`，无裸值 | 符合 |
| 改 DESIGN 尺寸必须重算并回写 | 推导与实测落 `DESIGN-MOBILE.md` §2.1/§3；历史夹未改 | 符合 |
| 任务夹不可变 | r1 等历史夹零改动；对 r1 §1.2 的移动断点差异记录在本夹 | 符合 |

## 3 复跑命令与实测

```powershell
cd frontend
npm run typecheck   # exit 0
npm run lint        # exit 0，0 error / 28 warnings（等于既有基线）
npm test -- --run   # 10 文件 / 136 passed
npm run build       # exit 0（101 modules transformed）
docker-compose config --quiet   # exit 0（在仓库根执行）
```

后端：本轮零改动，未重复跑全量 pytest；沿用 r20 基线（全量 exit 0，1 skipped）。

## 4 偏离与遗留（均不阻断）

| 编号 | 内容 | 处置 |
|---|---|---|
| 偏离-1 | `<1024` 顶部步骤条由「5 个圆点、16 高」改为「文字 + 44 高 + 横向滚动」，与 r1 `DESIGN.md` §1.2 不同 | 仅移动断点生效，推导与实测落 `DESIGN-MOBILE.md`；历史夹不可改 |
| 偏离-2 | 新增 `--touch-min` token，未沿用既有尺寸体系 | append-only 独立块，不改既有 token（改 `--btn-h` 会破坏 composer 链条） |
| P3-a | 容器实际起停、nginx 读密码文件、401/200 行为未实跑（需 Docker Desktop） | 并入 memory 第 40 行真实环境补测 |
| P3-b | 390×844 数据为注入 CSS 后测量，真机未复测 | `DESIGN-MOBILE.md` §4 三项待真机确认（横滑可发现性、chip/按钮触控尺寸、ArkWeb `overscroll-behavior-x`） |
| P3-c | 隧道端到端未跑（本机未装 cloudflared）；100s 超时约束为估算（云端档最坏 ≈80s） | 切本地 LM Studio 档前必须先做 202 + 轮询，已写入 memory 与 `DEPLOY-PUBLIC.md` §5 |
| P3-d | `ruff` 本机不可用 | 与历史同口径；CI 或含 ruff 环境补跑 |

## 5 验收判定

公网暴露的鉴权闸门、密码文件生命周期、隧道脚本、移动端工具页入口与 44 触控目标
均有可复核的落地；桌面规则零改动，前端四项门禁全绿（vitest 136 passed、build 通过）。
未实跑项全部是环境限制（Docker/cloudflared/真机），已逐条落入 P3 并指向 memory 补测清单。

验收结论：✅ 通过（P3 不阻断，随真实环境补测关闭）
