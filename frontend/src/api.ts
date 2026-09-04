const TOKEN_STORAGE_KEY = 'ai_chatbot_demo_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY)
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> | undefined),
  }
  if (token) {
    headers['X-Access-Token'] = token
  }

  const response = await fetch(path, { ...options, headers })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}) as { detail?: string })
    throw new ApiError(response.status, body.detail ?? 'Request failed')
  }
  return response.json() as Promise<T>
}

export interface LoginResponse {
  token: string
}

export async function login(password: string): Promise<LoginResponse> {
  return request<LoginResponse>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ password }),
  })
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

export interface SelectBotResponse {
  greeting: string
  quick_questions: string[]
}

export async function selectBot(
  sessionId: string,
  botId: string,
  lang: string,
): Promise<SelectBotResponse> {
  return request<SelectBotResponse>(`/api/chat/${sessionId}/select`, {
    method: 'POST',
    body: JSON.stringify({ bot_id: botId, lang }),
  })
}

export interface SendMessageResponse {
  reply: string
}

export async function sendMessage(sessionId: string, message: string): Promise<SendMessageResponse> {
  return request<SendMessageResponse>(`/api/chat/${sessionId}/message`, {
    method: 'POST',
    body: JSON.stringify({ message }),
  })
}

export async function resetSession(sessionId: string): Promise<{ status: string }> {
  return request(`/api/chat/${sessionId}/reset`, { method: 'POST' })
}

export function createSessionId(): string {
  return crypto.randomUUID()
}
