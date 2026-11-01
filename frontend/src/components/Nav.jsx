import styles from './Nav.module.css'

// App-level top navigation: switch between the Home (calendar/chores/reminders)
// and Food (shopping list + inventory) tabs, plus sign-out.
export default function Nav({ tabs, active, onChange, onLogout, familyName }) {
  return (
    <nav className={styles.nav}>
      <div className={styles.brand}>🏡 {familyName ? `${familyName} Family` : "Family Dashboard"}</div>
      <div className={styles.tabs}>
        {tabs.map(tab => (
          <button
            key={tab.id}
            className={`${styles.tab} ${active === tab.id ? styles.active : ''}`}
            onClick={() => onChange(tab.id)}
            data-testid={`nav-${tab.id}`}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <button className={styles.logout} onClick={onLogout} data-testid="logout">
        Sign out
      </button>
    </nav>
  )
}
