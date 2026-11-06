"""服务层：业务逻辑与外部依赖（AI / 文件解析 / 种子数据）都收敛在这里。

按业务域分包（单文件服务不建包，如 `login_guard.py` 留在本层）：

- `ai/`：AI 出网唯一通道（`ai.py` 运行时与池化客户端、`user_ai.py` 按用户解析）
- `resume/`：简历解析（`parser`）、润色（`resume_polish`）、提示（`resume_hints`）、教练文案（`coach_copy`）
- `profile/`：画像生成（`profile`）与合并（`profile_merge`）
- `interview/`：模拟面试（`interview`）与历史（`history`）
- `assessment/`：笔试与题库（`exam` / `exam_selector` / `practice` / `proficiency` / `question_*`）
- `report/`：诊断报告（`diagnosis` / `weakness` / `role_fit` / `rules` / `courses` / `markdown` / `timeline`）

基础设施（配置 / DB / 错误码 / 鉴权 / 可观测性 / 数据访问）在 `app.core`，不在本层。
"""
