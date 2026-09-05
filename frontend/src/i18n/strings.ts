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
  phoneEntry: {
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
  chat: {
    inputPlaceholder: string
    send: string
    reset: string
    resetConfirm: string
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
    phoneEntry: {
      title: '请输入手机号',
      subtitle: '用你在 WhatsApp 上的那个号码，手机上的对话会接着往下聊',
      placeholder: '例如 60123456789',
      button: '进入',
      error: '请输入一个有效的手机号',
    },
    botSelect: {
      title: '选择一个演示场景',
      subtitle: '每个场景都是一个独立的行业 AI 客服',
    },
    chat: {
      inputPlaceholder: '输入消息...',
      send: '发送',
      reset: '重新开始',
      resetConfirm: '确定要清空当前对话吗？',
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
    phoneEntry: {
      title: 'Enter your phone number',
      subtitle: 'The same number you use on WhatsApp - your conversation carries on from there',
      placeholder: 'e.g. 60123456789',
      button: 'Continue',
      error: 'Please enter a valid phone number',
    },
    botSelect: {
      title: 'Choose a demo scenario',
      subtitle: 'Each scenario is an independent industry AI assistant',
    },
    chat: {
      inputPlaceholder: 'Type a message...',
      send: 'Send',
      reset: 'Restart',
      resetConfirm: 'Clear the current conversation?',
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
    phoneEntry: {
      title: 'Masukkan nombor telefon anda',
      subtitle: 'Nombor yang sama seperti di WhatsApp - perbualan anda diteruskan dari situ',
      placeholder: 'cth. 60123456789',
      button: 'Teruskan',
      error: 'Sila masukkan nombor telefon yang sah',
    },
    botSelect: {
      title: 'Pilih senario demo',
      subtitle: 'Setiap senario adalah pembantu AI industri yang berasingan',
    },
    chat: {
      inputPlaceholder: 'Taip mesej...',
      send: 'Hantar',
      reset: 'Mula Semula',
      resetConfirm: 'Kosongkan perbualan semasa?',
      sendFailed: 'Gagal menghantar, ketik untuk cuba lagi',
      retry: 'Cuba lagi',
    },
  },
}
