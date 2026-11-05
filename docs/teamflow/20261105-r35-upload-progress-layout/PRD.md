# r35：上传页进度卡左右布局 + 重接入秒数从真实起点起算

## 背景

用户反馈「还是前端的那个上传简历的进度条的问题，还是有展示 bug」。r31 修掉了卡片被挤成细条的问题，但截图走查发现**卡片内部的布局仍然不对**。

## 问题（截图复现确认）

1. **环形进度圈孤零零占一行**：`.sc-upload-summary` 是 column flex，`RingProgress` 作为直接子项独占一行贴在卡片左上角，文件名 / 阶段列表 / 已用秒数 / 提示 / 按钮全部竖着挤在下面——卡片右半边大片空白，视觉上像坏掉而不是「进行中」。上传中、生成中、重接入三个进度态全部如此。
2. **重接入的「已用秒数」从 0 重计**：离开后回到上传页接上还在跑的任务时，秒数从 0 开始走——任务实际已在后台跑了 40 秒，页面显示「已用 1s」，进度语义失真。任务行里明明有 `created_at` 却没用。

## 修复

### 1. 环 + 阶段文字左右布局

- `base.css` 新增 `.sc-upload-progress { display: flex; align-items: center; gap: var(--sp-3) }`
- `UploadPage.tsx` 上传中 / 生成中两处把 `<RingProgress>` + `<PhaseLoader>` 包进 `.sc-upload-progress`：环在左垂直居中，标题 + 阶段列表 + 秒数在右

### 2. 重接入秒数从真实起点起算

- `lib/profileJob.ts` 新增纯函数 `jobElapsedSec(job, nowMs)`：`Date.parse(job.created_at)` 差值换秒，向下取整；时间不可解 / 未来时间戳（本机时钟偏慢）一律按 0（宁少勿错）
- 重接入 effect 的 `shouldReattach` 分支 `setProfileSec(jobElapsedSec(job))`

## 复验

Playwright mock 全条上传 API（路由拦截，免后端），四态截图：

- 上传中：环与文件名 / 阶段列表并排，第 1 步脉冲 ✓
- 生成中：环与标题、前两步 ✓ 第三步脉冲并排 ✓
- 完成：无环，不受影响 ✓
- 重接入（mock created_at = 43 秒前）：页面显示「已用 45s」✓

前端 typecheck / lint 0 warning / 205 测试（新增 jobElapsedSec 1 条）/ build 全绿。
