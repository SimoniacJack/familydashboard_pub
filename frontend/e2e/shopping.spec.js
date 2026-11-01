import { test, expect } from '@playwright/test'
import { login, gotoFood } from './helpers.js'

// Shopping -> inventory flow. Runs against the locally-served build WITH the
// Flask backend on :5000. The shopping list + inventory now live on the Food
// tab, so each test logs in then switches to Food. Steps that need list data
// skip cleanly when the Todoist list is empty.

test('shopping list section renders', async ({ page }) => {
  await login(page)
  await gotoFood(page)
  const shopping = page.getByTestId('shopping')
  await expect(shopping).toBeVisible()
  await expect(shopping).toContainText('Shopping List')
})

test('ticking an active item opens the inventory location picker', async ({ page }) => {
  await login(page)
  await gotoFood(page)
  const shopping = page.getByTestId('shopping')
  await expect(shopping).toBeVisible()

  const firstBuy = shopping.getByTestId('buy-btn').first()
  const hasItems = await firstBuy.count()
  test.skip(!hasItems, 'no active shopping items to tick (empty Todoist list)')

  await firstBuy.click()
  const picker = page.getByTestId('location-picker')
  await expect(picker).toBeVisible()
  await expect(picker.locator('button').first()).toBeVisible()
})
