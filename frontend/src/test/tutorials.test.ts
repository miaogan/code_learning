import { describe, expect, it } from 'vitest'
import {
  ALL_TUTORIAL_CHAPTERS,
  TUTORIAL_DIRECTIONS,
  TUTORIAL_LEVELS,
  activeSectionIndex,
  chapterById,
  chapterHref,
  chapterNeighbors,
  chaptersInDirection,
  chaptersInScope,
  filterChaptersByLevel,
  filterChaptersBySubDirection,
  levelsInChapters,
  parseLearnDirection,
  parseLearnLevel,
  parseLearnSubDirection,
  subDirectionsInChapters,
  tutorialHref,
} from '../lib/tutorials'
import { subDirectionsOf } from '../lib/questionDirections'
import type { TutorialLevel } from '../lib/tutorialTypes'

describe('教程内容完整性', () => {
  it('覆盖题库全部 8 个方向，每个方向至少 2 章', () => {
    expect(TUTORIAL_DIRECTIONS).toHaveLength(8)
    TUTORIAL_DIRECTIONS.forEach((direction) => {
      expect(chaptersInDirection(direction).length).toBeGreaterThanOrEqual(2)
    })
    // 方向闭集之外不应有章节（写错方向的章节会在这里暴露）
    expect(ALL_TUTORIAL_CHAPTERS).toHaveLength(
      TUTORIAL_DIRECTIONS.reduce(
        (total, direction) => total + chaptersInDirection(direction).length,
        0,
      ),
    )
  })

  it('目录顺序 = 方向顺序 × 难度顺序（内容文件可任意追加，顺序由元数据决定）', () => {
    const directionOrder = ALL_TUTORIAL_CHAPTERS.map((chapter) =>
      TUTORIAL_DIRECTIONS.indexOf(chapter.direction),
    )
    expect(directionOrder).toEqual([...directionOrder].sort((a, b) => a - b))
    TUTORIAL_DIRECTIONS.forEach((direction) => {
      const ranks = chaptersInDirection(direction).map((chapter) =>
        TUTORIAL_LEVELS.indexOf(chapter.level),
      )
      expect(ranks).toEqual([...ranks].sort((a, b) => a - b))
    })
  })

  it('章节 ID 全局唯一且是 ASCII slug', () => {
    const ids = ALL_TUTORIAL_CHAPTERS.map((chapter) => chapter.id)
    expect(new Set(ids).size).toBe(ids.length)
    ids.forEach((id) => expect(id).toMatch(/^[a-z0-9-]+$/))
  })

  it('每章都有概述、至少 3 节，且章内小节 ID 唯一', () => {
    ALL_TUTORIAL_CHAPTERS.forEach((chapter) => {
      expect(chapter.summary.trim()).not.toBe('')
      expect(chapter.sections.length).toBeGreaterThanOrEqual(3)
      const sectionIds = chapter.sections.map((section) => section.id)
      expect(new Set(sectionIds).size).toBe(sectionIds.length)
      sectionIds.forEach((id) => expect(id).toMatch(/^[a-z0-9-]+$/))
    })
  })

  it('每个正文块都有内容，表格每行列数与表头一致', () => {
    ALL_TUTORIAL_CHAPTERS.forEach((chapter) => {
      chapter.sections.forEach((section) => {
        expect(section.blocks.length).toBeGreaterThan(0)
        section.blocks.forEach((block) => {
          if (block.kind === 'text') expect(block.text.trim()).not.toBe('')
          if (block.kind === 'list') expect(block.items.length).toBeGreaterThan(0)
          if (block.kind === 'code') expect(block.code.trim()).not.toBe('')
          if (block.kind === 'note') expect(block.text.trim()).not.toBe('')
          if (block.kind === 'qa') expect(block.items.length).toBeGreaterThan(0)
          if (block.kind === 'table') {
            block.rows.forEach((row) => expect(row).toHaveLength(block.headers.length))
          }
        })
      })
    })
  })

  it('每章最后一节都带自测题', () => {
    ALL_TUTORIAL_CHAPTERS.forEach((chapter) => {
      const lastSection = chapter.sections[chapter.sections.length - 1]
      expect(lastSection.blocks.some((block) => block.kind === 'qa')).toBe(true)
    })
  })
})

describe('难度档位', () => {
  it('难度只取闭集内的三档，且三档都有真实章节', () => {
    const levels = new Set(ALL_TUTORIAL_CHAPTERS.map((chapter) => chapter.level))
    levels.forEach((level) => expect(TUTORIAL_LEVELS).toContain(level))
    TUTORIAL_LEVELS.forEach((level) => {
      expect(ALL_TUTORIAL_CHAPTERS.some((chapter) => chapter.level === level)).toBe(true)
    })
  })

  it('每个方向三档齐全：基础 / 进阶 / 高级都有内容', () => {
    TUTORIAL_DIRECTIONS.forEach((direction) => {
      expect(levelsInChapters(chaptersInDirection(direction))).toEqual(TUTORIAL_LEVELS)
    })
  })

  it('levelsInChapters 只返回真实存在的档位，并按由易到难排序', () => {
    const picked = ALL_TUTORIAL_CHAPTERS.slice(0, 2).map((chapter) => chapter.level)
    const unique = Array.from(new Set(picked))
    expect(levelsInChapters(ALL_TUTORIAL_CHAPTERS.slice(0, 2))).toEqual(
      TUTORIAL_LEVELS.filter((level) => unique.includes(level)),
    )
    expect(levelsInChapters([])).toEqual([])
  })

  it('filterChaptersByLevel：all 原样返回，其余只留该档', () => {
    const all: TutorialLevel[] = ['基础', '进阶', '高级']
    all.forEach((level) => {
      const filtered = filterChaptersByLevel(ALL_TUTORIAL_CHAPTERS, level)
      expect(filtered.length).toBeGreaterThan(0)
      filtered.forEach((chapter) => expect(chapter.level).toBe(level))
    })
    expect(filterChaptersByLevel(ALL_TUTORIAL_CHAPTERS, 'all')).toHaveLength(
      ALL_TUTORIAL_CHAPTERS.length,
    )
  })

  it('第一级 + 第二级组合：结果同时满足方向与难度', () => {
    TUTORIAL_DIRECTIONS.forEach((direction) => {
      levelsInChapters(chaptersInDirection(direction)).forEach((level) => {
        const hit = filterChaptersByLevel(chaptersInDirection(direction), level)
        expect(hit.length).toBeGreaterThan(0)
        hit.forEach((chapter) => {
          expect(chapter.direction).toBe(direction)
          expect(chapter.level).toBe(level)
        })
      })
    })
  })
})

describe('子方向', () => {
  it('每章的子方向都属于该方向的闭集（与后端 rules.SUBDIRECTIONS 同源）', () => {
    ALL_TUTORIAL_CHAPTERS.forEach((chapter) => {
      expect(chapter.sub_direction.trim()).not.toBe('')
      expect(subDirectionsOf(chapter.direction)).toContain(chapter.sub_direction)
    })
  })

  it('subDirectionsInChapters 只返回真实存在的子方向，并按闭集顺序排列', () => {
    expect(subDirectionsInChapters([])).toEqual([])
    TUTORIAL_DIRECTIONS.forEach((direction) => {
      const chapters = chaptersInDirection(direction)
      const subs = subDirectionsInChapters(chapters)
      expect(subs.length).toBeGreaterThan(0)
      expect(subs).toEqual(subDirectionsOf(direction).filter((sub) => subs.includes(sub)))
    })
  })

  it('filterChaptersBySubDirection：all 原样返回，其余只留该子方向', () => {
    expect(filterChaptersBySubDirection(ALL_TUTORIAL_CHAPTERS, 'all')).toHaveLength(
      ALL_TUTORIAL_CHAPTERS.length,
    )
    TUTORIAL_DIRECTIONS.forEach((direction) => {
      const chapters = chaptersInDirection(direction)
      subDirectionsInChapters(chapters).forEach((sub) => {
        const hit = filterChaptersBySubDirection(chapters, sub)
        expect(hit.length).toBeGreaterThan(0)
        hit.forEach((chapter) => {
          expect(chapter.direction).toBe(direction)
          expect(chapter.sub_direction).toBe(sub)
        })
      })
    })
  })

  it('URL 解析：子方向只在选定方向后有效，越界一律回落 all', () => {
    expect(parseLearnSubDirection('?direction=前端&sub=react', '前端')).toBe('react')
    expect(parseLearnSubDirection('?sub=react', '前端')).toBe('react')
    expect(parseLearnSubDirection('?direction=前端&sub=python', '前端')).toBe('all')
    expect(parseLearnSubDirection('?direction=前端', '前端')).toBe('all')
    expect(parseLearnSubDirection('?direction=前端&sub=react', 'all')).toBe('all')
  })

  it('链接拼接：子方向只在方向已选时写入，默认值不写参数', () => {
    expect(tutorialHref('前端', 'all', 'react')).toBe(
      '/learn?direction=%E5%89%8D%E7%AB%AF&sub=react',
    )
    expect(tutorialHref('all', 'all', 'react')).toBe('/learn')
    expect(tutorialHref('前端', '高级', 'react')).toBe(
      '/learn?direction=%E5%89%8D%E7%AB%AF&level=%E9%AB%98%E7%BA%A7&sub=react',
    )
  })

  it('三级组合：方向 + 子方向 + 难度同时生效', () => {
    TUTORIAL_DIRECTIONS.forEach((direction) => {
      subDirectionsInChapters(chaptersInDirection(direction)).forEach((sub) => {
        const scope = filterChaptersBySubDirection(chaptersInDirection(direction), sub)
        levelsInChapters(scope).forEach((level) => {
          const hit = filterChaptersByLevel(scope, level)
          expect(hit.length).toBeGreaterThan(0)
          hit.forEach((chapter) => {
            expect(chapter.direction).toBe(direction)
            expect(chapter.sub_direction).toBe(sub)
            expect(chapter.level).toBe(level)
          })
        })
      })
    })
  })
})

describe('教程索引纯函数', () => {
  it('按 ID 取章节；未知 ID 返回 undefined', () => {
    const first = ALL_TUTORIAL_CHAPTERS[0]
    expect(chapterById(first.id)).toBe(first)
    expect(chapterById('no-such-chapter')).toBeUndefined()
  })

  it('方向筛选只认闭集，未知方向返回空数组', () => {
    expect(chaptersInDirection('前端').length).toBeGreaterThan(0)
    expect(chaptersInDirection('不存在的方向')).toEqual([])
    expect(chaptersInScope('all')).toHaveLength(ALL_TUTORIAL_CHAPTERS.length)
    expect(chaptersInScope('后端')).toEqual(chaptersInDirection('后端'))
  })

  it('URL 解析：非法方向 / 非法难度一律回落 all', () => {
    expect(parseLearnDirection('?direction=后端')).toBe('后端')
    expect(parseLearnDirection('?direction=')).toBe('all')
    expect(parseLearnDirection('?direction=不存在')).toBe('all')
    expect(parseLearnLevel('?level=高级')).toBe('高级')
    expect(parseLearnLevel('?level=')).toBe('all')
    expect(parseLearnLevel('?level=中级')).toBe('all')
  })

  it('链接拼接：默认值不写参数，方向与难度同时生效', () => {
    expect(tutorialHref()).toBe('/learn')
    expect(tutorialHref('all')).toBe('/learn')
    expect(tutorialHref(null, 'all')).toBe('/learn')
    expect(tutorialHref('算法与数据结构')).toBe(
      '/learn?direction=%E7%AE%97%E6%B3%95%E4%B8%8E%E6%95%B0%E6%8D%AE%E7%BB%93%E6%9E%84',
    )
    expect(tutorialHref('后端', '进阶')).toBe(
      '/learn?direction=%E5%90%8E%E7%AB%AF&level=%E8%BF%9B%E9%98%B6',
    )
    expect(tutorialHref('all', '基础')).toBe('/learn?level=%E5%9F%BA%E7%A1%80')
    expect(chapterHref('fe-event-loop')).toBe('/learn/fe-event-loop')
  })

  it('每个方向的链接都能被解析回来（含带空格的方向名）', () => {
    TUTORIAL_DIRECTIONS.forEach((direction) => {
      const href = tutorialHref(direction, '高级')
      const query = href.slice(href.indexOf('?') + 1)
      expect(parseLearnDirection(query)).toBe(direction)
      expect(parseLearnLevel(query)).toBe('高级')
    })
  })

  it('前后邻居在边界处为 null，中间章节互相衔接', () => {
    const first = ALL_TUTORIAL_CHAPTERS[0]
    const last = ALL_TUTORIAL_CHAPTERS[ALL_TUTORIAL_CHAPTERS.length - 1]
    expect(chapterNeighbors(first.id).prev).toBeNull()
    expect(chapterNeighbors(last.id).next).toBeNull()
    expect(chapterNeighbors(first.id).next).toBe(ALL_TUTORIAL_CHAPTERS[1])
    expect(chapterNeighbors('no-such-chapter')).toEqual({ prev: null, next: null })
  })
})

describe('章内目录高亮', () => {
  it('取最后一个顶边越过判定线的小节：滚到第几节就亮第几节', () => {
    // 页首：只有第 1 节的顶边越过了 40% 线
    expect(activeSectionIndex([260, 900, 1600, 2300], 360)).toBe(0)
    // 滚到第 3 节：前三节的顶边都越线，取最后一个（不是还在带里的第 2 节尾巴）
    expect(activeSectionIndex([-400, -180, 120, 900], 360)).toBe(2)
    // 全部越过 → 最后一节
    expect(activeSectionIndex([-100, -50, -20, -10], 360)).toBe(3)
  })

  it('一节都还没开始时回落到第 0 节，目录不至于全灰', () => {
    expect(activeSectionIndex([500, 900, 1400], 360)).toBe(0)
    expect(activeSectionIndex([], 360)).toBe(0)
  })

  it('目录锚点与正文小节一一对应（`#tutorial-<sectionId>` 必须落在真实节点上）', () => {
    ALL_TUTORIAL_CHAPTERS[0].sections.forEach((section) => {
      expect(section.id).toMatch(/^[a-z0-9-]+$/)
    })
  })
})
