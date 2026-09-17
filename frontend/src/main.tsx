import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import Console from './pages/Console.tsx'
import Admin from './pages/Admin.tsx'
import Privacy from './pages/Privacy.tsx'

// Four screens, one bundle, and still no router: three of them are screens in
// the room rather than the customer's flow -- the console, the demos' back
// office, and the notice we publish. One path check remains cheaper
// than a dependency that would exist to express exactly this.
const path = window.location.pathname.replace(/\/$/, '')

const SCREENS: Record<string, React.ReactElement> = {
  '/console': <Console />,
  // The transcript page became a view of the console (task 37.6). The old path
  // still opens it, so a bookmark from before does not land on the customer demo.
  '/history': <Console />,
  // One back office with a tab per demo (task 38.5). The two pages it replaced
  // keep their addresses, each opening its own tab, so bookmarks and the phone
  // checklist from before still land somewhere.
  '/admin': <Admin />,
  '/vertical-admin': <Admin initial="realestate" />,
  '/food-admin': <Admin initial="food" />,
  // The public one (task 29.3). It is in this table rather than inside `App`
  // precisely because `App` asks for the console token first, and the Meta
  // reviewer who follows the app's privacy link has no token to type.
  '/privacy': <Privacy />,
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>{SCREENS[path] ?? <App />}</StrictMode>,
)
