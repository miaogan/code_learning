"""集中配置：全部经环境变量 / .env 注入，密钥只存在服务端（AC-8）。

**分工（r6 写死，两个方向都别漂）**：可调阈值（窗口天数 / 答对次数 / 近卷去重卷数）只住本文件，
一律可被环境变量覆盖；**闭集与结构闸门**（方向 / 难度 / 必备度 / 阶梯 / 题量与占比）只住
`services/rules.py`。阈值漂回 rules.py 或闭集散到 config.py，都会让面试 / 笔试 / 报告口径各自漂移
（`tests/test_engineering_gates.py::test_proficiency_thresholds_only_from_config` 反向钉住这一点）。

**AI 供应商档位（r9 写死）**：`Settings.resolve_ai()` 是「用哪套端点 / 模型 / JSON 模式 / 超时」的
**唯一解析出口** —— 出网口 `services/ai.py` 与探活 `main.health()` 都只认它返回的 `AiRuntime`，
服务层禁止再读裸配置字段（`test_r9_ai_uses_runtime_not_naked_fields` 反向钉住）。三条不变量：

1. **解析永不 raise**：配置错只置 `ready=False` + 中文 `reason`，由出网口转成既有
   `AI_UNAVAILABLE 503`；绝不让 `/health` 变 500，也不许 `Settings()` 构造期炸进程。
2. **具名档不回落全局**：`AI_PROVIDER=deepseek|lmstudio` 时 base_url / model / api_key **只读该档**，
   否则本地端点会收到云端 Key（安全边界写进解析器，不靠人记）；只有 `json_mode`（空则继承）与
   `timeout_s`（0 则继承）允许回落。
3. **闭集单源**：`json_mode` 允许值只在 `JsonMode` / `JSON_MODES` 一处，`services/ai.py` 只留一张
   `json_mode -> response_format` 投影表，两者键集相等由静态门禁牵制。
"""

from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any, Literal, get_args

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: `json_mode` 闭集（唯一出处；`services/ai.py` 的投影表必须与它键集相等）。
JsonMode = Literal["json_object", "none"]
#: 由 `JsonMode` 派生，禁止另写一份同义 tuple（二维真相＝迟早漂）。
JSON_MODES: frozenset[str] = frozenset(get_args(JsonMode))
#: `json_mode` 缺省值：与 r8 及之前发往 DeepSeek / OpenAI 的请求体逐字一致。
DEFAULT_JSON_MODE: str = "json_object"
#: 具名档白名单（唯一出处；中文提示语里的可用值也由它拼，不另写一份）。
AI_PROVIDER_NAMES: tuple[str, ...] = ("deepseek", "lmstudio")
#: `AI_PROVIDER` 为空时解析出的供应商标识（`/health` 也报这个名字）。
LEGACY_PROVIDER: str = "legacy"

#: 供应商 → 该档 5 个扁平字段名（`base_url` / `model` / `api_key` / `json_mode` / `timeout_s`）。
#: 新增第三套供应商＝在 `Settings` 加 5 个字段 + 此表加一行，不要在解析里复制粘贴分支。
_PROFILE_FIELDS: dict[str, tuple[str, str, str, str, str]] = {
    "deepseek": (
        "ai_deepseek_base_url",
        "ai_deepseek_model",
        "ai_deepseek_api_key",
        "ai_deepseek_json_mode",
        "ai_deepseek_timeout_s",
    ),
    "lmstudio": (
        "ai_lmstudio_base_url",
        "ai_lmstudio_model",
        "ai_lmstudio_api_key",
        "ai_lmstudio_json_mode",
        "ai_lmstudio_timeout_s",
    ),
}

#: 数值型档位字段：`.env` 里写成 `KEY=`（空值）时**按「没写」处理**，回落字段默认值。
#: 不做这一步，空串会进 `float` / `int` 校验并在 `Settings()` 构造期抛 `ValidationError` —— 那会把
#: 整个进程（和整批用例）打挂，恰好违反上面第 1 条不变量「配置错只置 ready=False，不许炸进程」。
#: 只处理数值型：字符串字段的「空值＝继承 / 未配置」语义由 `resolve_ai` 自己解释，不能被吞掉。
_NUMERIC_ENV_FIELDS: tuple[str, ...] = (
    "ai_timeout_s",
    "ai_max_retries",
    "ai_deepseek_timeout_s",
    "ai_lmstudio_timeout_s",
    "ai_vision_timeout_s",
    "login_max_failures",
    "login_lockout_minutes",
    "rate_limit_window_s",
    "rate_limit_auth_per_window",
    "rate_limit_api_per_window",
    "breaker_max_inflight",
    "breaker_window_s",
    "breaker_min_requests",
    "breaker_error_ratio",
    "breaker_open_s",
    "radar_fetch_timeout_s",
    "radar_fetch_max_bytes",
    "radar_run_max_techs",
    "radar_min_stars",
    "radar_max_assess_per_round",
    "radar_assess_timeout_s",
    "radar_gen_timeout_s",
    "radar_gen_max_questions",
    "radar_job_stale_minutes",
)

#: r41：视觉档未开通时的**唯一**中文说明（图片入口直接透传，不静默降级成 PDF 提示）。
VISION_UNCONFIGURED_REASON = "图片识别未开通，请改用 PDF 上传"


#: 统一 AI 出网超时（秒）：所有调用点共用这一档，不再按功能各自写数值。
#: 标定依据：本机 `qwen3.5-9b`（reasoning 类）单次画像实测 201.25s，取 ≈3 倍余量；
#: 画像 / 润色 / 报告文案这类长输出任务同样受益。改这里即改全局默认。
UNIFIED_AI_TIMEOUT_S = 600.0


@dataclass(frozen=True)
class AiRuntime:
    """一次解析出来的 AI 运行期口径（出网口与探活共用同一份事实）。

    `ready=False` 时 `reason` 必为中文说明；`api_key` 用 `repr=False` 挡住日志 / 断言输出泄漏。
    """

    provider: str
    base_url: str
    model: str
    api_key: str = field(repr=False, default="")
    json_mode: str = DEFAULT_JSON_MODE
    timeout_s: float = UNIFIED_AI_TIMEOUT_S
    max_retries: int = 1
    ready: bool = False
    reason: str = ""


def _resolve_json_mode(raw: str) -> tuple[str, str]:
    """把任意 `json_mode` 入力收敛成闭集内的值，返回 `(生效值, 中文错误说明)`。

    空值按缺省；闭集外**回落缺省值**并给出说明（调用方据此把 `ready` 置 False），
    这样闭集外的值永远不会流进出网口的投影表查表。
    """
    mode = (raw or "").strip()
    if not mode:
        return DEFAULT_JSON_MODE, ""
    if mode in JSON_MODES:
        return mode, ""
    allowed = " / ".join(sorted(JSON_MODES))
    return DEFAULT_JSON_MODE, f"AI_JSON_MODE 取值 {mode} 不在允许范围内，可用 {allowed}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _blank_numeric_env_uses_default(cls, data: Any) -> Any:
        """`AI_*_TIMEOUT_S=` / `AI_MAX_RETRIES=` 这类空值按「未设置」处理（回落字段默认值）。

        `pydantic-settings` 默认把空串当输入值，`float("")` / `int("")` 会在构造期抛错。运维照
        `.env.example` 抄完顺手清空一行的概率不低，那时后端不该起不来 —— 与「解析永不 raise」同一口径。
        """
        if not isinstance(data, dict):
            return data
        blank = [name for name in _NUMERIC_ENV_FIELDS if str(data.get(name, "")).strip() == ""
                 and data.get(name) is not None]
        if not blank:
            return data
        return {name: value for name, value in data.items() if name not in blank}

    # --- AI 全局（legacy：`AI_PROVIDER` 为空时逐字沿用 r8 语义） -----------------
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_model: str = "gpt-4o-mini"
    ai_timeout_s: float = UNIFIED_AI_TIMEOUT_S
    ai_max_retries: int = 1

    # --- AI 供应商档位（r9：`AI_PROVIDER` 空＝legacy） --------------------------
    #: 空＝legacy（直读上面的全局四项）；`deepseek` / `lmstudio` 时只读该档。
    ai_provider: str = ""
    #: 全局 JSON 模式，缺省 `json_object`。**故意用 `str`**：非法值不能抛校验错，
    #: 否则一个拼错的 `AI_JSON_MODE` 会让整批请求与用例在 `Settings()` 构造期崩掉。
    ai_json_mode: str = DEFAULT_JSON_MODE

    # deepseek 档：公开端点有稳定默认值，`json_mode` 空＝继承全局，`timeout_s` 0＝继承全局。
    ai_deepseek_base_url: str = "https://api.deepseek.com/v1"
    ai_deepseek_model: str = "deepseek-chat"
    ai_deepseek_api_key: str = ""
    ai_deepseek_json_mode: str = ""
    ai_deepseek_timeout_s: float = 0.0

    # lmstudio 档：端点默认本机；`model` 必须显式填（本地模型 id 因机器而异，且 /health 不联网探测）；
    # json_mode=none 是实测硬约束（本地端点拒绝 json_object）；timeout 见下方 600 的标定依据。
    ai_lmstudio_base_url: str = "http://localhost:1234/v1"
    ai_lmstudio_model: str = ""
    ai_lmstudio_api_key: str = ""
    ai_lmstudio_json_mode: str = "none"
    #: 标定依据（r9 复测）：本机 `qwen3.5-9b`（reasoning 类模型）单次画像实测 **201.25s**，
    #: 旧的 180s 默认值会把该链路掐成 503 `AI_UNAVAILABLE`。600s＝实测 ×3 余量（慢一档的
    #: 机器 / 更小的模型仍够用），且这只是**单请求上限**，不改变任何请求的等待语义。
    ai_lmstudio_timeout_s: float = 600.0

    # --- r41 图片简历识别（视觉档位） -----------------------------------------
    #: 视觉模型名：留空 = 图片入口未开通（接口明确返回 VISION_UNCONFIGURED_REASON）。
    #: DeepSeek 账号填 `deepseek-flash`（`deepseek-v4-pro` 不支持图像理解）。
    ai_vision_model: str = ""
    #: 留空 = 继承主档的 base_url / api_key（「同一账号、只换模型名」的默认用法）。
    ai_vision_base_url: str = ""
    ai_vision_api_key: str = ""
    #: 0 = 继承主档超时（全局 `AI_TIMEOUT_S` 或具名档 `AI_<档>_TIMEOUT_S`）。
    ai_vision_timeout_s: float = 0.0

    #: 日志级别（DEBUG / INFO / WARNING / ERROR），非法值按 INFO 处理（不因配置错起不来）。
    log_level: str = "INFO"

    db_path: str = "app.core.db"
    max_upload_mb: int = 10
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    # --- r23 登录 / 多用户 / 用户自带 AI Key ---------------------------------
    #: 会话 Cookie 是否带 `Secure`：开发走 http 时必须 false，生产 https 置 true。
    cookie_secure: bool = False
    #: 会话有效期（天）。
    session_days: int = 30
    #: 加密用户 API Key 的主密钥（`openssl rand -hex 32`）。为空时禁止保存用户 Key。
    secret_key: str = ""
    #: 内置（shared）Key 每用户每日 AI 调用上限。
    shared_ai_daily_limit: int = 20
    #: 同一邮箱在窗口期内允许的登录失败次数；达到后锁定 `login_lockout_minutes`。
    #: 0 = 关闭限流（仅供排障，生产不建议关）。
    login_max_failures: int = 5
    #: 登录失败窗口 / 锁定时长（分钟）。
    login_lockout_minutes: int = 15

    # --- r70 应用层防护：按 IP 限流 + 熔断 ------------------------------------
    #: 限流总开关（排障可关；生产不建议关）。
    rate_limit_enabled: bool = True
    #: 滑动窗口长度（秒）：窗口内同一 IP 的请求数超过分档上限即 429。
    rate_limit_window_s: int = 60
    #: 登录接口每 IP 每窗口上限：暴力破解与 scrypt 计算放大 DoS 都从这里进，单独收紧。
    rate_limit_auth_per_window: int = 10
    #: 其余接口每 IP 每窗口上限（前端轮询后台任务约 30 次/分钟，留足余量）。
    rate_limit_api_per_window: int = 120
    #: 熔断总开关。
    breaker_enabled: bool = True
    #: 同时在飞请求上限：超过即 503，保护单进程 uvicorn 与 SQLite 写锁。
    breaker_max_inflight: int = 32
    #: 熔断判定窗口（秒）与窗口内最少样本数（样本不足不判，避免低流量误开）。
    breaker_window_s: int = 60
    breaker_min_requests: int = 20
    #: 窗口内 5xx 占比达到该阈值即打开熔断。
    breaker_error_ratio: float = 0.5
    #: 熔断打开时长（秒）：到点放行一个探针，成功即恢复，失败立即再开。
    breaker_open_s: int = 30

    # --- 熟练度与近卷去重（r6，可环境变量覆盖） ------------------------------
    #: 熟练度滑动窗口天数：`answered_at >= now - window` 内的作答才算数（含边界）。
    proficiency_window_days: int = 30
    #: 窗口内答对多少次即判为「熟练」（且最近一次必须答对，答错立即回流）。
    proficiency_correct_threshold: int = 2
    #: 组卷时排除最近 N 卷已出过的题（不足时由 6 层阶梯兜底，绝不因此 400）。
    recent_paper_exclude: int = 3

    # --- r67 技术雷达（先锋 / 国子监） ----------------------------------------
    #: 离线模式：不访问任何上游，只读 `seed/radar_samples.json`（AC-1 的零成本出口）。
    radar_offline: bool = False
    #: 采集跳过 TLS 证书校验：仅供企业代理 / 自签证书的内网环境**临时**排障，默认关。
    #: 打开后上游内容可被中间人篡改（会进题库与国子监生成），内网问题处理完应立刻关回。
    radar_insecure_tls: bool = False
    #: 调度口径：`inapp` = 应用内 asyncio 循环（单进程 uvicorn）；`off` = 只允许手动采集。
    radar_schedule: str = "inapp"
    #: 应用内调度的采集时刻（逗号分隔 HH:MM，+08:00）。跨日空窗接受，用手动采集弥补。
    radar_slots: str = "08:00,12:00,18:00"
    #: 单源超时（秒）：实测 2.6–10.5s，取 8s 让慢源不进下一轮。
    radar_fetch_timeout_s: float = 8.0
    #: 单源读字节上限（流式读，超限截断并标记）：OpenAI Blog RSS 实测 836KB。
    radar_fetch_max_bytes: int = 2_000_000
    #: 一轮最多评估多少条技术（防止一次采集把库撑爆）。
    radar_run_max_techs: int = 40
    #: GitHub 检索的最低 star 门槛（噪声过滤，不是质量判断）。
    radar_min_stars: int = 100
    #: 每轮最多几条走模型评估（其余走规则评估，成本闸门）。
    radar_max_assess_per_round: int = 3
    #: 评估专用超时（秒）：输出是小 JSON，不跟全局 600s 一起等。
    radar_assess_timeout_s: float = 60.0
    #: 生成任务级硬上限（秒）：章节 + 题目 + 答案自检三次调用。
    radar_gen_timeout_s: float = 300.0
    #: 单次生成最多保留几道样例题（自检不通过的会被丢弃，不占这个额度）。
    radar_gen_max_questions: int = 5
    #: 读路径惰性清扫阈值（分钟）：running 超过该时长按 failed 落库（AC-4）。
    radar_job_stale_minutes: int = 15
    #: GitHub Search API token（未认证配额低且易 403；留空退化为「无 token 检索」）。
    github_token: str = ""
    #: 采集后是否自动为「必学」项生成样例（默认关：每条都要烧模型配额）。
    radar_auto_generate: bool = False

    def resolve_ai(self) -> AiRuntime:
        """唯一解析出口：把 env 收敛成一个 `AiRuntime`，**永不 raise**（配置错置 `ready=False`）。"""
        provider = self.ai_provider.strip()
        if not provider:
            return self._resolve_legacy()
        fields = _PROFILE_FIELDS.get(provider)
        if fields is None:
            allowed = " / ".join(AI_PROVIDER_NAMES)
            return AiRuntime(
                provider=provider,
                base_url="",
                model="",
                json_mode=DEFAULT_JSON_MODE,
                timeout_s=self.ai_timeout_s,
                max_retries=self.ai_max_retries,
                ready=False,
                reason=f"AI_PROVIDER 未识别，可用 {allowed}",
            )
        base_url_field, model_field, key_field, json_mode_field, timeout_field = fields
        base_url = str(getattr(self, base_url_field)).strip()
        model = str(getattr(self, model_field)).strip()
        api_key = str(getattr(self, key_field)).strip()  # 具名档：绝不回落全局 Key
        json_mode, mode_error = _resolve_json_mode(
            str(getattr(self, json_mode_field)).strip() or self.ai_json_mode
        )
        profile_timeout = float(getattr(self, timeout_field))
        timeout_s = profile_timeout if profile_timeout > 0 else self.ai_timeout_s
        runtime = AiRuntime(
            provider=provider,
            base_url=base_url,
            model=model,
            api_key=api_key,
            json_mode=json_mode,
            timeout_s=timeout_s,
            max_retries=self.ai_max_retries,
        )
        missing = [
            name.upper() for name, value in ((base_url_field, base_url), (model_field, model))
            if not value
        ]
        if missing:
            detail = "、".join(missing)
            return replace(
                runtime,
                reason=f"AI_PROVIDER={provider} 未配置完整：缺少 {detail}，请检查 backend/.env",
            )
        if mode_error:
            return replace(runtime, reason=mode_error)
        return replace(runtime, ready=True)

    def resolve_vision(self) -> AiRuntime:
        """图片识别（视觉）唯一解析出口：`AI_VISION_MODEL` 非空且主档就绪才算开通。

        端点 / Key / 超时留空一律**继承主档**，因此 DeepSeek 用户只需填一个模型名；
        `json_mode` 固定 `none` —— 转写结果是纯文本，不能带 `response_format`。
        同样**永不 raise**：未开通只置 `ready=False` + 中文 `reason`，由出网口转 503。
        """
        main = self.resolve_ai()
        model = self.ai_vision_model.strip()
        if not model:
            return AiRuntime(
                provider="vision",
                base_url="",
                model="",
                json_mode="none",
                timeout_s=main.timeout_s,
                max_retries=main.max_retries,
                reason=VISION_UNCONFIGURED_REASON,
            )
        if not main.ready:
            # 主档没配好时，视觉档也不可能出网：透传主档的中文原因（仍是同一套错误码）。
            return AiRuntime(
                provider="vision",
                base_url="",
                model=model,
                json_mode="none",
                timeout_s=main.timeout_s,
                max_retries=main.max_retries,
                reason=main.reason,
            )
        vision_timeout = float(self.ai_vision_timeout_s)
        return AiRuntime(
            provider="vision",
            base_url=self.ai_vision_base_url.strip() or main.base_url,
            model=model,
            api_key=self.ai_vision_api_key.strip() or main.api_key,
            json_mode="none",
            timeout_s=vision_timeout if vision_timeout > 0 else main.timeout_s,
            max_retries=main.max_retries,
            ready=True,
        )

    def _resolve_legacy(self) -> AiRuntime:
        """`AI_PROVIDER` 为空：直读全局四项，与 r8 逐字一致（ready 仍是「Key 非空」）。"""
        base_url = self.ai_base_url.strip()
        model = self.ai_model.strip()
        api_key = self.ai_api_key.strip()
        json_mode, mode_error = _resolve_json_mode(self.ai_json_mode)
        runtime = AiRuntime(
            provider=LEGACY_PROVIDER,
            base_url=base_url,
            model=model,
            api_key=api_key,
            json_mode=json_mode,
            timeout_s=self.ai_timeout_s,
            max_retries=self.ai_max_retries,
        )
        if mode_error:
            return replace(runtime, reason=mode_error)
        if not api_key:
            return replace(
                runtime,
                reason="AI 服务尚未配置（服务端缺少 AI_API_KEY），请配置 backend/.env 后重启服务",
            )
        if not base_url or not model:
            # 显式把全局端点 / 模型置空是运维错误：提前说清楚，不让请求打到 "/chat/completions"。
            return replace(runtime, reason="AI_BASE_URL / AI_MODEL 未配置，请检查 backend/.env")
        return replace(runtime, ready=True)

    @property
    def ai_configured(self) -> bool:
        """旧语义的保留入口：`resolve_ai().ready` 的**唯一**委托（不留第二处就绪判定）。"""
        return self.resolve_ai().ready

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
