import { useState, type FormEvent } from 'react'
import { login, setToken } from '../api'
import { STRINGS, type Lang } from '../i18n/strings'

interface Props {
  lang: Lang
  onSuccess: () => void
}

export default function PasswordGate({ lang, onSuccess }: Props) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(false)
  const t = STRINGS[lang].passwordGate

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setLoading(true)
    setError(false)
    try {
      const { token } = await login(password)
      setToken(token)
      onSuccess()
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page-centered">
      <form className="password-gate" onSubmit={handleSubmit}>
        <h1>{t.title}</h1>
        <p>{t.subtitle}</p>
        <input
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          placeholder={t.placeholder}
          autoFocus
        />
        <button type="submit" disabled={loading || !password}>
          {t.button}
        </button>
        {error && <p className="error-text">{t.error}</p>}
      </form>
    </div>
  )
}
