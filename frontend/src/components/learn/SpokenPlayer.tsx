/**
 * 听模式播放器（r151）：有音频就播，没音频就**明确说素材缺失**并退化为口播稿浏览。
 *
 * 两条铁律（来自 r150 的发布口径与 RELEASE-DATA-SOP）：
 * 1. 音频是离线预生成的部署期资产——本组件从不调 TTS，也绝不渲染「点了没声音」的空播放器；
 *    manifest 探测不到（404 / 损坏）一律走「素材筹备中」态。
 * 2. 任何播放出来的音频都是 AI 生成（manifest `aiGenerated` 缺省 true）——角标常驻，
 *    音色溯源（模型 / LoRA / 参考音）放 title 提示，不进产品文案。
 *
 * `chapter`（内嵌口播稿）可选：全量流水线（make_audio.py）合成的章只存在于
 * `/audio/index.json` + manifest，前端没有内嵌文本——ready 态完全由 manifest 驱动
 * （小节 tab 用 track.title），missing 态有内嵌稿才渲染口播稿浏览，没有就只给提示。
 *
 * 断点续听与阅读进度同源同链路：写 `state/learnProgress`（本地缓存 + 防抖整份 PUT 上云），
 * 契约字段为 `heard` / `listen_section_id` / `listen_position_ms`（r151 双侧同步，跨设备合并取新）。
 * 泛听三档（VERSION-PLAN §4.1）：本节循环 / 整章连播 / 跨章续播（`nextListenHref`）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { EMOTION_SPECS } from '../../lib/spoken'
import {
  loadSpokenAudio,
  spokenSectionDurationMs,
  type SpokenAudioCue,
  type SpokenAudioManifest,
  type SpokenAudioState,
} from '../../lib/spokenAudio'
import { PLAYBACK_SPEEDS, activeCueIndex, formatMs, validResume } from '../../lib/spokenPlayer'
import type { SpokenChapter, SpokenSection, SpokenSpeaker } from '../../lib/spokenTypes'
import {
  getLearnProgress,
  markListenPosition,
  markSectionHeard,
} from '../../state/learnProgress'

const SPEAKER_LABELS: Record<SpokenSpeaker, string> = {
  dou: '逗哏',
  peng: '捧哏',
  narrator: '旁白',
}

const HIGHLIGHT_FLAG_KEY = 'sc.listen.highlight'

function readHighlightFlag(): boolean {
  try {
    return window.localStorage.getItem(HIGHLIGHT_FLAG_KEY) !== '0'
  } catch {
    return true
  }
}

function emotionLabel(cue: SpokenAudioCue): string | null {
  const spec = EMOTION_SPECS[cue.emotion as keyof typeof EMOTION_SPECS]
  return spec?.label ?? null
}

/* ---------- 素材缺失态：提示 + 口播稿浏览（有内嵌稿才有） ---------- */

function MissingNotice({ chapterId }: { chapterId: string }) {
  return (
    <div className="sc-listen-missing" role="status">
      <p className="sc-listen-missingtitle">音频素材筹备中</p>
      <p className="sc-listen-missingtext">
        这一章的口播稿已完成并通过质量闸，但可发布的合规音频素材还在整理中（当前持有的配音素材
        授权不允许公开分发）。素材上线后这里就是完整播放器——届时无需升级前端，服务器放入音频即可。
      </p>
      <p className="sc-listen-missingmeta">素材目录约定：/audio/{chapterId}/（nginx 静态分发）</p>
    </div>
  )
}

function ScriptBrowse({ chapter }: { chapter: SpokenChapter }) {
  return (
    <div className="sc-listen-script">
      {chapter.sections.map((section: SpokenSection) => (
        <section key={section.sectionId} className="sc-listen-scriptsec">
          <h3 className="sc-listen-scripttitle">{section.title}</h3>
          {section.segments.map((segment, segIndex) => (
            <p key={segIndex} className="sc-listen-scriptline">
              <span className="sc-listen-scripttag">
                {SPEAKER_LABELS[segment.speaker]} · {EMOTION_SPECS[segment.emotion].label}
              </span>
              {segment.lines.join('')}
            </p>
          ))}
        </section>
      ))}
    </div>
  )
}

/* ---------- 就绪态：播放器（纯 manifest 驱动，不依赖内嵌口播稿） ---------- */

interface ReadyPlayerProps {
  chapterTitle: string
  manifest: SpokenAudioManifest
  /** 下一章的听模式链接（有稿才给）：整章播完后的跨章续播入口，`null` 表示没有下一章。 */
  nextListenHref: string | null
  /** URL 带 `autoplay=1` 时进页即播（跨章续播的落地方式；浏览器拒绝时静默降级为暂停态）。 */
  autoplay: boolean
}

function ReadyPlayer({ chapterTitle, manifest, nextListenHref, autoplay }: ReadyPlayerProps) {
  const navigate = useNavigate()
  const chapterId = manifest.chapterId
  const sectionIds = useMemo(() => manifest.tracks.map((t) => t.sectionId), [manifest])

  const [sectionId, setSectionId] = useState<string | null>(() => {
    // 断点存在进度 store（本地缓存 + 服务端合并结果）：只认仍有效的小节，失效从章首开始。
    const stored = getLearnProgress().chapters[chapterId]
    const valid = validResume(
      stored === undefined
        ? null
        : { sectionId: stored.listenSectionId ?? '', positionMs: stored.listenPositionMs },
      sectionIds,
      undefined,
    )
    return valid === null ? (sectionIds[0] ?? null) : valid.sectionId
  })
  const [playing, setPlaying] = useState(false)
  const [loopSection, setLoopSection] = useState(false)
  const [positionMs, setPositionMs] = useState(0)
  const [speed, setSpeed] = useState<number>(1)
  const [highlightOn, setHighlightOn] = useState(readHighlightFlag)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const lastSavedMsRef = useRef(0)
  /** 泛听开关要在 ended 回调里读到最新值：state 会闭包过期，ref 同步。 */
  const loopRef = useRef(loopSection)
  loopRef.current = loopSection

  const track = manifest.tracks.find((item) => item.sectionId === sectionId) ?? manifest.tracks[0]
  const sectionLabel = track.title ?? track.sectionId
  const durationMs = spokenSectionDurationMs(manifest, track.sectionId) ?? track.durationMs
  const cues = track.cues
  const sessionTitle = `${chapterTitle} · ${sectionLabel}`

  // 换章 / 换账号后重读断点：只认仍然有效的小节，失效就从章首开始。
  useEffect(() => {
    const stored = getLearnProgress().chapters[chapterId]
    const valid = validResume(
      stored === undefined
        ? null
        : { sectionId: stored.listenSectionId ?? '', positionMs: stored.listenPositionMs },
      sectionIds,
      undefined,
    )
    setSectionId((prev) =>
      prev !== null && sectionIds.includes(prev)
        ? prev
        : (valid?.sectionId ?? sectionIds[0] ?? null),
    )
  }, [chapterId, sectionIds])

  const persistResume = useCallback(
    (ms: number, force: boolean) => {
      const last = lastSavedMsRef.current
      if (!force && Math.abs(ms - last) < 3000) return
      lastSavedMsRef.current = ms
      markListenPosition(chapterId, track.sectionId, ms)
    },
    [chapterId, track.sectionId],
  )

  // 播放速率：换节 / 改档都同步到 audio 元素。
  useEffect(() => {
    const audio = audioRef.current
    if (audio === null) return
    audio.playbackRate = speed
  }, [speed, sectionId])

  // 断点对齐：只在换节时执行（timeupdate 走 persistResume 的节流，不走这里）。
  useEffect(() => {
    const audio = audioRef.current
    if (audio === null) return
    const stored = getLearnProgress().chapters[chapterId]
    const valid = validResume(
      stored === undefined
        ? null
        : { sectionId: stored.listenSectionId ?? '', positionMs: stored.listenPositionMs },
      sectionIds,
      durationMs,
    )
    const startMs = valid !== null && valid.sectionId === track.sectionId ? valid.positionMs : 0
    if (Math.abs(audio.currentTime * 1000 - startMs) > 500) {
      audio.currentTime = startMs / 1000
      setPositionMs(startMs)
    }
    lastSavedMsRef.current = startMs
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 只在换节时对齐断点
  }, [track.sectionId])

  // 跨章续播：URL 带 autoplay=1 时进页即播（浏览器拒绝自动播放则静默停在暂停态）。
  useEffect(() => {
    if (!autoplay) return
    const audio = audioRef.current
    if (audio === null) return
    void audio.play().catch(() => {
      /* 自动播放被策略拦截：停在暂停态，用户手动点播放 */
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 只在挂载时尝试一次
  }, [])

  // MediaSession：耳机键 / 锁屏元数据（VERSION-PLAN §4.1）。标题先算成纯值，依赖数组不用对象。
  useEffect(() => {
    if (typeof navigator === 'undefined' || !('mediaSession' in navigator)) return
    const media = navigator.mediaSession
    try {
      media.metadata = new MediaMetadata({
        title: sessionTitle,
        artist: 'SkillCoach 口播（AI 生成）',
        album: chapterTitle,
      })
      media.setActionHandler('play', () => void audioRef.current?.play())
      media.setActionHandler('pause', () => audioRef.current?.pause())
      media.setActionHandler('seekbackward', () => {
        const audio = audioRef.current
        if (audio !== null) audio.currentTime = Math.max(0, audio.currentTime - 10)
      })
      media.setActionHandler('seekforward', () => {
        const audio = audioRef.current
        if (audio !== null) audio.currentTime = Math.min(durationMs / 1000, audio.currentTime + 10)
      })
    } catch {
      /* 浏览器不支持部分 API：不影响页面内播放 */
    }
    return () => {
      try {
        media.setActionHandler('play', null)
        media.setActionHandler('pause', null)
        media.setActionHandler('seekbackward', null)
        media.setActionHandler('seekforward', null)
      } catch {
        /* 同上 */
      }
    }
  }, [chapterTitle, sessionTitle, durationMs])

  const togglePlay = useCallback(() => {
    const audio = audioRef.current
    if (audio === null) return
    if (audio.paused) void audio.play()
    else audio.pause()
  }, [])

  const handleTimeUpdate = useCallback(() => {
    const audio = audioRef.current
    if (audio === null) return
    const ms = audio.currentTime * 1000
    setPositionMs(ms)
    persistResume(ms, false)
  }, [persistResume])

  const handleEnded = useCallback(() => {
    // 听完一节 = `heard` 一节（与 `seen` 并列，不进阅读口径）。
    markSectionHeard(chapterId, track.sectionId)
    persistResume(durationMs, true)
    // 泛听第一档：本节循环——回到节首继续播，不推进。
    if (loopRef.current) {
      const audio = audioRef.current
      if (audio !== null) {
        audio.currentTime = 0
        void audio.play()
      }
      return
    }
    // 泛听第二档：整章连播——本节播完自动进下一节。
    const index = sectionIds.indexOf(track.sectionId)
    const nextId = index >= 0 && index + 1 < sectionIds.length ? sectionIds[index + 1] : null
    if (nextId !== null) {
      setSectionId(nextId)
      // 换节后 React 会先渲染新的 <audio src>，这里延迟一拍再播。
      window.setTimeout(() => void audioRef.current?.play(), 50)
      return
    }
    // 泛听第三档：跨章续播——整章播完跳下一章听模式（autoplay 让下一章接着播）。
    if (nextListenHref !== null) {
      navigate(nextListenHref)
    }
  }, [chapterId, durationMs, navigate, nextListenHref, persistResume, sectionIds, track.sectionId])

  const seekTo = useCallback((ms: number) => {
    const audio = audioRef.current
    if (audio === null) return
    audio.currentTime = ms / 1000
    setPositionMs(ms)
  }, [])

  const activeIndex = activeCueIndex(cues, positionMs)

  return (
    <div className="sc-listen">
      <div className="sc-listen-badge" title={`模型 ${manifest.voice.model}${manifest.voice.lora ? ` / ${manifest.voice.lora}` : ''}`}>
        <span className="sc-listen-badgetag">AI 生成音频</span>
        <span className="sc-listen-bademeta">{manifest.voice.model}</span>
      </div>

      <div className="sc-listen-sections" role="tablist" aria-label="口播小节">
        {manifest.tracks.map((item) => {
          const isActive = item.sectionId === track.sectionId
          const label = item.title ?? item.sectionId
          const ms = spokenSectionDurationMs(manifest, item.sectionId)
          return (
            <button
              key={item.sectionId}
              type="button"
              role="tab"
              aria-selected={isActive}
              className={isActive ? 'sc-listen-sectab is-active' : 'sc-listen-sectab'}
              onClick={() => setSectionId(item.sectionId)}
            >
              <span>{label}</span>
              {ms !== null && <span className="sc-listen-sectabmeta">{formatMs(ms)}</span>}
            </button>
          )
        })}
      </div>

      <div className="sc-listen-controls">
        <button
          type="button"
          className="sc-listen-playbtn"
          onClick={togglePlay}
          aria-label={playing ? '暂停' : '播放'}
        >
          {playing ? '⏸' : '▶'}
        </button>
        <span className="sc-listen-time">{formatMs(positionMs)}</span>
        <input
          className="sc-listen-seek"
          type="range"
          min={0}
          max={Math.max(1, durationMs)}
          value={Math.min(positionMs, durationMs)}
          onChange={(event) => seekTo(Number(event.target.value))}
          aria-label="播放进度"
        />
        <span className="sc-listen-time">{formatMs(durationMs)}</span>
        <label className="sc-listen-speed">
          倍速
          <select
            value={speed}
            onChange={(event) => setSpeed(Number(event.target.value))}
            aria-label="播放倍速"
          >
            {PLAYBACK_SPEEDS.map((rate) => (
              <option key={rate} value={rate}>
                {rate}×
              </option>
            ))}
          </select>
        </label>
        <label className="sc-listen-highlightflag" title="播完本节回到节首继续，适合磨耳朵">
          <input
            type="checkbox"
            checked={loopSection}
            onChange={(event) => setLoopSection(event.target.checked)}
          />
          本节循环
        </label>
        <label className="sc-listen-highlightflag">
          <input
            type="checkbox"
            checked={highlightOn}
            onChange={(event) => {
              setHighlightOn(event.target.checked)
              try {
                window.localStorage.setItem(HIGHLIGHT_FLAG_KEY, event.target.checked ? '1' : '0')
              } catch {
                /* 存不进就本次会话生效 */
              }
            }}
          />
          句级高亮
        </label>
      </div>

      <div className="sc-listen-cues">
        {cues.map((cue, index) => {
          const isActive = index === activeIndex && positionMs > 0
          const emotion = emotionLabel(cue)
          return (
            <button
              key={`${cue.startMs}-${index}`}
              type="button"
              className={
                'sc-listen-cue' +
                (isActive && highlightOn ? ' is-active' : '') +
                (cue.speaker === 'peng' ? ' is-peng' : '')
              }
              onClick={() => seekTo(cue.startMs)}
            >
              <span className="sc-listen-cuetag">
                {SPEAKER_LABELS[cue.speaker]}
                {emotion !== null ? ` · ${emotion}` : ''}
              </span>
              <span className="sc-listen-cuetext">{cue.text}</span>
            </button>
          )
        })}
      </div>

      <audio
        ref={audioRef}
        src={track.src}
        preload="metadata"
        onPlay={() => setPlaying(true)}
        onPause={() => {
          setPlaying(false)
          const audio = audioRef.current
          if (audio !== null) persistResume(audio.currentTime * 1000, true)
        }}
        onTimeUpdate={handleTimeUpdate}
        onEnded={handleEnded}
      />
    </div>
  )
}

/* ---------- 组件本体 ---------- */

export function SpokenPlayer({
  chapterId,
  chapter,
  chapterTitle,
  nextListenHref = null,
  autoplay = false,
}: {
  /** 章 id（探测 /audio/<chapterId>/manifest.json 的依据）。 */
  chapterId: string
  /** 内嵌口播稿（3 章黄金稿有；全量流水线合成的章为 `null`——文案只存在于音频产物里）。 */
  chapter: SpokenChapter | null
  chapterTitle: string
  /** 下一章听模式链接（跨章续播）；缺省 `null` = 没有下一章。 */
  nextListenHref?: string | null
  /** 跨章续播落地时自动播放（默认关，本地直接进听页不自动响）。 */
  autoplay?: boolean
}) {
  const [audioState, setAudioState] = useState<SpokenAudioState>({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    setAudioState({ status: 'loading' })
    void loadSpokenAudio(chapterId).then((state) => {
      if (!cancelled) setAudioState(state)
    })
    return () => {
      cancelled = true
    }
  }, [chapterId])

  if (audioState.status === 'loading') {
    return <div className="sc-listen-loading">正在探测音频资产…</div>
  }

  if (audioState.status === 'missing') {
    return (
      <div className="sc-listen">
        <MissingNotice chapterId={chapterId} />
        {chapter !== null && <ScriptBrowse chapter={chapter} />}
      </div>
    )
  }

  return (
    <ReadyPlayer
      chapterTitle={chapterTitle}
      manifest={audioState.manifest}
      nextListenHref={nextListenHref}
      autoplay={autoplay}
    />
  )
}
