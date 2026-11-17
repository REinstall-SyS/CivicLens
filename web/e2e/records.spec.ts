import { expect, test } from '@playwright/test';

test('finds an official proposal, follows its decision and saves a watch', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /Follow the decisions shaping Hattiesburg/ })).toBeVisible();
  await page.getByRole('textbox', { name: 'Search the public record' }).fill('2026-749');
  await page.getByRole('button', { name: 'Search' }).click();
  await expect(page.getByRole('heading', { name: /Results for.*2026-749/ })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Search results' }).getByText('Approved', { exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Timeline', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Decision timeline' })).toBeVisible();
  await expect(page.getByText('Recorded vote · 5 yeas, 0 nays')).toBeVisible();
  await expect(page.getByText('$26,483.20', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: /Minutes · PDF page 6/i }).first()).toHaveAttribute('href', /civicclerk\.com.*#page=6/);
  await page.getByRole('button', { name: 'Follow this item' }).click();
  await expect(page.getByRole('button', { name: 'Following item' })).toBeVisible();
  await page.getByRole('link', { name: 'Watchlists', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Item 2026-749' })).toBeVisible();
  await page.getByRole('button', { name: 'Pause', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Resume', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Delete watchlist data' }).click();
  await page.getByRole('button', { name: 'Delete data', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('Watchlist data deleted.');
});

test('renders historical meeting evidence on a narrow screen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/meetings');
  await page.getByRole('link', { name: 'City Council regular meeting', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'City Council regular meeting' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Official documents' })).toBeVisible();
  await expect(page.getByRole('link', { name: /1004 Spencer Street/ })).toBeVisible();
  await expect.poll(async () => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
