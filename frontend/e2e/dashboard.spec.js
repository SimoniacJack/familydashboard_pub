import { test, expect } from '@playwright/test'
import { login } from './helpers.js'

// Minimal smoke + responsive checks. Runs against the locally-served build with
// the Flask backend on :5000. Two projects: desktop + mobile (Pixel 5).
// The calendar lives on the default Home tab, so login() is enough.

test('dashboard loads and the calendar grid renders', async ({ page }) => {
  await login(page)
  await expect(page.getByTestId('calendar-grid')).toBeVisible()
  await expect(page.getByTestId('member-pills')).toBeVisible()
})

test('calendar shows the right number of day columns for the viewport', async ({ page }, testInfo) => {
  await login(page)
  const grid = page.getByTestId('calendar-grid')
  await expect(grid).toBeVisible()
  const dayCount = await grid.getAttribute('data-day-count')
  if (testInfo.project.name === 'mobile') {
    expect(dayCount).toBe('1')
  } else {
    expect(dayCount).toBe('7')
  }
})

test('member pills lay out horizontally on mobile', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile', 'mobile-only check')
  await login(page)
  const pills = page.getByTestId('member-pills')
  await expect(pills).toBeVisible()
  const tops = await pills.locator('button').evaluateAll(els => els.map(e => e.getBoundingClientRect().top))
  if (tops.length > 1) {
    const maxDelta = Math.max(...tops) - Math.min(...tops)
    expect(maxDelta).toBeLessThan(5)
  }
})

test('reminders section renders a grid', async ({ page }) => {
  await login(page)
  const reminders = page.getByTestId('reminders')
  if (await reminders.count()) {
    await expect(page.getByTestId('reminders-grid')).toBeVisible()
  }
})
