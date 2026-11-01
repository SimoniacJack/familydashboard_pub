import { expect } from '@playwright/test'

// Log in with the shared family password and wait for the app nav to appear.
// All specs need this now that the app opens on a login screen.
export async function login(page) {
  await page.goto('/')
  const pw = page.getByTestId('login-password')
  // If already authed (cookie), the nav shows and there's no login field.
  if (await pw.count()) {
    await pw.fill('parker')
    await page.getByTestId('login-submit').click()
  }
  await page.getByTestId('nav-home').waitFor({ state: 'visible', timeout: 10000 })
}

// Switch to the Food tab (shopping list + inventory live here now).
export async function gotoFood(page) {
  await page.getByTestId('nav-food').click()
  await expect(page.getByTestId('nav-food')).toBeVisible()
}
