"""r7 三块补强的中文文案与标签**单一出处**（只有常量，无逻辑、无提示词）。

为什么单独立模块：`weakness` / `resume_hints` / `role_fit` / `markdown` 四个服务 + 前端
`lib/coach.ts` 都渲染同一批文案，散落就会漂移（同一句「暂无该岗位的能力模型」在四处写法不同，
门禁也就无从断言）。集中后 `tests/test_engineering_gates.py::test_r7_copy_parity` 可以逐条
断言「后端常量逐字出现在前端镜像里」。

**不含任何模型指令**：AC-4 的静态检查要求页面/前端零提示词，本文件同样只放用户可见文案，
连「提示词」这几个字的痕迹都不出现，避免误伤静态检查。

标签字典的键是 `rules.py` 的闭集成员（`DIFFICULTIES` / `ESSENTIALITIES`），值只在这里出现一次；
调用方一律 `LABEL.get(x, x)` 兜底，不要自己再写一份中文。
"""

from __future__ import annotations

from app.schemas import PolishSection

# --- 三块区块的降级 / 空态文案（服务端定，前端只渲染）-------------------------

#: `Report.<block>` 为 `None`：旧报告（字段未落库），与「新报告但本块为空」严格区分（AC-13）。
LEGACY_BLOCK_NOTICE = "旧报告不含该区块，重新生成可补全"

#: `Report.weakness_map == []`：本次没有任何已计分客观题可聚合（AC-19）。
WEAKNESS_EMPTY = "本次测评还没有可统计的计分题"

#: `Report.resume_pointers == []` 且**没有**简历正文可定位（AC-6，跳过 AI 调用）。
RESUME_NO_TEXT = "还没有可定位的简历正文，先上传简历再回来看改进要点"

#: `Report.resume_pointers == []` 且正文存在但 AI 一路失败/未配置 Key（AC-11 降级）。
RESUME_AI_FALLBACK = "简历要点暂时没生成出来，可以先去润色页逐条查看"

#: `Report.role_fit.model is None`：目标岗位未命中内置能力模型（AC-10）。
ROLE_NO_MODEL = "暂无该岗位的能力模型"

#: 无模型时给出的下一步建议（与上面那句成对出现，避免只给结论不给动作）。
ROLE_NO_MODEL_HINT = "可以先按上面的薄弱地图补，或在简历画像里填写更常见的岗位名"

#: 目标岗位来源标签：键是 `RoleFit.role_source` 的闭集（AC-9）。
ROLE_SOURCE_LABEL: dict[str, str] = {
    "interview": "本次面试设定",
    "profile": "简历画像",
}

# --- 标签字典（闭集成员 → 中文）---------------------------------------------

#: 难度档位标签：键与 `rules.DIFFICULTIES` 一字不差。
DIFFICULTY_LABEL: dict[str, str] = {
    "basic": "基础",
    "intermediate": "进阶",
    "challenge": "挑战",
}

#: 必备度档位标签：键与 `rules.ESSENTIALITIES` 一字不差。
ESSENTIALITY_LABEL: dict[str, str] = {
    "must_know": "必备",
    "advanced": "进阶",
    "nice_to_know": "了解",
}

#: 简历段落标签：`resume_hints` 拼「项目经历 · 第 12 行」时用它，前端也镜像同一批字；
#: 与润色页 `SuggestionCard` 上移前的口径一致（r7 起只在这里定义一次）。
SECTION_LABEL: dict[PolishSection, str] = {
    "project": "项目经历",
    "experience": "工作经历",
    "education": "教育背景",
    "summary": "个人简介",
}
