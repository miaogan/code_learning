"""r67 技术雷达编排层：采集 → 归一化 → 翻译 → 入库 → 评估；定时轮次与应用内调度生命周期。

一轮的顺序是**先读旧快照再写新快照**（`previous_stars` 要在 `insert_snapshot` 之前取），
否则「7 日 star 增量」永远是 0。评估分两轨：规则基线全量写入，模型细化只给本轮排名最前的
`RADAR_MAX_ASSESS_PER_ROUND` 条（r53 的「离线回归 ≠ 模型质量」同源纪律：模型不可用时规则结论就是结论）。

r133：中文简介在**入库前**随本轮条目一起翻好（原文没变则复用旧译文），不再依赖清单页触发补翻。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from app.core.config import get_settings
from app.core.errors import AppError
from app.services.ai import user_ai
from app.services.ai.ai import AIClient
from app.services.radar import assess, normalize, rules, schedule, sources, store, translate

logger = logging.getLogger("app.radar")

PROMPT_VERSION = assess.PROMPT_VERSION

_scheduler: asyncio.Task[None] | None = None


def _ingest_client(user: dict[str, Any] | None) -> AIClient | None:
    """入库前翻译用的 AI 客户端：有用户走用户 Key，定时轮走服务端配置；都没配就返回 None。

    定时轮没有账号上下文，不能调用 `user_ai.client_for`；服务端 Key 由管理员配置，
    本函数调用不记到任何用户配额（与画像 / 报告等后台任务的口径一致），端点仍由统一
    `AIClient` 出口发出，不新增出网面（r115 登记制守卫覆盖）。
    """
    if user is not None:
        try:
            return user_ai.client_for(user, "light")
        except AppError:
            return None
    settings = get_settings()
    return AIClient(settings=settings) if settings.resolve_ai().ready else None


class _ClientGate:
    """一轮内只建一次客户端：翻译 / 模型细化 / 历史欠账补翻共用，共享 Key 只扣一次配额。"""

    def __init__(self, user: dict[str, Any] | None) -> None:
        self._user = user
        self._client: AIClient | None = None
        self._tried = False

    def get(self) -> AIClient | None:
        if not self._tried:
            self._tried = True
            self._client = _ingest_client(self._user)
        return self._client


async def _translate_for_storage(
    items: list[dict[str, Any]], gate: _ClientGate, notes: list[str]
) -> dict[str, str]:
    """入库前批量翻译本轮摘要；无 Key / 模型失败只保留英文，绝不拖垮采集。"""
    if not items:
        return {}
    client = gate.get()
    if client is None:
        return {}
    try:
        ready = await translate.prepare_for_storage(
            items, client, store.translation_states([str(item.get("slug") or "") for item in items])
        )
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 — 单批翻译失败不该让整轮采集失败
        logger.exception("radar.translate.ingest_failed")
        notes.append("入库前翻译失败，已保留英文原文")
        return {}
    translated = sum(
        1
        for item in items
        if translate.needs_translation(str(item.get("summary") or ""))
        and ready.get(str(item.get("slug") or ""))
    )
    if translated:
        notes.append(f"已翻译 {translated} 条英文简介（入库前完成）")
    return ready


async def run_round(
    trigger: str = "schedule",
    user: dict[str, Any] | None = None,
    direction: str = "",
    repo: str = "",
) -> dict[str, Any]:
    """跑一轮采集 + 评估，返回 `{run_id, started_at, finished_at, sources, notice, ...}`。

    `direction` 命中站内闭集时只保留该方向条目；`repo` 非空时只采这一个仓库（优先于方向）。
    """
    settings = get_settings()
    target = direction if direction in rules.DIRECTIONS else ""
    full_name = sources.repo_full_name(repo)
    run_id = store.create_run(trigger)
    items, status, degraded = await sources.fetch_all(settings, direction=target, repo=full_name)
    # r145：失败原因必须跟着本轮回执走到页面（尤其内网 TLS 证书失败），不能只留在容器日志里。
    failed_messages: list[str] = []
    for row in status:
        if row.get("status") != "failed":
            continue
        message = str(row.get("message") or "").strip()
        if message != "" and message not in failed_messages:
            failed_messages.append(message)
    if target and not full_name:
        items = [item for item in items if item["direction"] == target]
    summary = assess.profile_summary()
    digest = assess.profile_digest(summary)
    notes: list[str] = []
    pending: list[dict[str, Any]] = []
    gate = _ClientGate(user)
    round_items = items[: max(int(settings.radar_run_max_techs), 1)]
    translations = await _translate_for_storage(round_items, gate, notes)

    for item in round_items:
        zh = translations.get(str(item["slug"]))
        stored = {**item, "summary_zh": zh} if zh is not None else item
        store.upsert_tech(stored)
        previous = store.previous_stars(item["slug"])
        store.insert_snapshot(item)
        signals = normalize.signals_of(item, previous)
        result = rules.rule_assess(signals, summary)
        sha = assess.input_sha256(item, signals, digest)
        store.insert_assessment(
            item["slug"],
            run_id,
            result,
            input_sha256=sha,
            profile_digest=digest,
            prompt_version=PROMPT_VERSION,
            model="rule",
            rule_based=True,
        )
        pending.append({"item": stored, "signals": signals, "sha": sha, "result": result})

    dropped_total = await _refine_top(pending, summary, digest, run_id, user, gate, notes)
    await _translate_round(gate, notes)

    detail = "；".join(failed_messages[:3])
    if settings.radar_offline:
        notes.insert(0, "当前为离线模式，本轮只读取内置样本")
    elif full_name:
        # r145：指定仓库采集失败时也要把原因带到页面，不能被「只采集指定仓库」这句盖掉。
        if degraded:
            reason = f"（{detail}）" if detail != "" else ""
            notes.insert(0, f"指定仓库 {full_name} 本轮采集失败{reason}")
        notes.insert(0, f"本轮只采集指定仓库 {full_name}")
    elif degraded:
        notes.insert(
            0,
            f"部分信息源本轮不可用（{detail}）"
            if detail != ""
            else "部分信息源本轮不可用，只覆盖可用的来源",
        )
    if target and not full_name:
        notes.append(f"本轮按方向「{target}」采集，只保留该方向的条目")
        if not pending:
            notes.append("该方向本轮没有匹配到条目，可换个方向或稍后重试")
    if dropped_total:
        notes.append(f"已丢弃 {dropped_total} 条无依据的模型引用")

    store.finish_run(run_id, status, bool(degraded or settings.radar_offline), len(pending))
    return {**store.latest_run(), "notice": "；".join(notes)}


async def _refine_top(
    pending: list[dict[str, Any]],
    summary: dict[str, Any],
    digest: str,
    run_id: int,
    user: dict[str, Any] | None,
    gate: _ClientGate,
    notes: list[str],
) -> int:
    """对本轮排名最前的几条做模型细化；无 Key / 无账号 / 模型失败都**静默回落规则结论**。"""
    settings = get_settings()
    limit = max(int(settings.radar_max_assess_per_round), 0)
    if user is None or limit == 0 or not pending:
        return 0
    ranked = sorted(pending, key=lambda row: rules.sort_key({**row["item"], **row["result"]}))
    client = gate.get()
    if client is None:
        notes.append("未做模型细化：未配置可用的模型服务")
        return 0
    model = str(getattr(settings.resolve_ai(), "model", "") or "")
    dropped = 0
    for row in ranked[:limit]:
        try:
            refined = await assess.model_assess(row["item"], row["signals"], summary, client)
        except asyncio.CancelledError:
            raise
        except AppError as error:
            notes.append(f"模型细化中断：{error.message}")
            break
        except Exception:  # noqa: BLE001 — 单条细化失败不该让整轮采集失败
            logger.exception("radar.assess.model_failed slug=%s", row["item"].get("slug"))
            notes.append("模型细化中断，本轮其余条目只用规则结论")
            break
        dropped += int(refined.pop("dropped_evidence", 0))
        store.insert_assessment(
            row["item"]["slug"],
            run_id,
            refined,
            input_sha256=assess.model_sha(row["sha"]),
            profile_digest=digest,
            prompt_version=PROMPT_VERSION,
            model=model or "model",
            rule_based=False,
        )
    return dropped


async def ingest_manual(entry: dict[str, Any], user: dict[str, Any] | None = None) -> dict[str, Any]:
    """手工录入一条线索：GitHub 仓库链接先补一次公开元数据，其余不联网，直接落清单。

    GitHub 的 star / 库龄是评估的硬信号，手工录入时不补会让任何仓库都按 0 star 判成「跳过」；
    补失败（限流 / 断网 / 非仓库链接）就退回纯手工字段。返回形状与 `store.list_techs` 单条一致。
    """
    settings = get_settings()
    raw = {**entry, "source_key": "manual"}
    full_name = "" if settings.radar_offline else sources.github_full_name(str(entry.get("url") or ""))
    if full_name:
        repo = await sources.fetch_repo(full_name, settings)
        if repo is not None:
            raw = {**raw, **repo, "source_key": "github"}
            # 用户填了名称 / 说明就用用户的；链接统一回填成仓库的规范地址。
            raw["name"] = str(entry.get("name") or "").strip() or repo["name"]
            raw["summary"] = str(entry.get("summary") or "").strip() or repo["summary"]
            raw["url"] = repo["url"] or raw["url"]
            for field in ("direction", "sub_direction"):
                if str(entry.get(field) or "").strip():
                    raw[field] = str(entry[field]).strip()
    item = normalize.normalize_item(raw)
    summary = assess.profile_summary()
    digest = assess.profile_digest(summary)
    run_id = store.create_run("manual")
    notes: list[str] = []
    gate = _ClientGate(user)
    translations = await _translate_for_storage([item], gate, notes)
    zh = translations.get(str(item["slug"]))
    stored = {**item, "summary_zh": zh} if zh is not None else item
    store.upsert_tech(stored)
    previous = store.previous_stars(item["slug"])
    store.insert_snapshot(item)
    signals = normalize.signals_of(item, previous)
    result = rules.rule_assess(signals, summary)
    sha = assess.input_sha256(item, signals, digest)
    store.insert_assessment(
        item["slug"],
        run_id,
        result,
        input_sha256=sha,
        profile_digest=digest,
        prompt_version=PROMPT_VERSION,
        model="rule",
        rule_based=True,
    )
    await _refine_top(
        [{"item": stored, "signals": signals, "sha": sha, "result": result}],
        summary,
        digest,
        run_id,
        user,
        gate,
        notes,
    )
    # 本条已翻完再入库；这里只清历史欠账（含 HN 标题抓正文汇总），共享 Key 复用同一客户端。
    await _translate_round(gate, notes)
    store.finish_run(
        run_id,
        [{"source_key": "manual", "status": "ok", "items": 1, "latency_ms": 0,
          "message": "手工录入"}],
        False,
        1,
    )
    rows = store.list_techs(1, tech_slug=item["slug"])
    return rows[0] if rows else {
        **stored,
        "tech_slug": item["slug"],
        **{key: result[key] for key in ("verdict", "relevance", "adoption", "maturity", "effort",
                                        "reasons", "evidence")},
    }


async def _scheduled_round() -> None:
    await run_round(trigger="schedule", user=None)


async def _translate_round(gate: _ClientGate, notes: list[str]) -> int:
    """清历史欠账：待翻英文 + 「标题即简介」抓正文汇总（r74 / r89）。

    r133 起本轮新条目已在入库前翻好，这里只处理之前留下的队列；定时轮有服务端 Key 时
    也走同一路径。仍无 Key / 上游失败只保留原文，手动「翻译英文简介」按钮可兜底重试。
    """
    client = gate.get()
    if client is None:
        return 0
    try:
        translated, _ = await translate.translate_pending(
            max(int(get_settings().radar_translate_batch), 1), client
        )
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 — 单条摘要翻不出来不该让整轮采集失败
        logger.exception("radar.translate.failed")
        notes.append("英文摘要翻译失败，已保留原文，可在清单页点「翻译英文简介」重试")
        return 0
    if translated:
        notes.append(f"已翻译 {translated} 条英文简介")
    # r89：HN 等来源只有标题没描述，翻译只能得到翻译版标题——采完顺手抓正文汇总成中文概要。
    try:
        summarized, _ = await translate.summarize_pending(
            max(int(get_settings().radar_translate_batch), 1), client
        )
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 — 概要抓不到正文只是退回标题译文，不该影响采集
        logger.exception("radar.summarize.failed")
        return translated
    if summarized:
        notes.append(f"已为 {summarized} 条只有标题的条目生成中文概要")
    return translated


async def translate_summaries(user: dict[str, Any], limit: int | None = None) -> tuple[int, int]:
    """按需补翻接口的实现：无 Key / 未开通由 `client_for` 抛 503，路由直接透传。

    r89：补翻同时覆盖两类欠账——英文摘要未翻（translate_pending）与「标题即简介」
    未汇总（summarize_pending）；剩余条数取两者之和，界面提示语路由层拼。
    """
    settings = get_settings()
    client = user_ai.client_for(user, "light")
    batch = max(int(settings.radar_translate_batch if limit is None else limit), 1)
    translated, _ = await translate.translate_pending(batch, client)
    summarized, _ = await translate.summarize_pending(batch, client)
    return translated + summarized, store.count_pending_translation() + store.count_pending_summary()


def start_scheduler() -> None:
    """应用内定时：`RADAR_SCHEDULE=inapp` 才启动（`off` 时完全由手动按钮驱动）。"""
    global _scheduler
    if _scheduler is not None or get_settings().radar_schedule != "inapp":
        return
    _scheduler = asyncio.create_task(schedule.run_forever(_scheduled_round))


async def stop_scheduler() -> None:
    global _scheduler
    task, _scheduler = _scheduler, None
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task


__all__ = [
    "PROMPT_VERSION",
    "ingest_manual",
    "rules",
    "run_round",
    "start_scheduler",
    "stop_scheduler",
    "store",
    "translate_summaries",
]
