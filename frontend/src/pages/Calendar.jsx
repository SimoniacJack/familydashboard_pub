import styles from './Calendar.module.css'

// Set VITE_CALENDAR_EMBED_URL in your frontend .env to your own Google Calendar
// embed URL, e.g. https://calendar.google.com/calendar/embed?src=<id>&ctz=<tz>
const CALENDAR_URL = import.meta.env.VITE_CALENDAR_EMBED_URL || ''

export default function Calendar() {
  return (
    <div className={styles.container}>
      <h2 className={styles.heading}>Family Calendar</h2>
      <div className={styles.embedWrapper}>
        {CALENDAR_URL ? (
          <iframe
            src={CALENDAR_URL}
            title="Family Calendar"
            style={{ border: 0 }}
            width="100%"
            height="100%"
            frameBorder="0"
            scrolling="no"
          />
        ) : (
          <p className={styles.heading}>
            Set <code>VITE_CALENDAR_EMBED_URL</code> to embed your Google Calendar.
          </p>
        )}
      </div>
    </div>
  )
}
