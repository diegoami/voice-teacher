import { navigateTo } from "./support/voice";
import { test, expect } from "@playwright/test";
import {
  media,
  fake,
  open,
  press,
  speak,
  noOverlap,
  pending,
} from "./support/voice";
for (const mode of ["guided_conversation", "repetition"]) {
  test(`voice: ${mode} records a complete turn and teacher replay`, async ({
    page,
  }, info) => {
    await media(page);
    const f = await fake(page);
    await open(page, mode);
    await expect(page.getByLabel("Teacher instructions")).toContainText(
      "Добрий день!",
    );
    await speak(page, info);
    await expect(page.getByLabel("Teacher instructions")).toContainText(
      "Ось квиток.",
    );
    await expect(
      page.getByRole("button", { name: "Tap to talk", exact: true }),
    ).toBeEnabled();
    expect(f.uploads).toHaveLength(1);
    expect(f.uploads[0].revision).toBe(0);
    expect(f.uploads[0].type).toBe("audio/webm");
    await press(page, info, "Play teacher");
    await expect
      .poll(() => page.evaluate(() => (window as any).voiceTest.plays))
      .toBeGreaterThanOrEqual(2);
    expect(f.uploads).toHaveLength(1);
    await noOverlap(page);
  });
}
test("voice: denied permission, unsupported format and empty/short recordings recover without upload", async ({
  page,
}, info) => {
  await media(page);
  const f = await fake(page);
  await open(page);
  await page.evaluate(() => {
    (window as any).voiceTest.denied = true;
  });
  await press(page, info, "Tap to talk");
  await expect(page.getByRole("alert")).toContainText("permission was denied");
  await page.evaluate(() => {
    (window as any).voiceTest.denied = false;
    (window as any).voiceTest.unsupported = true;
  });
  await press(page, info, "Tap to talk");
  await expect(page.getByRole("alert")).toContainText("supported format");
  await page.evaluate(() => {
    (window as any).voiceTest.unsupported = false;
    (window as any).voiceTest.empty = true;
  });
  await speak(page, info);
  await expect(page.getByRole("alert")).toContainText("No usable speech");
  await page.evaluate(() => {
    (window as any).voiceTest.empty = false;
  });
  await press(page, info, "Tap to talk");
  await press(page, info, "Send answer");
  await expect(page.getByRole("alert")).toContainText("No usable speech");
  expect(f.uploads).toHaveLength(0);
  await noOverlap(page);
  await speak(page, info);
  await expect.poll(() => f.uploads.length).toBe(1);
});
for (const failure of ["before", "after"]) {
  test(`voice: lost response ${failure} commit recovers stable recording across refresh`, async ({
    page,
  }, info) => {
    await media(page);
    const f = await fake(page);
    await open(page);
    f.setFailure(failure);
    await speak(page, info);
    await expect(page.getByRole("alert")).toContainText("interrupted");
    const original = f.uploads[0];
    await page.reload();
    if (failure === "before") {
      await expect(page.getByRole("alert")).toContainText(
        "unfinished recording",
      );
      await press(page, info, "Recover saved response");
      await expect.poll(() => f.uploads.length).toBe(2);
      expect(f.uploads[1]).toEqual(original);
    } else {
      await expect(
        page.getByText("Your last response was saved. Play it when ready."),
      ).toBeVisible();
      expect(f.uploads).toHaveLength(1);
    }
    await expect(page.getByLabel("Teacher instructions")).toContainText(
      "Ось квиток.",
    );
    expect(f.getStarts()).toBe(1);
    await noOverlap(page);
  });
}
test("voice: blocked playback is actionable and recording interrupts playback without overlap", async ({
  page,
}, info) => {
  await media(page);
  const f = await fake(page);
  await open(page);
  await page.evaluate(() => {
    (window as any).voiceTest.blocked = true;
  });
  await press(page, info, "Play teacher");
  await expect(page.getByRole("alert")).toContainText("Tap Play teacher");
  await press(page, info, "Recover saved response");
  await expect(
    page.getByRole("button", { name: "Tap to talk", exact: true }),
  ).toBeEnabled();
  expect(f.controls).toHaveLength(0);
  await expect(page.getByLabel("Teacher instructions")).toContainText(
    "Добрий день!",
  );
  await page.evaluate(() => {
    (window as any).voiceTest.blocked = false;
    (window as any).voiceTest.hang = true;
  });
  await press(page, info, "Play teacher");
  await expect
    .poll(() => page.evaluate(() => (window as any).voiceTest.activePlayers))
    .toBe(1);
  await press(page, info, "Stop playback");
  await expect
    .poll(() => page.evaluate(() => (window as any).voiceTest.activePlayers))
    .toBe(0);
  await press(page, info, "Play teacher");
  await press(page, info, "Tap to talk");
  await expect
    .poll(() => page.evaluate(() => (window as any).voiceTest.activePlayers))
    .toBe(0);
  await page.waitForTimeout(300);
  await press(page, info, "Send answer");
  await expect.poll(() => f.uploads.length).toBe(1);
  await noOverlap(page);
  await press(page, info, "Stop playback");
});
test("voice: hold control is keyboard accessible", async ({ page }) => {
  await media(page);
  const f = await fake(page);
  await open(page);
  await page.getByLabel("Hold to talk instead of tapping").check();
  const talk = page.getByRole("button", { name: "Hold to talk", exact: true });
  await talk.focus();
  await page.keyboard.down("Space");
  await expect(
    page.getByRole("button", { name: "Release to send", exact: true }),
  ).toBeVisible();
  await page.waitForTimeout(300);
  await page.keyboard.up("Space");
  await expect.poll(() => f.uploads.length).toBe(1);
  await expect(
    page.getByRole("button", { name: "Hold to talk", exact: true }),
  ).toBeEnabled();
  expect(await page.evaluate(() => (window as any).voiceTest.records)).toBe(1);
  await noOverlap(page);
});
test("voice: finish during pending work cancels playback/capture and resolves a revision race", async ({
  page,
}, info) => {
  await media(page);
  const f = await fake(page);
  await open(page);
  f.setFailure("pending");
  await speak(page, info);
  await expect.poll(() => f.uploads.length).toBe(1);
  await press(page, info, "Finish session");
  await expect(page.getByText("Session finished and saved.")).toBeVisible();
  expect(f.controls).toHaveLength(2);
  expect(f.controls.map((c) => c.expected_revision)).toEqual([0, 1]);
  expect(f.controls[0].request_id).not.toBe(f.controls[1].request_id);
  expect(f.uploads).toHaveLength(1);
  await expect(
    page.getByRole("button", { name: "Tap to talk", exact: true }),
  ).toBeDisabled();
  await noOverlap(page);
});

test("voice: rapid double taps and double send cannot create duplicate attempts", async ({
  page,
}) => {
  await media(page);
  const f = await fake(page);
  await open(page);
  await page
    .getByRole("button", { name: "Tap to talk", exact: true })
    .dblclick();
  await expect(page.getByRole("alert")).toContainText("No usable speech");
  expect(f.uploads).toHaveLength(0);
  await noOverlap(page);
  await page.getByRole("button", { name: "Tap to talk", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Send answer", exact: true }),
  ).toBeEnabled();
  await page.waitForTimeout(300);
  await page
    .getByRole("button", { name: "Send answer", exact: true })
    .dblclick();
  await expect.poll(() => f.uploads.length).toBe(1);
  await expect.poll(() => pending(page)).toEqual([]);
  await noOverlap(page);
});
for (const failure of ["finish-before", "finish-after"]) {
  test(`voice: ${failure} response loss preserves stop intent across refresh`, async ({
    page,
  }, info) => {
    await media(page);
    const f = await fake(page);
    await open(page);
    f.setFailure(failure);
    await press(page, info, "Finish session");
    await expect(page.getByRole("alert")).toContainText(
      "Finish is still pending",
    );
    const intent = (await pending(page))[0];
    expect(intent.finish).toBeTruthy();
    expect(intent.containsGrant).toBe(false);
    f.reconnect();
    await page.reload();
    await expect(page.getByText("Session finished and saved.")).toBeVisible();
    expect(f.uploads).toHaveLength(0);
    expect(f.controls).toHaveLength(failure === "finish-before" ? 2 : 1);
    if (failure === "finish-before")
      expect(f.controls[1].request_id).toBe(f.controls[0].request_id);
    await expect.poll(() => pending(page)).toEqual([]);
    await noOverlap(page);
  });
}
test("voice: pending recording is learner/session bound and contains no access grant", async ({
  page,
}, info) => {
  await media(page);
  const f = await fake(page);
  await open(page);
  f.setFailure("before");
  await speak(page, info);
  await expect(page.getByRole("alert")).toBeVisible();
  const saved = await pending(page);
  expect(saved).toHaveLength(1);
  expect(saved[0]).toMatchObject({
    upload: f.uploads[0].id,
    containsGrant: false,
  });
  expect(JSON.parse(saved[0].key)).toHaveLength(2);
  expect(JSON.parse(saved[0].key)[0]).toBe("learner");
  expect(saved[0].bytes).toBeGreaterThan(0);
  await press(page, info, "Recover saved response");
  await expect.poll(() => pending(page)).toEqual([]);
});

test("voice: finishing while permission is pending releases a late microphone stream", async ({
  page,
}, info) => {
  await media(page);
  const f = await fake(page);
  await open(page);
  await page.evaluate(() => {
    (window as any).voiceTest.delayedPermission = true;
  });
  await press(page, info, "Tap to talk");
  await expect
    .poll(() =>
      page.evaluate(() => Boolean((window as any).voiceTest.releasePermission)),
    )
    .toBe(true);
  await press(page, info, "Finish session");
  await expect(page.getByText("Session finished and saved.")).toBeVisible();
  await page.evaluate(() => (window as any).voiceTest.releasePermission());
  await expect
    .poll(() => page.evaluate(() => (window as any).voiceTest.activeTracks))
    .toBe(0);
  expect(f.uploads).toHaveLength(0);
  expect(await page.evaluate(() => (window as any).voiceTest.records)).toBe(0);
});

test("voice: native pointer hold sends once and controls fit the session screen", async ({
  page,
  context,
}, info) => {
  await media(page);
  const f = await fake(page);
  await open(page);
  await page.getByLabel("Hold to talk instead of tapping").check();
  const talk = page.getByRole("button", { name: "Hold to talk", exact: true });
  await talk.scrollIntoViewIfNeeded();
  const box = (await talk.boundingBox())!;
  expect(box.height).toBeGreaterThanOrEqual(44);
  if (info.project.name === "android") {
    const cdp = await context.newCDPSession(page);
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchStart",
      touchPoints: [{ x: box.x + box.width / 2, y: box.y + box.height / 2 }],
    });
    await expect(
      page.getByRole("button", { name: "Release to send", exact: true }),
    ).toBeVisible();
    await page.waitForTimeout(300);
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchEnd",
      touchPoints: [],
    });
  } else {
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await expect(
      page.getByRole("button", { name: "Release to send", exact: true }),
    ).toBeVisible();
    await page.waitForTimeout(300);
    await page.mouse.up();
  }
  await expect.poll(() => f.uploads.length).toBe(1);
  await expect(
    page.getByRole("button", { name: "Hold to talk", exact: true }),
  ).toBeEnabled();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await noOverlap(page);
  await page
    .getByRole("region", { name: "Session ready" })
    .screenshot({ path: info.outputPath("voice.png") });
});
test("voice: multiple teacher segments play in order without overlap", async ({
  page,
}, info) => {
  await media(page);
  const f = await fake(page);
  f.setMultiple();
  await open(page);
  await press(page, info, "Play teacher");
  await expect
    .poll(() => page.evaluate(() => (window as any).voiceTest.plays))
    .toBe(2);
  await expect
    .poll(() => page.evaluate(() => (window as any).voiceTest.activePlayers))
    .toBe(0);
  expect(f.uploads).toHaveLength(0);
  await noOverlap(page);
});

test("voice: reopening the same saved session loads the current server presentation", async ({
  page,
}, info) => {
  await media(page);
  const f = await fake(page);
  await open(page);
  f.externalAdvance();
  await press(page, info, "Open Tickets");
  await expect(page.getByLabel("Teacher instructions")).toContainText(
    "Externally saved reply",
  );
  expect(f.getStarts()).toBe(1);
  expect(f.uploads).toHaveLength(0);
});

test("voice: finish uses durable state and succeeds while teacher speech is unavailable", async ({
  page,
}, info) => {
  await media(page);
  const f = await fake(page);
  await open(page);
  f.setFailure("tts");
  await press(page, info, "Finish session");
  await expect(page.getByText("Session finished and saved.")).toBeVisible();
  expect(f.controls).toHaveLength(1);
  expect(f.uploads).toHaveLength(0);
  await expect(
    page.getByRole("button", { name: "Tap to talk", exact: true }),
  ).toBeDisabled();
  await expect.poll(() => pending(page)).toEqual([]);
  await noOverlap(page);
});
