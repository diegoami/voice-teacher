import { test, expect, Page } from "@playwright/test";
import { server } from "./support/server";

async function connect(page: Page, service: { origin: string; code: string }) {
  await page.goto(service.origin);
  await page.getByLabel("Pairing code").fill(service.code);
  await page.getByRole("button", { name: "Connect and pair" }).click();
  await page.getByLabel("Lesson source").selectOption("alpha");
  await page
    .getByRole("combobox", { name: "Course", exact: true })
    .selectOption("basics");
  await page.getByLabel("Lesson or topic").selectOption("lesson-1");
  await page.getByRole("button", { name: "Load history and progress" }).click();
}
function alpha(page: Page) {
  return page.getByRole("article").filter({ hasText: "alpha / basics" });
}

test("lesson-completion: complete unpractised lesson, choose next, reopen and restart", async ({
  page,
}) => {
  const service = await server({ completion: true });
  try {
    await connect(page, service);
    const course = alpha(page);
    await expect(
      course.getByText("0 of 1 items covered", { exact: true }),
    ).toBeVisible();
    await course
      .getByRole("button", {
        name: "Mark lesson complete: Tickets",
        exact: true,
      })
      .click();
    await expect(
      course.getByText("Next lesson: Second lesson", { exact: true }),
    ).toBeVisible();
    await course
      .getByRole("button", { name: "Continue to next lesson" })
      .click();
    await expect(page.getByLabel("Lesson or topic")).toHaveValue("lesson-2");
    await expect(
      page.getByText("No sessions saved for this learner."),
    ).toBeVisible();
    await service.restart();
    await page.reload();
    await page
      .getByRole("button", { name: "Load history and progress" })
      .click();
    await expect(
      alpha(page).getByText("Completed by you", { exact: false }),
    ).toBeVisible();
    await alpha(page)
      .getByRole("button", { name: "Reopen lesson: Tickets", exact: true })
      .click();
    await expect(
      alpha(page).getByText("Next lesson: Tickets", { exact: true }),
    ).toBeVisible();
    await expect(
      alpha(page).getByText("0 of 1 items covered", { exact: true }),
    ).toBeVisible();
  } finally {
    await service.stop();
  }
});

test("lesson-completion: lost response survives refresh and retries the same intent", async ({
  page,
}) => {
  const service = await server({ completion: true });
  try {
    await connect(page, service);
    const intents: unknown[] = [];
    let lost = false;
    await page.route("**/api/v1/lesson-completions", async (route) => {
      intents.push(route.request().postDataJSON());
      const response = await route.fetch();
      if (!lost) {
        lost = true;
        await route.abort("failed");
      } else await route.fulfill({ response });
    });
    await alpha(page)
      .getByRole("button", {
        name: "Mark lesson complete: Tickets",
        exact: true,
      })
      .click();
    await expect(
      page.getByRole("button", { name: "Retry saved lesson choice" }),
    ).toBeEnabled();
    await page.reload();
    await page
      .getByRole("button", { name: "Retry saved lesson choice" })
      .click();
    await expect(
      alpha(page).getByText("Next lesson: Second lesson", { exact: true }),
    ).toBeVisible();
    expect(intents).toHaveLength(2);
    expect(intents[1]).toEqual(intents[0]);
    await expect(
      page.getByRole("button", { name: "Retry saved lesson choice" }),
    ).toHaveCount(0);
    await expect(
      page.getByText("No sessions saved for this learner."),
    ).toBeVisible();
  } finally {
    await service.stop();
  }
});

test("lesson-completion: imported position is visible and next selection is explicit", async ({
  page,
}) => {
  const service = await server({ completion: true });
  try {
    await connect(page, service);
    await expect(
      page.getByText(
        "historical-course / legacy: historical lessons covered lesson-1. Next: lesson-2.",
        { exact: true },
      ),
    ).toBeVisible();
    await expect(page.getByLabel("Lesson or topic")).toHaveValue("lesson-1");
    await page
      .getByRole("button", {
        name: "Use imported next lesson in selected course",
      })
      .click();
    await expect(page.getByLabel("Lesson or topic")).toHaveValue("lesson-2");
    await expect(
      alpha(page).getByText("Next lesson: Tickets", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("No sessions saved for this learner."),
    ).toBeVisible();
  } finally {
    await service.stop();
  }
});

test("lesson-completion: a different paired learner cannot see or replay pending choices", async ({
  page,
}) => {
  const service = await server({ completion: true });
  try {
    await connect(page, service);
    await page.route("**/api/v1/lesson-completions", (route) =>
      route.abort("failed"),
    );
    await alpha(page)
      .getByRole("button", {
        name: "Mark lesson complete: Tickets",
        exact: true,
      })
      .click();
    await expect(
      page.getByRole("button", { name: "Retry saved lesson choice" }),
    ).toBeEnabled();
    const code = await page.request.post(
      service.origin + "/api/v1/operator/pairing-codes",
      {
        headers: {
          Authorization: "Bearer synthetic-operator-" + "x".repeat(40),
        },
        data: {
          learner_id: "other-learner",
          label: "Synthetic ownership check",
        },
      },
    );
    expect(code.ok()).toBeTruthy();
    const paired = await page.request.post(service.origin + "/api/v1/pair", {
      data: { code: (await code.json()).code },
    });
    expect(paired.ok()).toBeTruthy();
    const grant = await paired.json();
    await page.evaluate(
      (value) =>
        localStorage.setItem("voice-teacher:grant:v1", JSON.stringify(value)),
      grant,
    );
    await page.reload();
    await page
      .getByRole("button", { name: "Load history and progress" })
      .click();
    await expect(
      page.getByRole("button", { name: "Retry saved lesson choice" }),
    ).toHaveCount(0);
    await expect(
      alpha(page).getByText("Next lesson: Tickets", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("historical-course / legacy:", { exact: false }),
    ).toHaveCount(0);
  } finally {
    await service.stop();
  }
});
