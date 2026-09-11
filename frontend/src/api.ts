export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string> | undefined),
    },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}) as { detail?: string })
    throw new ApiError(response.status, body.detail ?? 'Request failed')
  }
  return response.json() as Promise<T>
}

export interface BotSummary {
  id: string
  name: string
  description: string
  icon: string
}

export async function listBots(lang: string): Promise<BotSummary[]> {
  return request<BotSummary[]>(`/api/bots?lang=${lang}`)
}

export interface ChatTurn {
  role: 'user' | 'assistant'
  content: string
}

export interface IdentifyResponse {
  key: string
  bot: BotSummary | null
  history: ChatTurn[]
}

/** Open the chat as a phone number - the same record WhatsApp writes to. */
export async function identify(phone: string, lang: string): Promise<IdentifyResponse> {
  return request<IdentifyResponse>('/api/chat/identify', {
    method: 'POST',
    body: JSON.stringify({ phone, lang }),
  })
}

export interface SelectBotResponse {
  greeting: string
  quick_questions: string[]
}

export async function selectBot(
  key: string,
  botId: string,
  lang: string,
): Promise<SelectBotResponse> {
  return request<SelectBotResponse>(`/api/chat/${key}/select`, {
    method: 'POST',
    body: JSON.stringify({ bot_id: botId, lang }),
  })
}

export interface SendMessageResponse {
  reply: string
}

export async function sendMessage(key: string, message: string): Promise<SendMessageResponse> {
  return request<SendMessageResponse>(`/api/chat/${key}/message`, {
    method: 'POST',
    body: JSON.stringify({ message }),
  })
}

export async function resetSession(key: string): Promise<{ status: string }> {
  return request(`/api/chat/${key}/reset`, { method: 'POST' })
}


// --- the director's console and the audit log behind it ----------------------
//
// One token for both screens: the live feed (task 12) and the transcripts
// (task 37.2) sit behind the same CONSOLE_TOKEN, so making each page ask
// separately would be a worse version of the same thing.

const TOKEN_STORAGE_KEY = 'console_token'

export function storedToken(): string {
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

export function rememberToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, token)
  } catch {
    // A browser refusing storage still works, it just asks again next reload.
  }
}

export function forgetToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY)
  } catch {
    // Nothing was stored to begin with.
  }
}

/** One line on the director's console. Mirrors backend/app/console/events.py. */
export interface ConsoleEvent {
  seq: number
  at: number
  type: 'tool_start' | 'tool_end' | 'send_failed' | 'usage' | 'tools_switched'
  tool: string
  tool_use_id: string
  input: Record<string, unknown> | null
  output: string | null
  duration_ms: number | null
  // 'ok' | 'error' on tool_end; 'on' | 'off' on tools_switched.
  status: 'ok' | 'error' | 'on' | 'off' | null
  model: string | null
  tokens: Record<string, number> | null
  cost_myr: number | null
}

/**
 * The tool feed, gated by CONSOLE_TOKEN.
 *
 * The token travels as a query parameter because EventSource cannot set request
 * headers - see the note on `require_console_token` in the router. `replay` asks
 * for the buffer first, which is what a screen opened mid-conversation wants.
 */
export function consoleStreamUrl(token: string, replay = true): string {
  return `/console/stream?token=${encodeURIComponent(token)}&replay=${replay}`
}

// The transcript endpoints can send a header, so they do.
function consoleRequest<T>(path: string): Promise<T> {
  return request<T>(path, { headers: { 'X-Console-Token': storedToken() } })
}

export interface ConversationSummary {
  conversation_id: string
  key_id: string
  display_name: string | null
  channel: string
  bot_id: string
  messages: number
  tool_calls: number
  input_tokens: number
  output_tokens: number
  api_turns: number
  cost_myr: number
  started_at: string
  last_at: string
}

export interface ToolCallRecord {
  tool: string
  tool_use_id: string
  input: Record<string, unknown> | null
  output: string | null
  duration_ms: number | null
  status: string
  at: string
}

export interface TranscriptMessage {
  id: number
  role: string
  content: string
  source: string
  at: string
  tool_calls: ToolCallRecord[]
}

export interface ConversationDetail {
  conversation_id: string
  key_id: string
  display_name: string | null
  channel: string
  bot_id: string
  messages: TranscriptMessage[]
  input_tokens: number
  output_tokens: number
  cache_write_tokens: number
  cache_read_tokens: number
  api_turns: number
  cost_myr: number
}

export interface HistoryPage {
  conversations: ConversationSummary[]
  limit: number
  offset: number
}

export async function listConversations(search: string, offset = 0): Promise<HistoryPage> {
  const params = new URLSearchParams({ offset: String(offset) })
  if (search.trim()) params.set('key', search.trim())
  return consoleRequest<HistoryPage>(`/console/history?${params}`)
}

export async function readConversation(id: string): Promise<ConversationDetail> {
  return consoleRequest<ConversationDetail>(`/console/history/${encodeURIComponent(id)}`)
}

/** Whether the bots may call tools at all - the console's control arm. */
export interface ToolSwitch {
  enabled: boolean
}

// Both of these take the token rather than reading it back out of storage: this
// is the one screen that may be holding a token localStorage refused to keep (a
// private window, a token that arrived in the URL), and a switch that 401s while
// the feed beside it is live would read as the switch being broken.
export function readToolSwitch(token: string): Promise<ToolSwitch> {
  return request<ToolSwitch>('/console/tools', { headers: { 'X-Console-Token': token } })
}

export function setToolSwitch(token: string, enabled: boolean): Promise<ToolSwitch> {
  return request<ToolSwitch>('/console/tools', {
    method: 'POST',
    headers: { 'X-Console-Token': token },
    body: JSON.stringify({ enabled }),
  })
}

/** What the demo amounted to, as it was sent to the customer's phone. */
export interface DemoSummary {
  key_id: string
  display_name: string | null
  conversation_id: string
  minutes: number
  tool_calls: number
  text: string
}

// Closing the demo off (task 19.1). `keyId` is left out in the ordinary case -
// one customer in the room - and the reply names whoever it actually went to, so
// a room with three of them does not end on a guess.
export function sendDemoSummary(token: string, keyId?: string): Promise<DemoSummary> {
  return request<DemoSummary>('/console/demo-summary', {
    method: 'POST',
    headers: { 'X-Console-Token': token },
    body: JSON.stringify({ key_id: keyId ?? null }),
  })
}
