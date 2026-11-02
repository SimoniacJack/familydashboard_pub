import { useState, useEffect, useCallback } from 'react'
import styles from './CalendarView.module.css'
import Chores from './Chores.jsx'
import Reminders from '../components/Reminders.jsx'
import DraftReviewPanel from '../components/DraftReviewPanel.jsx'
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
  const [draft, setDraft] = useState(null) // {draft, used_gpt} once /draft returns -> opens review panel
  const [lunchCount, setLunchCount] = useState(3) // how many lunch ideas to generate
  const [generatingLunches, setGeneratingLunches] = useState(false)
  const [error, setError] = useState(null)
  const [selectedSlot, setSelectedSlot] = useState(null) // for detail popover
  const [mealStatus, setMealStatus] = useState({}) // mealId -> {makeable, ingredients:[{id,name,quantity,state}]}
  const [invItems, setInvItems] = useState([]) // flat inventory list for the match picker
  const [invLocations, setInvLocations] = useState([])
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

  // Per-accepted-meal inventory/shopping breakdown for the badges + detail.
  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${MEALS_API}/status`)
      const data = await res.json()
      setMealStatus(data.meals || {})
    } catch { /* badges just won't show; non-fatal */ }
  }, [])

  // Flat inventory list (+ locations) for the ingredient "match to inventory" picker.
  const fetchInventory = useCallback(async () => {
    try {
      const res = await fetch('/api/inventory/')
      const data = await res.json()
      setInvLocations(data.locations || [])
      const flat = []
      for (const loc of Object.keys(data.items || {})) {
        for (const it of data.items[loc]) flat.push({ id: it.id, name: it.name, location: loc })
      }
      flat.sort((a, b) => a.name.localeCompare(b.name))
      setInvItems(flat)
    } catch { /* picker just shows empty; non-fatal */ }
  }, [])

  // Apply a refreshed single-meal status returned by an ingredient edit, and
  // refresh the inventory picker (an add/consume may have changed stock).
  const applyStatus = useCallback((st) => {
    if (!st?.meal_key) return
    setMealStatus(m => ({ ...m, [st.meal_key]: { makeable: st.makeable, ingredients: st.ingredients } }))
    fetchInventory()
  }, [fetchInventory])

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

  // Refresh the inventory/shopping breakdown whenever the week (and its
  // accepted meals) may have changed.
  useEffect(() => { fetchStatus(); fetchInventory() }, [fetchStatus, fetchInventory, weekStart, week])

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
    const data = await res.json()
    patchSlot(data.slot || data)
    if (data.draft?.length) {
      setDraft({ draft: data.draft, used_gpt: data.used_gpt, kind: 'dinner', id: slotId })
    } else {
      setPushStatus('✅ Meal accepted — stock covers it, nothing to buy.')
    }
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

  async function generateLunches(count) {
    setGeneratingLunches(true)
    setError(null)
    try {
      const res = await fetch(`${MEALS_API}/lunch/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ count }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || 'Lunch generation failed')
      setWeek(w => ({ ...w, lunch_ideas: data.lunch_ideas || [] }))
    } catch (e) {
      setError(e.message)
    } finally {
      setGeneratingLunches(false)
    }
  }

  async function acceptLunch(lunchId) {
    const res = await fetch(`${MEALS_API}/lunch/${lunchId}/accept`, { method: 'POST' })
    const data = await res.json()
    patchLunch(data.idea || data)
    if (data.draft?.length) {
      setDraft({ draft: data.draft, used_gpt: data.used_gpt, kind: 'lunch', id: lunchId })
    } else {
      setPushStatus('✅ Lunch accepted — stock covers it, nothing to buy.')
    }
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

  // Step 1 of pushing the shopping list: reserve stock against accepted meals
  // and fetch the DRAFT of what looks missing. Writes nothing to Todoist yet —
  // the review panel does that on confirm.
  async function pushToTodoist() {
    setGenerating(true)
    setPushStatus(null)
    try {
      const res = await fetch('/api/shopping/draft', { method: 'POST' })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`)
      const reserved = data.counts?.reserved || 0
      if (!data.draft.length) {
        setPushStatus(
          `✅ Stock covers every meal${reserved ? ` — ${reserved} items reserved` : ''}. Nothing to buy.`
        )
      } else {
        setDraft(data) // opens the review panel
      }
    } catch (e) {
      setPushStatus(`❌ ${e.message}`)
    } finally {
      setGenerating(false)
    }
  }

  // Cancelling the review panel. For a per-meal draft (kind set on accept),
  // revert that meal to 'generated' and reconcile — closing the modal must NOT
  // leave the meal marked accepted/done. A batch "review full list" draft has
  // no kind, so cancel just closes it, touching nothing.
  async function cancelDraft() {
    const d = draft
    setDraft(null)
    if (!d?.kind) return
    try {
      const path = d.kind === 'lunch'
        ? `${MEALS_API}/lunch/${d.id}/unaccept`
        : `${MEALS_API}/${d.id}/unaccept`
      const res = await fetch(path, { method: 'POST' })
      const updated = await res.json()
      if (res.ok) {
        if (d.kind === 'lunch') patchLunch(updated)
        else patchSlot(updated)
      }
    } catch {
      // Revert is best-effort; refetch to resync if it failed.
      await fetchWeek(weekStart)
    }
  }

  // Step 2: the draft panel confirmed (or failed). Report the result.
  function onDraftConfirm(data, resolved, errMsg) {
    setDraft(null)
    if (errMsg) { setPushStatus(`❌ ${errMsg}`); return }
    const extra = []
    if (resolved?.matched) extra.push(`${resolved.matched} matched to stock`)
    if (resolved?.added) extra.push(`${resolved.added} added to inventory`)
    const suffix = extra.length ? ` (${extra.join(', ')})` : ''
    setPushStatus(
      data.added_count
        ? `✅ ${data.added_count} items pushed to Todoist: "${data.project}"${suffix}`
        : `✅ Nothing new to buy${suffix}.`
    )
  }

  // Mark an accepted dinner cooked: consumes its reserved stock (count drops).
  async function cook(slotId) {
    setLoadingSlot(slotId)
    const res = await fetch(`${MEALS_API}/${slotId}/cooked`, { method: 'POST' })
    const data = await res.json()
    if (res.ok && data.slot) patchSlot(data.slot)
    const used = (data.consumed || []).filter(c => c.used > 0)
    if (used.length) {
      setPushStatus(`🍳 Cooked — used ${used.map(c => `${c.used}× ${c.name}`).join(', ')}`)
    }
    setLoadingSlot(null)
  }

  const allSlots = week?.days?.flatMap(d => d.slots) ?? []
  const lunchIdeas = week?.lunch_ideas ?? []
  const hasSlots = week?.has_slots
  const pendingCount = allSlots.filter(s => s.status === 'pending' || s.status === 'generated').length
  const dinnersResolved = hasSlots && allSlots.every(s => s.status === 'accepted' || s.status === 'skipped' || s.status === 'cooked')
  const anyLunchAccepted = lunchIdeas.some(l => l.status === 'accepted')
  // Ready to shop once dinners are sorted and at least one lunch is picked
  const allResolved = dinnersResolved && anyLunchAccepted

  const memberById = Object.fromEntries(members.map(m => [m.id, m]))

  // On mobile: compact, hourly-resolution grid that fits a phone screen.
  // On desktop: 28px/hr, all 7 days.
  const hourHeight = isMobile ? 32 : HOUR_HEIGHT
  const totalHeight = (DAY_END_HOUR - DAY_START_HOUR) * hourHeight
  const topFor = h => Math.max(0, (h - DAY_START_HOUR) * hourHeight)
  const heightFor = (s, e) => Math.max(18, (e - s) * hourHeight)
  // Grid lines: hour-only on both (mobile used to show half-hours but that made
  // the grid too tall on a phone — hourly resolution is enough).
  const halfHours = []
  for (let h = DAY_START_HOUR; h < DAY_END_HOUR; h += 1) halfHours.push(h)
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
      {/* Off-today banner — desktop only; the user finds it noise on mobile. */}
      {!viewingToday && !isMobile && (
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
          {allResolved && (
            <button className={styles.btnSuccess} onClick={pushToTodoist} disabled={generating} data-testid="push-shopping">
              {generating ? 'Checking…' : 'Review full shopping list'}
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

      {draft && (
        <DraftReviewPanel
          draft={draft.draft}
          usedGpt={draft.used_gpt}
          onConfirm={onDraftConfirm}
          onCancel={cancelDraft}
        />
      )}

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
                        status={mealStatus[dinnerSlot.id]}
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
        </div>
      )}

      {/* ── Meal detail: modal popup (was a side panel) ── */}
      {selectedSlot && (
        <div
          className={styles.mealModalOverlay}
          onClick={() => setSelectedSlot(null)}
          data-testid="meal-modal"
        >
          <div className={styles.mealModalInner} onClick={e => e.stopPropagation()}>
            <MealDetail
              slot={selectedSlot}
              status={mealStatus[selectedSlot.id]}
              locations={invLocations}
              inventoryItems={invItems}
              onIngredientChanged={applyStatus}
              isLoading={loadingSlot === selectedSlot.id}
              isRejecting={rejectSlot === selectedSlot.id}
              rejectReason={rejectReason}
              onAccept={() => accept(selectedSlot.id)}
              onSkip={() => skip(selectedSlot.id)}
              onRejectOpen={() => { setRejectSlot(selectedSlot.id); setRejectReason('') }}
              onRejectCancel={() => setRejectSlot(null)}
              onRejectConfirm={() => reject(selectedSlot.id, rejectReason)}
              onRejectReasonChange={setRejectReason}
              onCook={() => cook(selectedSlot.id)}
              onClose={() => setSelectedSlot(null)}
            />
          </div>
        </div>
      )}

      {/* ── Lunch ideas + Chores, below the calendar ── */}
      {!loading && (
        <div className={styles.belowCalendar}>
          {hasSlots && (
            <div className={styles.clearPlanRow}>
              <button
                className={styles.btnSecondary}
                onClick={() => {
                  if (window.confirm('Clear the whole meal plan for this week? This removes all dinners and lunch ideas (accepted ones too).')) reset()
                }}
                disabled={generating}
                data-testid="clear-plan"
                title="Remove all dinners and lunch ideas for this week"
              >
                🗑 Clear meal plan
              </button>
            </div>
          )}
          <LunchIdeas
            ideas={week?.lunch_ideas ?? []}
            mealStatus={mealStatus}
            locations={invLocations}
            inventoryItems={invItems}
            onIngredientChanged={applyStatus}
            onAccept={acceptLunch}
            onReject={rejectLunch}
            count={lunchCount}
            onCountChange={setLunchCount}
            onGenerate={() => generateLunches(lunchCount)}
            generating={generatingLunches}
          />
          <div className={styles.choresSection}>
            <Reminders date={selectedDate} filterMember={filterMember} />
          </div>
          <div className={styles.choresSection}>
            <Chores filterMember={filterMember} selectedDate={selectedDate} />
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

// ─── Shared: per-ingredient inventory/shopping state tags + actions ──────────

const STATE_META = {
  in_stock: { icon: '✅', label: 'In stock', cls: 'stateInStock' },
  on_list:  { icon: '🛒', label: 'On shopping list', cls: 'stateOnList' },
  need:     { icon: '⚠️', label: 'Not on any list', cls: 'stateNeed' },
}

const ING_API = '/api/meals/ingredient'

// One ingredient row with an expandable action menu to correct its
// inventory/shopping link. onChanged receives the refreshed meal status.
function IngredientRow({ ing, locations, inventoryItems, onChanged }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [picking, setPicking] = useState(null) // 'match' | 'add' | null
  const [matchId, setMatchId] = useState('')
  const [addLoc, setAddLoc] = useState(locations?.[0] || 'pantry')
  const meta = STATE_META[ing.state] || STATE_META.need

  async function call(path, body) {
    setBusy(true)
    try {
      const res = await fetch(`${ING_API}/${ing.id}/${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
      })
      const data = await res.json()
      if (res.ok && data.status) onChanged?.(data.status)
    } finally {
      setBusy(false); setOpen(false); setPicking(null)
    }
  }

  function consume() {
    const n = window.prompt('How many did you use?', '1')
    if (n == null) return
    const qty = Math.max(1, parseInt(n, 10) || 1)
    call('consume', { qty })
  }

  return (
    <li className={`${styles.stateItem} ${styles[meta.cls]}`}>
      <div className={styles.stateRow}>
        <span className={styles.stateIcon} title={meta.label} aria-label={meta.label}>{meta.icon}</span>
        <span className={styles.stateName}>{ing.name}</span>
        {ing.quantity && <span className={styles.qty}> — {ing.quantity}</span>}
        <button
          className={styles.stateMenuBtn}
          onClick={() => setOpen(o => !o)}
          disabled={busy}
          title="Fix this ingredient"
          data-testid="ing-menu"
        >⋯</button>
      </div>

      {open && (
        <div className={styles.stateActions}>
          {ing.state === 'in_stock' ? (
            <>
              <button className={styles.stateAction} onClick={consume} disabled={busy}>Mark some used…</button>
              <button className={styles.stateAction} onClick={() => call('unmatch')} disabled={busy}>Wrong match — unmatch</button>
            </>
          ) : (
            <>
              <button className={styles.stateAction} onClick={() => setPicking(picking === 'match' ? null : 'match')} disabled={busy}>Match to inventory…</button>
              <button className={styles.stateAction} onClick={() => setPicking(picking === 'add' ? null : 'add')} disabled={busy}>I have it — add to inventory…</button>
              {ing.state !== 'on_list' && (
                <button className={styles.stateAction} onClick={() => call('to-shopping')} disabled={busy}>Add to shopping list</button>
              )}
            </>
          )}

          {picking === 'match' && (
            <div className={styles.statePicker}>
              <select value={matchId} onChange={e => setMatchId(e.target.value)}>
                <option value="">Choose an inventory item…</option>
                {inventoryItems.map(it => (
                  <option key={it.id} value={it.id}>{it.name} ({it.location})</option>
                ))}
              </select>
              <button className={styles.btnAccept} disabled={!matchId || busy}
                onClick={() => call('match', { inventory_item_id: matchId })}>Link</button>
            </div>
          )}

          {picking === 'add' && (
            <div className={styles.statePicker}>
              <select value={addLoc} onChange={e => setAddLoc(e.target.value)}>
                {locations.map(l => <option key={l} value={l}>{l}</option>)}
              </select>
              <button className={styles.btnAccept} disabled={busy}
                onClick={() => call('add-to-inventory', { location: addLoc, track_mode: 'count', count: 1 })}>Add</button>
            </div>
          )}
        </div>
      )}
    </li>
  )
}

function IngredientStates({ ingredients, locations = [], inventoryItems = [], onChanged }) {
  if (!ingredients?.length) return null
  return (
    <ul className={styles.stateList} data-testid="ingredient-states">
      {ingredients.map((ing, i) => (
        <IngredientRow
          key={ing.id || i}
          ing={ing}
          locations={locations}
          inventoryItems={inventoryItems}
          onChanged={onChanged}
        />
      ))}
    </ul>
  )
}

// ─── Meal chip (compact, shown in all-day strip) ──────────────────────────────

function MealChip({ slot, status, isLoading, onClick, isSelected }) {
  if (!slot) return null

  const chipClass = {
    accepted: styles.chipAccepted,
    cooked:   styles.chipAccepted,
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

  // Badge: only for accepted meals, from the inventory/shopping breakdown.
  const badge = (slot.status === 'accepted' && status)
    ? (status.makeable
        ? { icon: '🟢', title: 'Makeable from stock' }
        : { icon: '🛒', title: 'Needs shopping' })
    : null

  return (
    <button
      className={`${styles.mealChip} ${chipClass} ${isSelected ? styles.chipSelected : ''}`}
      onClick={onClick}
      title={badge ? badge.title : slot.meal?.name}
    >
      <span className={styles.chipType}>🍽️</span>
      <span className={styles.chipName}>{label}</span>
      {badge && <span className={styles.chipBadge} title={badge.title}>{badge.icon}</span>}
      {slot.status === 'accepted' && !badge && <span className={styles.chipTick}>✓</span>}
    </button>
  )
}

// ─── Meal detail panel (shown below the grid when a chip is clicked) ──────────

function MealDetail({ slot, status, locations = [], inventoryItems = [], onIngredientChanged, isLoading, isRejecting, rejectReason,
  onAccept, onSkip, onRejectOpen, onRejectCancel, onRejectConfirm, onRejectReasonChange, onCook, onClose }) {

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

      {/* Accepted meal: inventory vs shopping breakdown */}
      {slot.status === 'accepted' && status && (
        <div className={styles.stockSummary} data-testid="stock-breakdown">
          <p className={styles.stockHeadline}>
            {status.makeable
              ? '🟢 You can make this from stock'
              : '🛒 Needs shopping before you can make it'}
          </p>
          <IngredientStates
            ingredients={status.ingredients}
            locations={locations}
            inventoryItems={inventoryItems}
            onChanged={onIngredientChanged}
          />
        </div>
      )}

      {slot.meal && (
        <>
          <p className={styles.detailDesc}>{slot.meal.description}</p>
          {slot.meal.prep_minutes && (
            <p className={styles.detailPrep}>⏱ {slot.meal.prep_minutes} mins</p>
          )}
          {/* Raw ingredient list kept for non-accepted meals (no status yet). */}
          {slot.status !== 'accepted' && (
            <>
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
        <div className={styles.detailActions}>
          <span className={styles.acceptedText}>✓ Accepted</span>
          <button className={styles.btnAccept} onClick={onCook} data-testid="mark-cooked">
            🍳 Mark cooked
          </button>
        </div>
      )}

      {slot.status === 'cooked' && (
        <p className={styles.acceptedText}>🍳 Cooked — stock used</p>
      )}
    </div>
  )
}

// ─── Lunch ideas (not day-aligned) ────────────────────────────────────────────

function LunchIdeas({ ideas, mealStatus = {}, locations = [], inventoryItems = [], onIngredientChanged, onAccept, onReject, count, onCountChange, onGenerate, generating }) {
  const [rejectingId, setRejectingId] = useState(null)
  const [reason, setReason] = useState('')

  return (
    <section className={styles.lunchSection}>
      <div className={styles.lunchHeader}>
        <h2 className={styles.lunchHeading}>🥗 Lunch Ideas <span className={styles.lunchSub}>for the week — pick and mix</span></h2>
        <div className={styles.lunchControls}>
          <label className={styles.lunchCountLabel}>
            How many?
            <input
              type="number"
              min="1"
              max="10"
              value={count}
              onChange={e => onCountChange(Math.max(1, Math.min(10, Number(e.target.value) || 1)))}
              className={styles.lunchCountInput}
              disabled={generating}
              data-testid="lunch-count"
            />
          </label>
          <button
            className={styles.btnPrimary}
            onClick={onGenerate}
            disabled={generating}
            data-testid="generate-lunches"
          >
            {generating ? 'Generating…' : ideas.length ? 'Regenerate lunches' : 'Generate lunches'}
          </button>
        </div>
      </div>

      {ideas.length === 0 ? (
        <p className={styles.mutedText} data-testid="lunch-empty">
          No lunch ideas yet. Choose how many and generate them for the week.
        </p>
      ) : (
      <div className={styles.lunchGrid}>
        {ideas.map(idea => {
          const st = mealStatus[idea.id]
          return (
          <div
            key={idea.id}
            className={`${styles.lunchCard} ${idea.status === 'accepted' ? styles.lunchAccepted : ''}`}
          >
            <div className={styles.lunchTop}>
              <span className={styles.lunchName}>
                {idea.status === 'accepted' && st && (
                  <span title={st.makeable ? 'Makeable from stock' : 'Needs shopping'}>
                    {st.makeable ? '🟢 ' : '🛒 '}
                  </span>
                )}
                {idea.name}
              </span>
              {idea.prep_minutes && <span className={styles.lunchPrep}>⏱ {idea.prep_minutes}m</span>}
            </div>
            <p className={styles.lunchDesc}>{idea.description}</p>

            {/* Accepted: inventory/shopping breakdown. Otherwise the plain list. */}
            {idea.status === 'accepted' && st ? (
              <IngredientStates
                ingredients={st.ingredients}
                locations={locations}
                inventoryItems={inventoryItems}
                onChanged={onIngredientChanged}
              />
            ) : idea.ingredients?.length > 0 && (
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
          )
        })}
      </div>
      )}
    </section>
  )
}
