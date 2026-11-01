import { useState, useEffect } from 'react'
import styles from './MealPlan.module.css'

const API = '/api/meals'
const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

export default function MealPlan() {
  const [plan, setPlan] = useState(null)
  const [loading, setLoading] = useState(false)
  const [loadingSlot, setLoadingSlot] = useState(null)
  const [rejectSlot, setRejectSlot] = useState(null)
  const [rejectReason, setRejectReason] = useState('')
  const [pushStatus, setPushStatus] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => { fetchPlan() }, [])

  async function fetchPlan() {
    const res = await fetch(`${API}/current`)
    const data = await res.json()
    setPlan(data)
  }

  async function generate() {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API}/generate`, { method: 'POST' })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.error || 'Generation failed')
      }
      const data = await res.json()
      setPlan(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function accept(slotId) {
    setLoadingSlot(slotId)
    await fetch(`${API}/${slotId}/accept`, { method: 'POST' })
    await fetchPlan()
    setLoadingSlot(null)
  }

  async function skip(slotId) {
    setLoadingSlot(slotId)
    await fetch(`${API}/${slotId}/skip`, { method: 'POST' })
    await fetchPlan()
    setLoadingSlot(null)
  }

  async function reject(slotId) {
    setLoadingSlot(slotId)
    await fetch(`${API}/${slotId}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: rejectReason }),
    })
    setRejectSlot(null)
    setRejectReason('')
    await fetchPlan()
    setLoadingSlot(null)
  }

  async function pushToTodoist() {
    setLoading(true)
    setPushStatus(null)
    try {
      const res = await fetch(`${API}/shopping-list`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || data.error)
      setPushStatus(`✅ ${data.items_added} items pushed to Todoist project "${data.project}"`)
    } catch (e) {
      setPushStatus(`❌ ${e.message}`)
    } finally {
      setLoading(false)
    }
  }

  async function reset() {
    await fetch(`${API}/reset`, { method: 'POST' })
    setPushStatus(null)
    setError(null)
    fetchPlan()
  }

  const slots = plan?.slots || []
  const hasSlots = slots.length > 0
  const allResolved = hasSlots && slots.every(s => s.status === 'accepted' || s.status === 'skipped')
  const pendingCount = slots.filter(s => s.status === 'pending' || s.status === 'generated').length

  // Group slots by day
  const byDay = DAYS.map(day => ({
    day,
    slots: slots.filter(s => s.day === day),
  }))

  return (
    <div className={styles.container}>
      <div className={styles.topBar}>
        <h2 className={styles.heading}>Meal Plan</h2>
        <div className={styles.topActions}>
          {hasSlots && (
            <button className={styles.btnSecondary} onClick={reset}>
              Start Over
            </button>
          )}
          {(!hasSlots || pendingCount > 0) && (
            <button className={styles.btnPrimary} onClick={generate} disabled={loading}>
              {loading ? 'Generating…' : hasSlots ? `Regenerate ${pendingCount} pending` : '✨ Generate Meal Plan'}
            </button>
          )}
          {allResolved && (
            <button className={styles.btnSuccess} onClick={pushToTodoist} disabled={loading}>
              {loading ? 'Pushing…' : '🛒 Push to Todoist'}
            </button>
          )}
        </div>
      </div>

      {error && <p className={styles.error}>{error}</p>}
      {pushStatus && <p className={styles.pushStatus}>{pushStatus}</p>}

      {!hasSlots && !loading && (
        <div className={styles.empty}>
          <p>No meal plan yet for this week.</p>
          <p>Click <strong>Generate Meal Plan</strong> to get started.</p>
        </div>
      )}

      {loading && !hasSlots && (
        <div className={styles.empty}>
          <p className={styles.loadingText}>🤖 Generating your meal plan…</p>
        </div>
      )}

      {hasSlots && (
        <div className={styles.planGrid}>
          {byDay.map(({ day, slots: daySlots }) => (
            <div key={day} className={styles.dayColumn}>
              <h3 className={styles.dayHeading}>
                {day}
                {daySlots[0] && <span className={styles.dayDate}>{daySlots[0].display_date}</span>}
                {daySlots[0]?.calendar_events?.length > 0 && (
                  <span className={styles.calendarEvents} title={daySlots[0].calendar_events.join(', ')}>
                    📅 {daySlots[0].calendar_events.join(', ')}
                  </span>
                )}
              </h3>
              {daySlots.map(slot => (
                <MealCard
                  key={slot.id}
                  slot={slot}
                  isLoading={loadingSlot === slot.id}
                  isRejecting={rejectSlot === slot.id}
                  rejectReason={rejectReason}
                  onAccept={() => accept(slot.id)}
                  onSkip={() => skip(slot.id)}
                  onRejectOpen={() => { setRejectSlot(slot.id); setRejectReason('') }}
                  onRejectCancel={() => setRejectSlot(null)}
                  onRejectConfirm={() => reject(slot.id)}
                  onRejectReasonChange={setRejectReason}
                />
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function MealCard({ slot, isLoading, isRejecting, rejectReason,
  onAccept, onSkip, onRejectOpen, onRejectCancel, onRejectConfirm, onRejectReasonChange }) {

  const statusClass = {
    accepted: styles.cardAccepted,
    skipped: styles.cardSkipped,
    generated: styles.cardGenerated,
    pending: styles.cardPending,
  }[slot.status] || ''

  return (
    <div className={`${styles.mealCard} ${statusClass}`}>
      <div className={styles.mealType}>{slot.meal_type}</div>

      {slot.status === 'skipped' && (
        <p className={styles.skippedLabel}>Not required</p>
      )}

      {slot.status === 'pending' && (
        <p className={styles.pendingLabel}>Waiting to generate…</p>
      )}

      {(slot.status === 'generated' || slot.status === 'accepted') && slot.meal && (
        <>
          <h4 className={styles.mealName}>{slot.meal.name}</h4>
          <p className={styles.mealDesc}>{slot.meal.description}</p>
          {slot.meal.prep_minutes && (
            <p className={styles.prepTime}>⏱ {slot.meal.prep_minutes} mins</p>
          )}
          {slot.meal.ingredients?.length > 0 && (
            <ul className={styles.ingredients}>
              {slot.meal.ingredients.map((ing, i) => (
                <li key={i}>{ing.item} <span className={styles.qty}>— {ing.quantity}</span></li>
              ))}
            </ul>
          )}
        </>
      )}

      {isLoading && <p className={styles.loadingText}>Working…</p>}

      {slot.status === 'generated' && !isLoading && !isRejecting && (
        <div className={styles.cardActions}>
          <button className={styles.btnAccept} onClick={onAccept}>Accept</button>
          <button className={styles.btnReject} onClick={onRejectOpen}>Reject</button>
          <button className={styles.btnSkip} onClick={onSkip}>Not needed</button>
        </div>
      )}

      {isRejecting && (
        <div className={styles.rejectForm}>
          <input
            className={styles.rejectInput}
            placeholder="Why are you rejecting this? (helps AI improve)"
            value={rejectReason}
            onChange={e => onRejectReasonChange(e.target.value)}
            autoFocus
          />
          <div className={styles.cardActions}>
            <button className={styles.btnReject} onClick={onRejectConfirm} disabled={!rejectReason.trim()}>
              Regenerate
            </button>
            <button className={styles.btnSkip} onClick={onRejectCancel}>Cancel</button>
          </div>
        </div>
      )}

      {slot.status === 'accepted' && (
        <span className={styles.acceptedBadge}>✓ Accepted</span>
      )}
    </div>
  )
}
