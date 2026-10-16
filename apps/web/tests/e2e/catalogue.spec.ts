import { test, expect, Page } from "@playwright/test";
const code = "synthetic-pairing-code-".repeat(3),
  token = "synthetic-client-token-".repeat(3);
async function fake(page: Page) {
  const starts: any[] = [];
  let failSources = false,
    failStart = false,
    failStartBefore = false;
  const sessions = new Map();
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname;
    let result: any,
      status = 200;
    if (path === "/api/v1/pair") {
      expect(request.postDataJSON()).toEqual({ code });
      result = {
        token,
        client_id: "client-one",
        learner_id: "learner-one",
        expires_at: Date.now() / 1000 + 3600,
      };
    } else {
      expect(request.headers().authorization).toBe("Bearer " + token);
      expect(request.headers().cookie).toBeUndefined();
      if (path.endsWith("/identity")) result = { learner_id: "learner-one" };
      else if (path.endsWith("/sources")) {
        if (failSources) {
          status = 503;
          result = { error: { message: "RAW_PRIVATE_BACKEND_DETAILS" } };
        } else
          result = [
            {
              source_id: "alpha",
              name: "Travel Ukrainian",
              version_id: "revision-alpha-1",
              available: true,
            },
            {
              source_id: "beta",
              name: "Everyday phrases",
              version_id: "revision-beta-2",
              available: true,
            },
          ];
      } else if (path.endsWith("/courses"))
        result = [
          {
            course_id: "shared-course",
            title: "Course A",
            language: "uk",
            instruction_language: "en",
          },
        ];
      else if (path.endsWith("/lessons"))
        result = [
          {
            lesson_id: "shared-lesson",
            title: path.includes("/alpha/")
              ? "At the station"
              : "At the market",
            authored_modes: ["guided_conversation", "repetition"],
            available_modes: path.includes("/alpha/")
              ? ["guided_conversation"]
              : ["repetition"],
          },
        ];
      else if (path === "/api/v1/sessions") {
        const body = request.postDataJSON();
        starts.push(body);
        const entry = {
          session_id: body.session_id,
          request_id: null,
          revision: 0,
          status: "active",
          done: false,
          card:
            body.source_id === "alpha"
              ? "Ask about a ticket"
              : "Repeat the phrase",
          teacher: [{ text: "Привіт!", kind: "teacher" }],
          audio_ids: [],
        };
        if (!failStartBefore) sessions.set(body.session_id, entry);
        result = entry;
        status = 201;
        if (failStart || failStartBefore) {
          status = 502;
          result = { error: { message: "RAW_PRIVATE_BACKEND_DETAILS" } };
        }
      } else if (path.startsWith("/api/v1/sessions/")) {
        result = sessions.get(path.split("/").at(-1));
        if (!result) {
          status = 404;
          result = {};
        }
      } else {
        status = 404;
        result = {};
      }
    }
    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(result),
    });
  });
  return {
    starts,
    setFailSources: (v: boolean) => (failSources = v),
    setFailStart: (v: boolean) => (failStart = v),
    setFailStartBefore: (v: boolean) => (failStartBefore = v),
  };
}
async function pair(page: Page) {
  await page.goto("/");
  await page.getByLabel("Pairing code").fill(code);
  await page.getByRole("button", { name: "Connect and pair" }).click();
  await expect(page.getByText("Paired learner:")).toContainText("learner-one");
}
async function choose(page: Page, source: string) {
  await page.getByLabel("Lesson source").selectOption(source);
  await page
    .getByRole("combobox", { name: "Course", exact: true })
    .selectOption("shared-course");
  await page.getByLabel("Lesson or topic").selectOption("shared-lesson");
}

test("catalogue: two sources, supported modes and pinned saved session survive selection and refresh", async ({
  page,
}) => {
  const f = await fake(page);
  await pair(page);
  await choose(page, "alpha");
  await page.getByRole("button", { name: "Start practice" }).click();
  await expect(
    page.getByRole("heading", { name: "Session ready" }),
  ).toBeVisible();
  const original = f.starts[0];
  expect(original).toMatchObject({
    source_id: "alpha",
    course_id: "shared-course",
    lesson_id: "shared-lesson",
    mode: "guided_conversation",
  });
  await choose(page, "beta");
  await page.getByRole("radio", { name: "Repetition", exact: false }).check();
  await page.getByRole("button", { name: "Start practice" }).click();
  expect(f.starts[1]).toMatchObject({ source_id: "beta", mode: "repetition" });
  await page.reload();
  await expect(page.getByLabel("Lesson source")).toHaveValue("beta");
  await expect(page.getByLabel("Lesson or topic")).toHaveValue("shared-lesson");
  await expect(
    page.getByRole("radio", { name: "Repetition", exact: false }),
  ).toBeChecked();
  await page
    .getByRole("button", { name: "Open At the station", exact: true })
    .click();
  await expect(
    page.getByText("Ask about a ticket", { exact: true }),
  ).toBeVisible();
  expect(f.starts).toHaveLength(2);
});
test("catalogue: unsupported mode explains availability and catalogue errors recover", async ({
  page,
}) => {
  const f = await fake(page);
  f.setFailSources(true);
  await pair(page);
  await expect(page.getByRole("alert")).toContainText(
    "server could not complete",
  );
  await expect(page.getByRole("alert")).not.toContainText("RAW_PRIVATE");
  f.setFailSources(false);
  await page
    .getByRole("button", { name: "Retry connection and catalogue" })
    .click();
  await choose(page, "alpha");
  await page
    .getByRole("radio", { name: "Free conversation", exact: false })
    .check();
  await expect(
    page.getByText("This lesson does not include this mode."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Start practice" }),
  ).toBeDisabled();
  await page.getByRole("radio", { name: "Repetition", exact: false }).check();
  await expect(
    page.getByText(
      "Available in this lesson when the server enables this mode.",
    ),
  ).toBeVisible();
  expect(f.starts).toHaveLength(0);
});
test("catalogue: saved first response recovers after a failed start without another POST", async ({
  page,
}) => {
  const f = await fake(page);
  await pair(page);
  await choose(page, "alpha");
  f.setFailStart(true);
  await page.getByRole("button", { name: "Start practice" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.reload();
  await page
    .getByRole("button", { name: "Open At the station", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Session ready" }),
  ).toBeVisible();
  expect(f.starts).toHaveLength(1);
});
test("catalogue: identity revocation clears access and re-pairing keeps sessions separated", async ({
  page,
}) => {
  await fake(page);
  await pair(page);
  await choose(page, "alpha");
  await page.getByRole("button", { name: "Start practice" }).click();
  await page.route("**/api/v1/identity", (route) =>
    route.fulfill({ status: 401, body: "{}", contentType: "application/json" }),
  );
  await page.reload();
  await expect(page.getByLabel("Pairing code")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Your lessons" })).toHaveCount(
    0,
  );
  await page.unroute("**/api/v1/identity");
  await page.route("**/api/v1/identity", (route) =>
    route.fulfill({
      status: 200,
      body: JSON.stringify({ learner_id: "learner-two" }),
      contentType: "application/json",
    }),
  );
  await page.route("**/api/v1/pair", (route) =>
    route.fulfill({
      status: 200,
      body: JSON.stringify({
        token,
        client_id: "client-two",
        learner_id: "learner-two",
        expires_at: Date.now() / 1000 + 3600,
      }),
      contentType: "application/json",
    }),
  );
  await page.getByLabel("Pairing code").fill(code);
  await page.getByRole("button", { name: "Connect and pair" }).click();
  await expect(
    page.getByText("No sessions started on this device yet."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Open At the station" }),
  ).toHaveCount(0);
});
test("catalogue: server change navigates without forwarding pairing credentials", async ({
  page,
}) => {
  await fake(page);
  await page.route("https://other.example/**", async (route) => {
    expect(route.request().headers().authorization).toBeUndefined();
    expect(route.request().postData()).toBeNull();
    await route.fulfill({
      contentType: "text/html",
      body: "<h1>Other server</h1>",
    });
  });
  await pair(page);
  await page.getByLabel("Server address").fill("https://other.example");
  await page
    .getByRole("button", { name: "Open server address", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Other server" }),
  ).toBeVisible();
});
test("catalogue: keyboard selection, touch-sized controls and no horizontal overflow", async ({
  page,
}, info) => {
  const f = await fake(page);
  await pair(page);
  const source = page.getByLabel("Lesson source");
  await source.focus();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(source).toHaveValue("alpha");
  await page
    .getByRole("combobox", { name: "Course", exact: true })
    .selectOption("shared-course");
  await page.getByLabel("Lesson or topic").selectOption("shared-lesson");
  await page
    .getByRole("radio", { name: "Guided conversation", exact: false })
    .focus();
  await page.keyboard.press("Space");
  await page.getByRole("button", { name: "Start practice" }).focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { name: "Session ready" }),
  ).toBeVisible();
  expect(f.starts).toHaveLength(1);
  if (info.project.name === "android") {
    await page.getByRole("radio", { name: "Repetition", exact: false }).tap();
    await expect(
      page.getByRole("button", { name: "Start practice" }),
    ).toBeDisabled();
    await page
      .getByRole("radio", { name: "Guided conversation", exact: false })
      .tap();
    await page.getByRole("button", { name: "Start practice" }).tap();
    await expect.poll(() => f.starts.length).toBe(2);
  }
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  const box = await page
    .getByRole("button", { name: "Start practice" })
    .boundingBox();
  expect(box!.height).toBeGreaterThanOrEqual(44);
  await page.screenshot({
    path: info.outputPath("catalogue.png"),
    fullPage: true,
  });
});
test("catalogue: manifest, icons and Chromium installability checks", async ({
  page,
  context,
}) => {
  await page.goto("/");
  const manifest = await (
    await page.request.get("/manifest.webmanifest")
  ).json();
  expect(manifest).toMatchObject({
    name: "Voice Teacher",
    display: "standalone",
    start_url: "/",
    scope: "/",
  });
  expect(manifest.icons.map((i: any) => i.sizes)).toEqual([
    "192x192",
    "512x512",
  ]);
  for (const icon of manifest.icons) {
    const response = await page.request.get(icon.src);
    expect(response.ok()).toBe(true);
    expect(response.headers()["content-type"]).toContain("image/png");
  }
  const cdp = await context.newCDPSession(page);
  const result = await cdp.send("Page.getInstallabilityErrors");
  expect(result.installabilityErrors).toEqual([]);
});

test("resume: missing saved start retries the original source, mode and session ID after GET 404", async ({
  page,
}) => {
  const f = await fake(page);
  await pair(page);
  await choose(page, "alpha");
  f.setFailStartBefore(true);
  await page
    .getByRole("button", { name: "Start practice", exact: true })
    .click();
  await expect(page.getByRole("alert")).toBeVisible();
  const original = { ...f.starts[0] };
  f.setFailStartBefore(false);
  await page.reload();
  await choose(page, "beta");
  await page.getByRole("radio", { name: "Repetition", exact: true }).check();
  const missing = page.waitForResponse((r) =>
    r.url().endsWith("/sessions/" + original.session_id),
  );
  await page
    .getByRole("button", { name: "Open At the station", exact: true })
    .click();
  expect((await missing).status()).toBe(404);
  await expect(
    page.getByRole("heading", { name: "Session ready", exact: true }),
  ).toBeVisible();
  expect(f.starts).toHaveLength(2);
  expect(f.starts[1]).toEqual(original);
});
