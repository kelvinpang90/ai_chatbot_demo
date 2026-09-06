import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import Console from './pages/Console.tsx'

// Two screens, one bundle, and no router: the console is the only page that is
// not part of the customer's flow, and one path check is cheaper than a
// dependency that would exist to express exactly this.
const isConsole = window.location.pathname.replace(/\/$/, '') === '/console'

createRoot(document.getElementById('root')!).render(
  <StrictMode>{isConsole ? <Console /> : <App />}</StrictMode>,
)
