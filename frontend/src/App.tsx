import './App.css'
import { STRINGS } from './i18n/strings'

function App() {
  return (
    <div style={{ display: 'flex', minHeight: '100vh', alignItems: 'center', justifyContent: 'center' }}>
      <h1>{STRINGS.en.appTitle}</h1>
    </div>
  )
}

export default App
