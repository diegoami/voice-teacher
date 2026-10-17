import { test, expect, Page } from "@playwright/test";
import {
  media,
  fake,
  open,
  press,
  speak,
  noOverlap,
  pending,
} from "./support/voice";

async function records(page: Page, f: Awaited<ReturnType<typeof fake>>) {
  let down = false;
  await page.route("**/api/v1/sessions/*/transcript*", async (route) => {
    if (down) return route.fulfill({ status: 503, body: "{}" });
    const turns = [{ turn_id: "t0", role: "teacher", text: "Добрий день!" }];
    f.uploads.forEach((_, i) =>
      turns.push(
        {
          turn_id: `l${i}`,
          role: "learner",
          text: "<script>learner answer</script>",
        },
        { turn_id: `t${i + 1}`, role: "teacher", text: "Ось квиток." },
      ),
    );
    await route.fulfill({ json: turns });
  });
  await page.route("**/api/v1/sessions/*/evidence*", async (route) => {
    if (down) return route.fulfill({ status: 503, body: "{}" });
    const offset = Number(
      new URL(route.request().url()).searchParams.get("offset") || 0,
    );
    await route.fulfill({
      json: {
        session_id: f.current().session_id,
        rows: f.uploads.length
          ? [
              {
                event_id: `e${offset}`,
                turn: { turn_id: "l0" },
                correction: true,
                preferred:
                  offset === 0
                    ? "Uncertain correction"
                    : "Preferred synthetic phrase",
                reason: "A synthetic explanation",
                recognition_uncertain: offset === 0,
                superseded: false,
              },
              {
                event_id: `s${offset}`,
                turn: { turn_id: "l0" },
                correction: true,
                preferred: "Superseded correction",
                recognition_uncertain: false,
                superseded: true,
              },
            ]
          : [],
        next_offset: f.uploads.length && offset === 0 ? 50 : null,
      },
    });
  });
  return {
    setDown: (value: boolean) => {
      down = value;
    },
  };
}

test("conversation: server order, recognized text, written feedback and refresh without duplicates", async ({
  page,
}, info) => {
  await media(page);
  const f = await fake(page);
  await records(page, f);
  await open(page);
  const conversation = page.getByRole("region", {
    name: "Session conversation",
  });
  await expect(
    conversation.getByText("Добрий день!", { exact: true }),
  ).toBeVisible();
  await page.evaluate(() => {
    (window as any).voiceTest.hang = true;
  });
  await speak(page, info);
  await expect(
    conversation.getByText("Recognized answer (speech recognition)"),
  ).toHaveCount(1);
  await expect(
    conversation.getByText("<script>learner answer</script>", { exact: true }),
  ).toBeVisible();
  await expect(
    conversation.getByText("Preferred synthetic phrase", { exact: true }),
  ).toBeVisible();
  await expect(
    conversation.getByText("Uncertain correction", { exact: true }),
  ).toHaveCount(0);
  await expect(
    conversation.getByText("Superseded correction", { exact: true }),
  ).toHaveCount(0);
  expect(await conversation.getAttribute("aria-live")).toBe("off");
  await expect(
    page.getByRole("button", { name: "Stop playback", exact: true }),
  ).toBeEnabled();
  await press(page, info, "Stop playback");
  await expect.poll(() => pending(page)).toEqual([]);
  await page.reload();
  await press(page, info, "Open Tickets");
  await expect(
    conversation.getByText("Recognized answer (speech recognition)"),
  ).toHaveCount(1);
  await expect(conversation.locator("ol > li")).toHaveCount(3);
  await noOverlap(page);
});

test("conversation: history failure never blocks saved answer or controls", async ({
  page,
}, info) => {
  await media(page);
  const f = await fake(page);
  const record = await records(page, f);
  await open(page);
  record.setDown(true);
  await speak(page, info);
  await expect(
    page.getByRole("button", { name: "Tap to talk", exact: true }),
  ).toBeEnabled();
  await expect.poll(() => pending(page)).toEqual([]);
  const conversation = page.getByRole("region", {
    name: "Session conversation",
  });
  await expect(
    conversation.getByText(
      "Conversation unavailable. Your accepted answers are saved; retry loading the record.",
    ),
  ).toBeVisible();
  await expect(
    conversation.getByText("Recognized answer (speech recognition)"),
  ).toHaveCount(0);
  record.setDown(false);
  await conversation
    .getByRole("button", { name: "Retry conversation" })
    .click();
  await expect(
    conversation.getByText("Recognized answer (speech recognition)"),
  ).toHaveCount(1);
  await noOverlap(page);
});

test("conversation: permission and actual capture have different cues and a capture-only timer", async ({
  page,
}, info) => {
  await media(page);
  await fake(page);
  await open(page);
  await page.evaluate(() => {
    (window as any).voiceTest.delayedPermission = true;
  });
  await press(page, info, "Tap to talk");
  await expect(page.getByLabel("Microphone state")).toHaveText(
    "Waiting for microphone permission",
  );
  await expect(page.getByLabel("Recording elapsed time")).toHaveCount(0);
  await page.evaluate(() => (window as any).voiceTest.releasePermission());
  await expect(page.getByLabel("Microphone state")).toHaveText(
    "Recording — microphone is on",
  );
  await expect(page.getByLabel("Recording elapsed time")).toHaveText("0:01", {
    timeout: 5000,
  });
  await press(page, info, "Discard this recording");
  await expect(page.getByLabel("Microphone state")).toHaveText(
    "Ready for your answer",
  );
  await expect(page.getByLabel("Recording elapsed time")).toHaveCount(0);
  await noOverlap(page);
});

test("conversation: deferred feedback stays hidden until finish", async ({
  page,
}, info) => {
  await media(page);
  const f = await fake(page);
  await records(page, f);
  await open(page);
  // Restore a saved session with the owner's deferred correction preference.
  await page.evaluate(() => {
    const key = "voice-teacher:v1:learner:sessions";
    const sessions = JSON.parse(localStorage.getItem(key)!);
    sessions[0].start.correction_style = "end_of_session";
    localStorage.setItem(key, JSON.stringify(sessions));
  });
  await page.reload();
  await press(page, info, "Open Tickets");
  await speak(page, info);
  const conversation = page.getByRole("region", {
    name: "Session conversation",
  });
  await expect(
    conversation.getByText("Recognized answer (speech recognition)"),
  ).toHaveCount(1);
  await expect(
    conversation.getByText("Preferred synthetic phrase", { exact: true }),
  ).toHaveCount(0);
  await press(page, info, "Finish session");
  await expect(
    conversation.getByText("Preferred synthetic phrase", { exact: true }),
  ).toBeVisible();
  await noOverlap(page);
});

test("conversation: cancelling pending permission never implies a captured answer", async ({
  page,
}, info) => {
  await media(page);
  const f = await fake(page);
  await open(page);
  await page.evaluate(() => {
    (window as any).voiceTest.delayedPermission = true;
  });
  await press(page, info, "Tap to talk");
  await expect(page.getByLabel("Microphone state")).toHaveText(
    "Waiting for microphone permission",
  );
  await expect(
    page.getByRole("button", { name: "Send answer", exact: true }),
  ).toHaveCount(0);
  await press(page, info, "Cancel microphone request");
  await expect(page.getByLabel("Microphone state")).toHaveText(
    "Ready for your answer",
  );
  await page.evaluate(() => (window as any).voiceTest.releasePermission());
  await expect
    .poll(() => page.evaluate(() => (window as any).voiceTest.activeTracks))
    .toBe(0);
  expect(await page.evaluate(() => (window as any).voiceTest.records)).toBe(0);
  expect(f.uploads).toHaveLength(0);
  await noOverlap(page);
});
