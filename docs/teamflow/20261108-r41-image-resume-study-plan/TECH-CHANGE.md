# TECH-CHANGE · r41 图片简历入口 + 报告转 7 天学习计划

> 配套：同目录 `PRD.md`（AC A-1 ~ A-10 / B-1 ~ B-10）与 `TECH-PLAN.md`（实施方案）。
> 三项决策已按用户拍板落地：**D1 = A1**（复用 DeepSeek 账号视觉能力，`AI_VISION_MODEL=deepseek-flash`）、
> **D2 = 3 张**（多图按顺序拼成一份简历、共用一个 `resume_id`）、**B = B1**（纯前端确定性排程 + 本地持久化，打卡不计分）。

## 0. 一句话结论

- **功能 A**：新增 `POST /api/resumes/images`（1–3 张 JPG / PNG / WebP），视觉模型逐页转写、按上传顺序拼成一份简历、只入库正文；旧 `POST /api/resumes` 契约零变化（仅补两个带缺省值的新字段）。
- **功能 B**：报告页「7 天学习计划」数据源从 `reportPlan.ts` 换成 `studyPlan.ts` 的确定性排程，任务粒度打卡 + 15/30/60 分钟三档，计划与打卡只存本机，**界面上明示不跨设备、不计入熟练度与成绩**。

---

## 1. 后端改动（功能 A）

| 文件 | 改动 | 要点 |
|---|---|---|
| `backend/app/core/config.py` | 新增 `VISION_UNCONFIGURED_REASON`；`Settings` 增 `ai_vision_model / ai_vision_base_url / ai_vision_api_key / ai_vision_timeout_s`；新增 `resolve_vision()`；`_NUMERIC_ENV_FIELDS` 登记 `ai_vision_timeout_s` | 端点 / Key / 超时留空**继承主档**，只需填模型名；`json_mode` 固定 `none`（转写是纯文本，不能带 `response_format`）；**永不 raise**，未开通只置 `ready=False` + 中文原因 |
| `backend/app/services/ai/ai.py` | 新增 `complete_vision(system, user, image_data_urls, *, timeout_s, retry_unavailable)`；`_chat` 拆出 `_request(system, user: str \| list[dict], *, timeout_s, image_count)` | 请求体 `content` 支持块数组：`[{"type":"text"...}, {"type":"image_url"...}]`；日志只记 `prompt_chars` 与 `images` 张数，**不打印 data URL / 正文** |
| `backend/app/services/resume/image_resume.py`（新） | `sniff_image_mime()`、`extract_resume_text(images, client=None)` | 张数 / 格式校验 → 视觉逐页转写（`retry_unavailable=True`）→ 多图拼 `【第 n 页】` → 汇总字数 `< 60` 判识别不足；提示词要求逐字转写、保留换行、表格按「标签：内容」、无法辨认标 `[无法辨认]`、**禁止补写与推测** |
| `backend/app/services/resume/parser.py` | 增 `IMAGE_SUFFIXES / is_image_name() / build_parsed()`；`parse_resume` 对图片后缀抛 415 | 旧文档端点行为不变，只把图片明确引导到新入口 |
| `backend/app/schemas.py` | `ResumeMeta` 增 `source_type: Literal["pdf","docx","txt","image"] = "pdf"`、`image_count: int = 1` | 带缺省值 → 存量响应不变 |
| `backend/app/routers/resume.py` | 旧端点按后缀补 `source_type`；新增 `POST /api/resumes/images` | 路由层只做「数量 / 单张与总量体积 / 真实内容格式」三件校验 + 错误映射，抽取全部在 service；多图 `file_name` 记为 `照片简历（n 张）`，`mimes[0]` 入库 |
| `backend/.env.example` | 新增 r41 视觉配置块（`AI_VISION_MODEL=deepseek-flash`，端点 / Key / 超时留空） | 与 `backend/.env` 同步；注释写明「留空 = 未开通，明确报错不静默降级」 |
| `backend/tests/conftest.py` | 中性测试环境显式置空 `AI_VISION_*` | 保证用例不读本机 `.env` 的视觉配置 |
| `backend/tests/test_r41_image_resume.py`（新） | 8 个用例 | 见 `QA-REPORT.md` §2 |

错误映射（全部复用既有闭集码，`message` 中文且不含路径 / 端点 / Key）：

| 分支 | code | status | retryable | message |
|---|---|---|---|---|
| 视觉未配置 / 主档未就绪 | `AI_UNAVAILABLE` | 503 | false | 图片识别未开通，请改用 PDF 上传（主档原因透传） |
| 0 张 / 超过 3 张 | `VALIDATION_ERROR` | 400 | false | 请至少上传 1 张图片 / 一次最多上传 3 张图片 |
| 空文件 | `EMPTY_FILE` | 400 | false | 图片内容为空，请重新选择 |
| 单张或总量超 `max_upload_bytes()` | `FILE_TOO_LARGE` | 413 | false | 单张图片超过 {n}MB… / 图片总大小超过 {n}MB… |
| 非 JPEG / PNG / WebP（按真实字节判断） | `UNSUPPORTED_TYPE` | 415 | false | 仅支持 JPG / PNG / WebP 图片 |
| 汇总字数 < 60 | `VALIDATION_ERROR` | 400 | false | 识别到的文字太少，请重拍（正对、光线充足）或改用 PDF |
| 模型超时 / 5xx / 429 | `AI_UNAVAILABLE` | 503 | **true** | 图片识别失败，请稍后重试 |
| 旧端点收到图片后缀 | `UNSUPPORTED_TYPE` | 415 | false | 图片简历请用「拍照 / 相册上传」入口（支持 JPG / PNG / WebP） |

## 2. 契约同步（两侧一次改完）

- `backend/app/schemas.py` ↔ `frontend/src/api/types.ts`：`ResumeMeta` 同步新增 `source_type`、`image_count`，字段名 snake_case，JSON 零转换。
- `frontend/src/api/client.ts`：新增 `uploadResumeImages(files, signal)`，`FormData` 逐个 `append('files', f)`。
- `frontend/src/lib/profileJob.ts`：`jobToResumeMeta` 补 `source_type: 'pdf'` / `image_count: 1` —— 任务行（`profile_jobs`）不携带来源信息，不做表结构扩张，读路径按文档型简历的缺省值补齐；对应单测同步更新。

## 3. 前端改动（功能 A · `UploadPage.tsx`）

- **两个隐藏 input**：拍照 `accept="image/*" capture="environment"`（单选）、相册 `multiple`；hero 次按钮新增「拍照上传」。
- **预处理** `compressImage`：`<img>` 解码（EXIF 方向由浏览器渲染校正）→ canvas 等比缩到最长边 **1600** → JPEG **0.85**（白底填充避免透明 PNG 变黑）；解码失败给中文提示「这张图片打不开，请重新拍照或改用 PDF」。
- **上限 3 张**：超出按剩余名额截断并提示「本次只保留前 n 张」；单张 > 10MB 在前端先拦。
- **缩略图**：`--thumb-size` 56×56，右上删除按钮视觉 20、命中区 44（透明外扩）；`object URL` 在删除与卸载时 `revokeObjectURL`。
- **提交**：整批一次请求（1–3 张共用同一 `resume_id`），成功后沿用 r30 异步画像任务；阶段文案为「上传图片 / 识别图片中的文字 / AI 生成并合并画像」。
- **失败重试**：`InlineError` 原样展示 envelope 文案，「重试」按 `failure.stage` 分流（上传阶段整批重传）。
- **成功卡**：`source_type=image` 时额外一行「照片识别 · n 张拼成一份简历；只保存识别正文，原图未留存」。

## 4. 前端改动（功能 B）

**新 `frontend/src/lib/studyPlan.ts`（纯函数，可单测）**

- 候选池：`report.weakness_map` 每条一个候选，权重 `必备度×2 + 难度 + (1 − 错误率)×2`；只对唯一取值的筛选参数收窄链接。
- 任务生成：每短板最多「教程 1 + 练题 1」；教程指向该章**第一个未读小节**（整章已读则只留练题）；难度递进的「先读基础章」是**代理**（该方向基础章一节未读时插前置任务），UI 不宣称真实课程依赖。
- 装箱：按权重降序、`task.id` 去重，7 天贪心装箱（预算 15/30/60），排不下即截断并置 `truncated`。
- 补位：空天用通用任务（回看报告 / 重做错题 / 综合练习 / 模拟笔试 / 模拟面试）补到每天至少一条，`reason` 标注「通用建议」，**绝不编造短板名**。
- 存储：计划快照 `sc.plan.<userId>.<reportId>`、打卡与时长偏好 `sc.planState.<userId>.<reportId>`（拆两个 key，改时长重算不覆盖已完成 task.id）；解析失败一律退回重算 / 空状态，不炸页面。

**`frontend/src/components/report/WeekPlan.tsx`（重写数据层，保留卡片壳）**

- 15/30/60 分钟三档切换（`aria-pressed`）、任务粒度勾选、完成度进度条（`role="progressbar"`）。
- 固定文案 `PLAN_LOCAL_ONLY_NOTICE`：**「计划与打卡只保存在这台设备的浏览器里：换设备或换浏览器看不到，也不会同步。打卡只记「做完」，不计入熟练度或成绩。」** —— 落实「不跨设备必须界面上明说」。
- 旧报告（`weakness_map === null`）与无短板（`[]`）各给既有口径的提示，不渲染空计划。

**退役**：`frontend/src/lib/reportPlan.ts` 与其单测一并删除；`guidance.ts`、`TutorialPage.tsx` 的 `practiceHref` 导入切到 `studyPlan.ts`（全仓无其他引用）。

## 5. 样式与尺寸

- `tokens.css` 新增 `--thumb-size: 56px`、`--plan-task-min-h: 56px`，推导见 `docs/teamflow/20261108-r40-mobile-usable/DESIGN-MOBILE.md` §6（本轮增补）；既有 `--btn-h / --iq-composer-h / --iq-scroll-pad` 推导链未动。
- `base.css`：新增 `.sc-lab-image-entry` 及其子类（≤430 按钮占满行）、计划任务的 taskhead / meta / go / duration / progress / truncated 等；7 天计划在**文件末尾**用同选择器把 `.sc-lab-week .sc-plan-list` 覆盖成单列 flex（`grid-template-columns` 在 flex 容器下自然失效），r38 的周网格定义与媒体查询**原样保留**（样式基座是 append-only，工程门禁会拦删改）。全部只用 token，无裸色值 / 裸尺寸。

## 6. 与 TECH-PLAN 的差异（均为实现约束下的合理收敛）

1. **多图逐张独立请求**，而非一次请求塞多个图片块：每页可单独重试、页标与失败定位更清楚；代价是最多 3 次往返。
2. **`resolve_vision()` 独立方法**，未把配置字段塞进 `AiRuntime`：`AiRuntime` 是运行时值对象（含 `ready/reason`），配置解析留在 `Settings`。
3. **`<60` 字按多图汇总判定**（不是逐页），与「多图拼成一份简历」的口径一致；单页糊但合计够用时仍可通过。
4. `profile_jobs` 不扩表：`jobToResumeMeta` 用文档型简历缺省值补齐契约字段。
5. `reportPlan.ts` 直接删除（无外部引用），不保留 deprecated 壳。
6. `--plan-task-min-h` 的标题行高按 `--lh-small` 20（TECH-PLAN §2.5 原写 24 为笔误，已同步修正）。

## 7. 验证结果

见同目录 `QA-REPORT.md`：后端 r41 用例 8/8 通过、`ruff` 干净；前端 `typecheck / lint / test (207) / build` 全通过；真实 DeepSeek 视觉探针返回 200（`/v1` 路径 + `deepseek-flash` + data URL 可用）。
