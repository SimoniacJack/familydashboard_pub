import { useState, useEffect, useCallback } from 'react'
import styles from './Reminders.module.css'
import { memberColor, cap } from '../memberColors.js'

const API = '/api/reminders'
const MEMBERS_API = '/api/members'

function todayStr() {
  return new Date().toISOString().slice(0, 10)
}

export default function Reminders({ date, filterMember }) {
  const activeDate = date || todayStr()
  const isToday = activeDate === todayStr()

  const [allReminders, setAllReminders] = useState([])
  const [members, setMembers] = useState([])

  const fetchReminders = useCallback(async () => {
    const res = await fetch(`${API}/?date=${activeDate}`)
    const data = await res.json()
    setAllReminders(data.reminders)
  }, [activeDate])

  useEffect(() => { fetchReminders() }, [fetchReminders])

  useEffect(() => {
    fetch(`${MEMBERS_API}/`).then(r => r.json()).then(setMembers).catch(() => {})
  }, [])

  // When filtering by a member, show only their reminders (family/unassigned hidden)
  const reminders = filterMember
    ? allReminders.filter(r => r.member === filterMember)
    : allReminders

  async function toggle(reminderId) {
    setAllReminders(rs => rs.map(r => r.id === reminderId ? { ...r, done: !r.done } : r))
    await fetch(`${API}/${reminderId}/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date: activeDate }),
    })
  }

  // Build the row order: members who have reminders, then "family" (unassigned).
  const byPerson = {}
  for (const r of reminders) {
    const key = r.member || '__family__'
    ;(byPerson[key] = byPerson[key] || []).push(r)
  }
  const memberOrder = members.map(m => m.id).filter(id => byPerson[id])
  const rowKeys = [...memberOrder, ...(byPerson['__family__'] ? ['__family__'] : [])]

  function personMeta(key) {
    if (key === '__family__') return { name: 'Family', image: null, color: { bg: 'var(--color-surface-alt)', ink: 'var(--color-text-muted)' } }
    const m = members.find(x => x.id === key)
    return { name: m ? m.name : cap(key), image: m?.image, color: memberColor(key) }
  }

  if (reminders.length === 0) return null

  const heading = isToday
    ? "Today's Reminders"
    : `Reminders — ${new Date(activeDate + 'T00:00:00').toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'short' })}`

  // Columns of the XY grid. "anytime" reminders get their own column only if any exist.
  const hasAnytime = reminders.some(r => (r.routine || 'anytime') === 'anytime')
  const columns = [
    { key: 'morning', label: '☀️ Morning' },
    { key: 'evening', label: '🌙 Evening' },
    ...(hasAnytime ? [{ key: 'anytime', label: 'Anytime' }] : []),
  ]

  function cellItems(personKey, colKey) {
    return (byPerson[personKey] || []).filter(r => (r.routine || 'anytime') === colKey)
  }

  return (
    <section className={styles.section} data-testid="reminders">
      <h2 className={styles.heading}>{heading}</h2>
      <div
        className={styles.grid}
        data-testid="reminders-grid"
        style={{ gridTemplateColumns: `minmax(90px, 0.8fr) repeat(${columns.length}, 1fr)` }}
      >
        {/* Header row */}
        <div className={styles.corner} />
        {columns.map(c => (
          <div key={c.key} className={styles.colHead}>{c.label}</div>
        ))}

        {/* One row per person */}
        {rowKeys.map(key => {
          const meta = personMeta(key)
          return (
            <div key={key} className={styles.gridRow} style={{ display: 'contents' }}>
              <div className={styles.rowHead} style={{ background: meta.color.bg }}>
                {meta.image
                  ? <img src={meta.image} alt={meta.name} className={styles.avatar} />
                  : <span className={styles.avatarFallback}>{meta.name === 'Family' ? '🏠' : meta.name[0]}</span>}
                <span className={styles.rowName} style={{ color: meta.color.ink }}>{meta.name}</span>
              </div>
              {columns.map(c => {
                const items = cellItems(key, c.key)
                return (
                  <div key={c.key} className={styles.cell}>
                    {items.map(r => (
                      <button
                        key={r.id}
                        className={`${styles.item} ${r.done ? styles.itemDone : ''}`}
                        onClick={() => toggle(r.id)}
                      >
                        <span className={styles.checkbox}>{r.done ? '✓' : ''}</span>
                        <span className={styles.itemLabel}>{r.label}</span>
                      </button>
                    ))}
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>
    </section>
  )
}
