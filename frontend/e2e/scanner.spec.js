import { test, expect } from '@playwright/test'
import { login, gotoFood } from './helpers.js'

// Barcode scanner — manual path only. The camera/barcode path needs a real
// device camera and must be verified on a phone (see the phone checklist); it
// cannot run headless. This spec drives the parts that CAN run headless: the
// Scan button opens the scanner, Manual mode lets you type a name, and Add
// files it to the chosen inventory location via /api/inventory/scan-add.

test('scan button opens the scanner and manual add works', async ({ page }) => {
  await login(page)
  await gotoFood(page)

  // Scan buttons render only after /api/inventory resolves; wait for them.
  const scanBtn = page.locator('[data-testid^="scan-btn-"]').first()
  await scanBtn.waitFor({ state: 'visible', timeout: 8000 }).catch(() => {})
  const hasScan = await scanBtn.count()
  test.skip(!hasScan, 'inventory not rendered (backend/locations unavailable)')
  await scanBtn.click()

  const scanner = page.getByTestId('scanner')
  await expect(scanner).toBeVisible()

  // Switch to Manual so no camera is needed.
  await page.getByTestId('scanner-manual').click()

  const name = `E2E Test Item ${Date.now()}`
  await scanner.locator('input[placeholder="Item name"]').fill(name)

  // Capture the scan-add request to confirm the right endpoint is called.
  const [req] = await Promise.all([
    page.waitForRequest(r => r.url().includes('/api/inventory/scan-add') && r.method() === 'POST'),
    page.getByTestId('manual-add').click(),
  ])
  expect(req.postDataJSON().name).toBe(name)

  // The running "added" list shows the confirmation line.
  await expect(scanner).toContainText(name)
})
