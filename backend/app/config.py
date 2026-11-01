"""集中配置：全部经环境变量 / .env 注入，密钥只存在服务端（AC-8）。

**分工（r6 写死，两个方向都别漂）**：可调阈值（窗口天数 / 答对次数 / 近卷去重卷数）只住本文件，
一律可被环境变量覆盖；**闭集与结构闸门**（方向 / 难度 / 必备度 / 阶梯 / 题量与占比）只住
`services/rules.py`。阈值漂回 rules.py 或闭集散到 config.py，都会让面试 / 笔试 / 报告口径各自漂移
（`tests/test_engineering_gates.py::test_proficiency_thresholds_only_from_config` 反向钉住这一点）。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_model: str = "gpt-4o-mini"
    ai_timeout_s: float = 20.0
    ai_max_retries: int = 1

    db_path: str = "app.db"
    max_upload_mb: int = 10
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    # --- 熟练度与近卷去重（r6，可环境变量覆盖） ------------------------------
    #: 熟练度滑动窗口天数：`answered_at >= now - window` 内的作答才算数（含边界）。
    proficiency_window_days: int = 30
    #: 窗口内答对多少次即判为「熟练」（且最近一次必须答对，答错立即回流）。
    proficiency_correct_threshold: int = 2
    #: 组卷时排除最近 N 卷已出过的题（不足时由 6 层阶梯兜底，绝不因此 400）。
    recent_paper_exclude: int = 3

    @property
    def ai_configured(self) -> bool:
        return bool(self.ai_api_key.strip())

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
