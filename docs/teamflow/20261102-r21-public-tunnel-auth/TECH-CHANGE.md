# r21 · 公网自用访问与移动端导航修复（技术变更单）

> 目标形态：后端仍跑在**本机**（SQLite 与 `.env` 里的真实 Key 都不出本机），用内网穿透把
> `${WEB_PORT:-8080}` 暴露到公网，手机用 HTTPS 直接访问。本轮同时修掉手机端实测到的
> 「三个工具页没有入口 / 顶部步骤条点不准」两个缺陷。

## 1 背景与范围

触发场景：手机（鸿蒙 7.x，390×844）经 Cloudflare quick tunnel 访问本机 compose 实例。

两条立项理由：

1. **公网暴露必须有鉴权闸门**。端口一旦经隧道暴露，任何拿到 URL 的人都能读简历、看报告，
   并用 `backend/.env` 里的真实 Key 刷额度。`frontend/nginx.conf` 此前没有任何鉴权。
2. **移动端点不开工具页**（功能缺失，不是尺寸问题）。`<1024` 时 `.sc-sidebar { display:none }`，
   而 `ToolNav`（练习 / 成绩趋势 / 简历润色）此前只渲染在侧栏内，手机上完全没有入口；
   顶部步骤条又按 r1 DESIGN §1.2 只留 5 个圆点（每项 16 高、文字被 `clip-path` 隐藏）。

本轮**不含**：云服务器迁移、named tunnel 固定域名、画像/报告任务化（202 + 轮询）、
后端与 HTTP 契约、任何前端业务功能。

## 2 改动面

| 文件 | 改动 | 行为影响 |
| --- | --- | --- |
| `frontend/nginx.conf` | server 层新增 `auth_basic` + `auth_basic_user_file` | 页面、`/api`、`/health` 全部要求凭据 |
| `docker-compose.yml` | `frontend` 只读挂载 `./frontend/.htpasswd:/etc/nginx/.htpasswd:ro` | 密码文件不进镜像、可单独轮换 |
| `.gitignore` | 排除 `frontend/.htpasswd` | 密码不入库 |
| `frontend/.dockerignore` | 排除 `.htpasswd` | 密码不进构建上下文 |
| `scripts/gen-htpasswd.sh`（新） | `openssl passwd -apr1` 生成/更新密码文件 | 本地运维动作，非运行时 |
| `scripts/tunnel.sh`（新） | `cloudflared tunnel --url http://localhost:${WEB_PORT:-8080}` | 本地运维动作，缺 cloudflared 时给安装提示后退出 |
| `frontend/src/App.tsx` | `.sc-topstepper` 内新增 `<ToolNav items={TOOL_ITEMS} orientation="horizontal" />` | <1024 出现三个工具页入口；桌面该容器本就隐藏 |
| `frontend/src/styles/tokens.css` | append-only 新 `:root` 块：`--touch-min: 44px` | 仅新 token，不改既有变量 |
| `frontend/src/styles/base.css` | 文件末尾追加 `@media (max-width:1023px)` 段 | 仅移动断点生效；桌面规则一字未改 |
| `docs/teamflow/20261102-r21-public-tunnel-auth/**` | 新增任务夹（DEPLOY-PUBLIC / DESIGN-MOBILE / 本单 / 验收） | — |
| `docs/teamflow/memory.md` | 新增「公网自用访问约定」整条 | — |

契约（`backend/app/schemas.py` / `frontend/src/api/types.ts`）、后端代码、seed、依赖：**零改动**。

## 3 方案

### 3.1 Basic Auth 放在 nginx server 层

```nginx
auth_basic           "Skill Coach";
auth_basic_user_file /etc/nginx/.htpasswd;
```

选 server 层而非 `location /api` 的原因：

- 页面本身也含简历/报告内容，只保护 API 没有意义；
- 页面与接口**同源**（`/api` 由同一 nginx 反代），浏览器对同源请求自动携带凭据，
  **前端零改动**，也不会出现「401 HTML 被前端当 JSON envelope 解析」的问题；
- `/health` 一并受保护；容器内部 healthcheck 直连 `backend:8000`，不受影响。

密码文件生命周期（**刻意不入库**）：

1. `scripts/gen-htpasswd.sh` 用 `openssl passwd -apr1` 生成（APR1，nginx 原生支持），默认随机密码；
2. 写入 `frontend/.htpasswd`，被 `.gitignore` 与 `frontend/.dockerignore` 双向排除；
3. compose 以 `:ro` 挂载到 `/etc/nginx/.htpasswd`。

**文件缺失不是静默放行**：docker 会把缺失的源创建成同名空目录，nginx 启动时读到目录直接报错退出。
这是刻意的失败路径——宁可起不来，也不允许无鉴权上线。

仅本机 `vite` 开发（`:5173`）不经过这个 server，开发体验不受影响。

### 3.2 隧道脚本与超时约束

`scripts/tunnel.sh` 只做一件事：`cloudflared tunnel --url http://localhost:${WEB_PORT:-8080}`。
quick tunnel 自带 HTTPS（`navigator.clipboard` 只在 secure context 可用，http 公网地址下
报告页「复制 Markdown」必失败）。URL 每次重启都变，固定域名需 named tunnel + 自有域名。

Cloudflare 免费隧道边缘对长响应约 100s。当前云端 DeepSeek 档：`AI_TIMEOUT_S=20`、
`AI_MAX_RETRIES=1`，报告最多 2 处 AI 调用（其中一处 `asyncio.gather` 并行），
最坏 ≈ 80s < 100s，**故本轮不做任务化**。若切回本地 LM Studio 档（实测单次画像 201–224s）
必撞边缘超时，届时必须先做 202 + 轮询，或改 frp 直连自建 VPS。nginx 自身
`proxy_read_timeout 1300s`（r9 为本地模型所留）不是瓶颈。

### 3.3 移动端导航与触控

- **入口**：复用同一份 `TOOL_ITEMS`，把 `<ToolNav orientation="horizontal" />` 放进
  `.sc-topstepper`；组件早已支持横向（`ToolNav.tsx` 的 `orientation` 参数），此前只是从未接线。
- **尺寸**：`--touch-min: 44px`（Apple HIG 44pt / Material 48dp 的下限口径；取 44 而非 48，
  因为 390 宽下 8 个导航项横排，48 会让单屏可见项更少）。
  - 顶部条总高 **53 = 44（项）+ 4×2（`--sp-1` padding-y）+ 1（底边线）**；
  - 导航项宽 **104 = dot 16 + gap 8（`--sp-2`）+ 4 字标签 56 + padding-x 12×2（`--sp-3`）**；
  - 内容宽 **852**，超出 390 ⇒ `overflow-x: auto` + `overscroll-behavior-x: contain` +
    隐藏滚动条（触屏靠手势滑）；实测页面级 `scrollWidth` 仍为 390，无横向溢出。
- **步骤文字**：`<1024` 下取消 `clip-path: inset(50%)` 那套「只留圆点」的口径，恢复文字显示。

### 3.4 刻意未改的两处

| 目标 | 现值 | 理由 |
| --- | --- | --- |
| `--btn-h` 主按钮 | 40px | 被 `--iq-composer-h = 156`（padding 12×2 + 输入框 84 + gap 8 + 按钮行 40）等固定高推导引用；移动断点抬到 44 会让内容高 160 > 156、粘性输入区被裁。要改必须重算整条 composer 链条，属独立需求 |
| `--chip-h` 筛选 chip | 24px（实测渲染 32） | 练习页筛选区单屏最多 24+ 个 chip，抬到 44 会把筛选区撑成数屏、反而更难用；36–40 才是合理折中，需真机确认后再定 |

## 4 验证

```powershell
cd frontend
npm run typecheck   # exit 0
npm run lint        # exit 0，0 error / 28 warnings（等于既有 --max-warnings 28 基线）
npm test -- --run   # 10 文件 / 136 passed
npm run build       # exit 0（101 modules，dist 产物见 vite 输出）

docker-compose config --quiet   # exit 0
```

390×844 的实测数据（注入新 CSS 后测量）见本夹 `DESIGN-MOBILE.md` §3：
步骤项 16 → 44、步骤文字隐藏 → 5 项全部可见、工具项 44、顶部条 `scrollWidth 852 / clientWidth 390`、
页面级 `scrollWidth` 仍 390。

未执行（受环境所限）：容器实际起停与隧道端到端（需 Docker Desktop + cloudflared）、
真机复测（见验收 P3）。

## 5 风险与回滚

- 风险 1：忘记跑 `scripts/gen-htpasswd.sh` ⇒ nginx 起不来（刻意失败，按 §3.1 提示处理）。
- 风险 2：quick tunnel URL 每次变，手机书签失效；需固定则上 named tunnel。
- 风险 3：Basic Auth 凭据会被浏览器记住；只用于自用、不外发链接。
- 回滚：删 `nginx.conf` 两行 `auth_basic*` + compose 挂载（会失去公网鉴权，不建议）；
  移动端回滚删 `base.css` 末尾 r21 媒体段、`tokens.css` 的 `--touch-min` 块、`App.tsx` 那一行
  `ToolNav`，即回到 r20 基线（同时会重新失去手机上的三个工具页入口）。

## 6 文档与记忆

- 部署操作与排障：本夹 `DEPLOY-PUBLIC.md`。
- 移动端尺寸推导与实测：本夹 `DESIGN-MOBILE.md`。
- 跨需求约定：`docs/teamflow/memory.md` §团队约定「公网自用访问约定」。
