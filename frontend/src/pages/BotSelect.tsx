import { useEffect, useState } from 'react'
import { listBots, type BotSummary } from '../api'
import { STRINGS, type Lang } from '../i18n/strings'

interface Props {
  lang: Lang
  onSelect: (bot: BotSummary) => void
}

export default function BotSelect({ lang, onSelect }: Props) {
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
      .catch(() => {
        // Nothing to show but the empty list; the retry is reloading the page.
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [lang])

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
