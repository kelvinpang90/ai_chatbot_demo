import { useEffect, useMemo, useRef, useState } from 'react'
import './Console.css'
import { consoleStreamUrl, type ConsoleEvent } from '../api'

const TOKEN_STORAGE_KEY = 'console_token'

// How many times to let a stream that has never opened fail before giving up on
// it. Once it has opened, failures are the backend's, not the token's.
const MAX_FAILED_ATTEMPTS = 3

// How long to wait before rebuilding a stream the server dropped. Long enough
// not to hammer a backend that is still coming up, short enough that a redeploy
// mid-demo costs a few seconds rather than the operator's attention.
const RECONNECT_DELAY_MS = 3000

// How long the same enquiry takes a person. Not measured, deliberately
// conservative, and on screen because "it is fast" means nothing next to a
// number the owner can compare against a salary.
const HUMAN_MINUTES = 3

type Connection = 'connecting' | 'live' | 'error'

// React needs a key that is unique for the life of the list. The tool_use_id is
// not it: ids come from whichever backend process is running, and one that
// restarts mid-demo can hand out an id a row above already carries.
let nextRowKey = 1

/** One tool call, both halves of it, as a single line on the screen. */
interface ToolRow {
  key: number
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
  // Bumped to build a fresh EventSource after the server dropped the old one.
  const [attempt, setAttempt] = useState(0)
  const [connection, setConnection] = useState<Connection>('connecting')
  const [rows, setRows] = useState<ToolRow[]>([])
  const [costMyr, setCostMyr] = useState(0)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const feedRef = useRef<HTMLDivElement>(null)
  // Replay re-sends the whole buffer every time a stream opens, so the same
  // event arrives again after a reconnect. Sequence numbers make that harmless -
  // but only if they outlive the stream that saw them first, or a redeploy
  // mid-demo doubles every row on the screen and every sen on the total.
  const seenRef = useRef<Set<number>>(new Set())
  // Which run of the backend the sequence numbers in `seenRef` came from.
  const bootRef = useRef<string | null>(null)
  // The token this console has actually got a stream out of. Kept outside the
  // effect on purpose: a per-EventSource flag resets on every retry, so a
  // backend down for longer than one retry would look like a bad token again
  // and throw away a token we have proof is good.
  const provenTokenRef = useRef<string | null>(null)

  useEffect(() => {
    if (!token) return

    const seen = seenRef.current
    const proven = () => provenTokenRef.current === token
    let failures = 0
    let retryTimer: number | undefined
    const source = new EventSource(consoleStreamUrl(token))

    // The first frame of every stream names the backend process behind it. A
    // different one means the sequence numbers started over, so what we remember
    // seeing is about a run that no longer exists - keeping it would make every
    // event after a redeploy look like one we had already shown.
    function hello(raw: MessageEvent) {
      const { boot_id } = JSON.parse(raw.data) as { boot_id: string }
      if (bootRef.current !== boot_id) {
        seen.clear()
        bootRef.current = boot_id
      }
    }

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
      provenTokenRef.current = token
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
      setConnection('error')

      // Any non-2xx closes the stream for good - EventSource never retries one,
      // so this fires exactly once and "reconnecting..." would be a lie. But a
      // 401 and the 502 from a backend that is redeploying look identical here,
      // and only one of them is the token's fault. Whether this token has ever
      // got a stream out of the server is what tells them apart: a token that
      // worked a minute ago has not gone bad because the backend restarted.
      if (source.readyState === EventSource.CLOSED) {
        if (!proven()) {
          giveUp('订阅被拒绝：token 不对，或者后端没有配 CONSOLE_TOKEN。')
          return
        }
        source.close()
        retryTimer = window.setTimeout(() => setAttempt((n) => n + 1), RECONNECT_DELAY_MS)
        return
      }

      // Still CONNECTING: the browser is retrying on its own, which is the
      // right thing once we know the token works.
      if (proven()) return
      failures += 1
      if (failures >= MAX_FAILED_ATTEMPTS) {
        giveUp('连不上后端，试了几次都没成。')
      }
    }
    source.addEventListener('hello', hello as EventListener)
    for (const type of ['tool_start', 'tool_end', 'send_failed', 'usage']) {
      source.addEventListener(type, apply as EventListener)
    }

    return () => {
      window.clearTimeout(retryTimer)
      source.close()
    }
    // `attempt` is not read here - bumping it is how a dropped stream asks for
    // a whole new EventSource, since a closed one cannot be revived.
  }, [token, attempt])

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
              key={row.key}
              row={row}
              expanded={expanded.has(row.key)}
              onToggle={() =>
                setExpanded((current) => {
                  const next = new Set(current)
                  if (!next.delete(row.key)) next.add(row.key)
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

function _lastIndexOf(rows: ToolRow[], id: string): number {
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    if (rows[i].id === id) return i
  }
  return -1
}

/** Fold one event into the rows, pairing `tool_end` onto the call it answers. */
function mergeEvent(rows: ToolRow[], event: ConsoleEvent): ToolRow[] {
  if (event.type === 'send_failed') {
    return [
      ...rows,
      {
        key: nextRowKey++,
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
        key: nextRowKey++,
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
  //
  // Searched from the bottom: an end answers the most recent call with that id.
  // Anthropic's ids are unique so this is the same row either way in practice,
  // but scanning from the top means any repeat leaves the live call stuck on
  // "running" while a finished one further up is written to twice.
  const index = _lastIndexOf(rows, event.tool_use_id)
  const merged: ToolRow = {
    key: index === -1 ? nextRowKey++ : rows[index].key,
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
