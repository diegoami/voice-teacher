import { test, expect } from "@playwright/test";
import { media, fake, open } from "./support/voice";

test("legacy archive: distinguish records, render safe text, preserve provenance and retry", async ({
  page,
}) => {
  await media(page);
  await fake(page);
  const entry = {
    archive_id: "a".repeat(64),
    title: "Synthetic legacy A",
    record_kind: "transcript",
    source_label: "synthetic/session.md",
    source_date: "2026-01-02",
    source_sha256: "b".repeat(64),
    counts: { proposed: 1, unresolved: 2, conflict: 0 },
    imports: ["c".repeat(64)],
  };
  let unavailable = false;
  await page.route("**/api/v1/legacy-history", (route) =>
    route.fulfill({
      json: {
        configured: true,
        records: [
          entry,
          {
            ...entry,
            archive_id: "d".repeat(64),
            title: "Synthetic tracker",
            record_kind: "tracker",
          },
          {
            ...entry,
            archive_id: "e".repeat(64),
            title: "Synthetic notes",
            record_kind: "summary",
          },
        ],
      },
    }),
  );
  await page.route("**/api/v1/legacy-history/*", (route) =>
    route.fulfill(
      unavailable
        ? { status: 503, body: "{}" }
        : {
            json: {
              ...entry,
              text: "Learner: <script>window.archiveExecuted=true</script>\nTeacher: Synthetic reply",
              supporting_groups: [
                {
                  import_id: "c",
                  observation_id: "legacy-group",
                  record_ids: ["record-1"],
                  original_source: {
                    source_id: "original",
                    course_id: "course",
                    lesson_id: "A",
                  },
                  practice_source: {
                    source_id: "later",
                    course_id: "course",
                    lesson_id: "B",
                  },
                },
              ],
            },
          },
    ),
  );
  await open(page);
  const archive = page.getByRole("region", { name: "Legacy session archive" });
  await archive.getByRole("button", { name: "Load legacy archive" }).click();
  for (const label of [
    "Transcript (as labelled in the source)",
    "Tracker reference — not a session transcript",
    "Session summary or notes — no separate transcript identified",
  ])
    await expect(archive.getByText(label, { exact: true })).toBeVisible();
  await archive
    .getByRole("button", { name: "Read Synthetic legacy A" })
    .click();
  await expect(archive.locator("pre")).toContainText(
    "<script>window.archiveExecuted=true</script>",
  );
  expect(
    await page.evaluate(() => (window as any).archiveExecuted),
  ).toBeUndefined();
  await expect(
    archive.getByText(/1 proposed records · 2 unresolved · 0 conflicting/),
  ).toBeVisible();
  await archive
    .getByText("Source provenance and supporting groups", { exact: true })
    .click();
  await expect(
    archive.getByText("Original: original / course / A", { exact: true }),
  ).toBeVisible();
  await expect(
    archive.getByText("Practice: later / course / B", { exact: true }),
  ).toBeVisible();
  unavailable = true;
  await archive
    .getByRole("button", { name: "Read Synthetic legacy A" })
    .click();
  await expect(archive.getByRole("alert")).toContainText(
    "Retained records have not been changed",
  );
  await expect(archive.locator("pre")).toHaveCount(0);
  unavailable = false;
  await archive.getByRole("button", { name: "Retry legacy history" }).click();
  await expect(archive.locator("pre")).toContainText("Synthetic reply");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.reload();
  await page.getByRole("button", { name: "Load legacy archive" }).click();
  await expect(
    archive.getByText("Transcript (as labelled in the source)", {
      exact: true,
    }),
  ).toBeVisible();
});

test("legacy archive: absent configuration and empty owner archive are distinct", async ({
  page,
}) => {
  await media(page);
  await fake(page);
  let configured = false;
  await page.route("**/api/v1/legacy-history", (route) =>
    route.fulfill({ json: { configured, records: [] } }),
  );
  await open(page);
  const archive = page.getByRole("region", { name: "Legacy session archive" });
  await archive.getByRole("button", { name: "Load legacy archive" }).click();
  await expect(
    archive.getByText("The legacy archive is not configured on this server."),
  ).toBeVisible();
  configured = true;
  await archive.getByRole("button", { name: "Refresh legacy archive" }).click();
  await expect(
    archive.getByText(
      "No retained legacy records are available for this learner.",
    ),
  ).toBeVisible();
});
