import { useCallback, useEffect, useState } from 'react'
import {
  ApiError,
  clearConsoleToken,
  consoleToken,
  listConversations,
  readConversation,
  setConsoleToken,
  type ConversationDetail,
  type ConversationSummary,
  type ToolCallRecord,
} from '../api'

/** Opus 5 list prices, US dollars per million tokens. */
const USD_PER_M_INPUT = 5
const USD_PER_M_OUTPUT = 25
// Converted at display time rather than stored, so a rate change does not make
// every historical row wrong. Roughly right is the point: this line exists to
// answer "is this going to be expensive", and the honest answer is sen, not
// ringgit.
const MYR_PER_USD = 4.7

function cost(inputTokens: number, outputTokens: number): string {
  const usd = (inputTokens * USD_PER_M_INPUT + outputTokens * USD_PER_M_OUTPUT) / 1_000_000
  return `RM ${(usd * MYR_PER_USD).toFixed(4)}`
}

const SOURCE_LABEL: Record<string, string> = {
  voice: '🎤 语音',
  interactive: '👆 点选',
}

function TokenGate({ onUnlocked }: { onUnlocked: () => void }) {
  const [value, setValue] = useState('')
  return (
    <form
      className="history-gate"
      onSubmit={(e) => {
        e.preventDefault()
        if (!value.trim()) return
        setConsoleToken(value.trim())
        onUnlocked()
      }}
    >
      <h2>演示记录</h2>
      <p>需要 console token（服务器上的 CONSOLE_TOKEN）。</p>
      <input
        type="password"
        value={value}
        autoFocus
        placeholder="console token"
        onChange={(e) => setValue(e.target.value)}
      />
      <button type="submit">进入</button>
    </form>
  )
}

function ToolCall({ call }: { call: ToolCallRecord }) {
  return (
    <details className={`tool-call ${call.status}`}>
      <summary>
        <span className="tool-name">{call.tool}</span>
        <span className="tool-meta">
          {call.duration_ms != null && `${call.duration_ms}ms`} {call.status}
        </span>
      </summary>
      <div className="tool-body">
        <div className="tool-label">入参</div>
        <pre>{JSON.stringify(call.input ?? {}, null, 2)}</pre>
        <div className="tool-label">返回</div>
        <pre>{call.output || '(空)'}</pre>
      </div>
    </details>
  )
}

function Transcript({ detail }: { detail: ConversationDetail }) {
  return (
    <div className="transcript">
      <header className="transcript-head">
        <div>
          <strong>{detail.display_name || detail.key_id}</strong>
          <span className="pill">{detail.channel}</span>
          <span className="pill">{detail.bot_id}</span>
        </div>
        <div className="transcript-cost">
          {detail.input_tokens.toLocaleString()} in / {detail.output_tokens.toLocaleString()} out
          {' · '}
          {detail.api_turns} 次 API
          {' · '}
          <strong>{cost(detail.input_tokens, detail.output_tokens)}</strong>
          {detail.cache_read_tokens > 0 && (
            <span className="cache-hit"> · 缓存命中 {detail.cache_read_tokens.toLocaleString()}</span>
          )}
        </div>
      </header>

      {detail.messages.map((message) => (
        <div key={message.id} className={`turn ${message.role}`}>
          <div className="turn-head">
            <span>{message.role === 'user' ? '客户' : 'Bot'}</span>
            {SOURCE_LABEL[message.source] && (
              <span className="source">{SOURCE_LABEL[message.source]}</span>
            )}
            <span className="turn-at">{message.at.slice(11)}</span>
          </div>
          <div className="turn-body">{message.content}</div>
          {message.tool_calls.length > 0 && (
            <div className="turn-tools">
              {message.tool_calls.map((call) => (
                <ToolCall key={call.tool_use_id + call.at} call={call} />
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

export default function History() {
  const [unlocked, setUnlocked] = useState(() => consoleToken() !== '')
  const [search, setSearch] = useState('')
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<ConversationDetail | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const load = useCallback(async (term: string) => {
    setLoading(true)
    setError('')
    try {
      const page = await listConversations(term)
      setConversations(page.conversations)
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 401) {
        // A bad token is the one error worth forgetting, so the gate comes back
        // instead of a screen that keeps failing with no way to fix it.
        clearConsoleToken()
        setUnlocked(false)
      }
      setError(failure instanceof ApiError ? failure.message : '读不到记录')
      setConversations([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (unlocked) void load(search)
    // Re-runs on unlock and on each submitted search, not on every keystroke.
  }, [unlocked, search, load])

  useEffect(() => {
    if (!selected) {
      setDetail(null)
      return
    }
    let current = true
    readConversation(selected)
      .then((got) => {
        if (current) setDetail(got)
      })
      .catch(() => {
        if (current) setError('这通对话读不出来')
      })
    return () => {
      current = false
    }
  }, [selected])

  if (!unlocked) return <TokenGate onUnlocked={() => setUnlocked(true)} />

  return (
    <div className="history">
      <aside className="history-list">
        <form
          className="history-search"
          onSubmit={(e) => {
            e.preventDefault()
            const term = new FormData(e.currentTarget).get('term')
            setSearch(String(term ?? ''))
          }}
        >
          <input name="term" placeholder="手机号，任意写法" defaultValue={search} />
          <button type="submit">查</button>
        </form>

        {loading && <p className="history-note">读取中…</p>}
        {error && <p className="history-note error">{error}</p>}
        {!loading && !error && conversations.length === 0 && (
          <p className="history-note">没有记录。</p>
        )}

        {conversations.map((row) => (
          <button
            key={row.conversation_id}
            className={`history-row ${selected === row.conversation_id ? 'active' : ''}`}
            onClick={() => setSelected(row.conversation_id)}
          >
            <div className="history-row-top">
              <strong>{row.display_name || row.key_id}</strong>
              <span className="pill">{row.channel}</span>
            </div>
            <div className="history-row-meta">
              {row.last_at.slice(0, 16)} · {row.bot_id}
            </div>
            <div className="history-row-meta">
              {row.messages} 条 · {row.tool_calls} 次工具 · {cost(row.input_tokens, row.output_tokens)}
            </div>
          </button>
        ))}
      </aside>

      <main className="history-detail">
        {detail ? (
          <Transcript detail={detail} />
        ) : (
          <p className="history-note">左边选一通对话。</p>
        )}
      </main>
    </div>
  )
}
