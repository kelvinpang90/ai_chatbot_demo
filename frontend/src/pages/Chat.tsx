import { useEffect, useRef, useState, type FormEvent } from 'react'
import { sendMessage, type BotSummary, type ChatTurn } from '../api'
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
  chatKey: string
  history: ChatTurn[]
  quickQuestions: string[]
  onReset: () => void
}

export default function Chat({
  lang,
  bot,
  chatKey,
  history,
  quickQuestions: initialQuickQuestions,
  onReset,
}: Props) {
  // Seeded once, from whatever the customer already had on file - a greeting for
  // a demo just picked, or the conversation they were having on their phone.
  const [messages, setMessages] = useState<ChatMessage[]>(() =>
    history.map((turn) => ({ id: crypto.randomUUID(), role: turn.role, content: turn.content })),
  )
  const [quickQuestions, setQuickQuestions] = useState<string[]>(initialQuickQuestions)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const t = STRINGS[lang].chat
  const bottomRef = useRef<HTMLDivElement>(null)

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
      const res = await sendMessage(chatKey, text)
      setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: 'assistant', content: res.reply }])
    } catch {
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

  function handleReset() {
    if (!window.confirm(t.resetConfirm)) return
    onReset()
  }

  return (
    <div className="chat-page">
      <div className="chat-header">
        <span>{bot.icon}</span>
        <span className="chat-header-title">{bot.name}</span>
        <button type="button" className="reset-button" onClick={handleReset}>
          {t.reset}
        </button>
      </div>
      <div className="chat-messages">
        {messages.map((message) => (
          <div key={message.id} className={`bubble-row bubble-row-${message.role}`}>
            <div className={`bubble bubble-${message.role}`}>{message.content}</div>
            {message.failed && (
              <button type="button" className="retry-link" onClick={() => handleRetry(message.id)}>
                {t.sendFailed} · {t.retry}
              </button>
            )}
          </div>
        ))}
        {sending && (
          <div className="bubble-row bubble-row-assistant">
            <div className="bubble bubble-assistant bubble-typing">
              <span />
              <span />
              <span />
            </div>
          </div>
        )}
        {quickQuestions.length > 0 && (
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
        />
        <button type="submit" disabled={sending || !input.trim()}>
          {t.send}
        </button>
      </form>
    </div>
  )
}
