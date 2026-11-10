import { describe, expect, it } from 'vitest'
import type { Profile, ProfileProject, ProfileSkill, ResumeVersionDetail } from '../api/types'
import { canCompare, compareVersions, formatDelta } from './versionDiff'

function skill(name: string, status?: 'active' | 'historical'): ProfileSkill {
  return { name, source_quote: `${name} 原文`, status }
}

function project(name: string, status?: 'active' | 'historical'): ProfileProject {
  return { name, role: null, period: null, bullets: [], source_quote: `${name} 原文`, status }
}

function profile(overrides: Partial<Profile> = {}): Profile {
  return {
    id: 'prof-1',
    resume_id: 'res-1',
    updated_at: '2026-11-01T00:00:00Z',
    skills: [skill('Python')],
    tech_stack: ['FastAPI'],
    years_experience: 2,
    projects: [project('项目 A')],
    target_role: 'AI 应用工程师',
    ...overrides,
  }
}

function version(overrides: Partial<ResumeVersionDetail> = {}): ResumeVersionDetail {
  return {
    resume_id: 'res-1',
    file_name: '简历.pdf',
    source_type: 'pdf',
    chars: 1000,
    sections: 3,
    created_at: '2026-11-01T00:00:00Z',
    has_profile: true,
    interview_avg: null,
    exam_total: null,
    judged_count: 0,
    profile: profile(),
    ...overrides,
  }
}

describe('compareVersions', () => {
  it('计数差异按 after - before 给出，正数代表新版更多', () => {
    const before = version({ chars: 900, sections: 2 })
    const after = version({ chars: 1400, sections: 4 })
    const result = compareVersions(before, after)
    const byKey = Object.fromEntries(result.metrics.map((item) => [item.key, item]))
    expect(byKey.chars.delta).toBe(500)
    expect(byKey.sections.delta).toBe(2)
    expect(byKey.years.delta).toBe(0)
  })

  it('historical 项不计入画像计数（保留证据但不算当前简历的能力）', () => {
    const before = version({ profile: profile() })
    const after = version({
      profile: profile({
        skills: [skill('Python'), skill('Rust', 'historical')],
        projects: [project('项目 A'), project('项目 B', 'historical')],
      }),
    })
    const result = compareVersions(before, after)
    const byKey = Object.fromEntries(result.metrics.map((item) => [item.key, item]))
    expect(byKey.skills.after).toBe(1)
    expect(byKey.skills.delta).toBe(0)
    expect(byKey.projects.after).toBe(1)
  })

  it('能力项与技术栈给出新增 / 移除名单', () => {
    const before = version({
      profile: profile({ skills: [skill('Python'), skill('Docker')], tech_stack: ['FastAPI', 'Redis'] }),
    })
    const after = version({
      profile: profile({ skills: [skill('Python'), skill('LangGraph')], tech_stack: ['FastAPI', 'Postgres'] }),
    })
    const result = compareVersions(before, after)
    expect(result.skillsAdded).toEqual(['LangGraph'])
    expect(result.skillsRemoved).toEqual(['Docker'])
    expect(result.techAdded).toEqual(['Postgres'])
    expect(result.techRemoved).toEqual(['Redis'])
    expect(result.changed).toBe(true)
  })

  it('两版完全一致时 changed=false（页面据此提示「重新上传同一份」）', () => {
    const result = compareVersions(version(), version())
    expect(result.changed).toBe(false)
    expect(result.roleBefore).toBe(result.roleAfter)
  })

  it('只改目标岗位也算画像变化', () => {
    const result = compareVersions(
      version({ profile: profile({ target_role: '后端工程师' }) }),
      version({ profile: profile({ target_role: 'AI 应用工程师' }) }),
    )
    expect(result.changed).toBe(true)
    expect(result.roleBefore).toBe('后端工程师')
    expect(result.roleAfter).toBe('AI 应用工程师')
  })

  it('成绩差只在两端都有分时给出，无记录不能当 0 分', () => {
    const result = compareVersions(
      version({ interview_avg: 7, exam_total: null, judged_count: 1 }),
      version({ interview_avg: 8.5, exam_total: 72, judged_count: 3 }),
    )
    const byKey = Object.fromEntries(result.scores.map((item) => [item.key, item]))
    expect(byKey.interview_avg.delta).toBe(1.5)
    expect(byKey.exam_total.before).toBeNull()
    expect(byKey.exam_total.delta).toBeNull()
    expect(byKey.judged_count.delta).toBe(2)
    expect(byKey.interview_avg.scale).toBe(10)
    expect(byKey.exam_total.scale).toBe(100)
    expect(byKey.judged_count.scale).toBeNull()
  })

  it('画像缺失（尚未生成）时按空画像对比，不抛错', () => {
    const result = compareVersions(
      version({ has_profile: false, profile: null }),
      version({ profile: profile() }),
    )
    expect(result.roleBefore).toBeNull()
    expect(result.changed).toBe(true)
  })
})

describe('formatDelta', () => {
  it('null / 0 / 正负值分别给占位、持平与带符号读数', () => {
    expect(formatDelta(null)).toBe('—')
    expect(formatDelta(0)).toBe('持平')
    expect(formatDelta(0.5)).toBe('+0.5')
    expect(formatDelta(2, 0)).toBe('+2')
    expect(formatDelta(-2, 0)).toBe('−2')
    expect(formatDelta(-0.25)).toBe('−0.3')
  })
})

describe('canCompare', () => {
  it('同一版本不可对比，不同版本可对比', () => {
    expect(canCompare(version(), version())).toBe(false)
    expect(canCompare(version({ resume_id: 'res-0' }), version())).toBe(true)
  })
})
