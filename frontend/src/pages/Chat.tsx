import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ApiError, resetSession, selectBot, sendMessage, type BotSummary } from '../api'
import { STRINGS, type Lang } from '../i18n/strings'

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  failed?: boolean
}

interface Props {
  lang: Lang
  bot: BotSummary
  sessionId: string
  onAuthError: () => void
}

export default function Chat({ lang, bot, sessionId, onAuthError }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [quickQuestions, setQuickQuestions] = useState<string[]>([])
  const [input, setInput] = useState('')
  const [starting, setStarting] = useState(true)
  const [sending, setSending] = useState(false)
  const t = STRINGS[lang].chat
  const bottomRef = useRef<HTMLDivElement>(null)

  function startConversation() {
    setStarting(true)
    setMessages([])
    setQuickQuestions([])
    return selectBot(sessionId, bot.id, lang)
      .then((res) => {
        setMessages([{ id: crypto.randomUUID(), role: 'assistant', content: res.greeting }])
        setQuickQuestions(res.quick_questions)
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) onAuthError()
      })
      .finally(() => setStarting(false))
  }

  useEffect(() => {
    startConversation()
    // Switching the UI language mid-chat shouldn't wipe the conversation - only a new
    // session or bot should. Claude replies in whatever language the user types in,
    // independent of the UI toggle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, bot.id])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, sending])

  async function doSend(text: string, retryId?: string) {
    const id = retryId ?? crypto.randomUUID()
    if (retryId) {
      setMessages((prev) => prev.map((m) => (m.id === retryId ? { ...m, failed: false } : m)))
    } else {
      setMessages((prev) => [...prev, { id, role: 'user', content: text }])
    }
    setQuickQuestions([])
    setSending(true)
    try {
      const res = await sendMessage(sessionId, text)
      setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: 'assistant', content: res.reply }])
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onAuthError()
        return
      }
      setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, failed: true } : m)))
    } finally {
      setSending(false)
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const text = input.trim()
    if (!text || sending) return
    setInput('')
    await doSend(text)
  }

  function handleRetry(id: string) {
    const message = messages.find((m) => m.id === id)
    if (message) doSend(message.content, id)
  }

  async function handleReset() {
    if (!window.confirm(t.resetConfirm)) return
    try {
      await resetSession(sessionId)
    } catch {
      // best-effort - starting a new conversation resets server-side state anyway
    }
    startConversation()
  }

  return (
    <div className="chat-page">
      <div className="chat-header">
        <span>{bot.icon}</span>
        <span className="chat-header-title">{bot.name}</span>
        <button type="button" className="reset-button" onClick={handleReset} disabled={starting}>
          {t.reset}
        </button>
      </div>
      <div className="chat-messages">
        {starting ? (
          <p className="chat-status">{t.connecting}</p>
        ) : (
          messages.map((message) => (
            <div key={message.id} className={`bubble-row bubble-row-${message.role}`}>
              <div className={`bubble bubble-${message.role}`}>{message.content}</div>
              {message.failed && (
                <button type="button" className="retry-link" onClick={() => handleRetry(message.id)}>
                  {t.sendFailed} · {t.retry}
                </button>
              )}
            </div>
          ))
        )}
        {sending && (
          <div className="bubble-row bubble-row-assistant">
            <div className="bubble bubble-assistant bubble-typing">
              <span />
              <span />
              <span />
            </div>
          </div>
        )}
        {!starting && quickQuestions.length > 0 && (
          <div className="quick-questions">
            {quickQuestions.map((question) => (
              <button
                key={question}
                type="button"
                className="quick-question"
                onClick={() => doSend(question)}
                disabled={sending}
              >
                {question}
              </button>
            ))}
          </div>
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
