import type { Course } from '../../api/types'
import { Chip } from '../ui/Chip'

export interface CourseCardProps {
  course: Course
}

/**
 * 课程卡（132 高，DESIGN §2.5 / §0.7 第 7 条）：标题 16/24 + 「为什么学」两行 + 元信息行 24。
 * anti-goal 4：`url === null` 时渲染成 div 并置灰标注「链接待更新」——绝不拼 URL、不出 404；
 * 有链时 `target=_blank` + `rel="noopener noreferrer"`（不把 opener 交给外部站点）。
 */
export function CourseCard({ course }: CourseCardProps) {
  const body = (
    <>
      <h3>{course.title}</h3>
      <p>{course.why}</p>
      <div className="sc-course-card-meta">
        <Chip label={course.level} />
        <Chip label={course.direction} tone="direction" />
        {course.url === null ? (
          <span>链接待更新</span>
        ) : (
          <span aria-hidden="true">↗</span>
        )}
      </div>
    </>
  )

  if (course.url === null) {
    return (
      <div className="sc-course-card is-disabled" title="课程链接待更新，暂不可打开">
        {body}
      </div>
    )
  }

  return (
    <a
      className="sc-course-card"
      href={course.url}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={`在新标签打开课程：${course.title}`}
    >
      {body}
    </a>
  )
}
