import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { Profile, ProfileMergeSummary, ProfilePatch } from '../api/types'
import { EvidenceList } from '../components/profile/EvidenceList'
import { MergeSummaryBar } from '../components/profile/MergeSummaryBar'
import { ProfileDimension } from '../components/profile/ProfileDimension'
import type { ProfileDimensionKey } from '../components/profile/ProfileDimension'
import { ProfileEditor } from '../components/profile/ProfileEditor'
import { ProfileRadar } from '../components/profile/ProfileRadar'
import { Chip } from '../components/ui/Chip'
import { ConfirmModal } from '../components/ui/ConfirmModal'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { ResumeGate } from '../components/ui/ResumeGate'
import { polishRoleHref } from '../lib/coach'
import {
  DIMENSIONS,
  HISTORY_GROUP_ID,
  buildDeletePatch,
  buildDimensionPatch,
  buildEntryPatch,
  confirmedDimensions,
  dimensionEditorFields,
  dimensionEntries,
  entryEditorFields,
  evidenceOf,
  historicalProjects,
  historicalSkills,
  isHistorical,
  nextProfile,
  parseEntryKey,
  readMergeSummary,
  resumeTruncationNote,
  singleValueOf,
  sourceCount,
} from '../lib/profileEdit'
import type { TrackedEntry } from '../lib/profileEdit'
import { useAsync } from '../lib/useAsync'

type EditTarget = { dimension: ProfileDimensionKey; index: number | null }

/**
 * 立传页（AC-2）：读最新画像 → 5 维卡片 + 溯源源文 → 逐条行内编辑（PATCH 成功才替换）。
 * 服务端是唯一权威（TECHNICAL §4）：刷新只靠 `GET /api/profiles/latest`，PATCH 以响应体为真值，
 * 不做全局乐观更新；404 是引导态（空态），不是错误态。
 */
export default function ProfilePage() {
  const profileAsync = useAsync((signal) => api.latestProfile(signal), [])
  /**
   * 能力雷达的测评证据：最新报告（深度 / 广度）与成绩历史（技术力 / 学习力）。
   * 两者都是既有只读接口，失败（含 404 无报告）只让对应轴显示「暂无测评数据」，不阻塞画像本身。
   */
  const reportAsync = useAsync((signal) => api.latestReport(signal), [])
  const runsAsync = useAsync(() => api.history({ limit: 20 }), [])
  const location = useLocation()

  /**
   * 一次性合并摘要（DESIGN §2.2 / §7-1）：只由「上传 → 生成/合并」那一趟的 `location.state` 带入，
   * 刷新即消失，不落 localStorage、不扩 `GET /api/profiles/latest` 的持久契约。useState 初始化函数只跑一次。
   */
  const [mergeSummary] = useState<ProfileMergeSummary | null>(() => readMergeSummary(location.state))
  const [historyOpen, setHistoryOpen] = useState<{ skills: boolean; projects: boolean }>({
    skills: false,
    projects: false,
  })
  /**
   * r4 D-4：一次性跳转信号用**计数器**而非布尔（重复点击也能重放滚动/聚焦），
   * 并放在 effect 里执行——保证「展开态已提交 DOM」之后再滚动与聚焦。
   */
  const [historyJump, setHistoryJump] = useState(0)
  const skillsHistoryRef = useRef<HTMLDivElement | null>(null)
  const projectsHistoryRef = useRef<HTMLDivElement | null>(null)

  /** 已保存的画像：base 记下「保存时服务端那一版」的 updated_at，服务端刷新出新版就让位给它。 */
  const [patched, setPatched] = useState<{ base: string | null; profile: Profile } | null>(null)
  const [edit, setEdit] = useState<EditTarget | null>(null)
  const [saving, setSaving] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)
  const [retryPatch, setRetryPatch] = useState<ProfilePatch | null>(null)
  /** 待确认删除的条目（单击「删除」只打开确认框，不直接 PATCH）。 */
  const [pendingDelete, setPendingDelete] = useState<{ entryKey: string; title: string } | null>(null)

  const remote = profileAsync.data
  const baseId = remote?.updated_at ?? null
  const profile = patched !== null && patched.base === baseId ? patched.profile : remote

  const view: 'gate' | 'empty' | 'error' | 'ready' =
    profile === null
      ? profileAsync.status === 'error'
        ? profileAsync.error?.status === 404
          ? 'empty'
          : 'error'
        : 'gate'
      : 'ready'

  const entries = profile === null ? null : dimensionEntries(profile)
  const truncationNote = resumeTruncationNote(profile)

  /** 历史能力 / 历史项目条数（摘要条入口按钮的显示条件，AC-12：0 项 = 不渲染）。 */
  const historyCounts = {
    skills: profile === null ? 0 : historicalSkills(profile).length,
    projects: profile === null ? 0 : historicalProjects(profile).length,
  }
  const historyTotal = historyCounts.skills + historyCounts.projects
  const historyControls = (['skills', 'projects'] as const)
    .filter((dimension) => historyCounts[dimension] > 0)
    .map((dimension) => HISTORY_GROUP_ID[dimension])

  /** 入口：展开两个历史分组 → 递增跳转信号（滚动与聚焦由下面的 effect 完成）。 */
  const viewHistory = () => {
    setHistoryOpen({ skills: true, projects: true })
    setHistoryJump((current) => current + 1)
  }

  useEffect(() => {
    if (historyJump === 0 || profile === null) return
    // 取**第一个已渲染**（计数 >0）的容器：只有它才真正存在于 DOM 里
    const counts = {
      skills: historicalSkills(profile).length,
      projects: historicalProjects(profile).length,
    }
    const dimension: 'skills' | 'projects' = counts.skills > 0 ? 'skills' : 'projects'
    if (counts[dimension] === 0) return
    const container = dimension === 'skills' ? skillsHistoryRef.current : projectsHistoryRef.current
    if (container === null) return
    container.scrollIntoView({ block: 'center', behavior: 'smooth' })
    // preventScroll：滚动已由上一行完成，避免 focus 再跳一次（AC-11）
    container.focus({ preventScroll: true })
  }, [historyJump, profile])

  const submitPatch = async (patch: ProfilePatch | null): Promise<boolean> => {
    if (profile === null) return false
    if (patch === null) {
      setEditError('这一项暂不支持行内编辑')
      return false
    }
    setSaving(true)
    setEditError(null)
    setRetryPatch(null)
    try {
      const updated = await api.patchProfile(profile.id, patch)
      setPatched({ base: baseId, profile: nextProfile(profile, { ok: true, profile: updated }) })
      return true
    } catch (error) {
      const message = error instanceof ApiError ? error.message : '保存失败，请重试一次'
      setEditError(message)
      setRetryPatch(patch)
      return false
    } finally {
      setSaving(false)
    }
  }

  const saveEdit = async (values: Record<string, string>): Promise<void> => {
    if (profile === null || edit === null) return
    const patch =
      edit.index === null
        ? buildDimensionPatch(profile, edit.dimension, values)
        : buildEntryPatch(profile, edit.dimension, edit.index, values)
    if (await submitPatch(patch)) setEdit(null)
  }

  const deleteEntry = async (entryKey: string): Promise<void> => {
    if (profile === null) return
    const parsed = parseEntryKey(entryKey)
    if (parsed === null) return
    await submitPatch(buildDeletePatch(profile, parsed.dimension, parsed.index))
  }

  const startEdit = (dimension: ProfileDimensionKey, index: number | null) => {
    setEditError(null)
    setRetryPatch(null)
    setEdit({ dimension, index })
  }

  const cancelEdit = () => {
    setEdit(null)
    setEditError(null)
  }

  const editorFields =
    profile !== null && edit !== null
      ? edit.index === null
        ? dimensionEditorFields(profile, edit.dimension)
        : entryEditorFields(profile, edit.dimension, edit.index)
      : []

  /**
   * 技能 / 项目卡下方的增量可视区（AC-6 + AC-7）：
   * ①多证据折叠（旧→新、带来源文件名与日期），只在 ≥2 条时出现（单条已由卡片内的溯源按钮展示）；
   * ②历史分组（本次简历未出现的能力/项目）——用徽章区分、**不降对比度**（禁 opacity，DESIGN anti-pattern）。
   */
  const evidenceExtras = (dimension: 'skills' | 'projects') => {
    if (profile === null) return null
    const source: TrackedEntry[] = dimension === 'skills' ? profile.skills : profile.projects
    const foldable = source.filter((item) => !isHistorical(item) && evidenceOf(item).length >= 2)
    const historical = source.filter((item) => isHistorical(item))
    if (foldable.length === 0 && historical.length === 0) return null

    const open = historyOpen[dimension]

    return (
      <div className="sc-actions">
        {foldable.length > 0 ? (
          <div className="sc-evidence-list" aria-label="能力证据">
            {foldable.map((item) => (
              <EvidenceList
                key={`${dimension}-evidence-${item.name}`}
                evidence={evidenceOf(item)}
                label={`${item.name} · 证据 ${evidenceOf(item).length} 条 · 旧→新`}
              />
            ))}
          </div>
        ) : null}

        {historical.length > 0 ? (
          /*
           * 历史分组容器（r4 D-4）：id / ref / 焦点落在**始终渲染**的分组外壳上，
           * 这样 `aria-controls` 在展开前后都能解析到真实元素（AC-11），
           * 展开后焦点环包住的也是「开关 + 历史条目」这一整块，滚动落点即分组本身。
           */
          <div
            id={HISTORY_GROUP_ID[dimension]}
            ref={dimension === 'skills' ? skillsHistoryRef : projectsHistoryRef}
            tabIndex={-1}
            className="sc-hist sc-hist-group"
            aria-label={dimension === 'skills' ? '历史能力分组' : '历史项目分组'}
          >
            <button
              type="button"
              className={open ? 'sc-evidence-chip is-expanded' : 'sc-evidence-chip'}
              aria-expanded={open}
              onClick={() =>
                setHistoryOpen((current) => ({ ...current, [dimension]: !current[dimension] }))
              }
            >
              <span>
                {`${open ? '▾' : '▸'} ${dimension === 'skills' ? '历史能力' : '历史项目'} ${historical.length} 项（本次简历未出现 · 不参与出题与诊断）`}
              </span>
            </button>

            {open ? (
              <div className="sc-evidence-list" aria-label="历史条目">
                {historical.map((item) => (
                  <div key={`${dimension}-historical-${item.name}`} className="sc-evidence-item">
                    <div className="sc-chips">
                      <Chip label={item.name} />
                      <Chip label="历史" />
                      <Chip label={`证据 ${evidenceOf(item).length} 条`} />
                    </div>
                    <EvidenceList evidence={evidenceOf(item)} />
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <section>
      <header className="sc-page-header">
        <h1 className="sc-page-title">立传</h1>
        <p className="sc-page-sub">
          {profile === null
            ? '读取简历后自动生成 5 个维度，每条结论都带简历原文出处'
            : `${sourceCount(profile)} 条溯源 · ${profile.skills.length} 个技能 · ${profile.projects.length} 段项目 · 可选编辑后开始测评`}
        </p>
      </header>

      {mergeSummary !== null ? (
        <MergeSummaryBar
          summary={mergeSummary}
          historyCount={historyTotal}
          historyControls={historyControls}
          onViewHistory={viewHistory}
        />
      ) : null}

      {view === 'gate' ? (
        <PhaseLoader title="正在读取你的最新画像" phases={['读取最新画像']} active={0} />
      ) : null}

      {view === 'empty' ? (
        <ResumeGate
          reason="还没有画像。先上传一份简历（PDF / DOCX / TXT，≤10MB），AI 会据此建立可溯源的 5 维画像。"
          unlockLabel="回到本页查看画像"
        />
      ) : null}

      {view === 'error' && profileAsync.error ? (
        <InlineError message={profileAsync.error.message} onRetry={profileAsync.reload} />
      ) : null}

      {view === 'ready' && profile !== null && entries !== null ? (
        <>
          {truncationNote ? <p className="sc-meta-line">{truncationNote}</p> : null}

          {editError !== null && edit === null ? (
            <InlineError
              message={editError}
              onRetry={
                retryPatch === null
                  ? undefined
                  : () => {
                      void submitPatch(retryPatch)
                    }
              }
            />
          ) : null}

          <ProfileRadar report={reportAsync.data} runs={runsAsync.data?.items ?? []} />

          <div className="sc-grid-2">
            <div>
              {DIMENSIONS.map((item) => (
                <div key={item.key}>
                  <ProfileDimension
                    dimension={item.key}
                    title={item.title}
                    entries={entries[item.key]}
                    value={singleValueOf(profile, item.key)}
                    emptyHint={item.hint}
                    editable={item.editable}
                    editing={edit !== null && edit.dimension === item.key}
                    saving={saving}
                    onEdit={() => startEdit(item.key, null)}
                    onEditEntry={(entryKey) => {
                      const parsed = parseEntryKey(entryKey)
                      if (parsed !== null) startEdit(parsed.dimension, parsed.index)
                    }}
                    onDeleteEntry={(entryKey) => {
                      const parsed = parseEntryKey(entryKey)
                      if (parsed === null) return
                      const title = entries[parsed.dimension][parsed.index]?.title ?? '这一条'
                      setPendingDelete({ entryKey, title })
                    }}
                    editor={
                      edit !== null && edit.dimension === item.key ? (
                        <ProfileEditor
                          key={`${item.key}#${edit.index === null ? 'dimension' : edit.index}`}
                          fields={editorFields}
                          saving={saving}
                          error={editError}
                          onSave={(values) => {
                            void saveEdit(values)
                          }}
                          onCancel={cancelEdit}
                        />
                      ) : null
                    }
                  />
                  {item.key === 'skills' || item.key === 'projects' ? evidenceExtras(item.key) : null}
                </div>
              ))}
            </div>

            <aside>
              <p className="sc-mono">{`${confirmedDimensions(profile)}/5 维度已确认`}</p>
              <p className="sc-meta-line">编辑后以服务端返回为准；保存失败不会改动已保存的画像。</p>
              <div className="sc-btn-row">
                <Link className="sc-btn sc-btn--primary" to="/interview">
                  开始召对
                </Link>
                <Link className="sc-btn sc-btn--secondary" to="/exam">
                  改为笔试
                </Link>
                <Link
                  className="sc-btn sc-btn--secondary"
                  to={polishRoleHref(profile.target_role)}
                >
                  润色简历
                </Link>
                <Link className="sc-btn sc-btn--secondary" to="/">
                  重新上传简历
                </Link>
              </div>
            </aside>
          </div>
        </>
      ) : null}

      <ConfirmModal
        open={pendingDelete !== null}
        title="删除这一条"
        message={
          pendingDelete === null
            ? ''
            : `将从画像中删除「${pendingDelete.title}」。保存后立即生效，无法撤销。`
        }
        confirmLabel="删除"
        cancelLabel="保留"
        onConfirm={() => {
          const target = pendingDelete
          setPendingDelete(null)
          if (target !== null) void deleteEntry(target.entryKey)
        }}
        onCancel={() => setPendingDelete(null)}
      />
    </section>
  )
}
