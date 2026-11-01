import { useState, useEffect, useCallback } from 'react'
import styles from './ShoppingList.module.css'

const API = '/api/shopping'

const LOCATION_LABELS = {
  pantry: 'Pantry Cupboard',
  fridge_inside: 'Inside Fridge',
  freezer_inside: 'Inside Freezer',
  fridge_outside: 'Outside Fridge',
  freezer_outside: 'Outside Freezer',
}

export default function ShoppingList() {
  const [active, setActive] = useState([])
  const [completed, setCompleted] = useState([])
  const [locations, setLocations] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  // item currently awaiting a location choice: { todoist_id, name }
  const [filing, setFiling] = useState(null)

  const refresh = useCallback(async () => {
    setError(null)
    try {
      const [a, c] = await Promise.all([
        fetch(`${API}/active`).then(r => r.json()),
        fetch(`${API}/completed-unfiled`).then(r => r.json()),
      ])
      if (a.error) throw new Error(a.error)
      setActive(a.items || [])
      setCompleted(c.items || [])
      if (c.locations) setLocations(c.locations)
    } catch (e) {
      setError(e.message || 'Could not load the shopping list')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  // Tick an active item: complete it in Todoist, then prompt for a location.
  async function buy(item) {
    setActive(list => list.filter(i => i.todoist_id !== item.todoist_id))
    try {
      const res = await fetch(`${API}/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ todoist_id: item.todoist_id, content: item.content }),
      })
      const data = await res.json()
      setFiling({ todoist_id: item.todoist_id, name: data.name || item.content })
    } catch {
      setError('Could not complete the item in Todoist')
      refresh()
    }
  }

  // File the item awaiting a location into inventory at the chosen location.
  async function fileTo(location) {
    if (!filing) return
    const payload = { ...filing, location }
    setFiling(null)
    await fetch(`${API}/file-to-inventory`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    // remove from the "bought in Google Home" list if it was there
    setCompleted(list => list.filter(i => i.todoist_id !== payload.todoist_id))
  }

  function startFiling(item) {
    setFiling({ todoist_id: item.todoist_id, name: item.content })
  }

  async function dismiss(item) {
    setCompleted(list => list.filter(i => i.todoist_id !== item.todoist_id))
    await fetch(`${API}/dismiss-completed`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ todoist_id: item.todoist_id, content: item.content }),
    })
  }

  return (
    <section className={styles.section} data-testid="shopping">
      <h2 className={styles.heading}>
        🛒 Shopping List
        <span className={styles.sub}>from Todoist — tick to add to inventory</span>
      </h2>

      {error && <p className={styles.error}>{error}</p>}
      {loading && <p className={styles.muted}>Loading…</p>}

      {!loading && (
        <>
          <ul className={styles.itemList} data-testid="shopping-active">
            {active.map(item => (
              <li key={item.todoist_id} className={styles.item} data-testid="shopping-item">
                <button
                  className={styles.check}
                  title="Bought — add to inventory"
                  data-testid="buy-btn"
                  onClick={() => buy(item)}
                >○</button>
                <span className={styles.itemName}>{item.content}</span>
              </li>
            ))}
            {active.length === 0 && <li className={styles.emptyItem}>list is empty</li>}
          </ul>

          {completed.length > 0 && (
            <div className={styles.bought} data-testid="shopping-bought">
              <h3 className={styles.boughtHeading}>Just bought — file to inventory</h3>
              <ul className={styles.itemList}>
                {completed.map(item => (
                  <li key={item.todoist_id} className={styles.item} data-testid="bought-item">
                    <span className={styles.itemName}>{item.content}</span>
                    <button className={styles.fileBtn} data-testid="file-btn" onClick={() => startFiling(item)}>
                      File…
                    </button>
                    <button className={styles.dismissBtn} onClick={() => dismiss(item)} title="Not an inventory item">
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {/* Location picker modal */}
      {filing && (
        <div className={styles.overlay} onClick={() => setFiling(null)}>
          <div className={styles.modal} data-testid="location-picker" onClick={e => e.stopPropagation()}>
            <p className={styles.modalTitle}>
              Where does <strong>{filing.name}</strong> go?
            </p>
            <div className={styles.locationChoices}>
              {(locations.length ? locations : Object.keys(LOCATION_LABELS)).map(loc => (
                <button key={loc} className={styles.locationChoice} data-testid={`loc-${loc}`} onClick={() => fileTo(loc)}>
                  {LOCATION_LABELS[loc] || loc}
                </button>
              ))}
            </div>
            <button className={styles.cancelBtn} onClick={() => setFiling(null)}>Cancel</button>
          </div>
        </div>
      )}
    </section>
  )
}
