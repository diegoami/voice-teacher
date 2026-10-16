import { test, expect, Page } from "@playwright/test";
import { media, fake, open, press, speak } from "./support/voice";
import { server } from "./support/server";

function source(id: string) {
  return {
    source_id: id,
    course_id: "shared-course",
    lesson_id: "lesson-1",
    revision: {
      commit: null,
      content_sha256: (id === "alpha" ? "a" : "b").repeat(64),
      dirty: true,
    },
  };
}
async function history(page: Page) {
  let stage = 0,
    failed = false,
    expired = false;
  const course = (id: string, covered: number) => ({
    source_id: id,
    course_id: "shared-course",
    content_sha256: source(id).revision.content_sha256,
    title: "Shared course",
    required_items: 1,
    covered_items: covered,
    next_lesson_id: covered ? null : "lesson-1",
    lessons: [
      {
        lesson_id: "lesson-1",
        title: id + " lesson",
        required_items: 1,
        covered_items: covered,
        covered: Boolean(covered),
      },
    ],
  });
  const count = () => ({
    locally_saved: stage === 0 ? 3 : stage === 3 ? 1 : 0,
    exported: stage === 1 ? 3 : 0,
    pushed: stage >= 2 ? 3 : 0,
  });
  const view = () => ({
    criterion:
      "Item coverage includes repeated and cued practice; it does not measure mastery. Free observations do not advance the course.",
    courses: [course("alpha", 1), course("beta", 0)],
    sessions: [
      {
        session_id: "alpha-stopped",
        title: "Stopped practice",
        mode: "repetition",
        status: "finished",
        source: source("alpha"),
        updated_at: "2026-10-16T10:00:00Z",
        accepted_turns: 1,
        ...count(),
      },
      {
        session_id: "beta-partial",
        title: "Interrupted practice",
        mode: "guided_conversation",
        status: "paused",
        source: source("beta"),
        updated_at: "2026-10-16T09:00:00Z",
        accepted_turns: 2,
        ...count(),
      },
      {
        session_id: "free",
        title: "Travel topic",
        mode: "free_conversation",
        status: "finished",
        source: null,
        updated_at: "2026-10-16T08:00:00Z",
        accepted_turns: 1,
        ...count(),
      },
    ],
    more_sessions: false,
    sync: {
      configured: true,
      ...count(),
      last_push_at: stage >= 2 ? "2026-10-16T11:00:00Z" : null,
      error: stage === 1 ? "Sync failed; local progress is retained." : null,
    },
  });
  await page.route("**/api/v1/progress?*", async (route) => {
    await route.fulfill({
      status: expired ? 401 : failed ? 502 : 200,
      contentType: "application/json",
      body: JSON.stringify(
        expired || failed
          ? { error: { message: "RAW_PRIVATE_BACKEND_DETAILS" } }
          : view(),
      ),
    });
  });
  await page.route("**/api/v1/sessions/*/evidence?*", async (route) => {
    const sid = new URL(route.request().url()).pathname.split("/")[4];
    const row = (id: string, outcome: string, correction = false) => ({
      event_id: id,
      session_id: sid,
      turn: {
        turn_id: "turn-" + id,
        role: "learner",
        text: "Synthetic attempt " + id,
      },
      outcome,
      attempt: "Synthetic attempt " + id,
      preferred: correction ? "Supported preferred form" : null,
      reason: correction ? "Supported wording correction" : null,
      recognition_uncertain: sid === "free",
      correction,
      assistance: {
        kind:
          outcome === "independent"
            ? "none"
            : correction
              ? "correction"
              : "model",
        help_level: 0,
        target_exposed: outcome !== "independent",
      },
      provenance: {
        original_source: sid === "free" ? null : source("alpha"),
        original_item:
          sid === "free"
            ? null
            : {
                source_id: "alpha",
                course_id: "shared-course",
                item_id: "hello",
                item_revision: 1,
              },
        practice_source: sid === "free" ? null : source("beta"),
        origin_session_id: sid,
        origin_turn_id: "turn-" + id,
      },
      superseded: false,
    });
    const rows =
      sid === "free"
        ? [
            {
              ...row("observed", "observed"),
              preferred: "Unconfirmed suggested expression",
              reason: "Recognition may have omitted a word",
            },
          ]
        : [
            row("repeat", "repeated"),
            row("independent", "independent"),
            row("correction", "corrected_repeated", true),
          ];
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ session_id: sid, rows, next_offset: null }),
    });
  });
  await page.route("**/api/v1/sessions/*/transcript", async (route) => {
    const rows = ["repeat", "independent", "correction", "observed"].map(
      (id) => ({
        turn_id: "turn-" + id,
        role: "learner",
        text: "Synthetic attempt " + id,
      }),
    );
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(rows),
    });
  });
  return {
    setStage: (s: number) => (stage = s),
    fail: () => (failed = true),
    recover: () => (failed = false),
    expire: () => (expired = true),
  };
}

test("progress: separate course positions, provenance and supported-turn links", async ({
  page,
}, info) => {
  await media(page);
  await fake(page);
  await history(page);
  await open(page);
  await press(page, info, "Load history and progress");
  const panel = page.getByRole("region", { name: "History and progress" });
  await expect(
    panel.getByText("alpha / shared-course", { exact: false }).first(),
  ).toBeVisible();
  await expect(
    panel.getByText("beta / shared-course", { exact: false }).first(),
  ).toBeVisible();
  await expect(
    panel.getByText("1 of 1 items covered", { exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByText("0 of 1 items covered", { exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByText("Next lesson with uncovered material: beta lesson", {
      exact: true,
    }),
  ).toBeVisible();
  await press(page, info, "Evidence for Interrupted practice");
  const evidence = page.getByRole("article", { name: "Session evidence" });
  await expect(
    evidence.getByText("Repeated after a model", { exact: true }),
  ).toBeVisible();
  await expect(
    evidence.getByText("Independent use", { exact: true }),
  ).toBeVisible();
  await expect(
    evidence.getByText("Supported correction: Supported preferred form", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    evidence
      .getByText("Original: alpha / shared-course", { exact: false })
      .first(),
  ).toBeVisible();
  await expect(
    evidence
      .getByText("Later practice: beta / shared-course", { exact: false })
      .first(),
  ).toBeVisible();
  const links = evidence.getByRole("link", {
    name: "Supporting learner turn",
    exact: true,
  });
  expect(await links.count()).toBe(3);
  for (let i = 0; i < 3; i++) {
    await links.nth(i).click();
    const target = await links.nth(i).getAttribute("href");
    await expect(page.locator(target!)).toContainText("Synthetic attempt");
  }
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await panel.screenshot({ path: info.outputPath("progress.png") });
});

test("progress: stopped and partial sessions remain visible and free observations stay separate", async ({
  page,
}, info) => {
  await media(page);
  await fake(page);
  await history(page);
  await open(page);
  await press(page, info, "Load history and progress");
  const panel = page.getByRole("region", { name: "History and progress" });
  await expect(
    panel.getByText("finished · repetition · 1 saved response", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    panel.getByText("paused · guided conversation · 2 saved responses", {
      exact: true,
    }),
  ).toBeVisible();
  await press(page, info, "Evidence for Travel topic");
  const evidence = page.getByRole("article", { name: "Session evidence" });
  await expect(
    evidence.getByText("Observed use", { exact: true }),
  ).toBeVisible();
  await expect(
    evidence.getByText("recognition uncertain", { exact: false }),
  ).toBeVisible();
  await expect(
    evidence.getByText("Supported correction:", { exact: false }),
  ).toHaveCount(0);
  await expect(
    evidence.getByText(
      "Unconfirmed suggested form: Unconfirmed suggested expression",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(
    evidence.getByRole("link", {
      name: "Supporting learner turn",
      exact: true,
    }),
  ).toHaveCount(1);
});

test("progress: failed sync and retry distinguish local, exported and pushed records", async ({
  page,
}, info) => {
  await media(page);
  await fake(page);
  const f = await history(page);
  await open(page);
  await press(page, info, "Load history and progress");
  const panel = page.getByRole("region", { name: "History and progress" });
  await expect(
    panel
      .getByText("3 locally saved · 0 exported · 0 pushed", { exact: true })
      .first(),
  ).toBeVisible();
  f.setStage(1);
  await press(page, info, "Refresh history");
  await expect(
    panel
      .getByText("0 locally saved · 3 exported · 0 pushed", { exact: true })
      .first(),
  ).toBeVisible();
  await expect(
    panel.getByText("Sync failed; local progress is retained.", {
      exact: true,
    }),
  ).toBeVisible();
  f.setStage(2);
  await press(page, info, "Refresh history");
  await expect(
    panel
      .getByText("0 locally saved · 0 exported · 3 pushed", { exact: true })
      .first(),
  ).toBeVisible();
  await expect(
    panel.getByText("Last confirmed push:", { exact: false }),
  ).toBeVisible();
  f.setStage(3);
  await press(page, info, "Refresh history");
  await expect(
    panel
      .getByText("1 locally saved · 0 exported · 3 pushed", { exact: true })
      .first(),
  ).toBeVisible();
});

test("progress: unavailable history retries safely and revoked access clears the view", async ({
  page,
}, info) => {
  await media(page);
  await fake(page);
  const f = await history(page);
  await open(page);
  f.fail();
  await press(page, info, "Load history and progress");
  const panel = page.getByRole("region", { name: "History and progress" });
  await expect(panel.getByRole("alert")).toContainText("Please retry");
  await expect(panel).not.toContainText("RAW_PRIVATE");
  f.recover();
  await press(page, info, "Load history and progress");
  await expect(panel.getByText("Backup state", { exact: true })).toBeVisible();
  f.expire();
  await press(page, info, "Refresh history");
  await expect(
    page.getByRole("button", { name: "Connect and pair", exact: true }),
  ).toBeVisible();
  await expect(panel).toHaveCount(0);
});

test("progress: actual server history connects accepted evidence to the saved transcript", async ({
  page,
}, info) => {
  const service = await server();
  try {
    await media(page);
    await open(page, "repetition", service);
    await page.evaluate(() => {
      (window as any).voiceTest.transcript = "Оди́н квито́к, будь ла́ска.";
    });
    await speak(page, info);
    await expect(
      page
        .getByRole("region", { name: "Session ready" })
        .getByText("finished", { exact: true }),
    ).toBeVisible();
    await press(page, info, "Load history and progress");
    const panel = page.getByRole("region", { name: "History and progress" });
    await expect(
      panel.getByText("1 of 1 items covered", { exact: true }),
    ).toBeVisible();
    await expect(
      panel.getByText("Remote progress sync is not configured.", {
        exact: true,
      }),
    ).toBeVisible();
    await panel.getByRole("button", { name: /Evidence for Tickets/ }).click();
    const evidence = page.getByRole("article", { name: "Session evidence" });
    await expect(
      evidence.getByText("Repeated after a model", { exact: true }),
    ).toBeVisible();
    await expect(
      evidence.getByText("Assistance: model · target was offered", {
        exact: true,
      }),
    ).toBeVisible();
    const link = evidence.getByRole("link", {
      name: "Supporting learner turn",
      exact: true,
    });
    await link.click();
    await expect(
      page.locator((await link.getAttribute("href"))!),
    ).toContainText("Один квиток");
  } finally {
    await service.stop();
  }
});
