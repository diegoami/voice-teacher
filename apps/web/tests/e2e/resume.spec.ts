import { navigateTo } from "./support/voice";
import { test, expect } from "@playwright/test";
import { media, fake, open, press } from "./support/voice";

test("resume: pause and continue restore the current activity", async ({
  page,
}, info) => {
  await media(page);
  const f = await fake(page);
  await open(page);
  await press(page, info, "Pause session");
  await expect(
    page.getByRole("button", { name: "Continue session", exact: true }),
  ).toBeEnabled();
  await expect(
    page.getByRole("button", { name: "Tap to talk", exact: true }),
  ).toBeDisabled();
  await press(page, info, "Continue session");
  await expect(
    page.getByRole("button", { name: "Tap to talk", exact: true }),
  ).toBeEnabled();
  expect(f.uploads).toHaveLength(0);
});

import { server } from "./support/server";
import { speak, pending, noOverlap } from "./support/voice";

const ticket = "Оди́н квито́к, будь ла́ска.";

test("resume: real process restart and new connection preserve cue, source, profile and step", async ({
  page,
  browser,
}, info) => {
  const service = await server();
  let fresh;
  try {
    await media(page);
    const started = page.waitForResponse(
      (r) =>
        r.url() === service.origin + "/api/v1/sessions" &&
        r.request().method() === "POST",
    );
    await open(page, "guided_conversation", service);
    const id = (await (await started).json()).session_id;
    await page.evaluate(() => {
      (window as any).voiceTest.transcript = "bad";
    });
    await speak(page, info);
    await expect(
      page.getByRole("button", { name: "Tap to talk", exact: true }),
    ).toBeEnabled();
    const cue = await page.getByLabel("Teacher instructions").innerText();
    const before = await service.inspect(id);
    const activity = before.snapshot.engine_state.data.engine.data.current;
    expect(activity.data.state.help).toBe("cue");
    await press(page, info, "Pause session");
    await expect(
      page.getByRole("button", { name: "Continue session", exact: true }),
    ).toBeEnabled();
    await page.reload();
    await expect(
      page.getByText("Your turn: Ask for one ticket.", { exact: true }),
    ).toBeVisible();
    await service.changeSourceAndProfile();
    const oldPID = service.pid;
    const state = await page.context().storageState();
    await page.close();
    await service.restart();
    expect(service.pid).not.toBe(oldPID);
    fresh = await browser.newContext({
      ...info.project.use,
      storageState: state,
    });
    const next = await fresh.newPage();
    await media(next);
    await next.goto(service.origin);
    // A new selection is unrelated to the saved session's source and snapshot.
    await navigateTo(next, "Lessons");
    await next.getByLabel("Lesson source").selectOption("beta");
    await press(next, info, "Open Tickets");
    await expect(
      next.getByText("Your turn: Ask for one ticket.", { exact: true }),
    ).toBeVisible();
    await press(next, info, "Continue session");
    await expect(
      next.getByRole("button", { name: "Tap to talk", exact: true }),
    ).toBeEnabled();
    await expect(next.getByLabel("Teacher instructions")).toHaveText(cue);
    const resumed = await service.inspect(id);
    expect(resumed.snapshot.source).toEqual(before.snapshot.source);
    expect(resumed.snapshot.learner_profile).toEqual({ level: "A2" });
    expect(resumed.snapshot.engine_state.data.engine.data.current).toEqual(
      activity,
    );
    await next.evaluate((t) => {
      (window as any).voiceTest.transcript = t;
    }, ticket);
    await speak(next, info);
    await expect(
      next.getByRole("button", { name: "Continue session", exact: true }),
    ).toBeEnabled();
    await expect(
      next.getByText("This activity is complete.", { exact: false }),
    ).toBeVisible();
    const completed = await service.inspect(id);
    const evidence = completed.events.filter(
      (e: any) => e.event_type === "evidence.recorded",
    );
    expect(evidence).toHaveLength(1);
    expect(evidence[0].evidence.outcome).toBe("cued");
    expect(evidence[0].provenance.original_source).toEqual(
      before.snapshot.source,
    );
    await press(next, info, "Finish session");
    await expect(next.getByText("Session finished and saved.")).toBeVisible();
    const finished = await service.inspect(id);
    const refused = await next.evaluate(
      async ({ id, revision }) => {
        const grant = JSON.parse(
          localStorage.getItem("voice-teacher:grant:v1")!,
        );
        return (
          await fetch("/api/v1/sessions/" + id + "/turns", {
            method: "POST",
            headers: {
              Authorization: "Bearer " + grant.token,
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              request_id: "after-finish",
              expected_revision: revision,
              text: "bad",
            }),
          })
        ).status;
      },
      { id, revision: finished.snapshot.revision },
    );
    expect(refused).toBe(409);
    expect((await service.inspect(id)).events).toEqual(finished.events);
    await noOverlap(next);
  } finally {
    await fresh?.close();
    await service.stop();
  }
});

for (const stage of ["recognition", "judge", "synthesis"]) {
  test(`resume: pause during real ${stage}, kill server and recover one accepted attempt`, async ({
    page,
  }, info) => {
    const service = await server();
    try {
      await media(page);
      const started = page.waitForResponse(
        (r) =>
          r.url() === service.origin + "/api/v1/sessions" &&
          r.request().method() === "POST",
      );
      await open(page, "guided_conversation", service);
      const id = (await (await started).json()).session_id;
      const uploads: (string | null)[] = [];
      page.on("request", (r) => {
        if (
          r.method() === "POST" &&
          new URL(r.url()).pathname.endsWith("/audio")
        )
          uploads.push(new URL(r.url()).searchParams.get("request_id"));
      });
      await page.evaluate((t) => {
        (window as any).voiceTest.transcript = t;
      }, ticket);
      await service.arm(stage);
      await speak(page, info);
      await expect
        .poll(async () => (await service.arrived())?.stage)
        .toBe(stage);
      await press(page, info, "Pause session");
      await expect
        .poll(async () => (await pending(page))[0]?.control)
        .toBe("pause");
      await service.restart();
      await page.reload();
      await expect(
        page.getByRole("button", { name: "Continue session", exact: true }),
      ).toBeEnabled();
      await expect.poll(() => pending(page)).toEqual([]);
      const saved = await service.inspect(id);
      expect(
        saved.events.filter((e: any) => e.event_type === "evidence.recorded"),
      ).toHaveLength(1);
      expect(
        saved.events.filter(
          (e: any) =>
            e.event_type === "turn.accepted" && e.turn.role === "learner",
        ),
      ).toHaveLength(1);
      for (const retry of uploads) expect(retry).toEqual(uploads[0]);
      await press(page, info, "Continue session");
      await expect(
        page.getByRole("button", { name: "Tap to talk", exact: true }),
      ).toBeEnabled();
      expect(
        (await service.inspect(id)).events.filter(
          (e: any) => e.event_type === "evidence.recorded",
        ),
      ).toHaveLength(1);
      await noOverlap(page);
    } finally {
      await service.stop();
    }
  });
}

for (const failure of ["before", "after"]) {
  test(`resume: pause drains a saved recording ${failure} commit without a new attempt ID`, async ({
    page,
  }, info) => {
    await media(page);
    const f = await fake(page);
    await open(page);
    f.setFailure(failure);
    await speak(page, info);
    await expect(page.getByRole("alert")).toBeVisible();
    const original = { ...f.uploads[0] };
    await press(page, info, "Pause session");
    await expect(
      page.getByRole("button", { name: "Continue session", exact: true }),
    ).toBeEnabled();
    expect(f.uploads).toHaveLength(failure === "before" ? 2 : 1);
    for (const upload of f.uploads) expect(upload).toEqual(original);
    expect(f.controls).toHaveLength(1);
    expect(f.controls[0].expected_revision).toBe(1);
    await expect.poll(() => pending(page)).toEqual([]);
    await press(page, info, "Continue session");
    await expect(
      page.getByRole("button", { name: "Tap to talk", exact: true }),
    ).toBeEnabled();
    await noOverlap(page);
  });
}

for (const operation of ["pause", "resume"]) {
  test(`resume: lost ${operation} response preserves the original control ID across refresh`, async ({
    page,
  }, info) => {
    await media(page);
    const f = await fake(page);
    await open(page);
    if (operation === "resume") {
      await press(page, info, "Pause session");
      await expect(
        page.getByRole("button", { name: "Continue session", exact: true }),
      ).toBeEnabled();
    }
    f.setFailure("control-before");
    await press(
      page,
      info,
      operation === "pause" ? "Pause session" : "Continue session",
    );
    await expect(page.getByRole("alert")).toBeVisible();
    const original = { ...f.controls.at(-1) };
    expect((await pending(page))[0].control).toBe(operation);
    await page.reload();
    await expect(
      page.getByText(
        operation === "pause"
          ? "Session paused and saved. Continue when ready."
          : "Session continued from saved progress.",
        { exact: true },
      ),
    ).toBeVisible();
    expect(f.controls.at(-1)).toEqual(original);
    await expect.poll(() => pending(page)).toEqual([]);
  });
}

test("resume: saved request receipt prevents replay after another control changes latest request", async ({
  page,
}, info) => {
  await media(page);
  const f = await fake(page);
  await open(page);
  f.setFailure("after");
  await speak(page, info);
  await expect(page.getByRole("alert")).toBeVisible();
  f.externalAdvance();
  await page.reload();
  await expect(page.getByLabel("Teacher instructions")).toContainText(
    "Externally saved reply",
  );
  await expect.poll(() => pending(page)).toEqual([]);
  expect(f.uploads).toHaveLength(1);
});

test("resume: speech outage still opens saved text and permits pause and continue", async ({
  page,
}, info) => {
  await media(page);
  const f = await fake(page);
  await open(page);
  f.setFailure("tts");
  await page.reload();
  await expect(page.getByLabel("Teacher instructions")).toContainText(
    "Добрий день!",
  );
  await press(page, info, "Pause session");
  await expect(
    page.getByRole("button", { name: "Continue session", exact: true }),
  ).toBeEnabled();
  await press(page, info, "Continue session");
  await expect(
    page.getByRole("button", { name: "Tap to talk", exact: true }),
  ).toBeEnabled();
  expect(f.getStarts()).toBe(1);
});

for (const finish of [false, true]) {
  test(`resume: version-one journal migrates ${finish ? "finish intent" : "recording"} without losing another learner's data`, async ({
    page,
  }, info) => {
    await media(page);
    const f = await fake(page);
    await open(page);
    const id = f.current().session_id;
    await page.evaluate(
      async ({ id, finish }) => {
        const database = "voice-teacher-pending-v1";
        await new Promise<void>((r, j) => {
          const q = indexedDB.deleteDatabase(database);
          q.onsuccess = () => r();
          q.onerror = () => j(q.error);
          q.onblocked = () => j(new Error("blocked"));
        });
        const db = await new Promise<IDBDatabase>((r, j) => {
          const q = indexedDB.open(database, 1);
          q.onupgradeneeded = () =>
            q.result.createObjectStore("pending", { keyPath: "key" });
          q.onsuccess = () => r(q.result);
          q.onerror = () => j(q.error);
        });
        await new Promise<void>((r, j) => {
          const tx = db.transaction("pending", "readwrite");
          const upload = {
            request_id: "legacy-upload",
            expected_revision: 0,
            recording: new Blob(["legacy recording"], { type: "audio/webm" }),
            media_type: "audio/webm",
          };
          tx.objectStore("pending").put({
            key: JSON.stringify(["learner", id]),
            upload,
            finish: finish
              ? { request_id: "legacy-finish", expected_revision: 0 }
              : null,
          });
          tx.objectStore("pending").put({
            key: JSON.stringify(["another", id]),
            upload: { ...upload, request_id: "other-upload" },
            finish: null,
          });
          tx.oncomplete = () => r();
          tx.onabort = tx.onerror = () => j(tx.error);
        });
        db.close();
      },
      { id, finish },
    );
    await page.reload();
    if (finish) {
      await expect(page.getByText("Session finished and saved.")).toBeVisible();
      expect(f.controls[0].request_id).toBe("legacy-finish");
      expect(f.uploads).toHaveLength(0);
    } else {
      await expect(page.getByRole("alert")).toContainText(
        "unfinished recording",
      );
      expect(
        (await pending(page)).find((r) => r.upload === "legacy-upload")?.bytes,
      ).toBe(16);
      await press(page, info, "Recover saved response");
      await expect(
        page.getByRole("button", { name: "Tap to talk", exact: true }),
      ).toBeEnabled();
      expect(f.uploads).toHaveLength(1);
      expect(f.uploads[0]).toMatchObject({
        id: "legacy-upload",
        bytes: Buffer.from("legacy recording").toString("base64"),
        revision: 0,
      });
    }
    const remaining = await pending(page);
    expect(remaining).toHaveLength(1);
    expect(remaining[0].upload).toBe("other-upload");
    expect(JSON.parse(remaining[0].key)[0]).toBe("another");
  });
}
