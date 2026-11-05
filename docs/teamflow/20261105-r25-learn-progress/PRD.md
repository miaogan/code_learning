# PRD · 学习模块阅读进度（r25）

## 1. 背景

`/learn` 上线后（`86e07d3`，r24 扩到 8 方向 × 3 档 = 24 章），教程本身已经完整可读，但**读完没有痕迹**：

- 目录页 24 张卡片永远长一个样子，用户看不出「哪章读过、读到哪、还剩哪些」；
- 关掉页面再回来，只能凭记忆手动找回上次的位置——4 节长文要重新翻一遍；
- 「画像 → 测评 → 报告 → 学习」的闭环在最后一步断了：报告能推荐章节，学习页却不记得用户走到哪。

r24 的 PRD §3.3 已把「阅读进度 / 已读标记」列为下一轮要做的项，本轮兑现。

## 2. 目标

1. **读到哪记得住**：以小节为粒度记录已读，进度在刷新、重开浏览器后仍在。
2. **继续学习一眼可见**：目录页顶部给出唯一入口，点进去直接落在上次看到的那一节。
3. **不打扰阅读**：不弹窗、不阻断、不要求登录才能读；进度只是辅助信息。
4. **按账号隔离**：同一台机器多人使用时，退出后不能把进度留给下一个人（与 `sc.flow` 同口径）。

## 3. 范围

### 3.1 进度模型

- 存储键：`sc.learn`（匿名）/ `sc.learn.<userId>`（登录），localStorage，**不进后端**。
- 数据形状：

```ts
interface LearnProgressState {
  lastChapterId: string | null                                   // 最近在读
  chapters: Record<string, { seen: string[]; lastSectionId: string | null; updatedAt: number }>
}
```

- **已读判定**：小节顶部进入视口上部 75% 即视为「读到」（IntersectionObserver，`rootMargin: 0 0 -25% 0`）。
  全部小节读到 = 本章「已读完」。口径是「读过」，不是「掌握」。
- **失效自愈**：`seen` 与当前章节的小节 id 求交集，内容改版后旧 id 自动失配，不需要迁移脚本，也不会把 2/4 算成 3/4。
- **打开 ≠ 读过**：`markChapterOpened` 只更新 `lastChapterId`，不写 `seen`；翻一眼就走不刷进度。

### 3.2 交互

- **目录页**
  - 页头统计：`已读 42% · 读完 3 章 · 在读 2 章`（按小节加权，无进度时不渲染）。
  - 顶部「继续学习」卡片：章节标题 + 方向/难度 + `读到 2/4 节 · 上次读到第 2 节` + 进度条 + `从这里接着读 →`。
  - 章节卡片：有进度时显示 `2/4 节` + 细进度条 + 状态（读到 2/4 节 / 已读完），底部动作随状态变成「继续阅读 / 再读一遍」。
- **文章页**
  - meta 行下方一条进度行：`读到 2/4 节` + 进度条（`role="progressbar"`，带 `aria-valuenow`）。
  - 带 `#tutorial-<sectionId>` 进入时滚到该小节；锚点失效（章节改版）则回页首。
- **状态优先级**：上次那章没读完 → 回那章那一节；读完了 → 顺延到目录里下一本没读完的；全部读完 → 不渲染入口。

### 3.3 不做（本轮）

全文搜索、章内 TOC 浮层、阅读时长统计、跨设备同步（需要后端表与合并策略）、把进度计入任何成绩或报告。

## 4. 验收标准

- AC-1 匿名与登录各用各的键：`user-a` 的进度在 `user-b` 登录后不可见，退回 `user-a` 能原样恢复。
- AC-2 打开章节不写已读小节；重复上报同一小节不产生重复记录；回滚到已读小节会更新续读位置。
- AC-3 进度视图三态正确（未开始 / 读到 N/M 节 / 已读完），百分比按小节计算，失效小节 id 不计入。
- AC-4 「继续学习」目标解析正确：无记录 → 第一章；未读完 → 同章同节（链接带 `#tutorial-xxx`）；读完 → 顺延下一本；全读完 → 无目标。
- AC-5 存储值损坏（非 JSON、字段类型错）时降级为空状态，不白屏、不抛错。
- AC-6 样式只用 design token，深色主题下进度条与状态文字对比度足够；颜色不是唯一信息（旁边总有文字）。
- AC-7 类型检查、lint、单测、构建全绿；r24 的方向/难度筛选与练习页零回归。

## 5. 验证

```bash
cd frontend
npm run typecheck && npm run lint && npm test -- --run && npm run build
```

结果：typecheck 通过；lint 0 warning；17 个测试文件 / **193 条用例**全通过（其中阅读进度 13 条、教程 17 条）；`dist/` 构建正常。

## 6. 改动清单

| 文件 | 变化 |
|---|---|
| `lib/learnProgress.ts` | 新增：进度视图（`progressView`）、续读目标（`resumeTarget`）、统计（`summarizeProgress`），纯函数无 DOM |
| `state/learnProgress.ts` | 新增：账号隔离 store，`markChapterOpened / markSectionSeen`，坏数据降级 |
| `state/auth.ts` | 登录态变化时同步绑定进度键 |
| `components/learn/TutorialArticle.tsx` | 小节 IntersectionObserver 上报（不支持时静默跳过） |
| `components/learn/ResumeCard.tsx` | 新增「继续学习」卡片 |
| `pages/TutorialPage.tsx` | 记录打开、进度行、`#tutorial-xxx` 断点定位 |
| `pages/LearnPage.tsx` | 页头统计、续读入口、卡片进度与状态化 CTA |
| `styles/base.css` | `.sc-learn-track*`、`.sc-learn-resume*`、`.sc-learn-chapterread`、`.sc-learn-readline` |
| `test/learnProgress.test.ts` | 新增 13 条：视图三态、失效 id、续读目标、统计、账号隔离、去重、坏数据 |
