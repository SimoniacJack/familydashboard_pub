import { test, expect } from '@playwright/test'
import { login } from './helpers.js'

// Draft-review flow (Stage 2 of "push to shopping list"). The live reservation
// engine, GPT matcher and Todoist write are proven by backend tests and a live
// end-to-end check; here we drive the UI by stubbing the two shopping calls so
// the panel logic (render, batch-remove, keep-only push) is tested headless
// with no GPT spend and no live Todoist write. Needs a resolved meal plan
// seeded in the backend so the "Push to Todoist" button is present.

const FAKE_DRAFT = {
  draft: [
    { name: 'Chopped tomatoes', quantity: '400g', reason: 'not in inventory' },
    { name: 'Milk', quantity: '', reason: 'running low' },
    { name: 'Basmati rice', quantity: '500g', reason: 'short in stock' },
  ],
  used_gpt: true,
  reserved: [],
  counts: { reserved: 0, unmatched: 1, shortfalls: 1, draft: 3 },
}

test('push opens the draft panel; only kept lines are pushed', async ({ page }) => {
  await page.route('**/api/shopping/draft', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(FAKE_DRAFT) })
  )
  let confirmBody = null
  await page.route('**/api/shopping/push-confirm', route => {
    confirmBody = route.request().postDataJSON()
    const added = (confirmBody.items || []).map(i => i.name)
    route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ project: 'Family Shopping List', added, added_count: added.length }),
    })
  })

  await login(page)

  const pushBtn = page.getByTestId('push-shopping')
  await pushBtn.waitFor({ state: 'visible', timeout: 8000 }).catch(() => {})
  const hasPush = await pushBtn.count().catch(() => 0)
  test.skip(!hasPush, 'no resolved meal plan seeded; Push button absent')
  await pushBtn.click()

  const panel = page.getByTestId('draft-panel')
  await expect(panel).toBeVisible({ timeout: 8000 })
  await expect(panel).toContainText('Chopped tomatoes')
  await expect(panel).toContainText('Basmati rice')

  // Batch-remove everything, then re-keep one line.
  await page.getByTestId('draft-remove-all').click()
  await panel.getByTestId('draft-keep').first().check()

  // Confirm -> only the one kept line should be sent to push-confirm.
  await page.getByTestId('draft-confirm').click()
  await expect(panel).toBeHidden({ timeout: 8000 })

  expect(confirmBody).not.toBeNull()
  expect(confirmBody.items.length).toBe(1)
})
