import { test, expect } from "@playwright/test";
import { media, fake, open, press, noOverlap, pending } from "./support/voice";
const destination = (page: import("@playwright/test").Page, name: string) =>
  page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name, exact: true })
    .click();

test("navigation: focused destinations preserve selection, back and refresh resume the same server session", async ({
  page,
}) => {
  await media(page);
  const f = await fake(page);
  await open(page);
  const id = f.current().session_id;
  await expect(page).toHaveURL(new RegExp("#/practice/" + id + "$"));
  await destination(page, "History");
  await expect(
    page.getByRole("heading", { name: "History", exact: true }),
  ).toBeFocused();
  await expect(page.getByLabel("Lesson source")).not.toBeVisible();
  await expect(
    page.getByRole("button", { name: "Tap to talk", exact: true }),
  ).not.toBeVisible();
  await destination(page, "Settings");
  await expect(
    page.getByRole("heading", { name: "Settings", exact: true }),
  ).toBeFocused();
  await expect(
    page.getByRole("button", { name: "Disconnect", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "Return to practice", exact: true })
    .click();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Tap to talk", exact: true }),
  ).toBeEnabled();
  expect(f.getStarts()).toBe(1);
  await destination(page, "Lessons");
  await expect(page.getByLabel("Lesson source")).toHaveValue("alpha");
  await expect(
    page.getByRole("button", { name: "Start practice", exact: true }),
  ).toBeDisabled();
  await page.goBack();
  await expect(
    page.getByRole("heading", { name: "Practice", exact: true }),
  ).toBeFocused();
  expect(f.current().session_id).toBe(id);
  await noOverlap(page);
});

test("navigation: back during capture requires a choice and restores the current history entry", async ({
  page,
}, info) => {
  await media(page);
  const f = await fake(page);
  await open(page);
  const length = await page.evaluate(() => history.length);
  await press(page, info, "Tap to talk");
  await expect(
    page.getByRole("button", { name: "Send answer", exact: true }),
  ).toBeEnabled();
  await page.goBack();
  const dialog = page.getByRole("dialog", { name: "Leave Practice?" });
  await expect(dialog).toBeVisible();
  await expect(page).toHaveURL(/#\/practice\//);
  await dialog
    .getByRole("button", { name: "Stay in Practice", exact: true })
    .click();
  expect(await page.evaluate(() => history.length)).toBe(length);
  await expect(
    page.getByRole("button", { name: "Send answer", exact: true }),
  ).toBeEnabled();
  await destination(page, "History");
  await dialog
    .getByRole("button", { name: "Discard recording and leave", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "History", exact: true }),
  ).toBeFocused();
  expect(f.uploads).toHaveLength(0);
  await page.goBack();
  await expect(
    page.getByRole("heading", { name: "Practice", exact: true }),
  ).toBeVisible();
  await noOverlap(page);
});

test("navigation: leaving a permission request releases a late stream", async ({
  page,
}, info) => {
  await media(page);
  const f = await fake(page);
  await open(page);
  await page.evaluate(() => {
    (window as any).voiceTest.delayedPermission = true;
  });
  await press(page, info, "Tap to talk");
  await destination(page, "Settings");
  const dialog = page.getByRole("dialog", { name: "Leave Practice?" });
  await expect(
    dialog.getByRole("button", { name: "Send answer and leave", exact: true }),
  ).toHaveCount(0);
  await dialog
    .getByRole("button", { name: "Discard recording and leave", exact: true })
    .click();
  await page.evaluate(() => (window as any).voiceTest.releasePermission());
  await expect(
    page.getByRole("heading", { name: "Settings", exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(() => (window as any).voiceTest.records)).toBe(0);
  expect(f.uploads).toHaveLength(0);
  await noOverlap(page);
});

test("navigation: send and leave preserves one upload without hidden autoplay or replacing its controller", async ({
  page,
}, info) => {
  await media(page);
  const f = await fake(page);
  await open(page);
  let release!: () => void;
  await page.route("**/api/v1/sessions/*/audio?*", async (route) => {
    await new Promise<void>((resolve) => {
      release = resolve;
    });
    await route.fallback();
  });
  await press(page, info, "Tap to talk");
  await page.waitForTimeout(300);
  await destination(page, "Settings");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Send answer and leave", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Settings", exact: true }),
  ).toBeFocused();
  await expect(
    page.getByRole("button", { name: "Disconnect", exact: true }),
  ).toBeDisabled();
  await expect.poll(() => Boolean(release)).toBe(true);
  release();
  await expect.poll(() => f.uploads.length).toBe(1);
  await expect.poll(() => pending(page)).toEqual([]);
  expect(await page.evaluate(() => (window as any).voiceTest.plays)).toBe(0);
  await destination(page, "Practice");
  await expect(page.getByLabel("Teacher instructions")).toContainText(
    "Ось квиток.",
  );
  expect(await page.evaluate(() => (window as any).voiceTest.plays)).toBe(0);
  expect(f.getStarts()).toBe(1);
  await noOverlap(page);
});

test("navigation: missing session deep links do not create a session and invalid routes fail safely", async ({
  page,
}) => {
  await media(page);
  const f = await fake(page);
  await open(page);
  await page.route("**/api/v1/sessions/foreign?*", (route) =>
    route.fulfill({ status: 404, body: "{}" }),
  );
  await page.goto("/#/practice/foreign");
  await page.reload();
  await expect(page.getByRole("alert")).toContainText(
    "unavailable for the paired learner",
  );
  expect(f.getStarts()).toBe(1);
  await page.goto("/#/practice/../../etc");
  await expect(
    page.getByRole("heading", { name: "Page unavailable", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Go to Lessons", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Lessons", exact: true }),
  ).toBeFocused();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
