// Each member gets a signature pastel used consistently across the app
// (reminder dots, avatar rings, chore credit, etc.). A member's own colour
// comes from the DB (/api/members); this palette is the fallback, assigned
// deterministically by member id so the same person always gets the same hue.
const PALETTE = [
  { bg: 'var(--pastel-sky)',      ink: 'var(--pastel-sky-ink)' },
  { bg: 'var(--pastel-pink)',     ink: 'var(--pastel-pink-ink)' },
  { bg: 'var(--pastel-sage)',     ink: 'var(--pastel-sage-ink)' },
  { bg: 'var(--pastel-lavender)', ink: 'var(--pastel-lavender-ink)' },
  { bg: 'var(--pastel-butter)',   ink: 'var(--pastel-butter-ink)' },
]

function hashId(id) {
  let h = 0
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) | 0
  return Math.abs(h)
}

export function memberColor(id) {
  if (!id) return { bg: 'var(--color-surface-alt)', ink: 'var(--color-text-muted)' }
  return PALETTE[hashId(id) % PALETTE.length]
}

export function cap(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s
}

// Event titles follow "[Person] - [Event]" e.g. "Sam - Swimming".
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
