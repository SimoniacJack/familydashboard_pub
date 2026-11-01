import { useState, useEffect, useCallback, lazy, Suspense } from 'react'
import styles from './Inventory.module.css'

// Lazy so the ~480KB barcode library only loads when the user taps Scan.
const BarcodeScanner = lazy(() => import('./BarcodeScanner'))

const API = '/api/inventory'

const LOCATION_LABELS = {
  pantry: 'Pantry Cupboard',
  fridge_inside: 'Inside Fridge',
  freezer_inside: 'Inside Freezer',
  fridge_outside: 'Outside Fridge',
  freezer_outside: 'Outside Freezer',
}

const LOCATION_ICONS = {
  pantry: '🫙',
  fridge_inside: '🥬',
  freezer_inside: '🧊',
  fridge_outside: '🧀',
  freezer_outside: '❄️',
}

const LEVELS = ['full', 'ok', 'low', 'out']
const LEVEL_LABELS = { full: 'Full', ok: 'OK', low: 'Low', out: 'Out' }

export default function Inventory() {
  const [locations, setLocations] = useState([])
  const [items, setItems] = useState({})
  const [adding, setAdding] = useState(null) // which location is in "add" mode
  const [newName, setNewName] = useState('')
  const [newMode, setNewMode] = useState('count') // count | level
  const [newCount, setNewCount] = useState(1)
  const [newRestock, setNewRestock] = useState('')
  const [scanLocation, setScanLocation] = useState(null) // location the scanner opened from
  const [editing, setEditing] = useState(null) // { location, item } being edited in the modal

  const fetchInventory = useCallback(async () => {
    const res = await fetch(`${API}/`)
    const data = await res.json()
    setLocations(data.locations)
    setItems(data.items)
  }, [])

  useEffect(() => { fetchInventory() }, [fetchInventory])

  function patchLocal(location, itemId, patch) {
    setItems(it => ({
      ...it,
      [location]: it[location].map(i => i.id === itemId ? { ...i, ...patch } : i),
    }))
  }

  function resetAddForm() {
    setNewName(''); setNewMode('count'); setNewCount(1); setNewRestock('')
  }

  async function addItem(location) {
    const name = newName.trim()
    if (!name) return
    const count = newMode === 'count' ? Math.max(1, parseInt(newCount, 10) || 1) : 1
    const payload = {
      name, location, track_mode: newMode,
      count, restock: newMode === 'level' ? newRestock.trim() : '',
    }
    const temp = {
      id: `tmp-${Date.now()}`, name, location, note: '',
      track_mode: newMode, count, planned: 0,
      available: newMode === 'count' ? count : null,
      level: 'full', restock: payload.restock,
    }
    setItems(it => ({ ...it, [location]: [...(it[location] || []), temp] }))
    resetAddForm()
    const res = await fetch(`${API}/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    const saved = await res.json()
    setItems(it => ({
      ...it,
      [location]: it[location].map(i => i.id === temp.id ? saved : i),
    }))
  }

  async function removeItem(location, itemId) {
    setItems(it => ({ ...it, [location]: it[location].filter(i => i.id !== itemId) }))
    await fetch(`${API}/${itemId}`, { method: 'DELETE' })
  }

  async function setLevel(location, item, level) {
    patchLocal(location, item.id, { level })
    await fetch(`${API}/${item.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ level }),
    })
  }

  // Switch an item between count and level tracking. Rare — lives in the edit modal.
  async function setMode(location, item, mode) {
    if (item.track_mode === mode) return
    patchLocal(location, item.id, { track_mode: mode })
    setEditing(e => e && e.item.id === item.id
      ? { ...e, item: { ...e.item, track_mode: mode } } : e)
    const res = await fetch(`${API}/${item.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ track_mode: mode }),
    })
    const saved = await res.json()
    patchLocal(location, item.id, saved)
    setEditing(e => e && e.item.id === item.id ? { ...e, item: saved } : e)
  }

  // Adjust a count item by delta (−1 = used one, +1 = added one).
  async function adjustUnits(location, item, delta) {
    const nextCount = Math.max(0, (item.count || 0) + delta)
    // Consuming also releases a reservation, mirroring the backend.
    const nextPlanned = delta < 0
      ? Math.min(nextCount, Math.max(0, (item.planned || 0) + delta))
      : Math.min(nextCount, item.planned || 0)
    patchLocal(location, item.id, {
      count: nextCount, planned: nextPlanned,
      available: Math.max(0, nextCount - nextPlanned),
    })
    const res = await fetch(`${API}/${item.id}/use`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ delta }),
    })
    const saved = await res.json()
    patchLocal(location, item.id, saved)
  }

  async function removeFromModal() {
    if (!editing) return
    const { location, item } = editing
    setEditing(null)
    await removeItem(location, item.id)
  }

  return (
    <section className={styles.section}>
      <h2 className={styles.heading}>
        🍴 Food Inventory
        <span className={styles.sub}>
          count things you can count (cans), set a level for things you can&rsquo;t (rice)
        </span>
      </h2>

      <div className={styles.grid}>
        {locations.map(loc => (
          <div key={loc} className={styles.locationCard}>
            <div className={styles.locationHeader}>
              <span className={styles.locationName}>
                {LOCATION_ICONS[loc]} {LOCATION_LABELS[loc] || loc}
              </span>
              <span className={styles.count}>{(items[loc] || []).length}</span>
            </div>

            <ul className={styles.itemList}>
              {(items[loc] || []).map(item => (
                <li
                  key={item.id}
                  className={styles.item}
                  data-testid="inventory-item"
                >
                  <div className={styles.itemMain}>
                    <button
                      className={styles.itemName}
                      onClick={() => setEditing({ location: loc, item })}
                      title="Edit or remove"
                      data-testid="item-open"
                    >{item.name}</button>

                    {item.track_mode === 'count' ? (
                      <div className={styles.counter} data-testid="count-controls">
                        <button
                          className={styles.stepBtn}
                          onClick={() => adjustUnits(loc, item, -1)}
                          disabled={(item.count || 0) <= 0}
                          title="Used one"
                          data-testid="count-minus"
                        >−</button>
                        <span
                          className={`${styles.countVal} ${(item.count || 0) <= 0 ? styles.countOut : ''}`}
                          data-testid="count-value"
                        >{item.count ?? 0}</span>
                        <button
                          className={styles.stepBtn}
                          onClick={() => adjustUnits(loc, item, 1)}
                          title="Add one"
                          data-testid="count-plus"
                        >+</button>
                      </div>
                    ) : null}
                  </div>

                  {item.track_mode === 'count' && (item.planned || 0) > 0 && (
                    <div className={styles.reserved} data-testid="reserved-line">
                      {item.planned} reserved · {item.available ?? Math.max(0, (item.count || 0) - (item.planned || 0))} free
                    </div>
                  )}

                  {item.track_mode === 'level' && (
                    <div className={styles.levels} data-testid="level-toggle">
                      {LEVELS.map(lv => (
                        <button
                          key={lv}
                          className={`${styles.levelBtn} ${styles['lv_' + lv]} ${item.level === lv ? styles.levelActive : ''}`}
                          onClick={() => setLevel(loc, item, lv)}
                          data-testid={`level-${lv}`}
                        >
                          {LEVEL_LABELS[lv]}
                        </button>
                      ))}
                    </div>
                  )}
                </li>
              ))}
              {(items[loc] || []).length === 0 && (
                <li className={styles.emptyItem}>empty</li>
              )}
            </ul>

            {adding === loc ? (
              <form
                className={styles.addForm}
                onSubmit={e => { e.preventDefault(); addItem(loc) }}
              >
                <input
                  className={styles.addInput}
                  placeholder="Add item…"
                  value={newName}
                  onChange={e => setNewName(e.target.value)}
                  autoFocus
                />
                <div className={styles.modeRow}>
                  <button
                    type="button"
                    className={`${styles.modeTab} ${newMode === 'count' ? styles.modeTabOn : ''}`}
                    onClick={() => setNewMode('count')}
                  >Count (cans)</button>
                  <button
                    type="button"
                    className={`${styles.modeTab} ${newMode === 'level' ? styles.modeTabOn : ''}`}
                    onClick={() => setNewMode('level')}
                  >Level (rice)</button>
                </div>
                {newMode === 'count' ? (
                  <label className={styles.qtyRow}>
                    How many?
                    <input
                      type="number"
                      min="1"
                      className={styles.qtyInput}
                      value={newCount}
                      onChange={e => setNewCount(e.target.value)}
                    />
                  </label>
                ) : (
                  <input
                    className={styles.addInput}
                    placeholder="Restock text, e.g. 2L milk"
                    value={newRestock}
                    onChange={e => setNewRestock(e.target.value)}
                  />
                )}
                <div className={styles.addActions}>
                  <button type="submit" className={styles.saveBtn}>Add</button>
                  <button
                    type="button"
                    className={styles.cancelBtn}
                    onClick={() => { setAdding(null); resetAddForm() }}
                  >
                    Cancel
                  </button>
                </div>
              </form>
            ) : (
              <div className={styles.cardActions}>
                <button
                  className={styles.addBtn}
                  onClick={() => { setAdding(loc); resetAddForm() }}
                >
                  + Add
                </button>
                <button
                  className={styles.scanBtn}
                  onClick={() => setScanLocation(loc)}
                  data-testid={`scan-btn-${loc}`}
                >
                  📷 Scan
                </button>
              </div>
            )}
          </div>
        ))}
      </div>

      {editing && (
        <div
          className={styles.modalOverlay}
          onClick={() => setEditing(null)}
          data-testid="item-modal"
        >
          <div className={styles.modal} onClick={e => e.stopPropagation()}>
            <div className={styles.modalHead}>
              <span className={styles.modalTitle}>{editing.item.name}</span>
              <button
                className={styles.modalClose}
                onClick={() => setEditing(null)}
                title="Close"
              >✕</button>
            </div>

            <div className={styles.modalBody}>
              <div className={styles.modalLabel}>How is this tracked?</div>
              <div className={styles.modeRow} data-testid="mode-toggle">
                <button
                  className={`${styles.modeTab} ${editing.item.track_mode === 'count' ? styles.modeTabOn : ''}`}
                  onClick={() => setMode(editing.location, editing.item, 'count')}
                  data-testid="mode-count"
                >Count (cans)</button>
                <button
                  className={`${styles.modeTab} ${editing.item.track_mode === 'level' ? styles.modeTabOn : ''}`}
                  onClick={() => setMode(editing.location, editing.item, 'level')}
                  data-testid="mode-level"
                >Level (rice)</button>
              </div>
              <p className={styles.modalHint}>
                {editing.item.track_mode === 'count'
                  ? 'Counted in whole units — set the number on the item.'
                  : 'An estimate — Full / OK / Low / Out on the item.'}
              </p>
            </div>

            <button
              className={styles.modalDanger}
              onClick={removeFromModal}
              data-testid="modal-remove"
            >
              Remove item
            </button>
          </div>
        </div>
      )}

      {scanLocation && (
        <Suspense fallback={null}>
          <BarcodeScanner
            locations={locations}
            defaultLocation={scanLocation}
            onClose={() => { setScanLocation(null); fetchInventory() }}
            onAdded={() => fetchInventory()}
          />
        </Suspense>
      )}
    </section>
  )
}
