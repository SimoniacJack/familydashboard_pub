import { useState, useEffect, useMemo } from 'react'
import styles from './DraftReviewPanel.module.css'

const INV_API = '/api/inventory'
const SHOP_API = '/api/shopping'

const LOCATION_LABELS = {
  pantry: 'Pantry Cupboard',
  fridge_inside: 'Inside Fridge',
  freezer_inside: 'Inside Freezer',
  fridge_outside: 'Outside Fridge',
  freezer_outside: 'Outside Freezer',
}

const REASON_LABELS = {
  'not in inventory': 'not in your inventory',
  'short in stock': 'not enough in stock',
  'running low': 'running low',
}

// One draft line, each independently resolvable:
//   keep  -> gets bought (default)
//   skip  -> removed from the list (you already have it)
//   match -> point it at an existing inventory item (don't buy; it's in stock)
//   add   -> create a new inventory item in a location (don't buy; you'll stock it)
export default function DraftReviewPanel({ draft, usedGpt, onConfirm, onCancel }) {
  const [rows, setRows] = useState([])
  const [inventory, setInventory] = useState([]) // flat [{id, name, location, track_mode}]
  const [locations, setLocations] = useState([])
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setRows(draft.map((d, i) => ({
      key: i, name: d.name, quantity: d.quantity || '', reason: d.reason,
      action: 'keep', matchId: '', addLocation: 'pantry',
    })))
  }, [draft])

  useEffect(() => {
    fetch(`${INV_API}/`).then(r => r.json()).then(data => {
      setLocations(data.locations || [])
      const flat = []
      Object.values(data.items || {}).forEach(list => list.forEach(it => flat.push(it)))
      flat.sort((a, b) => a.name.localeCompare(b.name))
      setInventory(flat)
    })
  }, [])

  function setRow(key, patch) {
    setRows(rs => rs.map(r => r.key === key ? { ...r, ...patch } : r))
  }

  function setAll(action) {
    setRows(rs => rs.map(r => ({ ...r, action })))
  }

  const keepCount = useMemo(() => rows.filter(r => r.action === 'keep').length, [rows])

  async function confirm() {
    setBusy(true)
    try {
      // 1. Resolve "add new inventory item" rows first, so a mistaken match
      //    can't leave an orphan. Each becomes a real count item (qty 1).
      const adds = rows.filter(r => r.action === 'add')
      for (const r of adds) {
        await fetch(`${INV_API}/scan-add`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: r.name, location: r.addLocation, track_mode: 'count', count: 1,
          }),
        })
      }
      // 2. "match to existing" rows -> bump that item's count (you have it).
      const matches = rows.filter(r => r.action === 'match' && r.matchId)
      for (const r of matches) {
        await fetch(`${INV_API}/${r.matchId}/use`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ delta: 1 }),
        })
      }
      // 3. Push only the kept lines to Todoist.
      const keep = rows.filter(r => r.action === 'keep')
        .map(r => ({ name: r.name, quantity: r.quantity }))
      const res = await fetch(`${SHOP_API}/push-confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items: keep }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`)
      onConfirm(data, { added: adds.length, matched: matches.length })
    } catch (e) {
      onConfirm(null, null, e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={styles.overlay} data-testid="draft-panel">
      <div className={styles.panel}>
        <div className={styles.header}>
          <div>
            <h3 className={styles.title}>Looks like you&rsquo;re missing these</h3>
            <p className={styles.subtitle}>
              Keep what you need to buy. Remove anything you already have, or match
              it to your inventory.
              {usedGpt ? ' Matches suggested by AI.' : ' Matched by name.'}
            </p>
          </div>
          <button className={styles.closeBtn} onClick={onCancel} data-testid="draft-close">✕</button>
        </div>

        {rows.length === 0 ? (
          <p className={styles.empty}>Nothing missing — your stock covers every meal. 🎉</p>
        ) : (
          <>
            <div className={styles.bulkRow}>
              <span>{rows.length} items</span>
              <div className={styles.bulkBtns}>
                <button className={styles.bulkBtn} onClick={() => setAll('keep')}>Keep all</button>
                <button className={styles.bulkBtn} onClick={() => setAll('skip')} data-testid="draft-remove-all">Remove all</button>
              </div>
            </div>

            <ul className={styles.list}>
              {rows.map(r => (
                <li
                  key={r.key}
                  className={`${styles.row} ${r.action === 'skip' ? styles.rowSkipped : ''}`}
                  data-testid="draft-row"
                >
                  <div className={styles.rowMain}>
                    <label className={styles.keepLabel}>
                      <input
                        type="checkbox"
                        checked={r.action === 'keep'}
                        onChange={e => setRow(r.key, { action: e.target.checked ? 'keep' : 'skip' })}
                        data-testid="draft-keep"
                      />
                      <span className={styles.rowName}>
                        {r.name}
                        {r.quantity && <span className={styles.rowQty}> — {r.quantity}</span>}
                      </span>
                    </label>
                    <span className={styles.reason}>{REASON_LABELS[r.reason] || r.reason}</span>
                  </div>

                  <div className={styles.resolveRow}>
                    <select
                      className={styles.resolveSelect}
                      value={r.action}
                      onChange={e => setRow(r.key, { action: e.target.value })}
                      data-testid="draft-action"
                    >
                      <option value="keep">Buy it</option>
                      <option value="skip">Already have — remove</option>
                      <option value="match">Match to inventory…</option>
                      <option value="add">Add to inventory…</option>
                    </select>

                    {r.action === 'match' && (
                      <select
                        className={styles.resolveSelect}
                        value={r.matchId}
                        onChange={e => setRow(r.key, { matchId: e.target.value })}
                        data-testid="draft-match-select"
                      >
                        <option value="">Pick an item…</option>
                        {inventory.map(it => (
                          <option key={it.id} value={it.id}>
                            {it.name} ({LOCATION_LABELS[it.location] || it.location})
                          </option>
                        ))}
                      </select>
                    )}

                    {r.action === 'add' && (
                      <select
                        className={styles.resolveSelect}
                        value={r.addLocation}
                        onChange={e => setRow(r.key, { addLocation: e.target.value })}
                        data-testid="draft-add-location"
                      >
                        {locations.map(l => (
                          <option key={l} value={l}>{LOCATION_LABELS[l] || l}</option>
                        ))}
                      </select>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}

        <div className={styles.footer}>
          <button className={styles.cancelBtn} onClick={onCancel} disabled={busy}>Cancel</button>
          <button
            className={styles.confirmBtn}
            onClick={confirm}
            disabled={busy}
            data-testid="draft-confirm"
          >
            {busy ? 'Pushing…' : `Push ${keepCount} to shopping list`}
          </button>
        </div>
      </div>
    </div>
  )
}
