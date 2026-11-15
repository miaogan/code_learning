import { useState } from 'react'
import { api } from '../api/client'
import { ENGINEERING_ARCHIVE, ENGINEERING_STATS } from '../content/engineeringArchive'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { buildTutorialChunks } from '../lib/ragIngest'
import { useAsync } from '../lib/useAsync'

/** 数据规模行的中文标签（key 与后端 `evidence_data_scale()` 的键逐字对齐）。 */
const SCALE_LABELS: Record<string, string> = {
  questions: '题库题目',
  attempts: '作答记录',
  interview_runs: '面试场次',
  exam_runs: '笔试场次',
  documents: '简历版本',
  profiles: '技术画像',
  reports: '诊断报告',
  ai_calls: '模型调用',
}

const ENGINE_LABELS: Record<string, string> = {
  pgvector: 'pgvector（索引内余弦）',
  array: '降级形态（取回后 Python 余弦）',
  missing: '未初始化',
}

/**
 * 考工（r100 工程证据中心）：把「看不见的工程深度」摆上界面。
 *
 * 三个区：实时证据（行数事实 + RAG 索引状态与重建入口）→ 营造档案（静态工程卡片）
 * → 评测与文档入口。只读聚合零 AI、零评分；「RAG 索引」区的两个按钮是本页唯一写操作
 * （重建题库索引 / 整份推送教程正文），都走幂等的全量替换语义。
 */
export default function EvidencePage() {
  const evidence = useAsync((signal) => api.evidenceSummary(signal), [])
  const [rebuilding, setRebuilding] = useState<'rebuild' | 'ingest' | null>(null)
  const [actionMessage, setActionMessage] = useState('')
  const [actionError, setActionError] = useState('')

  const runRebuild = async (): Promise<void> => {
    setRebuilding('rebuild')
    setActionMessage('')
    setActionError('')
    try {
      const result = await api.ragRebuild()
      setActionMessage(`题库索引已重建：${result.question_chunks} 条 chunk（${result.embedder}）`)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error))
    } finally {
      setRebuilding(null)
      void evidence.reload()
    }
  }

  const runIngest = async (): Promise<void> => {
    setRebuilding('ingest')
    setActionMessage('')
    setActionError('')
    try {
      const items = buildTutorialChunks()
      const result = await api.ragIngest(items)
      setActionMessage(`教程正文已推送 ${result.written} 个小节并完成向量化`)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error))
    } finally {
      setRebuilding(null)
      void evidence.reload()
    }
  }

  const data = evidence.data
  const loading = evidence.status === 'loading' && data === null
  const rag = data?.rag

  return (
    <section>
      <header className="sc-page-header">
        <h1 className="sc-page-title">考工</h1>
        <p className="sc-page-sub">
          工程证据中心：真实落库的行数事实、RAG 向量索引状态与营造档案。所有数字来自本服务
          的实时聚合与已落盘的工程事实，零评分、零模型参与。
        </p>
      </header>

      {loading ? <PhaseLoader title="正在读取工程证据" phases={['聚合行数与索引状态']} active={0} /> : null}
      {evidence.status === 'error' && evidence.error ? (
        <InlineError message={evidence.error.message} onRetry={evidence.reload} />
      ) : null}

      {data ? (
        <>
          <h2>实时证据</h2>
          <div className="sc-btn-row">
            <span>数据表 {data.tables} 张</span>
            {ENGINEERING_STATS.map((stat) => (
              <span key={stat.label}>
                {stat.label} {stat.value}
              </span>
            ))}
          </div>
          <table>
            <thead>
              <tr>
                <th>数据维度</th>
                <th>行数</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data.data_scale).map(([key, value]) => (
                <tr key={key}>
                  <td>{SCALE_LABELS[key] ?? key}</td>
                  <td>{value}</td>
                  <td>
                    {key === 'questions' ? '共享题库（全量）' : '当前账号（按账号隔离）'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <h2>RAG 向量索引</h2>
          <table>
            <tbody>
              <tr>
                <td>索引状态</td>
                <td>
                  {rag?.built ? '已构建' : '未构建'}
                  {rag?.stale ? '（与当前 embedding 配置不一致，建议重建）' : ''}
                </td>
              </tr>
              <tr>
                <td>embedding</td>
                <td>
                  {rag?.embedder ?? '—'}（{rag?.embedder_kind === 'remote' ? '远端模型' : '离线确定性'}，维度{' '}
                  {rag?.dim ?? 0}）
                </td>
              </tr>
              <tr>
                <td>检索引擎</td>
                <td>{ENGINE_LABELS[rag?.engine ?? 'missing'] ?? rag?.engine}</td>
              </tr>
              <tr>
                <td>chunk 规模</td>
                <td>
                  共 {rag?.chunk_count ?? 0} 条（题库 {rag?.question_chunks ?? 0} · 教程{' '}
                  {rag?.tutorial_chunks ?? 0}）{rag?.built_at ? ` · 构建于 ${rag.built_at}` : ''}
                </td>
              </tr>
            </tbody>
          </table>
          <div className="sc-btn-row">
            <button type="button" disabled={rebuilding !== null} onClick={() => void runRebuild()}>
              {rebuilding === 'rebuild' ? '重建中…' : '重建题库索引'}
            </button>
            <button type="button" disabled={rebuilding !== null} onClick={() => void runIngest()}>
              {rebuilding === 'ingest' ? '推送中…' : '推送教程正文'}
            </button>
          </div>
          {actionMessage ? <p>{actionMessage}</p> : null}
          {actionError ? <InlineError message={actionError} /> : null}
          {rag?.notice ? <p>{rag.notice}</p> : null}
          <p>
            管线：题库与教程小节分块 → embedding（默认离线确定性哈希，可配真实语义模型）→
            pgvector 余弦索引 → 向量与关键词两腿 RRF(k=60) 融合检索 → 带引用白名单的生成。
            教程正文只在前端，因此「推送教程正文」把整份语料（全量替换语义）送进向量索引。
          </p>

          <h2>营造档案</h2>
          {ENGINEERING_ARCHIVE.map((card) => (
            <div className="sc-card" key={card.tag} style={{ marginBottom: 'var(--sp-4)' }}>
              <p>
                <b>{card.title}</b> <em>{card.tag}</em>
              </p>
              <ul>
                {card.points.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            </div>
          ))}

          <h2>评测与文档</h2>
          <p className="sc-btn-row">
            <span>模型调用质量看板在「评鉴」页</span>
            <span>
              RAG 三态检索评测：scripts/eval_rag.py（--check 进 CI 门禁，报告见
              docs/eval/RAG-RETRIEVAL-REPORT.md）
            </span>
            <span>
              RAG 生成评审：scripts/eval_rag_judge.py（DRY-RUN 进 CI，--live 需 AI_LIVE=1，
              报告见 docs/eval/RAG-JUDGE-REPORT.md）
            </span>
          </p>
        </>
      ) : null}
    </section>
  )
}
