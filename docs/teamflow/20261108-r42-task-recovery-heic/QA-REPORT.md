# QA-REPORT · r42

> 记录本轮实际执行的验证、结果与**没测到的部分**。不把「按文档推断」写成「实测」。

---

## 1. 后端

```powershell
cd backend
python -m ruff check app tests
python -m pytest tests/test_r42_jobs.py tests/test_profile_job.py -q
```

| 项 | 结果 |
|---|---|
| ruff | 通过（0 error） |
| 任务 / 幂等 / 清扫 / 图片异步 / HEIC 共 15 例 | **15 passed** |

覆盖点：
- `test_profile_job_reuses_running_job`：同一简历重复提交返回同一 `job_id`，库里只有一条 running。
- `test_resume_job_reuses_running_job`：同一批图片字节重复提交返回同一 `job_id`。
- `test_stale_profile_job_is_failed_on_read` / `test_stale_resume_job_is_failed_on_read`：僵尸行读一次即 `failed` + 中文原因。
- `test_image_job_completes_and_stores_resume`：受理 → 轮询 → `completed`，`ResumeMeta` 正确且正文真的入库。
- `test_image_job_failure_is_visible`：AI 失败落 `failed` + 可展示中文。
- `test_heic_gets_dedicated_message`（同步 / 异步两个入口）：HEIC → `UNSUPPORTED_TYPE` + 专用文案（含「兼容性最佳」）。

> 未跑后端全量：仓库既有全量 pytest 极慢（单轮可达 20 分钟以上），本轮只跑受影响的两个文件；未改动的模块由既有测试保障。

---

## 2. 前端

```powershell
cd frontend
npm run typecheck
npm run lint
npm test -- --run
npm run build
```

| 项 | 结果 |
|---|---|
| typecheck | 通过 |
| lint | 通过（0 warning） |
| vitest | **219 passed / 19 files**（新增 `uploadSession.test.ts` 12 例） |
| build | 通过（141 modules） |

新增测试覆盖：会话按账号隔离、24h 失效与脏数据清理、完成态 30 分钟回放窗口、已用秒数、HEIC 字节识别（含真实样本头）。

---

## 3. HEIC：实测与推断分开写

### 3.1 实测确认（本机可完成的部分）

1. **真实 HEIC 样本的真实字节**
   - 样本：`libheif` 的 `example.heic`（718,114 字节，下载仅用于探针，未入库）。
   - 头部：`00 00 00 1c ftyp mif1 00 00 00 00 mif1 heic hevc ...`
   - 后端 `is_heif()` / 前端 `isHeifHeader()` 都按 major brand + 兼容品牌识别 → 判为 HEIC（已写入单测，真实样本头作为固定 fixture）。

2. **桌面 Chromium 不能解码 HEIC**
   - 环境：`Chrome/142.0.7444.235`（Electron / Trae 内核，Windows 10）。
   - 做法：本地 HTTP 服务 + 真实 `sample.heic` + `new Image()` → `canvas.drawImage` / `getImageData`。
   - 结果：`loaded=false`、`naturalWidth=0`、`error="decode-error"`、`canvas="not-run"`。
   - 结论：**浏览器确实可能完全解不开 HEIC**；前端若只依赖 canvas 解码，用户只会得到笼统失败。r42 的「读字节 → 专用文案」是必要兜底。

3. **后端嗅探不会把 HEIC 误判成 JPG/PNG**：`sniff_image_mime` 返回 `None`，`sniff_or_raise` 走 HEIC 分支 → 415 + 专用文案。

### 3.2 测不了（如实标注）

| 事项 | 状态 | 说明 |
|---|---|---|
| iOS Safari 从「相册选原图」是否把 HEIC 转成 JPEG | **测不了** | 本环境无 iOS 真机 / 模拟器；Playwright WebKit 未安装，且 Windows 上的 WebKit 不代表 iOS Safari 的相册转码行为 |
| iOS Safari `<canvas>` 解码 HEIC | **测不了** | 同上 |
| Android 各厂商相册行为 | **测不了** | 无设备矩阵 |

### 3.3 按公开行为推断（不是实测）

- iOS 通过 `<input type="file" accept="image/*">` 调系统照片选择器时，常见行为是**转码为 JPEG** 再交给网页。
- 走「文件」App 直接选 `.heic`，或部分 Android / 桌面浏览器，会**原样送出 HEIC**。
- 因此实现不假设「一定转码成功」：前后端都按真实字节兜底；不能解码时给可行替代路径（相机格式改「兼容性最佳」/ 相册导出 JPG / PNG）。

---

## 4. 兼容性核对

| 项 | 结论 |
|---|---|
| 旧同步 `POST /api/resumes` / `POST /api/resumes/images` / `POST /api/resumes/{id}/profile` | 签名与响应不变；同步图片入口只把「格式不支持」细化为 HEIC 专用文案 |
| r30 async/latest | 复用；多简历并发受理改为复用同一在途任务 |
| r32 失败可见性 | 复用；清扫阈值 10 → 30 分钟（避免误杀合法长任务） |
| r33 24h 失败窗口 | 未改 |
| r34 超时 / 重试 | 未改；新增任务级 `wait_for` 兜住客户端超时失效 |
| 错误码闭集 | 未新增；HEIC 复用 `UNSUPPORTED_TYPE` |
| 契约两侧 | `schemas.py` ↔ `types.ts` 同步，全 snake_case |
| 样式 | 零 CSS 改动，无新 token；复用既有窄屏规则 |

---

## 5. 遗留与风险

1. 服务重启会中断在途任务：行被清扫为 `failed`，用户需重试（不承诺断点续跑）。
2. 图片字节在任务期间驻留内存（与 r41 同口径，最多 3 张 × 10MB）。
3. 本地会话被清缓存 / 换浏览器后，只能靠服务端 `latest`（仅 running）恢复；已完成的历史任务不回放。
4. 未在 iOS 真机验证 HEIC；若后续有条件，应按 §3.2 补测并回写本文件。
