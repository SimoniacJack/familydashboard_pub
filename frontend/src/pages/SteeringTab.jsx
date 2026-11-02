import { useState, useEffect, useCallback } from 'react'
import styles from './SteeringTab.module.css'

const API = '/api/steering'

// View/edit the AI meal-planning prompt and per-member likes/dislikes.
// Edits persist in the DB (override the baked file); revert drops the override.
export default function SteeringTab() {
  const [docs, setDocs] = useState([])
  const [loading, setLoading] = useState(true)

  const fetchDocs = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API}/`)
      const data = await res.json()
      setDocs(data.docs || [])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchDocs() }, [fetchDocs])

  return (
    <div className={styles.page}>
      <h2 className={styles.heading}>
        ⚙️ Steering
        <span className={styles.sub}>edit the AI meal-planning prompt and each person&rsquo;s likes &amp; dislikes</span>
      </h2>
      {loading ? (
        <p className={styles.muted}>Loading…</p>
      ) : (
        docs.map(doc => <SteeringDoc key={doc.key} doc={doc} onSaved={fetchDocs} />)
      )}
    </div>
  )
}

function SteeringDoc({ doc, onSaved }) {
  const [text, setText] = useState(doc.content)
  const [status, setStatus] = useState('') // '' | 'saving' | 'saved' | 'error'
  const dirty = text !== doc.content

  async function save() {
    setStatus('saving')
    try {
      const res = await fetch(`${API}/${encodeURIComponent(doc.key)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text }),
      })
      if (!res.ok) throw new Error()
      setStatus('saved')
      onSaved?.()
      setTimeout(() => setStatus(''), 1500)
    } catch {
      setStatus('error')
    }
  }

  async function revert() {
    if (!window.confirm('Revert this to the built-in default? Your edits here will be discarded.')) return
    setStatus('saving')
    try {
      const res = await fetch(`${API}/${encodeURIComponent(doc.key)}`, { method: 'DELETE' })
      if (!res.ok) throw new Error()
      onSaved?.()
    } catch {
      setStatus('error')
    }
  }

  return (
    <section className={styles.doc} data-testid="steering-doc">
      <div className={styles.docHead}>
        <span className={styles.docTitle}>{doc.title}</span>
        {doc.overridden && <span className={styles.editedTag}>edited</span>}
      </div>
      {doc.help && <p className={styles.docHelp}>{doc.help}</p>}
      <textarea
        className={styles.textarea}
        value={text}
        onChange={e => setText(e.target.value)}
        spellCheck={false}
        rows={Math.min(20, Math.max(5, text.split('\n').length + 1))}
      />
      <div className={styles.docActions}>
        <button className={styles.saveBtn} onClick={save} disabled={!dirty || status === 'saving'}>
          {status === 'saving' ? 'Saving…' : 'Save'}
        </button>
        {doc.overridden && (
          <button className={styles.revertBtn} onClick={revert} disabled={status === 'saving'}>
            Revert to default
          </button>
        )}
        {status === 'saved' && <span className={styles.savedMsg}>✓ Saved</span>}
        {status === 'error' && <span className={styles.errMsg}>Save failed</span>}
      </div>
    </section>
  )
}
