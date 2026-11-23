# /audio/ —— 有声书音频资产挂载点（r151）

这里在容器里被挂到 nginx 的 `/usr/share/nginx/html/audio`（只读），
前端播放器按约定路径 `/audio/<章>/manifest.json` 探测音频。

## 素材缺失（当前状态）

**本目录目前是空的**：当前持有的配音素材（gdg 参考音 / LoRA）授权不允许公开分发，
生产环境对 `/audio/*` 一律 404，播放器渲染「音频素材筹备中」+ 口播稿浏览态。

## 素材上线（找到合法素材后）

1. 把合规素材经离线工具链合成（`scripts/tts/synthesize.py`，参考 RELEASE-DATA-SOP.md）；
2. 把产物按下面的结构放进本目录（服务器上即 `~/skillcoach/audio/`）：

```
audio/
  be-distributed-consistency/
    manifest.json          # 播放器入口，含 aiGenerated 标识与音色溯源
    concept.wav
    concept.timeline.json
    ...
```

3. 零发版：nginx 直接静态返回（`try_files $uri =404`，缓存 1 天），
   刷新页面播放器即从「素材筹备中」切到完整播放器。
4. 换素材 = 换文件名（缓存键）或 `docker compose restart frontend`（清 nginx 缓存头无必要，浏览器按 max-age 走）。

## 合规红线（RELEASE-DATA-SOP.md）

- 只上**可商用授权**的声音素材（本人 / 书面授权 / CC0 / Apache-2.0 等经许可集）；
- manifest 必须带 `aiGenerated: true`，界面角标不可移除；
- 素材溯源与 hash 记录在 `assets/manifest.json`。
