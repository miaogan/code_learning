import { describe, expect, it } from 'vitest'
import {
  ALL_TUTORIAL_CHAPTERS,
  TUTORIAL_DIRECTIONS,
  chapterById,
  chapterHref,
  chapterNeighbors,
  chaptersInDirection,
  parseLearnDirection,
  tutorialHref,
} from '../lib/tutorials'

describe('教程内容完整性', () => {
  it('每个方向都有章节，章节总数与方向数对得上', () => {
    expect(TUTORIAL_DIRECTIONS).toHaveLength(5)
    TUTORIAL_DIRECTIONS.forEach((direction) => {
      expect(chaptersInDirection(direction).length).toBeGreaterThanOrEqual(2)
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

describe('教程索引纯函数', () => {
  it('按 ID 取章节；未知 ID 返回 undefined', () => {
    const first = ALL_TUTORIAL_CHAPTERS[0]
    expect(chapterById(first.id)).toBe(first)
    expect(chapterById('no-such-chapter')).toBeUndefined()
  })

  it('方向筛选只认闭集，未知方向返回空数组', () => {
    expect(chaptersInDirection('前端').length).toBeGreaterThan(0)
    expect(chaptersInDirection('中间件与运维')).toEqual([])
  })

  it('URL 解析与链接拼接：非法方向回落 all，all 不写参数', () => {
    expect(parseLearnDirection('?direction=后端')).toBe('后端')
    expect(parseLearnDirection('?direction=')).toBe('all')
    expect(parseLearnDirection('?direction=不存在')).toBe('all')
    expect(tutorialHref()).toBe('/learn')
    expect(tutorialHref('all')).toBe('/learn')
    expect(tutorialHref('算法与数据结构')).toBe('/learn?direction=%E7%AE%97%E6%B3%95%E4%B8%8E%E6%95%B0%E6%8D%AE%E7%BB%93%E6%9E%84')
    expect(chapterHref('fe-event-loop')).toBe('/learn/fe-event-loop')
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
