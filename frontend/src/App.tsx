import { useState } from 'react'
import './App.css'
import LanguageSwitcher from './components/LanguageSwitcher'
import PasswordGate from './pages/PasswordGate'
import BotSelect from './pages/BotSelect'
import IdentitySelect from './pages/IdentitySelect'
import Chat from './pages/Chat'
import { clearToken, createSessionId, getToken, type BotSummary } from './api'
import { DEFAULT_LANG, type Lang } from './i18n/strings'

type View =
  | { name: 'password' }
  | { name: 'botSelect' }
  | { name: 'identitySelect'; bot: BotSummary }
  | { name: 'chat'; bot: BotSummary; identityId: string; sessionId: string }

function App() {
  const [lang, setLang] = useState<Lang>(DEFAULT_LANG)
  const [view, setView] = useState<View>(() => (getToken() ? { name: 'botSelect' } : { name: 'password' }))

  function handleAuthError() {
    clearToken()
    setView({ name: 'password' })
  }

  return (
    <div className="app-shell">
      <LanguageSwitcher lang={lang} onChange={setLang} />

      {view.name === 'password' && (
        <PasswordGate lang={lang} onSuccess={() => setView({ name: 'botSelect' })} />
      )}

      {view.name === 'botSelect' && (
        <BotSelect
          lang={lang}
          onSelect={(bot) => setView({ name: 'identitySelect', bot })}
          onAuthError={handleAuthError}
        />
      )}

      {view.name === 'identitySelect' && (
        <IdentitySelect
          lang={lang}
          botId={view.bot.id}
          onSelect={(identityId) =>
            setView({ name: 'chat', bot: view.bot, identityId, sessionId: createSessionId() })
          }
          onBack={() => setView({ name: 'botSelect' })}
          onAuthError={handleAuthError}
        />
      )}

      {view.name === 'chat' && (
        <Chat
          lang={lang}
          bot={view.bot}
          identityId={view.identityId}
          sessionId={view.sessionId}
          onAuthError={handleAuthError}
        />
      )}
    </div>
  )
}

export default App
