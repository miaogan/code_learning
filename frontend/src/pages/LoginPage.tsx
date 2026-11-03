import { useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../api/client'
import { Button } from '../components/ui/Button'
import { InlineError } from '../components/ui/InlineError'
import { login } from '../state/auth'

/**
 * r23 登录页：邮箱 + 密码（不开放自助注册，账号由管理员用 `admin_cli.py` 创建）。
 * 成功后服务端种 HttpOnly 会话 Cookie，本页随登录态切到工作台自动卸载。
 */
export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      await login(email.trim(), password)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '登录失败，请稍后重试')
      setBusy(false)
    }
  }

  return (
    <section className="sc-auth">
      <div className="sc-auth-card">
        <header className="sc-page-header">
          <h1 className="sc-page-title">登录 Skill Coach</h1>
          <p className="sc-page-sub">AI 读简历建画像 → 模拟面试 / 笔试 → 短板报告 → 精选课程</p>
        </header>

        <form className="sc-form" onSubmit={submit}>
          <label className="sc-field">
            <span className="sc-field-label">邮箱</span>
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              disabled={busy}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
            />
          </label>
          <label className="sc-field">
            <span className="sc-field-label">密码</span>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              disabled={busy}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="请输入密码"
            />
          </label>
          {error !== null ? <InlineError message={error} /> : null}
          <Button type="submit" loading={busy}>
            登录
          </Button>
        </form>

        <p className="sc-auth-note">
          账号由管理员创建，不开放自助注册；还没有账号请向管理员索取邮箱与初始密码。
        </p>
      </div>
    </section>
  )
}
