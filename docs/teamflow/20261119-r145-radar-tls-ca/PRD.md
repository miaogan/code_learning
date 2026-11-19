# r145 内网采集 TLS：挂企业 CA + 失败原因上屏

## 背景

用户反馈：

> 内网部署 先锋模块 采集失效 报错 ssl：certificate-verify-failed

内网机器普遍过一层 TLS 代理（或上游是自签证书的内网镜像），系统的信任库里没有这张证书。
采集链路 `radar/sources.py` 走 `httpx` 且默认 `verify=True`，于是每一轮采集都整轮失败。

## 根因（三个层次，都不是「加个开关」能一次解决的）

| # | 问题 | 后果 |
|---|---|---|
| 1 | 只有 `RADAR_INSECURE_TLS` 一个「跳过校验」的粗暴开关，没有「挂企业 CA」的正规路径 | 用户要么采集全挂，要么为了能跑把整条链路的证书校验永久关掉——用安全问题换可用性 |
| 2 | `fetch_repo()` 失败只回一句泛化文案（「仓库不存在、限流、网络或 TLS 证书校验失败」） | 用户看到四种可能，无法判断到底是哪一种；日志里才有 `certificate verify failed` |
| 3 | `run_round()` 的降级提示只有「部分信息源本轮不可用」 | 页面看不到原因，必须 `docker compose logs backend` 才知道是证书 |

## 改动

### 1. 新增 `RADAR_CA_BUNDLE`（正规路径）

`app/core/config.py`：

```python
radar_ca_bundle: str = ""
```

`app/services/radar/sources.py` 新增 `verify_for(settings) -> bool | str`，作为采集客户端
`verify` 的唯一取值入口（三处 `httpx.AsyncClient` 全部改用它）：

```
优先级：RADAR_INSECURE_TLS=true  →  False（跳过校验）
        RADAR_CA_BUNDLE 非空      →  该 PEM 路径
        其余                      →  True（系统信任库）
```

**关键的诚实设计**：`RADAR_CA_BUNDLE` 填了但文件不存在时，**不**静默跳过校验（那等于把配置
笔误变成安全降级），而是 WARNING 后回退系统信任库，让原来的证书错误继续暴露出来。

### 2. 失败原因带上中文指引

新增 `TLS_HINT` 常量（页面与日志共用同一份措辞），两条路都写清楚：

```
上游 TLS 证书校验失败：请把企业根证书挂进容器，并让 RADAR_CA_BUNDLE 指向该 PEM 文件；
仅临时排障可设 RADAR_INSECURE_TLS=true（跳过校验，用完请关回）
```

`fetch_repo()` 增加 `error_sink: list[str] | None`，按异常类型分流成可展示的中文原因：

| 异常 | message |
|---|---|
| TLS 证书失败（`_tls_failed()`） | `TLS_HINT` |
| `HTTPStatusError` | `仓库元数据接口返回 {code}（仓库不存在或无权限）` |
| `TimeoutException` | `仓库元数据接口超时` |
| 其余 | `仓库元数据拉取失败（网络不可用或返回格式异常）` |

`error_sink` 是**可选**的：锚点录入（`ingest_manual`）不传，保持「补不到就退回纯手工字段」的
静默语义——用户手填名字时不该被一条采集报错打断。

`_run_source()` 的兜底文案同样接 `TLS_HINT`，TLS 不再退化成「上游不可用或返回格式异常」。

### 3. 原因跟回执走到页面

`app/services/radar/__init__.py` 的 `run_round()` 收集所有 `status == failed` 的 message
（去重、最多 3 条），拼进 notice：

- 全源轮次：`部分信息源本轮不可用：{reason}`
- 指定仓库轮次：`指定仓库 {owner/repo} 本轮采集失败：{reason}`

第二条是本次发现的一个真 bug：原来的 `elif full_name` 分支排在 `elif degraded` 之前，
指定仓库采集失败时 notice 只显示「本轮只采集指定仓库 X」，失败原因被完全盖住——而这恰好是
内网用户最可能的操作路径（手填一个仓库试水）。

### 4. 文档

- `backend/.env.example`：补 `RADAR_CA_BUNDLE=` 与注释（容器内路径示例）。
- `README.md` 内网章节新增「内网采集的 TLS 证书」小节：挂载 PEM 的 compose 片段 +
  `RADAR_CA_BUNDLE` + 临时开关两条路，并说明「路径写错不会静默跳过校验」。
- 无需改 `docker-compose.yml`：backend 已有 `env_file: ./backend/.env`，加变量即生效；
  挂证书用本地 `docker-compose.override.yml`（`up -d` 自动叠加）。

## 测试

`backend/tests/test_r67_radar.py` 新增 4 例：

| 用例 | 钉住什么 |
|---|---|
| `test_verify_for_prefers_ca_bundle` | 三态优先级 + CA 文件缺失回退系统库（不是跳过） |
| `test_tls_failure_surfaces_chinese_hint` | `fetch_repo(error_sink=)` 写入 `TLS_HINT`；不传 sink 时静默；`fetch_all(repo=)` 透传 |
| `test_round_notice_carries_failure_reason` | 全源降级 notice 带原因 |
| `test_round_repo_failure_notice_carries_reason` | 指定仓库失败 notice **同时**有「只采该仓库」与失败原因 |

另外把两处 `_fake_repo` 替身补上第三个参数（`fetch_all` 现在传 `error_sink`），语义不变。

## 验证

- `pytest tests/test_r67_radar.py -q`：**32 passed**
- `ruff check app tests`：All checks passed
- 后端全量 pytest：见 AGENTS.md 记录

## 已知边界

- `RADAR_CA_BUNDLE` 只作用于**采集链路**，不影响业务 LLM / embedding / rerank（那三条各有自己的
  base_url，内网通常直接指 http 内网端点）。要做全局信任库可以另外挂 `SSL_CERT_FILE`，但本项目
  不依赖它——显式一个变量比隐式改运行时环境更好排查。
- CA bundle 走 `httpx` 的 `verify=<path>`，即**替换**系统信任库而非追加。内网镜像若同时需要
  公网 CA（例如 GitHub 走代理、arXiv 直连），需要把企业根证书与公网根证书合并在同一个 PEM 里。
- 采集仍受 r115 的登记制守卫（出网点清单不变，只改了校验方式）。
