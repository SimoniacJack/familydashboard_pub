import { useState, useEffect, useCallback } from 'react'
import CalendarView from './pages/CalendarView.jsx'
import FoodTab from './pages/FoodTab.jsx'
import SteeringTab from './pages/SteeringTab.jsx'
import Login from './components/Login.jsx'
import Nav from './components/Nav.jsx'
import styles from './App.module.css'

const TABS = [
  { id: 'home', label: '📅 Calendar' },
  { id: 'food', label: '🍴 Inventory' },
  { id: 'steering', label: '⚙️ Steering' },
]

export default function App() {
  // null = still checking, false = logged out, true = logged in
  const [authed, setAuthed] = useState(null)
  const [tab, setTab] = useState('home')  // always start on Home
  const [familyName, setFamilyName] = useState('')

  const checkAuth = useCallback(async () => {
    try {
      const res = await fetch('/api/auth/me')
      const data = await res.json()
      setAuthed(Boolean(data.authed))
    } catch {
      setAuthed(false)
    }
  }, [])

  useEffect(() => { checkAuth() }, [checkAuth])

  // Instance branding (family name) — public, safe to fetch before auth.
  useEffect(() => {
    fetch('/api/config/')
      .then(r => r.json())
      .then(d => setFamilyName(d.family_name || ''))
      .catch(() => {})
  }, [])

  async function logout() {
    await fetch('/api/auth/logout', { method: 'POST' }).catch(() => {})
    setAuthed(false)
  }

  if (authed === null) {
    return <div className={styles.app} />  // brief blank while checking
  }
  if (!authed) {
    return <Login onSuccess={() => setAuthed(true)} familyName={familyName} />
  }

  return (
    <div className={styles.app}>
      <Nav tabs={TABS} active={tab} onChange={setTab} onLogout={logout} familyName={familyName} />
      <div className={styles.tabBody}>
        {tab === 'home' ? <CalendarView /> : tab === 'food' ? <FoodTab /> : <SteeringTab />}
      </div>
    </div>
  )
}
