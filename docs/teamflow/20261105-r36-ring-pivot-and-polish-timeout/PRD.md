# r36：进度环弧线偏心甩出轨道修复 + 简历润色专用超时

## 背景

用户反馈两件事：① 上传页「进度条还是有问题」；② 简历润色也超时了。

## 问题 1：进度环弧线甩出轨道（真正的一直存在的展示 bug）

截图放大后确认：灰色轨道是完整圆，但强调色的旋转弧**不在轨道上**——绕着一个偏心枢轴甩出环外乱转。之前 r31/r35 修的都是布局（卡宽、左右排列），环本身的渲染一直是坏的。

### 根因

`RingProgress` 的 indeterminate 动画写在 SVG 内部的 `<circle class="sc-ring-value">` 上：

```css
.sc-ring.is-indeterminate .sc-ring-value {
  animation: sc-ring-spin 1.2s linear infinite;
  transform-origin: center;
}
```

Chrome 对 **SVG 子元素**的 CSS transform 动画，`transform-origin` 无论按默认 `view-box` 还是显式 `transform-box: fill-box` 解析，实测枢轴都不落在圆心（`getComputedStyle().transform` 带 22~44px 的平移分量），弧线整体被甩离轨道。

### 修复（两次尝试，最终方案）

- 尝试 A：`transform-box: fill-box; transform-origin: center` —— computed style 确认生效（origin 22px 22px = 圆心），**但弧线仍偏出轨道**，SVG 子元素行为不可靠，弃用
- **最终方案：把动画移到 `<svg>` 根元素**——它是常规盒模型元素，`transform-origin: center` 严格等于自身 56×56 的中心，无 SVG 语义歧义：

```css
.sc-ring.is-indeterminate {
  animation: sc-ring-spin 1.2s linear infinite;
  transform-origin: center;
}
```

内部 circle 的 SVG 属性 `transform="rotate(-90 28 28)"` 保留——determinate（倒计时/完成度）弧的 12 点起点不受影响（它们没有 CSS transform 覆盖，一直是对的；坏的只有 indeterminate）。

### 复验

4 帧连拍：弧线完全贴合轨道、圆心正确、逐帧转动。副作用：元素持续变动会让 Playwright 元素截图报「not stable」，改用 clip 截图即可。

## 问题 2：简历润色超时

`resume_polish.build_suggestions` 沿用全局 `AI_TIMEOUT_S=20`：润色要逐条「逐字抄录原句 + 改写 + 说明」输出大 JSON，与画像生成同属重调用，真实简历 + 网络波动下必撞 20s。

修复（与 r34 同一策略）：

- `POLISH_TIMEOUT_S = 120.0` 专用超时
- `retry_unavailable=True`：超时/5xx/429 自动重来一次；鉴权/额度不重试

实测：真实后端润色大简历 **8.6s 返回 200**（此前 20s 判死）。

## 校验

- ruff 全绿；相关后端测试 41 passed / 1 skipped
- 前端 typecheck / lint / 205 测试 / build 全绿（本轮无 TS 改动，回归确认）
