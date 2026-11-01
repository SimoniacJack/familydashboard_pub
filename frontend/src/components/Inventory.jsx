import { useState, useEffect, useCallback } from 'react'
import styles from './Inventory.module.css'

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

export default function Inventory() {
  const [locations, setLocations] = useState([])
  const [items, setItems] = useState({})
  const [adding, setAdding] = useState(null) // which location is in "add" mode
  const [newName, setNewName] = useState('')

  const fetchInventory = useCallback(async () => {
    const res = await fetch(`${API}/`)
    const data = await res.json()
    setLocations(data.locations)
    setItems(data.items)
  }, [])

  useEffect(() => { fetchInventory() }, [fetchInventory])

  async function addItem(location) {
    const name = newName.trim()
    if (!name) return
    // optimistic
    const temp = { id: `tmp-${Date.now()}`, name, location, note: '' }
    setItems(it => ({ ...it, [location]: [...(it[location] || []), temp] }))
    setNewName('')
    const res = await fetch(`${API}/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, location }),
    })
    const saved = await res.json()
    // swap temp for the saved record (gets a real id)
    setItems(it => ({
      ...it,
      [location]: it[location].map(i => i.id === temp.id ? saved : i),
    }))
  }

  async function removeItem(location, itemId) {
    setItems(it => ({ ...it, [location]: it[location].filter(i => i.id !== itemId) }))
    await fetch(`${API}/${itemId}`, { method: 'DELETE' })
  }

  return (
    <section className={styles.section}>
      <h2 className={styles.heading}>
        🍴 Food Inventory
        <span className={styles.sub}>what we have — the shopping list skips these</span>
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
                <li key={item.id} className={styles.item}>
                  <span className={styles.itemName}>{item.name}</span>
                  <button
                    className={styles.removeBtn}
                    onClick={() => removeItem(loc, item.id)}
                    title="Remove"
                  >
                    ✕
                  </button>
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
                  onBlur={() => { if (!newName.trim()) setAdding(null) }}
                />
              </form>
            ) : (
              <button
                className={styles.addBtn}
                onClick={() => { setAdding(loc); setNewName('') }}
              >
                + Add
              </button>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
