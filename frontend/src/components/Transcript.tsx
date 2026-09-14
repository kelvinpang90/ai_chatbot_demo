import type { ConversationDetail, ToolCallRecord } from '../api'
import { money } from '../transcript'

// Moved here from pages/History.tsx when that page became a view of the console
// (task 37.6). The transcript is the past half of one customer's console: what was
// said, and what was called in between, as the audit log kept it.

const SOURCE_LABEL: Record<string, string> = {
  voice: '🎤 语音',
  interactive: '👆 点选',
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

export function Transcript({ detail }: { detail: ConversationDetail }) {
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
          <strong>{money(detail.cost_myr)}</strong>
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
