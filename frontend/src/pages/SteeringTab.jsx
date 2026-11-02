import { useState, useEffect, useCallback } from 'react'
import styles from './SteeringTab.module.css'

const API = '/api/steering'

// Minimal, safe markdown -> HTML for the preview. Escapes HTML first, then
// renders headings, bold, italic, inline code, and - / * bullet lists. The
// content is short profile/prompt markdown, so this covers it without pulling
// in a heavy markdown dependency (keeps the PWA bundle lean).
function renderMarkdown(src) {
  const esc = (s) => s
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const inline = (s) => esc(s)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')

  const lines = (src || '').split('\n')
  const out = []
  let inList = false
  const closeList = () => { if (inList) { out.push('</ul>'); inList = false } }
  for (const raw of lines) {
    const line = raw.trimEnd()
    const h = line.match(/^(#{1,4})\s+(.*)$/)
    const li = line.match(/^\s*[-*]\s+(.*)$/)
    if (h) {
      closeList()
      const lvl = h[1].length
      out.push(`<h${lvl}>${inline(h[2])}</h${lvl}>`)
    } else if (li) {
      if (!inList) { out.push('<ul>'); inList = true }
      out.push(`<li>${inline(li[1])}</li>`)
    } else if (line === '') {
      closeList()
    } else {
      closeList()
      out.push(`<p>${inline(line)}</p>`)
    }
  }
  closeList()
  return out.join('\n')
}

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
  const [mode, setMode] = useState('preview') // preview | edit
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

      <div className={styles.modeRow}>
        <button
          className={mode === 'preview' ? styles.modeOn : styles.modeOff}
          onClick={() => setMode('preview')}
        >Preview</button>
        <button
          className={mode === 'edit' ? styles.modeOn : styles.modeOff}
          onClick={() => setMode('edit')}
        >Edit</button>
      </div>

      {mode === 'edit' ? (
        <textarea
          className={styles.textarea}
          value={text}
          onChange={e => setText(e.target.value)}
          spellCheck={false}
          rows={Math.min(20, Math.max(5, text.split('\n').length + 1))}
        />
      ) : (
        <div
          className={styles.preview}
          dangerouslySetInnerHTML={{ __html: renderMarkdown(text) }}
        />
      )}
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
