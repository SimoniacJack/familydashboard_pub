import ShoppingList from '../components/ShoppingList.jsx'
import Inventory from '../components/Inventory.jsx'
import styles from './FoodTab.module.css'

// The food-supply loop: the live shopping list (Todoist) + the inventory it
// files into. Kept separate from the Home tab's daily calendar/chores rhythm.
export default function FoodTab() {
  return (
    <div className={styles.page}>
      <section className={styles.section}>
        <ShoppingList />
      </section>
      <section className={styles.section}>
        <Inventory />
      </section>
    </div>
  )
}
