import { test, expect } from '@playwright/test'
import { login, gotoFood } from './helpers.js'

// Verifies the Inventory UI rework:
//  - inventory rows have NO inline count/level mode toggle
//  - clicking an item name opens the edit modal
//  - the modal carries the mode switch + a Remove button
test('clicking an item opens a modal with mode switch and remove; no inline toggle', async ({ page }) => {
  await login(page)
  await gotoFood(page)

  // Inventory section renders its location cards + at least one item.
  const firstItem = page.getByTestId('inventory-item').first()
  await firstItem.waitFor({ state: 'visible', timeout: 10000 })

  // The per-row mode toggle must be gone.
  await expect(page.getByTestId('mode-toggle')).toHaveCount(0)

  // Open the modal by clicking the item name.
  await firstItem.getByTestId('item-open').click()
  const modal = page.getByTestId('item-modal')
  await expect(modal).toBeVisible()

  // Modal has the count/level switch and a remove button.
  await expect(modal.getByTestId('mode-count')).toBeVisible()
  await expect(modal.getByTestId('mode-level')).toBeVisible()
  await expect(modal.getByTestId('modal-remove')).toBeVisible()

  // Close without changing anything (click the overlay).
  await page.keyboard.press('Escape').catch(() => {})
  await modal.getByTestId('mode-count').click() // harmless no-op if already count
})
