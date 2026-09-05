import { useState, type FormEvent } from 'react'
import { ApiError, identify, type IdentifyResponse } from '../api'
import { STRINGS, type Lang } from '../i18n/strings'

interface Props {
  lang: Lang
  onIdentified: (result: IdentifyResponse) => void
  onAuthError: () => void
}

/**
 * The first thing the web chat asks for, and the reason it exists: a phone
 * number is who you are on WhatsApp, so typing one here opens that customer's
 * record rather than an anonymous session. Type a number that has been talking
 * to the bot on a phone and the conversation is already there.
 */
export default function PhoneEntry({ lang, onIdentified, onAuthError }: Props) {
  const [phone, setPhone] = useState('')
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(false)
  const t = STRINGS[lang].phoneEntry

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setLoading(true)
    setError(false)
    try {
      onIdentified(await identify(phone.trim(), lang))
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onAuthError()
        return
      }
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
          type="tel"
          value={phone}
          onChange={(event) => setPhone(event.target.value)}
          placeholder={t.placeholder}
          autoFocus
        />
        <button type="submit" disabled={loading || !phone.trim()}>
          {t.button}
        </button>
        {error && <p className="error-text">{t.error}</p>}
      </form>
    </div>
  )
}
