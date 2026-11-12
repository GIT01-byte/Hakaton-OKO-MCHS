import { useState } from 'react'
import type { User } from './types'
import { Api } from './api'
import { ROLE_LABELS } from './format'
import { EyeLogo } from './icons'

interface Props {
  onLogin: (token: string, user: User) => void
}

const DEMO_ACCOUNTS = [
  { username: 'operator', password: 'operator123', hint: 'все типы ЧС, управление статусами' },
  { username: 'fire', password: 'fire123', hint: 'пожары, наводнения, оползни' },
  { username: 'eco', password: 'eco123', hint: 'только загрязнения' },
  { username: 'viewer', password: 'viewer123', hint: 'все типы, только просмотр' },
]

export default function LoginScreen({ onLogin }: Props) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function submit(u: string, p: string) {
    setBusy(true)
    setErr(null)
    try {
      const api = new Api(null)
      const res = await api.login(u, p)
      onLogin(res.token, res.user)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Ошибка входа')
      setBusy(false)
    }
  }

  return (
    <div className="loginwrap">
      <div className="logincard">
        <div className="brand">
          <EyeLogo />
          <div>
            Око МЧС
            <small>панель мониторинга ЧС</small>
          </div>
        </div>
        <p className="sub">
          Вход по ролям: служба видит только свои типы ЧС
        </p>

        {err && <div className="formerr" role="alert">{err}</div>}

        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (username.trim() && password) void submit(username.trim(), password)
          }}
        >
          <div className="field">
            <label htmlFor="login">Логин</label>
            <input
              id="login"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="operator"
            />
          </div>
          <div className="field">
            <label htmlFor="password">Пароль</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
            />
          </div>
          <button className="loginbtn" type="submit" disabled={busy || !username.trim() || !password}>
            {busy ? 'Вход…' : 'Войти'}
          </button>
        </form>

        <div className="demo">
          <p>Демо-аккаунты (стенд хакатона):</p>
          <div className="chips">
            {DEMO_ACCOUNTS.map((a) => (
              <button
                key={a.username}
                className="chip"
                title={`${ROLE_LABELS[a.username === 'fire' ? 'firefighter' : a.username === 'eco' ? 'ecologist' : a.username as 'operator' | 'viewer']}: ${a.hint}`}
                disabled={busy}
                onClick={() => {
                  setUsername(a.username)
                  setPassword(a.password)
                  void submit(a.username, a.password)
                }}
              >
                {a.username}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
