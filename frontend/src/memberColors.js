// Each family member gets a signature pastel used consistently across the app
// (reminder dots, avatar rings, chore credit, etc.).
export const MEMBER_COLORS = {
  jack:   { bg: 'var(--pastel-sky)',      ink: 'var(--pastel-sky-ink)' },
  hannah: { bg: 'var(--pastel-pink)',     ink: 'var(--pastel-pink-ink)' },
  rafe:   { bg: 'var(--pastel-sage)',     ink: 'var(--pastel-sage-ink)' },
  ada:    { bg: 'var(--pastel-lavender)', ink: 'var(--pastel-lavender-ink)' },
  kit:    { bg: 'var(--pastel-butter)',   ink: 'var(--pastel-butter-ink)' },
}

export function memberColor(id) {
  return MEMBER_COLORS[id] || { bg: 'var(--color-surface-alt)', ink: 'var(--color-text-muted)' }
}

export function cap(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s
}

// Event titles follow "[Person] - [Event]" e.g. "Ada - Beavers".
// Returns the member id (lowercase first word) if it matches a known member,
// else null. `memberIds` is the list of valid ids from /api/members.
export function parseEventMember(summary, memberIds) {
  if (!summary) return null
  const dash = summary.indexOf(' - ')
  if (dash === -1) return null
  const candidate = summary.slice(0, dash).trim().toLowerCase()
  return memberIds.includes(candidate) ? candidate : null
}

export function eventTitleWithoutMember(summary) {
  const dash = summary.indexOf(' - ')
  return dash === -1 ? summary : summary.slice(dash + 3).trim()
}
