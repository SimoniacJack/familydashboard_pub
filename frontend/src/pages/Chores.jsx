import { useState, useEffect, useCallback } from 'react'
import styles from './Chores.module.css'
import { memberColor } from '../memberColors.js'

const API = '/api'

// 1 point = 10p. Format a point total as pounds.
function pointsToMoney(pts) {
  return `£${(pts * 0.10).toFixed(2)}`
}

const SCOPE_SECTIONS = [
  { key: 'day', label: 'Daily' },
  { key: 'week', label: 'Weekly' },
  { key: 'month', label: 'Monthly' },
  { key: 'once', label: 'One-off jobs' },
]

export default function Chores({ filterMember, selectedDate }) {
  const [buckets, setBuckets] = useState({ day: [], week: [], month: [], once: [] })
  const [members, setMembers] = useState([])
  const [rooms, setRooms] = useState([])
  const [points, setPoints] = useState({})
  const [showForm, setShowForm] = useState(false)
  const [completingId, setCompletingId] = useState(null) // instance id in "who did it?" mode
  const [roomFilter, setRoomFilter] = useState('')       // room id to filter by, or ''
  const [error, setError] = useState(null)

  const [form, setForm] = useState({
    name: '', description: '', assigned_to: '', points: 5, frequency: 'weekly', assignable: 'all', room_id: ''
  })

  const fetchAll = useCallback(async () => {
    try {
      const dateQ = selectedDate ? `?date=${selectedDate}` : ''
      const [c, m, p, r] = await Promise.all([
        fetch(`${API}/chores/for-date${dateQ}`).then(r => r.json()),
        fetch(`${API}/members/`).then(r => r.json()),
        fetch(`${API}/chores/points`).then(r => r.json()),
        fetch(`${API}/chores/rooms`).then(r => r.json()),
      ])
      setBuckets(c.buckets || { day: [], week: [], month: [], once: [] })
      setMembers(m)
      setPoints(p)
      setRooms(r)
    } catch {
      setError('Could not connect to backend. Is it running?')
    }
  }, [selectedDate])

  useEffect(() => { fetchAll() }, [fetchAll])

  async function createChore(e) {
    e.preventDefault()
    await fetch(`${API}/chores/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    })
    setShowForm(false)
    setForm({ name: '', description: '', assigned_to: '', points: 5, frequency: 'weekly', assignable: 'all', room_id: '' })
    fetchAll()
  }

  async function deleteChore(id) {
    await fetch(`${API}/chores/${id}`, { method: 'DELETE' })
    fetchAll()
  }

  async function recordCompletion(instanceId, memberId) {
    await fetch(`${API}/chores/instance/${instanceId}/complete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ completed_by: memberId }),
    })
    setCompletingId(null)
    fetchAll()
  }

  async function uncompleteInstance(instanceId) {
    await fetch(`${API}/chores/instance/${instanceId}/uncomplete`, { method: 'POST' })
    fetchAll()
  }

  function choreMatchesMember(chore, memberId) {
    const member = members.find(m => m.id === memberId)
    if (!member) return true
    if (chore.frequency === 'once') return chore.assigned_to === memberId
    const assignable = chore.assignable || 'all'
    if (assignable === 'adults') return member.role === 'adult'
    if (assignable === 'children') return member.role === 'child'
    return true
  }

  function visible(list) {
    let out = list
    if (filterMember) out = out.filter(c => choreMatchesMember(c, filterMember))
    if (roomFilter) out = out.filter(c => c.room_id === roomFilter)
    return out
  }

  const anyVisible = SCOPE_SECTIONS.some(s => visible(buckets[s.key] || []).length > 0)

  return (
    <div className={styles.container}>
      <div className={styles.topBar}>
        <h2 className={styles.heading}>Chores</h2>
        <div className={styles.topRight}>
          <div className={styles.pointsInline}>
            {members.filter(m => m.role === 'child').map(m => (
              <span key={m.id} className={styles.pointsPill}>
                {m.name}: <strong>{pointsToMoney(points[m.id] || 0)}</strong>
              </span>
            ))}
          </div>
          {/* Compact room filter */}
          <select className={styles.roomFilter} value={roomFilter} onChange={e => setRoomFilter(e.target.value)}>
            <option value="">All rooms</option>
            {rooms.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
          <button className={styles.btnPrimary} onClick={() => setShowForm(v => !v)}>
            {showForm ? 'Cancel' : '+ Add'}
          </button>
        </div>
      </div>

      {error && <p className={styles.error}>{error}</p>}

      {/* Add chore form */}
      {showForm && (
        <form className={styles.form} onSubmit={createChore}>
          <div className={styles.formGrid}>
            <label className={styles.label}>
              Name
              <input className={styles.input} value={form.name}
                onChange={e => setForm(f => ({ ...f, name: e.target.value }))} required />
            </label>
            <label className={styles.label}>
              Points (1pt = 10p)
              <input className={styles.input} type="number" min="0" value={form.points}
                onChange={e => setForm(f => ({ ...f, points: Number(e.target.value) }))} required />
            </label>
            <label className={styles.label}>
              Who can do it
              <select className={styles.input} value={form.assignable}
                onChange={e => setForm(f => ({ ...f, assignable: e.target.value }))}>
                <option value="all">Anyone</option>
                <option value="children">Kids only</option>
                <option value="adults">Adults only</option>
              </select>
            </label>
            <label className={styles.label}>
              Frequency
              <select className={styles.input} value={form.frequency}
                onChange={e => setForm(f => ({ ...f, frequency: e.target.value }))}>
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
                <option value="once">One-off job</option>
              </select>
            </label>
            <label className={styles.label}>
              Room
              <select className={styles.input} value={form.room_id}
                onChange={e => setForm(f => ({ ...f, room_id: e.target.value }))}>
                <option value="">None</option>
                {rooms.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
            </label>
            {form.frequency === 'once' && (
              <label className={styles.label}>
                Assign to
                <select className={styles.input} value={form.assigned_to}
                  onChange={e => setForm(f => ({ ...f, assigned_to: e.target.value }))} required>
                  <option value="">Select person</option>
                  {members.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
                </select>
              </label>
            )}
            <label className={styles.label} style={{ gridColumn: '1 / -1' }}>
              Description
              <input className={styles.input} value={form.description}
                onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
            </label>
          </div>
          <button className={styles.btnPrimary} type="submit">Save Chore</button>
        </form>
      )}

      {!anyVisible && !showForm && (
        <p className={styles.empty}>
          {filterMember || roomFilter ? 'No chores match this filter.' : 'No chores yet. Add one to get started.'}
        </p>
      )}

      {/* Sections by scope: Daily / Weekly / Monthly / One-off */}
      {SCOPE_SECTIONS.map(section => {
        const list = visible(buckets[section.key] || [])
        if (list.length === 0) return null
        return (
          <div key={section.key} className={styles.scopeSection}>
            <h3 className={styles.scopeHeading}>{section.label}</h3>
            <div className={styles.choresGrid}>
              {list.map(chore => (
                <ChoreCard
                  key={chore.instance_id}
                  chore={chore}
                  members={members}
                  rooms={rooms}
                  isCompleting={completingId === chore.instance_id}
                  onStartComplete={() => setCompletingId(chore.instance_id)}
                  onCancelComplete={() => setCompletingId(null)}
                  onComplete={memberId => recordCompletion(chore.instance_id, memberId)}
                  onUncomplete={() => uncompleteInstance(chore.instance_id)}
                  onDelete={() => deleteChore(chore.chore_id)}
                />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ─── Chore card ──────────────────────────────────────────────────────────────

function ChoreCard({ chore, members, rooms, isCompleting, onStartComplete, onCancelComplete, onComplete, onUncomplete, onDelete }) {
  const isDone = chore.status === 'done'
  const doneBy = isDone ? members.find(m => m.id === chore.completed_by) : null

  const isOneOff = chore.frequency === 'once'
  const assignedTo = isOneOff ? members.find(m => m.id === chore.assigned_to) : null
  const room = chore.room_id ? (rooms || []).find(r => r.id === chore.room_id) : null

  const assignable = chore.assignable || 'all'
  const eligibleMembers = members.filter(m =>
    assignable === 'all' ? true :
    assignable === 'adults' ? m.role === 'adult' :
    assignable === 'children' ? m.role === 'child' :
    true
  )

  return (
    <div className={`${styles.choreCard} ${isDone ? styles.choreCardDone : ''} ${isOneOff ? styles.choreCardOneOff : ''}`}>
      <button className={styles.deleteBtn} onClick={onDelete} title="Delete chore">✕</button>

      <div className={styles.choreTop}>
        <span className={styles.choreName}>{chore.name}</span>
        <span className={styles.chorePoints}>{chore.points}pt</span>
      </div>
      {chore.description && <p className={styles.choreDesc}>{chore.description}</p>}
      <div className={styles.choreBadges}>
        {room && <span className={styles.roomBadge}>{room.name}</span>}
        {!isOneOff && assignable === 'adults' && <span className={styles.constraintBadge}>Adults only</span>}
        {!isOneOff && assignable === 'children' && <span className={styles.constraintBadge}>Kids</span>}
        {assignedTo && (
          <span className={styles.assignedPill}>
            {assignedTo.image && <img src={assignedTo.image} alt={assignedTo.name} className={styles.assignedAvatar} />}
            for {assignedTo.name}
          </span>
        )}
      </div>

      {isDone && !isCompleting ? (
        <button className={styles.doneState} onClick={onUncomplete} title="Click to undo">
          {doneBy?.image ? (
            <img src={doneBy.image} alt={doneBy.name} className={styles.doneAvatar} />
          ) : (
            <span className={styles.doneTick}>✓</span>
          )}
          <span>Done{doneBy ? ` by ${doneBy.name}` : ''}</span>
        </button>
      ) : isOneOff ? (
        /* One-off: credit the assignee directly, no picker */
        <button className={styles.doneBtn} onClick={() => onComplete(chore.assigned_to)}>
          Mark done
        </button>
      ) : !isCompleting ? (
        <button className={styles.doneBtn} onClick={onStartComplete}>Mark done</button>
      ) : (
        <div className={styles.whoDidIt}>
          <span className={styles.whoLabel}>Who did it?</span>
          <div className={styles.avatars}>
            {eligibleMembers.map(m => (
              <button
                key={m.id}
                className={styles.avatarBtn}
                style={{ borderColor: memberColor(m.id).bg }}
                onClick={() => onComplete(m.id)}
                title={m.name}
              >
                {m.image ? (
                  <img src={m.image} alt={m.name} className={styles.avatarImg} />
                ) : (
                  <span className={styles.avatarFallback}>{m.name[0]}</span>
                )}
              </button>
            ))}
          </div>
          <button className={styles.cancelLink} onClick={onCancelComplete}>cancel</button>
        </div>
      )}
    </div>
  )
}
