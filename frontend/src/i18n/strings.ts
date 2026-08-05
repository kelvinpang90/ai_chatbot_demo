export type Lang = 'zh' | 'en' | 'ms'

export const LANGUAGES: { code: Lang; label: string }[] = [
  { code: 'zh', label: '中文' },
  { code: 'en', label: 'English' },
  { code: 'ms', label: 'Bahasa Melayu' },
]

export const DEFAULT_LANG: Lang = 'en'

interface Strings {
  appTitle: string
  passwordGate: {
    title: string
    subtitle: string
    placeholder: string
    button: string
    error: string
  }
  botSelect: {
    title: string
    subtitle: string
  }
  identitySelect: {
    title: string
    subtitle: string
    back: string
  }
  chat: {
    inputPlaceholder: string
    send: string
    reset: string
    resetConfirm: string
    connecting: string
    sendFailed: string
    retry: string
  }
}

export const STRINGS: Record<Lang, Strings> = {
  zh: {
    appTitle: 'AI Chatbot 演示',
    passwordGate: {
      title: '请输入访问密码',
      subtitle: '这是一个受限访问的产品演示',
      placeholder: '访问密码',
      button: '进入',
      error: '密码不正确',
    },
    botSelect: {
      title: '选择一个演示场景',
      subtitle: '每个场景都是一个独立的行业 AI 客服',
    },
    identitySelect: {
      title: '选择一个演示身份',
      subtitle: '不同身份会看到不同的模拟数据',
      back: '返回',
    },
    chat: {
      inputPlaceholder: '输入消息...',
      send: '发送',
      reset: '重新开始',
      resetConfirm: '确定要清空当前对话吗？',
      connecting: '连接中...',
      sendFailed: '发送失败，点击重试',
      retry: '重试',
    },
  },
  en: {
    appTitle: 'AI Chatbot Demo',
    passwordGate: {
      title: 'Enter Access Password',
      subtitle: 'This is a password-protected product demo',
      placeholder: 'Access password',
      button: 'Enter',
      error: 'Incorrect password',
    },
    botSelect: {
      title: 'Choose a demo scenario',
      subtitle: 'Each scenario is an independent industry AI assistant',
    },
    identitySelect: {
      title: 'Choose a demo identity',
      subtitle: 'Different identities see different mock data',
      back: 'Back',
    },
    chat: {
      inputPlaceholder: 'Type a message...',
      send: 'Send',
      reset: 'Restart',
      resetConfirm: 'Clear the current conversation?',
      connecting: 'Connecting...',
      sendFailed: 'Failed to send, tap to retry',
      retry: 'Retry',
    },
  },
  ms: {
    appTitle: 'Demo Chatbot AI',
    passwordGate: {
      title: 'Masukkan Kata Laluan Akses',
      subtitle: 'Ini adalah demo produk yang dilindungi kata laluan',
      placeholder: 'Kata laluan akses',
      button: 'Masuk',
      error: 'Kata laluan salah',
    },
    botSelect: {
      title: 'Pilih senario demo',
      subtitle: 'Setiap senario adalah pembantu AI industri yang berasingan',
    },
    identitySelect: {
      title: 'Pilih identiti demo',
      subtitle: 'Identiti berbeza akan melihat data mock yang berbeza',
      back: 'Kembali',
    },
    chat: {
      inputPlaceholder: 'Taip mesej...',
      send: 'Hantar',
      reset: 'Mula Semula',
      resetConfirm: 'Kosongkan perbualan semasa?',
      connecting: 'Menyambung...',
      sendFailed: 'Gagal menghantar, ketik untuk cuba lagi',
      retry: 'Cuba lagi',
    },
  },
}
