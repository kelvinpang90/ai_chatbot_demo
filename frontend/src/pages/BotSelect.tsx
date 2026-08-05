import { useEffect, useState } from 'react'
import { ApiError, listBots, type BotSummary } from '../api'
import { STRINGS, type Lang } from '../i18n/strings'

interface Props {
  lang: Lang
  onSelect: (bot: BotSummary) => void
  onAuthError: () => void
}

export default function BotSelect({ lang, onSelect, onAuthError }: Props) {
  const [bots, setBots] = useState<BotSummary[]>([])
  const [loading, setLoading] = useState(true)
  const t = STRINGS[lang].botSelect

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listBots(lang)
      .then((data) => {
        if (!cancelled) setBots(data)
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
  }, [lang, onAuthError])

  return (
    <div className="page">
      <h1>{t.title}</h1>
      <p>{t.subtitle}</p>
      {loading ? (
        <p>...</p>
      ) : (
        <div className="bot-grid">
          {bots.map((bot) => (
            <button key={bot.id} type="button" className="bot-card" onClick={() => onSelect(bot)}>
              <span className="bot-card-icon">{bot.icon}</span>
              <span className="bot-card-name">{bot.name}</span>
              <span className="bot-card-desc">{bot.description}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
