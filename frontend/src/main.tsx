import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import Console from './pages/Console.tsx'
import VerticalAdmin from './pages/VerticalAdmin.tsx'

// Three screens, one bundle, and still no router: two of them are screens in the
// room rather than the customer's flow -- the console, and the property agency's
// own back office. One path check remains cheaper than a dependency that would
// exist to express exactly this.
const path = window.location.pathname.replace(/\/$/, '')

const SCREENS: Record<string, React.ReactElement> = {
  '/console': <Console />,
  // The transcript page became a view of the console (task 37.6). The old path
  // still opens it, so a bookmark from before does not land on the customer demo.
  '/history': <Console />,
  '/vertical-admin': <VerticalAdmin />,
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>{SCREENS[path] ?? <App />}</StrictMode>,
)
