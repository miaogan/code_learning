# r115 内网 / 气隙部署：放行私网 AI 端点 + 零遥测

- 起始：2026-11-17
- 触发：用户报「自定义的 LLM API 提示不能指向内网」，并说明「需要在内网环境部署，有信息安全要求，不能出现任何遥测的功能」。
- 结论：第一条是 r99 的 SSRF 防护与内网部署形态**直接冲突**，需要加一个显式开关；第二条经审计**已经成立**，但此前只是口头承诺 —— 本轮把它变成可复跑的断言。

## 1. 为什么自定义端点被拦

`POST /api/me/ai/test` 会拿表单里的 `base_url` 直接发请求，所以 r99 给它加了 SSRF 门禁：
用户自带端点只能指向**公网**地址（`services/ai/user_ai.py::validate_ai_base_url`，
原名 `validate_public_base_url`）。公网部署这是必需的 —— 否则任何登录用户都能拿它探测内网端口。

但内网部署里模型就在 `http://10.x.x.x:8000/v1` 或 `http://localhost:11434/v1` 上，
不放行等于整个 AI 功能不可用。所以门禁本身没错，缺的是「部署形态」这个维度。

## 2. 方案：一个显式开关，两档语义

`AI_ALLOW_PRIVATE_ENDPOINTS`（默认 `false`）：

| 档位 | 私网 / 环回 | 云元数据 · 链路本地 | 适用 |
|---|---|---|---|
| `false`（默认） | 拒绝 | 拒绝 | 公网部署，沿用 r99 口径不变 |
| `true` | **放行** | **仍然拒绝** | 内网 / 气隙部署 |

放行内网却仍然拒绝元数据，是刻意保留的硬边界：内网机器常常就是云主机，
`169.254.169.254` / `100.100.100.200` 这类地址拿到的临时凭证比「内网端口」危险得多。
两个国内云的元数据地址被单独列进 `_METADATA_ADDRESSES`，因为 `ipaddress` 会把它们
归进 private / link-local 段，只按段判断挡不住。

**踩到的坑**：`localhost` 在测试机上优先解析成 `::1`，而 Python 的 `ipaddress`
把 `::1` 同时标成 `is_reserved` —— 先判 reserved 会直接挡掉「模型与后端同机」
这个最常见的单机形态。所以环回判断必须排在 reserved 之前（`_is_blocked_address()` 有注释钉住）。

两个入口一起生效：保存设置（`normalize_ai_settings`）与测试连接（`test_connection`），
否则会出现「保存能过、测试照挂」。启动时打一条 `[安全]` 日志留痕：

```
[安全] AI_ALLOW_PRIVATE_ENDPOINTS=true → 用户自带 AI 端点可指向私网 / 环回地址（内网部署专用；公网部署等于放开内网端口探测）
[安全] 内网放行已开，但雷达采集仍会访问公网（GitHub / arXiv / Hacker News 等）：内网 / 气隙环境请设 RADAR_OFFLINE=true 或 RADAR_SCHEDULE=off
```

## 3. 遥测审计：结论是「一个都没有」，证据是四条

| 检查项 | 结果 |
|---|---|
| 统计 / 埋点 / 崩溃上报 SDK（前端与后端） | 无。生产依赖只有 react / react-dom / react-router-dom / ai / @ai-sdk/react |
| 外部静态资源（CDN、外部字体、图标、头像） | 无。`index.html` 只有本地 `/src/main.tsx`；`public/` 只有一个本地 jpg |
| 更新检查 / 版本上报 / 心跳 | 无。代码里没有任何「回家」请求 |
| 运行期出网点 | 4 处，全部可指向内网或关闭（见下） |

运行期出网清单（`test_outbound_call_sites_are_registered` 钉住，新增即红）：

| 文件 | 用途 | 内网方案 |
|---|---|---|
| `app/services/ai/ai.py` | 业务 LLM 调用 | 端点来自服务端配置 / 用户设置，可指内网 |
| `app/services/retrieval/embeddings.py` | 远端 embedding | `AI_EMBED_MODEL` 留空＝离线哈希（零网络） |
| `app/services/radar/sources.py` | 雷达采集（HN / arXiv / OpenAI / GoogleAI / GitHub） | `RADAR_OFFLINE=true` 或 `RADAR_SCHEDULE=off` |
| `app/main.py` | 自建 embedder 健康探针 | 指向内网 TEI，或不开 embed 档 |

构建期与运行期要分开看：pip / npm 源是**构建期**依赖（可用内网镜像
`PIP_INDEX_URL` / `NPM_REGISTRY`），运行期容器不装包、不下载任何东西。
唯一例外是可选档 `--profile embed` 的 TEI 容器首次启动会拉模型 —— 气隙环境请预置
`skillcoach-embedcache` 卷，或干脆不开这个档（默认就是不开）。

## 4. 守卫测试

`backend/tests/test_r115_intranet.py`：

- 默认档仍是「私网一律拒绝」（`test_switch_defaults_to_off`，回归在 `test_r99_ssrf_guard.py`）；
- 内网档放行 RFC1918 / 环回 / IPv6 ULA，仍拒元数据（含两个国内云地址）；
- 保存与测试连接两个入口行为一致；
- 前端入口 HTML 完全自包含、生产依赖无遥测包；
- 源码里不出现遥测域名与统计 SDK 的 import；
- 后端出网点必须与清单完全一致（多一处少一处都红）。

**为什么用「登记制」而不是「扫关键字」**：关键字扫描只能挡住已知 SDK，挡不住
「自己手写一个 `fetch('https://…/collect')`」。登记制要求任何新增 `httpx` 出网调用
都必须改这份清单，也就必须在 code review 里解释这个新出网点是干什么的。

## 5. 验证

```
pytest tests/test_r115_intranet.py tests/test_r99_ssrf_guard.py    → 44 passed
ruff check app tests                                              → All checks passed
后端全量 pytest                                                   → 0 failed ✅
```

手工验收（内网档）：

```bash
AI_ALLOW_PRIVATE_ENDPOINTS=true python -c "
from app.services.ai.user_ai import validate_ai_base_url as v
print(v('http://10.0.0.5:8000/v1'))          # 通过
try: v('http://169.254.169.254/v1')
except Exception as exc: print(exc)          # 仍然拒绝（元数据）
"
```

## 6. 已知边界

- DNS rebinding 未彻底消除（校验时公网 IP、请求时换成内网 IP）。内网部署下这个风险
  本来就存在（用户能连内网），公网部署靠 `ai_test_timeout_s` + 按 IP 限流压低收益。
- 开关是**全局**的：打开后所有登录用户都能填私网端点。公网部署不要打开。
- 内网放行只管「用户自带端点」；服务端配置（`AI_*`、`AI_EMBED_*`）从来不受 SSRF 门禁约束，
  管理员向来可以直接填内网地址。

## 7. 「设了开关还是报不允许指向内网」——先分清三种可能

文案由 `_SSRF_MESSAGE` 唯一产出，说明进程里读到的仍是 `false`。**别急着改配置，先确认代码版本**：

```bash
cd backend
python -c "from app.core.config import get_settings as g; print(g().ai_allow_private_endpoints)"
```

| 输出 | 含义 | 动作 |
|---|---|---|
| `AttributeError: ai_allow_private_endpoints` | **这台机器还是 r115 之前的代码**（该字段不存在）。内网环境往往是离线拷贝的代码包，最容易停在这一步 | 更新代码（见下） |
| `False` | 代码是新的，开关没生效 | 按下一段四种原因排查 |
| `True` | 开关已生效 | 报错来自旧进程 / 旧标签页 / 另一台机器 |

一条命令看全部（r115 起）：`python -m app.admin_cli doctor`（只读，不建库不连库改状态）

```
== 部署自查 ==
工作目录        : /opt/skillcoach/backend
配置文件        : /opt/skillcoach/backend/.env（存在）
DB_MODE         : auto
数据层          : 无 PostgreSQL、SQLite 为空 → 首次启动新建单机库 /opt/skillcoach/backend/data/app-fallback.db
服务端 AI 档位  : provider=lmstudio model=qwen2.5-32b  端点=http://10.0.0.5:8000/v1 就绪=是
缓存层          : memory（未配置 Redis，进程内缓存）
雷达采集        : 会访问公网（调度=inapp）

结论：用户自带 AI 端点【不能】填内网地址 ❌（只允许公网地址）
      要放行：在 …/backend/.env 里加一行 AI_ALLOW_PRIVATE_ENDPOINTS=true，然后重启后端进程
```

开关设了但仍是 `off` 的四种原因，按出现频率排：

| # | 原因 | 怎么确认 | 怎么修 |
|---|---|---|---|
| 1 | 写在 `deploy.env` 里 | compose 的 `env_file` 只指向 `backend/.env`；`--env-file deploy.env` **只用于 compose 变量插值，不注入容器** | 挪到 `backend/.env` |
| 2 | 改了没重建容器 | `docker inspect` 里看不到这个变量 | `docker compose up -d`（`restart` 不会更新容器环境变量） |
| 3 | 跑的是旧镜像 / 旧代码 | `doctor` 里没有「用户自带 AI 端点」这一行 | 更新代码后重建 |
| 4 | 从源码起但 cwd 不对 | `doctor` 打印的「配置文件」路径不是你改的那个 `.env` | 在 `backend/` 目录下启动 |

### 内网 / 离线机器怎么更新代码

内网机器上不了 GitHub，用 bundle 搬运（有网机器在仓库里执行）：

```bash
git bundle create /tmp/skillcoach.bundle dev      # 产出单文件，含完整历史
# 拷进内网机器后：
git pull /path/to/skillcoach.bundle dev           # 或 git clone 该 bundle 到新目录
```

只关心这次修复的话，最小改动是四个文件：`app/core/config.py`、`app/services/ai/user_ai.py`、
`app/main.py`、`app/admin_cli.py`（外加 `tests/test_r115_intranet.py` 用于自证）。
更新后**必须重启后端进程**，配置只在进程启动时读一次。

### 为此做的三处改动（不只是文档）

1. **启动日志两档都打印**（`security.ai_private_endpoints=on|off`）。原来只在开启时打印，
   于是「设了却没生效」没有任何线索 —— 这正是上面第 1～4 种原因最难排除的地方。
2. **拒绝文案给出下一步**：`…（内网部署可设 AI_ALLOW_PRIVATE_ENDPOINTS=true 放行私网端点，改动后需重启服务）`。
   只报「不允许」会让用户无从判断是没设对还是没生效。
3. **空值 / 带空白的布尔值不再炸进程**：排查中发现 `AI_ALLOW_PRIVATE_ENDPOINTS=`（照
   `.env.example` 抄完清空一行）和 `" true "`（复制带空格）都会在 `Settings()` 构造期抛
   `ValidationError`，服务直接起不来。原来的容错只在**手工维护的数值字段清单**上，
   现在改成按字段类型判断（`_tolerate_padded_env`）：`int` / `float` / `bool` 一律容错，
   字符串字段不动（「空值＝继承」的语义要留给 `resolve_ai` 解释）。
