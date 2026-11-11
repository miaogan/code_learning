import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { ResumeVersionDetail, ResumeVersionSummary } from '../api/types'
import { Card } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { useAsync } from '../lib/useAsync'
import { canCompare, compareVersions, formatDelta } from '../lib/versionDiff'

interface Picked {
  older: string | null
  newer: string | null
}

/**
 * r60 简历版本对比页。
 *
 * 读数全部来自后端只读投影（`GET /api/resumes` + `/api/resumes/{id}`），
 * 页面只做选择与展示；差异计算在 `lib/versionDiff.ts` 的纯函数里，便于单测与口径复算。
 */

function formatWhen(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(
    date.getDate(),
  ).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(
    date.getMinutes(),
  ).padStart(2, '0')}`
}

function versionLabel(version: ResumeVersionSummary): string {
  return `${formatWhen(version.created_at)} · ${version.file_name}`
}

function scoreText(value: number | null, unit: string, digits = 1): string {
  return value === null ? '暂无成绩' : `${value.toFixed(digits).replace(/\.0$/, '')}${unit}`
}

/** 未选过时默认「最新 vs 次新」；选择失效（版本被删）或两栏相同时回落到相邻两条。 */
function resolveSelection(
  versions: ResumeVersionSummary[],
  picked: Picked,
): { older: string | null; newer: string | null } {
  const ids = versions.map((version) => version.resume_id)
  if (ids.length === 0) return { older: null, newer: null }
  const newer = picked.newer !== null && ids.includes(picked.newer) ? picked.newer : ids[0]
  let older =
    picked.older !== null && ids.includes(picked.older) ? picked.older : (ids[1] ?? ids[0])
  if (older === newer) older = ids.find((id) => id !== newer) ?? newer
  return { older, newer }
}

function deltaClass(value: number | null): string {
  if (value === null || value === 0) return 'is-equal'
  return value > 0 ? 'is-up' : 'is-down'
}

function DeltaChip({ value, digits = 0 }: { value: number | null; digits?: number }) {
  return <span className={`sc-delta-chip ${deltaClass(value)}`}>{formatDelta(value, digits)}</span>
}

function ChipRow({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null
  return (
    <div className="sc-version-chips">
      <span className="sc-coach-meta">{title}</span>
      <div className="sc-tl-chips">
        {items.map((item) => (
          <span key={item} className="sc-chip">
            {item}
          </span>
        ))}
      </div>
    </div>
  )
}

export default function VersionsPage() {
  const [picked, setPicked] = useState<Picked>({ older: null, newer: null })
  const listAsync = useAsync(() => api.listResumeVersions(20), [])
  // `data` 在重载期间保留上一次成功值；按 status 派生会让版本选择器闪空并级联重拉详情。
  const versions = listAsync.data

  const selection = useMemo(
    () => (versions === null ? { older: null, newer: null } : resolveSelection(versions, picked)),
    [versions, picked],
  )

  const detailAsync = useAsync(async (signal) => {
    if (selection.older === null || selection.newer === null) return null
    const [before, after] = await Promise.all([
      api.getResumeVersion(selection.older, signal),
      api.getResumeVersion(selection.newer, signal),
    ])
    return { before, after }
  }, [selection.older, selection.newer])

  const detail: { before: ResumeVersionDetail; after: ResumeVersionDetail } | null =
    detailAsync.status === 'success' ? detailAsync.data : null
  const comparison = detail === null ? null : compareVersions(detail.before, detail.after)

  return (
    <div className="sc-page">
      <header className="sc-page-header">
        <h1 className="sc-page-title">校勘</h1>
        <p className="sc-page-sub">
          每次上传存档为一个版本；选两版即可看画像与测评成绩的变化。成绩只算该版本下已完成的测评。
        </p>
      </header>

      {listAsync.status === 'loading' && versions === null && (
        <PhaseLoader title="正在读取简历版本" phases={['读取版本列表']} active={0} />
      )}
      {listAsync.status === 'error' && listAsync.error !== null && (
        <InlineError message={listAsync.error.message} onRetry={listAsync.reload} />
      )}

      {versions !== null && versions.length === 0 && (
        <EmptyState
          reason="还没有任何简历版本：上传一份简历即可开始存档。"
          actionLabel="去上传简历"
          actionTo="/"
        />
      )}

      {versions !== null && versions.length === 1 && (
        <Card>
          <h3 className="sc-coach-blocktitle">再上传一版就能对比</h3>
          <p className="sc-coach-note">
            当前只有「{versions[0].file_name}」（{formatWhen(versions[0].created_at)}）。改完简历后重新上传，
            这里会自动列出两版画像与成绩的差异。
          </p>
          <div className="sc-btn-row">
            <Link className="sc-btn sc-btn--secondary" to="/">
              上传新版本
            </Link>
            <Link className="sc-btn sc-btn--secondary" to="/profile">
              查看当前画像
            </Link>
          </div>
        </Card>
      )}

      {versions !== null && versions.length > 1 && (
        <>
          <div className="sc-versions-picker">
            <label className="sc-field">
              <span className="sc-field-label">旧版（基线）</span>
              <select
                className="sc-filter-select"
                value={selection.older ?? ''}
                onChange={(event) => setPicked((prev) => ({ ...prev, older: event.target.value }))}
              >
                {versions.map((version) => (
                  <option key={version.resume_id} value={version.resume_id}>
                    {versionLabel(version)}
                  </option>
                ))}
              </select>
            </label>
            <label className="sc-field">
              <span className="sc-field-label">新版（当前）</span>
              <select
                className="sc-filter-select"
                value={selection.newer ?? ''}
                onChange={(event) => setPicked((prev) => ({ ...prev, newer: event.target.value }))}
              >
                {versions.map((version) => (
                  <option key={version.resume_id} value={version.resume_id}>
                    {versionLabel(version)}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {detailAsync.status === 'loading' && (
            <PhaseLoader title="正在读取两个版本的画像" phases={['读取画像与成绩']} active={0} />
          )}
          {detailAsync.status === 'error' && detailAsync.error !== null && (
            <InlineError message={detailAsync.error.message} onRetry={detailAsync.reload} />
          )}

          {detail !== null && comparison !== null && !canCompare(detail.before, detail.after) && (
            <Card>
              <p className="sc-coach-note">两侧选的是同一个版本，换个版本才能看到差异。</p>
            </Card>
          )}

          {detail !== null && comparison !== null && canCompare(detail.before, detail.after) && (
            <>
              <Card>
                <h3 className="sc-coach-blocktitle">画像与内容</h3>
                <table className="sc-trend-table sc-version-table">
                  <thead>
                    <tr>
                      <th scope="col">维度</th>
                      <th scope="col">旧版</th>
                      <th scope="col">新版</th>
                      <th scope="col">变化</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparison.metrics.map((row) => (
                      <tr key={row.key}>
                        <td>{row.label}</td>
                        <td>{row.key === 'years' ? row.before || '未填写' : row.before}</td>
                        <td>{row.key === 'years' ? row.after || '未填写' : row.after}</td>
                        <td>
                          <DeltaChip value={row.delta} digits={row.key === 'years' ? 1 : 0} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {comparison.roleBefore !== comparison.roleAfter && (
                  <p className="sc-coach-note">
                    目标岗位：{comparison.roleBefore ?? '未填写'} → {comparison.roleAfter ?? '未填写'}
                  </p>
                )}
                <ChipRow title="新增能力项" items={comparison.skillsAdded} />
                <ChipRow title="移除能力项" items={comparison.skillsRemoved} />
                <ChipRow title="新增技术栈" items={comparison.techAdded} />
                <ChipRow title="移除技术栈" items={comparison.techRemoved} />
                {!comparison.changed && (
                  <p className="sc-coach-note">两版画像与正文计数完全一致（可能只是同一份简历重新上传）。</p>
                )}
              </Card>

              <Card>
                <h3 className="sc-coach-blocktitle">测评成绩</h3>
                <table className="sc-trend-table sc-version-table">
                  <thead>
                    <tr>
                      <th scope="col">指标</th>
                      <th scope="col">旧版</th>
                      <th scope="col">新版</th>
                      <th scope="col">变化</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparison.scores.map((row) => (
                      <tr key={row.key}>
                        <td>{row.label}</td>
                        <td>{scoreText(row.before, row.unit ?? '')}</td>
                        <td>{scoreText(row.after, row.unit ?? '')}</td>
                        <td>
                          <DeltaChip value={row.delta} digits={row.scale === null ? 0 : 1} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="sc-coach-note">
                  成绩取该版本下最近一次有分测评；「暂无成绩」不是 0 分。变化只标示增减方向，不代表能力判定。
                </p>
              </Card>
            </>
          )}
        </>
      )}
    </div>
  )
}
