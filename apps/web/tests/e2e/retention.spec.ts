import { test, expect, Page } from "@playwright/test";
import { server } from "./support/server";
import { media, open, speak, pending, navigateTo } from "./support/voice";

async function settings(page: Page) {
  await navigateTo(page, "Settings");
  await page.getByText("Recording privacy", { exact: true }).click();
  await page
    .getByRole("button", { name: "Load recording settings", exact: true })
    .click();
  return page.getByRole("region", { name: "Recording privacy", exact: true });
}
async function practice(page: Page, service: { origin: string; code: string }) {
  await media(page);
  const started = page.waitForResponse(
    (r) =>
      r.url() === service.origin + "/api/v1/sessions" &&
      r.request().method() === "POST",
  );
  await open(page, "repetition", service);
  return (await (await started).json()).session_id as string;
}
async function recordingStatus(page: Page) {
  await navigateTo(page, "History");
  await page
    .getByRole("button", { name: "Load history and progress", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Evidence for Tickets", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Load recording status", exact: true })
    .click();
  return page.getByRole("region", {
    name: "Saved recording status",
    exact: true,
  });
}

test("retention: default off removes acknowledged device upload and stores no server audio", async ({
  page,
}, info) => {
  const service = await server({ retention: true });
  try {
    await practice(page, service);
    const panel = await settings(page);
    await expect(
      panel.getByText("Current server setting: saving off.", { exact: true }),
    ).toBeVisible();
    await speak(page, info);
    await expect.poll(() => service.recordingFiles()).toEqual([]);
    await expect.poll(() => pending(page)).toEqual([]);
    const history = await recordingStatus(page);
    await expect(history.getByText(/Not saved · recorded/)).toBeVisible();
  } finally {
    await service.stop();
  }
});

test("retention: enabled setting survives restart and idle expiry keeps history", async ({
  page,
}, info) => {
  const service = await server({ retention: true });
  try {
    const id = await practice(page, service);
    const panel = await settings(page);
    await panel.getByLabel("Save new recordings for").selectOption("1");
    await panel
      .getByRole("button", { name: "Apply recording setting", exact: true })
      .click();
    await expect(
      panel.getByText("Current server setting: save for 1 day.", {
        exact: true,
      }),
    ).toBeVisible();
    await speak(page, info);
    await expect.poll(() => service.recordingFiles()).toHaveLength(1);
    const before = await service.inspect(id);
    await service.restart();
    await page.reload();
    const restored = await settings(page);
    await expect(
      restored.getByText("Current server setting: save for 1 day.", {
        exact: true,
      }),
    ).toBeVisible();
    const history = await recordingStatus(page);
    await expect(history.getByText(/Saved privately · recorded/)).toBeVisible();
    await service.expireRecordings();
    await expect.poll(() => service.recordingFiles()).toEqual([]); // background worker, before API refresh
    await history
      .getByRole("button", { name: "Refresh recording status", exact: true })
      .click();
    await expect(history.getByText(/Expired — audio removed/)).toBeVisible();
    expect((await service.inspect(id)).events).toEqual(before.events);
  } finally {
    await service.stop();
  }
});

test("retention: lost disable response reloads truthful state and keeps evidence", async ({
  page,
}, info) => {
  const service = await server({ retention: true });
  try {
    const id = await practice(page, service);
    const panel = await settings(page);
    await panel.getByLabel("Save new recordings for").selectOption("7");
    await panel
      .getByRole("button", { name: "Apply recording setting", exact: true })
      .click();
    await expect(
      panel.getByText("Current server setting: save for 7 days.", {
        exact: true,
      }),
    ).toBeVisible();
    await speak(page, info);
    await expect.poll(() => service.recordingFiles()).toHaveLength(1);
    const before = await service.inspect(id);
    let lost = false;
    await page.route("**/api/v1/recording-retention", async (route) => {
      if (route.request().method() === "POST" && !lost) {
        lost = true;
        await route.fetch();
        await route.abort("failed");
      } else await route.continue();
    });
    await navigateTo(page, "Settings");
    await panel
      .getByRole("button", {
        name: "Delete saved recordings and turn saving off",
        exact: true,
      })
      .click();
    await expect(panel.getByRole("alert")).toContainText(
      "could not be confirmed",
    );
    await panel
      .getByRole("button", { name: "Reload recording settings", exact: true })
      .click();
    await expect(
      panel.getByText("Current server setting: saving off.", { exact: true }),
    ).toBeVisible();
    expect(await service.recordingFiles()).toEqual([]);
    const history = await recordingStatus(page);
    await expect(
      history.getByText(/Deleted — saving turned off/),
    ).toBeVisible();
    expect((await service.inspect(id)).events).toEqual(before.events);
  } finally {
    await service.stop();
  }
});

test("retention: paired learner settings stay separate", async ({ page }) => {
  const service = await server({ retention: true });
  try {
    await practice(page, service);
    const panel = await settings(page);
    await panel.getByLabel("Save new recordings for").selectOption("30");
    await panel
      .getByRole("button", { name: "Apply recording setting", exact: true })
      .click();
    await expect(
      panel.getByText("Current server setting: save for 30 days.", {
        exact: true,
      }),
    ).toBeVisible();
    const code = await page.request.post(
      service.origin + "/api/v1/operator/pairing-codes",
      {
        headers: {
          Authorization: "Bearer synthetic-operator-" + "x".repeat(40),
        },
        data: {
          learner_id: "other-learner",
          label: "Synthetic retention isolation",
        },
      },
    );
    expect(code.ok()).toBeTruthy();
    const paired = await page.request.post(service.origin + "/api/v1/pair", {
      data: { code: (await code.json()).code },
    });
    expect(paired.ok()).toBeTruthy();
    await page.evaluate(
      (grant) =>
        localStorage.setItem("voice-teacher:grant:v1", JSON.stringify(grant)),
      await paired.json(),
    );
    await page.reload();
    const other = await settings(page);
    await expect(
      other.getByText("Current server setting: saving off.", { exact: true }),
    ).toBeVisible();
  } finally {
    await service.stop();
  }
});
