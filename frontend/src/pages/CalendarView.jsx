import { useState, useEffect, useCallback } from 'react'
import styles from './CalendarView.module.css'
import Chores from './Chores.jsx'
import Inventory from '../components/Inventory.jsx'
import Reminders from '../components/Reminders.jsx'
import { memberColor, eventTitleWithoutMember } from '../memberColors.js'

const MEMBERS_API = '/api/members'
const MEALS_API = '/api/meals'
const CAL_API = '/api/calendar'

// Calendar runs 07:00 – 22:00. Per-hour pixel height is derived per-render
// (compact on desktop, taller on mobile) inside the component.
const DAY_START_HOUR = 7
const DAY_END_HOUR = 22
const HOUR_HEIGHT = 28  // desktop px per hour

// ─── Helpers ──────────────────────────────────────────────────────────────────

function parseLocalTime(isoString) {
  // isoString like "2026-11-02T14:30:00+00:00" or "...Z"
  const d = new Date(isoString)
  return d.getHours() + d.getMinutes() / 60  // fractional hour in local time
}

function formatTime(isoString) {
  if (!isoString) return ''
  const d = new Date(isoString)
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false })
}

// ─── Top-level page ───────────────────────────────────────────────────────────

export default function CalendarView() {
  const [week, setWeek] = useState(null)
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [loadingSlot, setLoadingSlot] = useState(null)
  const [rejectSlot, setRejectSlot] = useState(null)
  const [rejectReason, setRejectReason] = useState('')
  const [pushStatus, setPushStatus] = useState(null)
  const [error, setError] = useState(null)
  const [selectedSlot, setSelectedSlot] = useState(null) // for detail popover
  const [members, setMembers] = useState([])
  const [now, setNow] = useState(new Date())
  const [weekStart, setWeekStart] = useState(null) // YYYY-MM-DD Monday being viewed; null = this week
  const [selectedDate, setSelectedDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [filterMember, setFilterMember] = useState(null) // member id to filter the whole page by, or null
  const [assignEvent, setAssignEvent] = useState(null) // event being re-assigned, or null
  // Mobile (e.g. Android Chrome): single-day view + taller grid. Tracks viewport.
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia('(max-width: 768px)').matches
  )

  // Keep the clock ticking for the header
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  // Track viewport for the mobile single-day layout
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 768px)')
    const handler = e => setIsMobile(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

  useEffect(() => {
    fetch(`${MEMBERS_API}/`).then(r => r.json()).then(setMembers).catch(() => {})
  }, [])

  const fetchWeek = useCallback(async (ws) => {
    // Only show the full-screen loader on the very first load (no week yet).
    // Subsequent fetches keep the current week on screen and show a subtle
    // "refreshing" indicator instead.
    setWeek(prev => {
      if (prev) setRefreshing(true)
      else setLoading(true)
      return prev
    })
    try {
      const url = ws ? `${CAL_API}/week?week_start=${ws}` : `${CAL_API}/week`
      const res = await fetch(url)
      const data = await res.json()
      setWeek(data)
      setWeekStart(data.week_start)
    } catch {
      setError('Could not load calendar data.')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  // Navigate weeks by offsetting both week_start and the selected day by ±7 days
  function shiftWeek(deltaDays) {
    if (!weekStart) return
    const d = new Date(weekStart + 'T00:00:00')
    d.setDate(d.getDate() + deltaDays)
    fetchWeek(d.toISOString().slice(0, 10))
    // Keep the same weekday selected in the new week
    const sel = new Date(selectedDate + 'T00:00:00')
    sel.setDate(sel.getDate() + deltaDays)
    setSelectedDate(sel.toISOString().slice(0, 10))
    setSelectedSlot(null)
  }

  // Save the local assignment override for an event, then refetch.
  // members: array of ids, or null to reset to automatic (name/colour).
  async function saveAssignment(eventId, members) {
    await fetch('/api/assignments/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_id: eventId, members }),
    })
    setAssignEvent(null)
    fetchWeek(weekStart)
  }

  function goToday() {
    const today = new Date().toISOString().slice(0, 10)
    setSelectedDate(today)
    fetchWeek(week?.this_week_start)
    setSelectedSlot(null)
  }

  useEffect(() => { fetchWeek() }, [fetchWeek])

  // Propose meals. With no argument: the whole (next) week. With a date:
  // just that one day's dinner.
  async function generate(forDate) {
    setGenerating(true)
    setError(null)
    try {
      const res = await fetch(`${MEALS_API}/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(forDate ? { date: forDate } : {}),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.error || 'Generation failed')
      }
      const data = await res.json()
      if (forDate) {
        // Stay on the current view; just refresh to show the new day's meal
        await fetchWeek(weekStart)
      } else {
        // Jump to the week the meal plan covers so the new meals are visible
        const mealWeekStart = data.slots?.length ? [...data.slots].sort((a, b) => a.date.localeCompare(b.date))[0].date : null
        await fetchWeek(mealWeekStart || weekStart)
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setGenerating(false)
    }
  }

  // Patch a single slot in the week state without refetching the whole week.
  function patchSlot(updatedSlot) {
    setWeek(w => ({
      ...w,
      days: w.days.map(d => ({
        ...d,
        slots: d.slots.map(s => s.id === updatedSlot.id ? { ...s, ...updatedSlot } : s),
      })),
    }))
    // Keep the open detail panel in sync if it's showing this slot
    setSelectedSlot(sel => (sel && sel.id === updatedSlot.id ? { ...sel, ...updatedSlot } : sel))
  }

  async function accept(slotId) {
    setLoadingSlot(slotId)
    const res = await fetch(`${MEALS_API}/${slotId}/accept`, { method: 'POST' })
    const updated = await res.json()
    patchSlot(updated)
    setLoadingSlot(null)
  }

  async function skip(slotId) {
    setLoadingSlot(slotId)
    const res = await fetch(`${MEALS_API}/${slotId}/skip`, { method: 'POST' })
    const updated = await res.json()
    patchSlot(updated)
    setLoadingSlot(null)
  }

  async function reject(slotId, reason) {
    setLoadingSlot(slotId)
    const res = await fetch(`${MEALS_API}/${slotId}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    })
    const updated = await res.json()
    patchSlot(updated)
    setRejectSlot(null)
    setRejectReason('')
    setLoadingSlot(null)
  }

  async function reset() {
    await fetch(`${MEALS_API}/reset`, { method: 'POST' })
    setPushStatus(null)
    setError(null)
    setSelectedSlot(null)
    await fetchWeek(weekStart)
  }

  function patchLunch(updatedLunch) {
    setWeek(w => ({
      ...w,
      lunch_ideas: w.lunch_ideas.map(l => l.id === updatedLunch.id ? { ...l, ...updatedLunch } : l),
    }))
  }

  async function acceptLunch(lunchId) {
    const res = await fetch(`${MEALS_API}/lunch/${lunchId}/accept`, { method: 'POST' })
    const updated = await res.json()
    patchLunch(updated)
  }

  async function rejectLunch(lunchId, reason) {
    const res = await fetch(`${MEALS_API}/lunch/${lunchId}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    })
    const updated = await res.json()
    patchLunch(updated)
  }

  async function pushToTodoist() {
    setGenerating(true)
    setPushStatus(null)
    try {
      const res = await fetch(`${MEALS_API}/shopping-list`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || data.error)
      const skipped = data.already_have?.length
        ? ` (${data.already_have.length} already in stock, skipped)`
        : ''
      if (data.items_added === 0) {
        setPushStatus(`✅ ${data.message || 'Nothing to buy — all in stock.'}`)
      } else {
        setPushStatus(`✅ ${data.items_added} items pushed to Todoist: "${data.project}"${skipped}`)
      }
    } catch (e) {
      setPushStatus(`❌ ${e.message}`)
    } finally {
      setGenerating(false)
    }
  }

  const allSlots = week?.days?.flatMap(d => d.slots) ?? []
  const lunchIdeas = week?.lunch_ideas ?? []
  const hasSlots = week?.has_slots
  const pendingCount = allSlots.filter(s => s.status === 'pending' || s.status === 'generated').length
  const dinnersResolved = hasSlots && allSlots.every(s => s.status === 'accepted' || s.status === 'skipped')
  const anyLunchAccepted = lunchIdeas.some(l => l.status === 'accepted')
  // Ready to shop once dinners are sorted and at least one lunch is picked
  const allResolved = dinnersResolved && anyLunchAccepted

  const memberById = Object.fromEntries(members.map(m => [m.id, m]))

  // On mobile: taller grid so every 30-min increment is visible, and show only
  // the selected day's column. On desktop: compact 28px/hr, all 7 days.
  const hourHeight = isMobile ? 64 : HOUR_HEIGHT
  const totalHeight = (DAY_END_HOUR - DAY_START_HOUR) * hourHeight
  const topFor = h => Math.max(0, (h - DAY_START_HOUR) * hourHeight)
  const heightFor = (s, e) => Math.max(18, (e - s) * hourHeight)
  // Half-hour grid lines (mobile shows them; desktop just hour lines)
  const halfHours = []
  for (let h = DAY_START_HOUR; h < DAY_END_HOUR; h += 0.5) halfHours.push(h)
  const allDays = week?.days ?? []
  const shownDays = isMobile ? allDays.filter(d => d.date === selectedDate) : allDays

  // Day navigation (mobile): step the selected day by ±1, crossing weeks as needed
  function shiftDay(delta) {
    const d = new Date(selectedDate + 'T00:00:00')
    d.setDate(d.getDate() + delta)
    const iso = d.toISOString().slice(0, 10)
    setSelectedDate(iso)
    // If we've left the loaded week, fetch the week containing the new day
    if (week?.days && !week.days.some(x => x.date === iso)) {
      const monday = new Date(d); monday.setDate(d.getDate() - ((d.getDay() + 6) % 7))
      fetchWeek(monday.toISOString().slice(0, 10))
    }
    setSelectedSlot(null)
  }

  const todayISO = new Date().toISOString().slice(0, 10)
  const viewingToday = selectedDate === todayISO
  const selectedLabel = new Date(selectedDate + 'T00:00:00').toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })

  return (
    <div className={`${styles.page} ${viewingToday ? '' : styles.pageOffToday}`}>
      {/* Off-today banner */}
      {!viewingToday && (
        <div className={styles.offTodayBanner}>
          <span>Viewing <strong>{selectedLabel}</strong> — not today</span>
          <button className={styles.backToTodayBtn} onClick={goToday}>Back to today</button>
        </div>
      )}

      {/* ── Date/time banner ── */}
      <div className={styles.dateBanner}>
        <div className={styles.dateBlock}>
          <span className={styles.bannerDay}>
            {now.toLocaleDateString('en-GB', { weekday: 'long' })}
          </span>
          <span className={styles.bannerDate}>
            {now.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}
          </span>
        </div>
        <span className={styles.bannerClock}>
          {now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}
        </span>
      </div>

      {/* ── Controls row ── */}
      <div className={styles.pageHeader}>
        {/* Week navigation */}
        <div className={styles.weekNav}>
          <button className={styles.todayBtn} onClick={goToday}>Today</button>
          <span className={styles.weekLabel}>
            {isMobile
              ? new Date(selectedDate + 'T00:00:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
              : (week?.days?.length ? `${week.days[0].display_date} – ${week.days[6].display_date}` : '')}
            {!isMobile && weekStart && week?.this_week_start === weekStart && <span className={styles.thisWeekTag}>This week</span>}
          </span>
        </div>

        {/* Member avatar pills — click to filter the whole page */}
        <div className={styles.memberPills} data-testid="member-pills">
          {members.map(m => {
            const active = filterMember === m.id
            const dimmed = filterMember && !active
            return (
              <button
                key={m.id}
                className={`${styles.memberPill} ${active ? styles.pillActive : ''} ${dimmed ? styles.pillDimmed : ''}`}
                style={{ background: memberColor(m.id).bg, color: memberColor(m.id).ink }}
                onClick={() => setFilterMember(active ? null : m.id)}
                title={active ? `Clear ${m.name} filter` : `Show only ${m.name}`}
              >
                {m.image
                  ? <img src={m.image} alt={m.name} className={styles.pillAvatar} />
                  : <span className={styles.pillDot} style={{ background: memberColor(m.id).ink }} />}
                {m.name}
              </button>
            )
          })}
          {filterMember && (
            <button className={styles.clearFilterBtn} onClick={() => setFilterMember(null)}>
              Show all ✕
            </button>
          )}
        </div>

        <div className={styles.mealActions}>
          {hasSlots && (
            <button className={styles.btnSecondary} onClick={reset} disabled={generating}>
              Start Over
            </button>
          )}
          {allResolved && (
            <button className={styles.btnSuccess} onClick={pushToTodoist} disabled={generating}>
              {generating ? 'Pushing…' : 'Push to Todoist'}
            </button>
          )}
          {(!hasSlots || pendingCount > 0) && (
            <button className={styles.btnPrimary} onClick={() => generate()} disabled={generating}>
              {generating ? 'Proposing…' : hasSlots ? `Regenerate ${pendingCount} pending` : 'Propose meals for week'}
            </button>
          )}
          <button className={styles.btnSecondary} onClick={() => generate(selectedDate)} disabled={generating}>
            Propose a meal for {selectedDate === todayISO ? 'today' : 'this day'}
          </button>
        </div>
      </div>

      {error && <p className={styles.errorBanner}>{error}</p>}
      {pushStatus && <p className={styles.successBanner}>{pushStatus}</p>}

      {/* Thin progress bar during background refreshes */}
      {refreshing && <div className={styles.progressBar} />}

      {loading && !week ? (
        <p className={styles.loadingText}>Loading…</p>
      ) : (
        <div className={styles.calendarAndDetail}>
          <button
            className={styles.weekScrollBtn}
            onClick={() => (isMobile ? shiftDay(-1) : shiftWeek(-7))}
            title={isMobile ? 'Previous day' : 'Previous week'}
          >
            <span>◀</span>
          </button>
          <div className={`${styles.calendarOuter} ${refreshing ? styles.calendarRefreshing : ''}`}>
            {/* ── Header + timed grid ── */}
            <div
              className={styles.calendarGrid}
              data-testid="calendar-grid"
              data-day-count={shownDays.length}
              style={{ gridTemplateColumns: `52px repeat(${shownDays.length || 7}, 1fr)` }}
            >

              {/* Time gutter header cell */}
              <div className={styles.timeGutter} />

              {/* Day headers */}
              {shownDays.map(day => {
                const isToday = day.date === new Date().toISOString().slice(0, 10)
                const isSelected = day.date === selectedDate
                return (
                  <div
                    key={`hdr-${day.date}`}
                    data-testid="day-header"
                    className={`${styles.dayWrapper} ${isToday ? styles.today : ''} ${isSelected ? styles.selected : ''}`}
                  >
                    <button className={styles.dayHeader} onClick={() => setSelectedDate(day.date)}>
                      <span className={styles.dayName}>{day.day}</span>
                      <span className={styles.dayDate}>{day.display_date}</span>
                      {isToday && <span className={styles.todayPip}>today</span>}
                    </button>
                  </div>
                )
              })}

              {/* All-day strip gutter */}
              <div className={styles.allDayGutter}>all‑day</div>

              {/* All-day strip per day: all-day events + dinner chip */}
              {shownDays.map(day => {
                const allDayEvents = (day.calendar_events ?? [])
                  .filter(e => e.all_day)
                  .filter(e => !filterMember || (e.assigned_to || []).includes(filterMember))
                const dinnerSlot = filterMember ? null : day.slots.find(s => s.meal_type === 'dinner')
                return (
                  <div key={`allday-${day.date}`} className={styles.allDayStrip}>
                    {allDayEvents.map((ev, i) => {
                      const assignees = (ev.assigned_to || []).map(id => memberById[id]).filter(Boolean)
                      const single = assignees.length === 1 ? assignees[0] : null
                      const tint = single ? memberColor(single.id) : null
                      return (
                        <button
                          key={ev.id || i}
                          className={styles.allDayEvent}
                          style={tint ? { background: tint.bg, color: tint.ink } : undefined}
                          onClick={() => setAssignEvent(ev)}
                          title="Click to change who this is for"
                        >
                          {assignees.length > 0 && (
                            <span className={styles.eventAvatarStack}>
                              {assignees.map(m => m.image
                                ? <img key={m.id} src={m.image} alt={m.name} className={styles.allDayAvatar} />
                                : <span key={m.id} className={styles.eventDot} style={{ background: memberColor(m.id).ink }} />)}
                            </span>
                          )}
                          <span className={styles.eventName}>
                            {assignees.length ? eventTitleWithoutMember(ev.summary) : ev.summary}
                          </span>
                        </button>
                      )
                    })}
                    {dinnerSlot && (
                      <MealChip
                        slot={dinnerSlot}
                        isLoading={loadingSlot === dinnerSlot.id}
                        onClick={() => setSelectedSlot(selectedSlot?.id === dinnerSlot.id ? null : dinnerSlot)}
                        isSelected={selectedSlot?.id === dinnerSlot.id}
                      />
                    )}
                  </div>
                )
              })}

              {/* Time gutter column (hour labels; mobile also shows half-hours) */}
              <div className={styles.timeGutterCol} style={{ height: totalHeight }}>
                {halfHours.map(h => {
                  const isHour = Number.isInteger(h)
                  if (!isMobile && !isHour) return null
                  const hh = Math.floor(h)
                  const mm = isHour ? '00' : '30'
                  return (
                    <div
                      key={h}
                      className={`${styles.hourLabel} ${!isHour ? styles.halfHourLabel : ''}`}
                      style={{ top: topFor(h) }}
                    >
                      {String(hh).padStart(2, '0')}:{mm}
                    </div>
                  )
                })}
              </div>

              {/* Timed day columns */}
              {shownDays.map(day => {
                const timedEvents = (day.calendar_events ?? [])
                  .filter(e => !e.all_day)
                  .filter(e => !filterMember || (e.assigned_to || []).includes(filterMember))
                return (
                  <div key={`timed-${day.date}`} className={styles.dayColumn} style={{ height: totalHeight }}>
                    {halfHours.map(h => {
                      const isHour = Number.isInteger(h)
                      if (!isMobile && !isHour) return null
                      return (
                        <div
                          key={h}
                          className={`${styles.hourLine} ${!isHour ? styles.halfHourLine : ''}`}
                          style={{ top: topFor(h) }}
                        />
                      )
                    })}
                    {timedEvents.map((ev, i) => {
                      const startH = parseLocalTime(ev.start_time)
                      const endH = parseLocalTime(ev.end_time)
                      const assignees = (ev.assigned_to || []).map(id => memberById[id]).filter(Boolean)
                      const single = assignees.length === 1 ? assignees[0] : null
                      const tint = single ? memberColor(single.id) : null
                      return (
                        <button
                          key={ev.id || i}
                          className={styles.timedEvent}
                          style={{
                            top: topFor(startH),
                            height: heightFor(startH, endH),
                            ...(tint ? { background: tint.bg } : {}),
                          }}
                          title={`${ev.summary} — click to change who this is for`}
                          onClick={() => setAssignEvent(ev)}
                        >
                          {assignees.length > 0 && (
                            <span className={styles.eventAvatarCorner}>
                              {assignees.map(m => m.image
                                ? <img key={m.id} src={m.image} alt={m.name} className={styles.cornerAvatar} />
                                : <span key={m.id} className={styles.cornerDot} style={{ background: memberColor(m.id).ink }} />)}
                            </span>
                          )}
                          <span className={styles.timedEventTime} style={tint ? { color: tint.ink } : undefined}>
                            {formatTime(ev.start_time)}
                          </span>
                          <span className={styles.timedEventName} style={tint ? { color: tint.ink } : undefined}>
                            {assignees.length ? eventTitleWithoutMember(ev.summary) : ev.summary}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                )
              })}
            </div>
          </div>
          <button
            className={styles.weekScrollBtn}
            onClick={() => (isMobile ? shiftDay(1) : shiftWeek(7))}
            title={isMobile ? 'Next day' : 'Next week'}
          >
            <span>▶</span>
          </button>

          {/* ── Meal detail panel (right side) ── */}
          {selectedSlot && (
            <MealDetail
              slot={selectedSlot}
              isLoading={loadingSlot === selectedSlot.id}
              isRejecting={rejectSlot === selectedSlot.id}
              rejectReason={rejectReason}
              onAccept={() => accept(selectedSlot.id)}
              onSkip={() => skip(selectedSlot.id)}
              onRejectOpen={() => { setRejectSlot(selectedSlot.id); setRejectReason('') }}
              onRejectCancel={() => setRejectSlot(null)}
              onRejectConfirm={() => reject(selectedSlot.id, rejectReason)}
              onRejectReasonChange={setRejectReason}
              onClose={() => setSelectedSlot(null)}
            />
          )}
        </div>
      )}

      {/* ── Lunch ideas + Chores, below the calendar ── */}
      {!loading && (
        <div className={styles.belowCalendar}>
          {(week?.lunch_ideas?.length > 0) && (
            <LunchIdeas
              ideas={week.lunch_ideas}
              onAccept={acceptLunch}
              onReject={rejectLunch}
            />
          )}
          <div className={styles.choresSection}>
            <Reminders date={selectedDate} filterMember={filterMember} />
          </div>
          <div className={styles.choresSection}>
            <Chores filterMember={filterMember} selectedDate={selectedDate} />
          </div>
          <div className={styles.choresSection}>
            <Inventory />
          </div>
        </div>
      )}

      {/* ── Event assignment picker ── */}
      {assignEvent && (
        <AssignModal
          event={assignEvent}
          members={members}
          onSave={members => saveAssignment(assignEvent.id, members)}
          onReset={() => saveAssignment(assignEvent.id, null)}
          onClose={() => setAssignEvent(null)}
        />
      )}
    </div>
  )
}

// ─── Event assignment modal (multi-select) ───────────────────────────────────

function AssignModal({ event, members, onSave, onReset, onClose }) {
  const [selected, setSelected] = useState(() => new Set(event.assigned_to || []))

  function toggle(id) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  return (
    <div className={styles.assignOverlay} onClick={onClose}>
      <div className={styles.assignModal} data-testid="event-modal" onClick={e => e.stopPropagation()}>
        <div className={styles.assignHeader}>
          <span className={styles.assignTitle}>{event.summary}</span>
          <button className={styles.closeBtn} onClick={onClose}>✕</button>
        </div>

        {/* Event time + description */}
        <div className={styles.eventMeta}>
          <span className={styles.eventTime}>
            {event.all_day
              ? 'All day'
              : event.start_time
                ? `${formatTime(event.start_time)}${event.end_time ? ` – ${formatTime(event.end_time)}` : ''}`
                : ''}
          </span>
          {event.description && <p className={styles.eventDesc}>{event.description}</p>}
        </div>

        <p className={styles.assignLabel}>Who is this for? (select any number)</p>
        <div className={styles.assignOptions}>
          {members.map(m => {
            const on = selected.has(m.id)
            return (
              <button
                key={m.id}
                className={`${styles.assignOption} ${on ? styles.assignOptionActive : ''}`}
                style={on ? { background: memberColor(m.id).bg, color: memberColor(m.id).ink } : undefined}
                onClick={() => toggle(m.id)}
              >
                {m.image
                  ? <img src={m.image} alt={m.name} className={styles.assignAvatar} />
                  : <span className={styles.pillDot} style={{ background: memberColor(m.id).ink }} />}
                {m.name}
                {on && <span className={styles.assignCheck}>✓</span>}
              </button>
            )
          })}
        </div>
        <div className={styles.assignActions}>
          <button className={styles.btnPrimary} onClick={() => onSave([...selected])}>
            Save
          </button>
          <button className={styles.btnSecondary} onClick={() => onSave([])}>
            Nobody
          </button>
          <button className={styles.assignReset} onClick={onReset}>
            Reset to automatic
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Meal chip (compact, shown in all-day strip) ──────────────────────────────

function MealChip({ slot, isLoading, onClick, isSelected }) {
  if (!slot) return null

  const chipClass = {
    accepted: styles.chipAccepted,
    skipped:  styles.chipSkipped,
    generated: styles.chipGenerated,
    pending:  styles.chipPending,
  }[slot.status] || ''

  const label = isLoading
    ? '…'
    : slot.status === 'skipped'
    ? `${slot.meal_type}: skip`
    : slot.status === 'pending'
    ? `${slot.meal_type}: pending`
    : slot.meal?.name || slot.meal_type

  return (
    <button
      className={`${styles.mealChip} ${chipClass} ${isSelected ? styles.chipSelected : ''}`}
      onClick={onClick}
      title={slot.meal?.name}
    >
      <span className={styles.chipType}>🍽️</span>
      <span className={styles.chipName}>{label}</span>
      {slot.status === 'accepted' && <span className={styles.chipTick}>✓</span>}
    </button>
  )
}

// ─── Meal detail panel (shown below the grid when a chip is clicked) ──────────

function MealDetail({ slot, isLoading, isRejecting, rejectReason,
  onAccept, onSkip, onRejectOpen, onRejectCancel, onRejectConfirm, onRejectReasonChange, onClose }) {

  const [showIngredients, setShowIngredients] = useState(false)

  return (
    <div className={styles.detailPanel}>
      <div className={styles.detailHeader}>
        <div>
          <span className={styles.detailMealType}>{slot.meal_type} — {slot.day} {slot.display_date}</span>
          {slot.meal && <h3 className={styles.detailMealName}>{slot.meal.name}</h3>}
        </div>
        <button className={styles.closeBtn} onClick={onClose}>✕</button>
      </div>

      {slot.status === 'skipped' && <p className={styles.mutedText}>Marked as not needed.</p>}
      {slot.status === 'pending' && <p className={styles.mutedText}>Waiting to be generated.</p>}

      {slot.meal && (
        <>
          <p className={styles.detailDesc}>{slot.meal.description}</p>
          {slot.meal.prep_minutes && (
            <p className={styles.detailPrep}>⏱ {slot.meal.prep_minutes} mins</p>
          )}
          <button
            className={styles.ingredientsToggle}
            onClick={() => setShowIngredients(v => !v)}
          >
            {showIngredients ? 'Hide ingredients ▲' : `Show ingredients (${slot.meal.ingredients?.length ?? 0}) ▼`}
          </button>
          {showIngredients && slot.meal.ingredients?.length > 0 && (
            <ul className={styles.ingredients}>
              {slot.meal.ingredients.map((ing, i) => (
                <li key={i}>{ing.item} <span className={styles.qty}>— {ing.quantity}</span></li>
              ))}
            </ul>
          )}
        </>
      )}

      {isLoading && <p className={styles.mutedText}>Working…</p>}

      {slot.status === 'generated' && !isLoading && !isRejecting && (
        <div className={styles.detailActions}>
          <button className={styles.btnAccept} onClick={onAccept}>✓ Accept</button>
          <button className={styles.btnReject} onClick={onRejectOpen}>✕ Reject</button>
          <button className={styles.btnSkip} onClick={onSkip}>Not needed</button>
        </div>
      )}

      {isRejecting && (
        <div className={styles.rejectForm}>
          <input
            className={styles.rejectInput}
            placeholder="Why? (helps the AI improve next time)"
            value={rejectReason}
            onChange={e => onRejectReasonChange(e.target.value)}
            autoFocus
          />
          <div className={styles.detailActions}>
            <button className={styles.btnReject} onClick={onRejectConfirm} disabled={!rejectReason.trim()}>
              Regenerate
            </button>
            <button className={styles.btnSkip} onClick={onRejectCancel}>Cancel</button>
          </div>
        </div>
      )}

      {slot.status === 'accepted' && (
        <p className={styles.acceptedText}>✓ Accepted</p>
      )}
    </div>
  )
}

// ─── Lunch ideas (not day-aligned) ────────────────────────────────────────────

function LunchIdeas({ ideas, onAccept, onReject }) {
  const [rejectingId, setRejectingId] = useState(null)
  const [reason, setReason] = useState('')

  return (
    <section className={styles.lunchSection}>
      <h2 className={styles.lunchHeading}>🥗 Lunch Ideas <span className={styles.lunchSub}>for the week — pick and mix</span></h2>
      <div className={styles.lunchGrid}>
        {ideas.map(idea => (
          <div
            key={idea.id}
            className={`${styles.lunchCard} ${idea.status === 'accepted' ? styles.lunchAccepted : ''}`}
          >
            <div className={styles.lunchTop}>
              <span className={styles.lunchName}>{idea.name}</span>
              {idea.prep_minutes && <span className={styles.lunchPrep}>⏱ {idea.prep_minutes}m</span>}
            </div>
            <p className={styles.lunchDesc}>{idea.description}</p>

            {idea.ingredients?.length > 0 && (
              <ul className={styles.lunchIngredients}>
                {idea.ingredients.map((ing, i) => (
                  <li key={i}>{ing.item} <span className={styles.qty}>— {ing.quantity}</span></li>
                ))}
              </ul>
            )}

            {rejectingId === idea.id ? (
              <div className={styles.rejectForm}>
                <input
                  className={styles.rejectInput}
                  placeholder="Why? (helps the AI improve)"
                  value={reason}
                  onChange={e => setReason(e.target.value)}
                  autoFocus
                />
                <div className={styles.detailActions}>
                  <button
                    className={styles.btnReject}
                    disabled={!reason.trim()}
                    onClick={() => { onReject(idea.id, reason); setRejectingId(null); setReason('') }}
                  >
                    Regenerate
                  </button>
                  <button className={styles.btnSkip} onClick={() => { setRejectingId(null); setReason('') }}>
                    Cancel
                  </button>
                </div>
              </div>
            ) : idea.status === 'accepted' ? (
              <p className={styles.acceptedText}>✓ On the shopping list</p>
            ) : (
              <div className={styles.detailActions}>
                <button className={styles.btnAccept} onClick={() => onAccept(idea.id)}>✓ Accept</button>
                <button className={styles.btnReject} onClick={() => setRejectingId(idea.id)}>✕ Reject</button>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
