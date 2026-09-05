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
