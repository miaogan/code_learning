# r29 — 上传页中途离开保护

## 背景

排查「上传过程中切换/刷新页面会不会中断」发现：

- **刷新 / 关闭标签页**：会中断。浏览器杀掉在途请求；后端 `upload_resume` 是单协程读 → 解析 → 入库的同步链路，断开时协程被取消、`insert_document` 不执行——要么完整入库、要么什么都没有，不会存半截文件。但上传页没有 `beforeunload` 拦截（笔试页 / 润色页都有），30 秒解析期间随手刷新就会白传。
- **站内切换路由**：不中断但更糟——UploadPage 没有卸载中止逻辑，请求继续在后台跑完，UI 状态却随组件销毁；用户回到上传页看到 idle，不知道上传已发生/失败，错误也无人看见。

## 修复（复用 ExamPage/PolishPage 的离开保护写法）

1. **busy（uploading/profiling）时**：`beforeunload` 原生提示 + 站内链接 click-capture 拦截，`ConfirmModal` 确认后先 `abort()` 再跳转。文案区分两阶段（上传中断需重传 / 生成中断简历不丢）。
2. **卸载兜底**：`useEffect(() => () => abortRef.current?.abort(), [])` —— 未被拦截路径（登出等）下不让请求变成无 UI 的后台任务。

## AC

- 上传/生成中刷新或关闭 → 浏览器弹原生确认。
- 上传/生成中点任意站内链接 → 确认弹窗；确认离开后无残留请求。
- 空闲态不拦截任何导航；`typecheck / lint / test / build` 全绿。

## 改动清单

- `frontend/src/pages/UploadPage.tsx`：新增 `pendingLeave` 状态、离开保护 effect、卸载中止 effect、`confirmLeave`、页尾 `ConfirmModal`。
- `docs/teamflow/20261105-r29-upload-leave-guard/`：本任务夹。
