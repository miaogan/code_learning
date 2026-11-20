import { useEffect, useState, type MouseEvent } from 'react'
import type { TutorialChapter } from '../../lib/tutorialTypes'

export interface TutorialTocProps {
  chapter: TutorialChapter
  /** 当前正在读的小节（由正文的可见性观察得出），高亮用。 */
  activeSectionId: string | null
  /** 已读小节 id（与进度条同一份数据）。 */
  readIds: Set<string>
  seen: number
}

/** 与 `.sc-learn-layout` 的侧栏断点保持一致：宽屏常驻，窄屏折叠。 */
const WIDE_QUERY = '(min-width: 1280px)'

/**
 * 宽屏时目录常驻右侧；窄屏默认折叠成一行，点开才展开。
 * `open` 只在跨越断点时由 React 改写，用户手动展开/收起不会被后续渲染覆盖。
 */
function useWideLayout(): boolean {
  const [wide, setWide] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(WIDE_QUERY).matches,
  )

  useEffect(() => {
    const query = window.matchMedia(WIDE_QUERY)
    const onChange = () => setWide(query.matches)
    onChange()
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  return wide
}

/**
 * 章内目录：4 个小节的锚点入口（锚点 id 由 `TutorialArticle` 生成，`#tutorial-<sectionId>`）。
 *
 * 三件事同时说清：读到第几节（高亮）、哪几节读过（✓）、一共几节。
 * r148：点击改为**模拟滚动**（`scrollIntoView({ behavior: 'smooth' })`）——浏览器原生
 * hash 跳转是瞬移，长章节里读者会失去「自己在哪里」的位置感；目标小节自带的
 * `scroll-margin-top` 保证落点不被粘性顶栏压住。hash 照旧更新（`pushState` 不触发
 * 原生跳转），链接仍可直接分享；初次进页（「继续学习」深链）仍走瞬时定位。
 */
export function TutorialToc({ chapter, activeSectionId, readIds, seen }: TutorialTocProps) {
  const wide = useWideLayout()

  const jumpTo = (event: MouseEvent<HTMLAnchorElement>, sectionId: string): void => {
    event.preventDefault()
    document.getElementById(`tutorial-${sectionId}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    window.history.pushState(null, '', `#tutorial-${sectionId}`)
  }

  return (
    <details className="sc-learn-toc" open={wide}>
      <summary className="sc-learn-tocsummary">
        <span>本章目录</span>
        <span className="sc-learn-toccount">{`${seen}/${chapter.sections.length} 节已读`}</span>
      </summary>

      <nav aria-label="本章小节">
        <ol className="sc-learn-toclist">
          {chapter.sections.map((section, index) => {
            const active = section.id === activeSectionId
            const read = readIds.has(section.id)
            return (
              <li key={section.id}>
                <a
                  className={active ? 'sc-learn-tocitem is-active' : 'sc-learn-tocitem'}
                  href={`#tutorial-${section.id}`}
                  onClick={(event) => jumpTo(event, section.id)}
                  aria-current={active ? 'location' : undefined}
                  aria-label={`第 ${index + 1} 节 ${section.title}${read ? '（已读）' : ''}`}
                >
                  <span className="sc-learn-tocnum" aria-hidden="true">
                    {index + 1}
                  </span>
                  <span className="sc-learn-toctext">{section.title}</span>
                  {read ? (
                    <span className="sc-learn-tocmark" aria-hidden="true">
                      ✓
                    </span>
                  ) : null}
                </a>
              </li>
            )
          })}
        </ol>
      </nav>
    </details>
  )
}
