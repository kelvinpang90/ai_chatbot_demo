import { useEffect, useState } from 'react'
import { ApiError, getBot, type BotDetail } from '../api'
import { STRINGS, type Lang } from '../i18n/strings'

interface Props {
  lang: Lang
  botId: string
  onSelect: (identityId: string) => void
  onBack: () => void
  onAuthError: () => void
}

export default function IdentitySelect({ lang, botId, onSelect, onBack, onAuthError }: Props) {
  const [bot, setBot] = useState<BotDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const t = STRINGS[lang].identitySelect

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getBot(botId, lang)
      .then((data) => {
        if (!cancelled) setBot(data)
      })
      .catch((err: unknown) => {
        if (!cancelled && err instanceof ApiError && err.status === 401) {
          onAuthError()
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [botId, lang, onAuthError])

  return (
    <div className="page">
      <button type="button" className="back-link" onClick={onBack}>
        ← {t.back}
      </button>
      <h1>{t.title}</h1>
      <p>{t.subtitle}</p>
      {loading || !bot ? (
        <p>...</p>
      ) : (
        <div className="identity-list">
          {bot.identities.map((identity) => (
            <button
              key={identity.id}
              type="button"
              className="identity-card"
              onClick={() => onSelect(identity.id)}
            >
              {identity.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
