import { useState } from 'react'
import styles from './Login.module.css'

export default function Login({ onSuccess, familyName }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      })
      if (res.ok) {
        onSuccess()
      } else {
        const data = await res.json().catch(() => ({}))
        setError(data.error === 'incorrect password' ? 'Wrong password — try again.' : 'Could not log in.')
      }
    } catch {
      setError('Could not reach the server.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={styles.wrap}>
      <form className={styles.card} onSubmit={submit}>
        <div className={styles.title}>🏡 {familyName ? `${familyName} Family Dashboard` : "Family Dashboard"}</div>
        <label className={styles.label} htmlFor="pw">Family password</label>
        <input
          id="pw"
          type="password"
          className={styles.input}
          value={password}
          onChange={e => setPassword(e.target.value)}
          autoFocus
          autoComplete="current-password"
          data-testid="login-password"
        />
        {error && <div className={styles.error} data-testid="login-error">{error}</div>}
        <button type="submit" className={styles.button} disabled={busy} data-testid="login-submit">
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
        <div className={styles.hint}>You&rsquo;ll stay signed in on this device for 30 days.</div>
      </form>
    </div>
  )
}
