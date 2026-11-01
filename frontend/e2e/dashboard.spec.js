import { test, expect } from '@playwright/test'

// Minimal smoke + responsive checks. Runs against the locally-served build with
// the Flask backend on :5000. Two projects: desktop + mobile (Pixel 5).

test('dashboard loads and the calendar grid renders', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('calendar-grid')).toBeVisible()
  // Member filter pills render
  await expect(page.getByTestId('member-pills')).toBeVisible()
})

test('calendar shows the right number of day columns for the viewport', async ({ page }, testInfo) => {
  await page.goto('/')
  const grid = page.getByTestId('calendar-grid')
  await expect(grid).toBeVisible()
  const dayCount = await grid.getAttribute('data-day-count')
  if (testInfo.project.name === 'mobile') {
    // Mobile: single-day view
    expect(dayCount).toBe('1')
  } else {
    // Desktop: full week
    expect(dayCount).toBe('7')
  }
})

test('member pills lay out horizontally on mobile', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile', 'mobile-only check')
  await page.goto('/')
  const pills = page.getByTestId('member-pills')
  await expect(pills).toBeVisible()
  // All pill buttons should sit on the same row (equal top offset), i.e. not stacked.
  const tops = await pills.locator('button').evaluateAll(els => els.map(e => e.getBoundingClientRect().top))
  if (tops.length > 1) {
    const maxDelta = Math.max(...tops) - Math.min(...tops)
    expect(maxDelta).toBeLessThan(5) // same row
  }
})

test('reminders section renders a grid', async ({ page }) => {
  await page.goto('/')
  // Reminders may be absent if none exist; only assert the grid when the section shows.
  const reminders = page.getByTestId('reminders')
  if (await reminders.count()) {
    await expect(page.getByTestId('reminders-grid')).toBeVisible()
  }
})
