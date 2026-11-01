import type { RoleFit } from '../../api/types'
import { COACH_COPY, roleGapLabel } from '../../lib/coach'
import { Card } from '../ui/Card'

export interface RoleFitCardProps {
  /** `null` = 旧报告（字段未落库）｜`model === null` = 目标岗位未命中内置模型（降级）。 */
  roleFit: RoleFit | null
}

/** 先补条目上限（与后端 `FIRST_FIX_LIMIT` 同口径）。 */
const PRIORITY_LIMIT = 3

/**
 * 区块 C · 市场竞争力对标（DESIGN r7 §2.3）。
 *
 * - 差距全部可复算：`我的 / 要求 / 差距` 三列都来自 `RoleFit.items`，前端不做减法、不排序；
 * - `先补什么` 的 1/2/3 圆点顺序 = `first_fix` 顺序（缺省才回退到前 3 个 `gap > 0`），**前端绝不重排**（AC-20）；
 * - `差距 > 0` 用 `--warn` 数字、`0` 渲染「达标」文字（颜色不单独承载信息）；
 * - `model === null`：只留降级文案，不渲染空表 / 空目标岗位（AC-10）。
 */
export function RoleFitCard({ roleFit }: RoleFitCardProps) {
  if (roleFit === null) {
    return (
      <Card className="sc-coach-block">
        <div className="sc-coach-blockhead">
          <h3 className="sc-coach-blocktitle">市场竞争力对标</h3>
        </div>
        <p className="sc-coach-note">{COACH_COPY.legacy}</p>
      </Card>
    )
  }

  const { model, items, missing_must, first_fix, conclusion, notice, role_source_label } = roleFit

  if (model === null) {
    return (
      <Card className="sc-coach-block">
        <div className="sc-coach-blockhead">
          <h3 className="sc-coach-blocktitle">市场竞争力对标</h3>
          {role_source_label ? <span className="sc-chip">{`来源：${role_source_label}`}</span> : null}
        </div>
        <p className="sc-coach-note">{notice ?? COACH_COPY.roleNoModel}</p>
        <p className="sc-coach-note">{COACH_COPY.roleNoModelHint}</p>
      </Card>
    )
  }

  const priority =
    first_fix.length > 0
      ? first_fix
      : items
          .filter((item) => item.gap > 0)
          .map((item) => item.name)
          .slice(0, PRIORITY_LIMIT)

  return (
    <Card className="sc-coach-block">
      <div className="sc-coach-blockhead">
        <h3 className="sc-coach-blocktitle">市场竞争力对标</h3>
        {role_source_label ? <span className="sc-chip">{`来源：${role_source_label}`}</span> : null}
      </div>

      <p className="sc-role-target">
        <span>目标岗位</span>
        <span>{model.label}</span>
      </p>

      <table className="sc-role-table" aria-label="能力差距">
        <thead>
          <tr>
            <th scope="col">能力项</th>
            <th scope="col">我的 / 要求</th>
            <th scope="col">差距</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.name}>
              <td>
                {item.must ? (
                  <>
                    <span className="sc-chip">必备</span>{' '}
                  </>
                ) : null}
                {item.name}
              </td>
              <td className="sc-mono">{`${item.user_level} / ${item.required}`}</td>
              <td className={item.gap > 0 ? 'sc-role-gap sc-mono' : 'sc-role-met'}>
                {roleGapLabel(item.gap)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {priority.length > 0 ? (
        <div className="sc-profile-dim">
          <p className="sc-meta-line">先补什么</p>
          <ol className="sc-role-prio">
            {priority.map((name, index) => (
              <li className="sc-role-prio-item" key={name}>
                <span className="sc-prio-dot" aria-hidden="true">
                  {index + 1}
                </span>
                {name}
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      {missing_must.length > 0 ? (
        <div className="sc-weak-line">
          <p className="sc-meta-line">缺失的必备技能</p>
          {missing_must.map((name) => (
            <span className="sc-must-chip" key={name}>
              {name}
            </span>
          ))}
        </div>
      ) : null}

      {conclusion ? <p className="sc-coach-note">{conclusion}</p> : null}
    </Card>
  )
}
