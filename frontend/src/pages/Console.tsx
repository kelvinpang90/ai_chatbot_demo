import { useEffect, useMemo, useRef, useState } from 'react'
import './Console.css'
import { consoleStreamUrl, type ConsoleEvent } from '../api'

const TOKEN_STORAGE_KEY = 'console_token'

// How many times to let a stream that is genuinely retrying fail before giving
// up on it. A refused subscription is handled separately - see `onerror`.
const MAX_FAILED_ATTEMPTS = 3

// How long the same enquiry takes a person. Not measured, deliberately
// conservative, and on screen because "it is fast" means nothing next to a
// number the owner can compare against a salary.
const HUMAN_MINUTES = 3

type Connection = 'connecting' | 'live' | 'error'

/** One tool call, both halves of it, as a single line on the screen. */
interface ToolRow {
  id: string
  seq: number
  at: number
  tool: string
  input: Record<string, unknown> | null
  output: string | null
  durationMs: number | null
  status: 'ok' | 'error' | 'running'
}

function storedToken(): string {
  // A token handed over in the URL is the convenient path (open the link on the
  // laptop); it gets kept so a refresh mid-demo does not drop the screen, and
  // wiped out of the address bar so it is not sitting on a projector.
  const fromUrl = new URLSearchParams(window.location.search).get('token')
  if (fromUrl) {
    try {
      window.localStorage.setItem(TOKEN_STORAGE_KEY, fromUrl)
    } catch {
      // Private windows refuse. The token still works for this page load.
    }
    window.history.replaceState(null, '', window.location.pathname)
    return fromUrl
  }
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY) ?? ''
  } catch {
    return ''
  }
}

function forgetToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY)
  } catch {
    // Nothing was stored to begin with.
  }
}

function formatTime(at: number): string {
  return new Date(at * 1000).toLocaleTimeString('en-GB', { hour12: false })
}

function formatRinggit(total: number): string {
  // Below one sen, two decimals reads as free and looks broken. Four decimals
  // reads as a real, very small number, which is the actual point being made.
  return `RM ${total.toFixed(total > 0 && total < 0.01 ? 4 : 2)}`
}

function preview(text: string, limit: number, expanded: boolean): string {
  if (expanded || text.length <= limit) return text
  return `${text.slice(0, limit)}…`
}

/**
 * The director's console: what the bot actually did, while the customer is
 * looking at a chat bubble on their phone.
 */
export default function Console() {
  const [token, setToken] = useState(storedToken)
  const [draftToken, setDraftToken] = useState('')
  const [gateNote, setGateNote] = useState('')
  const [connection, setConnection] = useState<Connection>('connecting')
  const [rows, setRows] = useState<ToolRow[]>([])
  const [costMyr, setCostMyr] = useState(0)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const feedRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!token) return

    // Replay re-sends the buffer on every reconnect, so the same event can
    // arrive twice; the sequence numbers are what make that harmless.
    const seen = new Set<number>()
    let failures = 0
    const source = new EventSource(consoleStreamUrl(token))

    function apply(raw: MessageEvent) {
      const event = JSON.parse(raw.data) as ConsoleEvent
      if (seen.has(event.seq)) return
      seen.add(event.seq)

      if (event.type === 'usage') {
        setCostMyr((total) => total + (event.cost_myr ?? 0))
        return
      }

      setRows((current) => mergeEvent(current, event))
    }

    source.onopen = () => {
      failures = 0
      setConnection('live')
    }
    function giveUp(why: string) {
      source.close()
      // Forget the token too, or a refresh quietly retries the same bad one and
      // lands back here a few seconds later with no explanation.
      forgetToken()
      setGateNote(why)
      setToken('')
    }

    source.onerror = () => {
      // A refused subscription (401, 503) is terminal: the browser closes the
      // stream and never retries, so this fires exactly once. Counting failures
      // would leave the screen saying "reconnecting..." forever over a stream
      // nothing is reconnecting -- which is the one thing a screen whose job is
      // to show what is happening must not do. Only a stream still CONNECTING
      // is genuinely retrying.
      if (source.readyState === EventSource.CLOSED) {
        giveUp('订阅被拒绝：token 不对，或者后端没有配 CONSOLE_TOKEN。')
        return
      }
      failures += 1
      setConnection('error')
      if (failures >= MAX_FAILED_ATTEMPTS) {
        giveUp('连不上后端，试了几次都没成。')
      }
    }
    for (const type of ['tool_start', 'tool_end', 'send_failed', 'usage']) {
      source.addEventListener(type, apply as EventListener)
    }

    return () => source.close()
  }, [token])

  useEffect(() => {
    // Newest at the bottom, like every other console; follow it down.
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight })
  }, [rows])

  const statusText = useMemo(
    () =>
      ({
        connecting: '连接中…',
        live: '● 实时',
        error: '连接中断，重试中…',
      })[connection],
    [connection],
  )

  function saveToken() {
    const value = draftToken.trim()
    if (!value) return
    try {
      window.localStorage.setItem(TOKEN_STORAGE_KEY, value)
    } catch {
      // Fine - it just will not survive a refresh.
    }
    setGateNote('')
    setToken(value)
    setConnection('connecting')
  }

  if (!token) {
    return (
      <div className="console">
        <div className="console-gate">
          <h1>导演台</h1>
          {gateNote && <p className="console-gate-note">{gateNote}</p>}
          <p>
            这条流里有真实的订单和客户资料，需要 CONSOLE_TOKEN 才能订阅。也可以直接打开
            <code> /console?token=…</code>。
          </p>
          <input
            type="password"
            value={draftToken}
            placeholder="CONSOLE_TOKEN"
            autoFocus
            onChange={(e) => setDraftToken(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && saveToken()}
          />
          <button onClick={saveToken}>连接</button>
        </div>
      </div>
    )
  }

  return (
    <div className="console">
      <header className="console-header">
        <span className="console-title">导演台 · 工具调用实时流</span>
        <span className="console-status" data-state={connection}>
          {statusText}
        </span>
        <span className="console-compare">
          同样这通询问，人工客服约 {HUMAN_MINUTES} 分钟
        </span>
        <span className="console-cost">本次会话成本 {formatRinggit(costMyr)}</span>
      </header>

      <div className="console-feed" ref={feedRef}>
        {rows.length === 0 ? (
          <p className="console-empty">等待第一条消息…（在手机上给这个号码发点什么）</p>
        ) : (
          rows.map((row) => (
            <Row
              key={row.id}
              row={row}
              expanded={expanded.has(row.id)}
              onToggle={() =>
                setExpanded((current) => {
                  const next = new Set(current)
                  if (!next.delete(row.id)) next.add(row.id)
                  return next
                })
              }
            />
          ))
        )}
      </div>
    </div>
  )
}

/** Fold one event into the rows, pairing `tool_end` onto the call it answers. */
function mergeEvent(rows: ToolRow[], event: ConsoleEvent): ToolRow[] {
  if (event.type === 'send_failed') {
    return [
      ...rows,
      {
        id: `failed:${event.seq}`,
        seq: event.seq,
        at: event.at,
        tool: '回复没有送达',
        input: null,
        output: event.output,
        durationMs: null,
        status: 'error',
      },
    ]
  }

  if (event.type === 'tool_start') {
    return [
      ...rows,
      {
        id: event.tool_use_id,
        seq: event.seq,
        at: event.at,
        tool: event.tool,
        input: event.input,
        output: null,
        durationMs: null,
        status: 'running',
      },
    ]
  }

  // A `tool_end` whose start we never saw (a screen that connected without
  // replay) still deserves a line rather than being dropped on the floor.
  const index = rows.findIndex((row) => row.id === event.tool_use_id)
  const merged: ToolRow = {
    id: event.tool_use_id,
    seq: index === -1 ? event.seq : rows[index].seq,
    at: index === -1 ? event.at : rows[index].at,
    tool: event.tool,
    input: index === -1 ? null : rows[index].input,
    output: event.output,
    durationMs: event.duration_ms,
    status: event.status === 'error' ? 'error' : 'ok',
  }
  if (index === -1) return [...rows, merged]
  return rows.map((row, i) => (i === index ? merged : row))
}

function Row({
  row,
  expanded,
  onToggle,
}: {
  row: ToolRow
  expanded: boolean
  onToggle: () => void
}) {
  const badge = { running: '运行中', ok: 'ok', error: 'error' }[row.status]

  return (
    <div className="console-row" data-status={row.status} onClick={onToggle}>
      <div className="console-row-head">
        <span className="console-time">{formatTime(row.at)}</span>
        <span className="console-tool">{row.tool}</span>
        <span className="console-badge" data-status={row.status}>
          {badge}
        </span>
        {row.durationMs !== null && (
          <span className="console-duration">{row.durationMs} ms</span>
        )}
      </div>

      {row.input && (
        <div className="console-field">
          <span className="console-field-label">入参</span>
          {preview(JSON.stringify(row.input), 200, expanded)}
        </div>
      )}

      {row.output && (
        <div className="console-field console-field-out">
          <span className="console-field-label">返回</span>
          {preview(row.output, 300, expanded)}
        </div>
      )}
    </div>
  )
}
