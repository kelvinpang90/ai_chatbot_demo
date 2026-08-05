import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ApiError, selectBot, sendMessage, type BotSummary } from '../api'
import { STRINGS, type Lang } from '../i18n/strings'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

interface Props {
  lang: Lang
  bot: BotSummary
  identityId: string
  sessionId: string
  onAuthError: () => void
}

export default function Chat({ lang, bot, identityId, sessionId, onAuthError }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [starting, setStarting] = useState(true)
  const [sending, setSending] = useState(false)
  const t = STRINGS[lang].chat
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let cancelled = false
    setStarting(true)
    setMessages([])
    selectBot(sessionId, bot.id, identityId, lang)
      .then((res) => {
        if (cancelled) return
        setMessages([{ role: 'assistant', content: res.greeting }])
      })
      .catch((err: unknown) => {
        if (!cancelled && err instanceof ApiError && err.status === 401) {
          onAuthError()
        }
      })
      .finally(() => {
        if (!cancelled) setStarting(false)
      })
    return () => {
      cancelled = true
    }
  }, [sessionId, bot.id, identityId, lang, onAuthError])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const text = input.trim()
    if (!text || sending) return
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setSending(true)
    try {
      const res = await sendMessage(sessionId, text)
      setMessages((prev) => [...prev, { role: 'assistant', content: res.reply }])
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onAuthError()
        return
      }
      setMessages((prev) => [...prev, { role: 'assistant', content: t.sendFailed }])
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="chat-page">
      <div className="chat-header">
        <span>{bot.icon}</span>
        <span>{bot.name}</span>
      </div>
      <div className="chat-messages">
        {starting ? (
          <p className="chat-status">{t.connecting}</p>
        ) : (
          messages.map((message, index) => (
            <div key={index} className={`bubble bubble-${message.role}`}>
              {message.content}
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
      <form className="chat-input-bar" onSubmit={handleSubmit}>
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder={t.inputPlaceholder}
          disabled={starting}
        />
        <button type="submit" disabled={starting || sending || !input.trim()}>
          {t.send}
        </button>
      </form>
    </div>
  )
}
