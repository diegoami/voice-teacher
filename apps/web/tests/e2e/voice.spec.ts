import { test, expect, Page, TestInfo } from "@playwright/test";
const token = "synthetic-client-token-".repeat(3),
  code = "synthetic-pair-code-".repeat(3);
async function media(page: Page) {
  await page.addInitScript(() => {
    const state = {
      denied: false,
      delayedPermission: false,
      releasePermission: null as null | (() => void),
      unsupported: false,
      empty: false,
      blocked: false,
      hang: false,
      activeTracks: 0,
      activePlayers: 0,
      overlaps: 0,
      records: 0,
      plays: 0,
    };
    (window as any).voiceTest = state;
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: async () => {
          if (state.delayedPermission)
            await new Promise<void>((resolve) => {
              state.releasePermission = resolve;
            });
          if (state.denied) throw new DOMException("denied", "NotAllowedError");
          state.activeTracks++;
          if (state.activePlayers) state.overlaps++;
          let live = true;
          return {
            getTracks: () => [
              {
                stop: () => {
                  if (live) {
                    live = false;
                    state.activeTracks--;
                  }
                },
              },
            ],
          };
        },
      },
    });
    class Recorder {
      static isTypeSupported() {
        return !state.unsupported;
      }
      state = "inactive";
      mimeType: string;
      ondataavailable: any;
      onstop: any;
      onerror: any;
      constructor(_stream: any, options: any) {
        this.mimeType = options.mimeType;
      }
      start() {
        this.state = "recording";
        state.records++;
      }
      stop() {
        if (this.state === "inactive") return;
        this.state = "inactive";
        setTimeout(() => {
          this.ondataavailable?.({
            data: new Blob(state.empty ? [] : ["synthetic recording"], {
              type: this.mimeType,
            }),
          });
          this.onstop?.();
        }, 0);
      }
    }
    (window as any).MediaRecorder = Recorder;
    class Player {
      onended: any;
      onerror: any;
      live = false;
      constructor(_url: string) {}
      async play() {
        state.plays++;
        if (state.blocked) throw new DOMException("blocked", "NotAllowedError");
        this.live = true;
        state.activePlayers++;
        if (state.activeTracks || state.activePlayers > 1) state.overlaps++;
        if (!state.hang)
          setTimeout(() => {
            if (this.live) {
              this.pause();
              this.onended?.();
            }
          }, 30);
      }
      pause() {
        if (this.live) {
          this.live = false;
          state.activePlayers--;
        }
      }
    }
    (window as any).Audio = Player;
  });
}
async function fake(page: Page) {
  const uploads: {
      id: string;
      revision: number;
      bytes: string;
      type: string;
    }[] = [],
    controls: any[] = [];
  let pendingAnswer: any = null;
  let current: any = null,
    mode = "guided_conversation",
    failure = "",
    starts = 0;
  let multiple = false;
  const answer = (id: string) => ({
    ...current,
    request_id: id,
    revision: current.revision + 1,
    teacher: [{ text: "Ось квиток.", kind: "line" }],
    audio_ids: ["reply"],
  });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      url = new URL(request.url()),
      path = url.pathname;
    let result: any = {},
      status = 200;
    if (path.endsWith("/pair"))
      result = {
        token,
        client_id: "client",
        learner_id: "learner",
        expires_at: Date.now() / 1000 + 3600,
      };
    else {
      expect(request.headers().authorization).toBe("Bearer " + token);
      expect(request.headers().cookie).toBeUndefined();
      if (path.endsWith("/identity")) result = { learner_id: "learner" };
      else if (path.endsWith("/sources"))
        result = [
          {
            source_id: "alpha",
            name: "Synthetic lessons",
            version_id: "one",
            available: true,
          },
        ];
      else if (path.endsWith("/courses"))
        result = [
          {
            course_id: "basics",
            title: "Basics",
            language: "uk",
            instruction_language: "en",
          },
        ];
      else if (path.endsWith("/lessons"))
        result = [
          {
            lesson_id: "ticket",
            title: "Tickets",
            authored_modes: ["guided_conversation", "repetition"],
            available_modes: ["guided_conversation", "repetition"],
          },
        ];
      else if (path === "/api/v1/sessions") {
        starts++;
        const body = request.postDataJSON();
        mode = body.mode;
        current = {
          session_id: body.session_id,
          request_id: null,
          revision: 0,
          status: "active",
          done: false,
          card:
            mode === "repetition"
              ? "Repeat what you hear"
              : "Ask for one ticket",
          teacher: [{ text: "Добрий день!", kind: "line" }],
          audio_ids: multiple ? ["intro", "second"] : ["intro"],
        };
        result = current;
        status = 201;
      } else if (path.endsWith("/audio") && request.method() === "POST") {
        const id = url.searchParams.get("request_id")!,
          revision = Number(url.searchParams.get("expected_revision"));
        uploads.push({
          id,
          revision,
          bytes: request.postDataBuffer()!.toString("base64"),
          type: request.headers()["content-type"],
        });
        if (failure === "before") {
          failure = "";
          await route.abort("failed");
          return;
        }
        pendingAnswer = answer(id);
        if (failure !== "pending") current = pendingAnswer;
        if (failure === "after") {
          failure = "";
          await route.abort("failed");
          return;
        }
        if (failure === "pending") {
          // Simulate a turn committing while a finish request races it.
          await new Promise<void>((resolve) => {
            release = resolve;
          });
          try {
            await route.fulfill({
              contentType: "application/json",
              body: JSON.stringify(current),
            });
          } catch {}
          return;
        }
        result = current;
      } else if (path.includes("/audio/")) {
        expect(url.searchParams.get("revision")).toBe(String(current.revision));
        await route.fulfill({
          contentType: "audio/mpeg",
          body: Buffer.from("synthetic teacher audio"),
        });
        return;
      } else if (path.endsWith("/controls")) {
        const body = request.postDataJSON();
        controls.push(body);
        if (failure === "finish-before") {
          failure = "";
          await route.abort("failed");
          return;
        }
        if (failure === "pending") {
          failure = "";
          current = pendingAnswer;
          release?.();
          status = 409;
        } else {
          expect(body.expected_revision).toBe(current.revision);
          current = {
            ...current,
            request_id: body.request_id,
            revision: current.revision + 1,
            done: true,
            status: "finished",
            teacher: [{ text: "Заняття закінчено.", kind: "close" }],
            audio_ids: [],
          };
          result = current;
          if (failure === "finish-after") {
            failure = "";
            await route.abort("failed");
            return;
          }
        }
      } else if (path.startsWith("/api/v1/sessions/")) result = current;
      else status = 404;
    }
    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(result),
    });
  });
  let release: (() => void) | undefined;
  return {
    uploads,
    controls,
    setMultiple: () => {
      multiple = true;
    },
    setFailure: (v: string) => {
      failure = v;
    },
    getStarts: () => starts,
    externalAdvance: () => {
      current = {
        ...current,
        request_id: "external-turn",
        revision: current.revision + 1,
        teacher: [{ text: "Externally saved reply", kind: "reply" }],
      };
    },
  };
}
async function open(page: Page, mode = "guided_conversation") {
  await page.goto("/");
  await page.getByLabel("Pairing code").fill(code);
  await page.getByRole("button", { name: "Connect and pair" }).click();
  await page.getByLabel("Lesson source").selectOption("alpha");
  await page
    .getByRole("combobox", { name: "Course", exact: true })
    .selectOption("basics");
  await page.getByLabel("Lesson or topic").selectOption("ticket");
  await page
    .getByRole("radio", {
      name: mode === "repetition" ? "Repetition" : "Guided conversation",
      exact: false,
    })
    .check();
  await page.getByRole("button", { name: "Start practice" }).click();
  await expect(
    page.getByRole("button", { name: "Tap to talk", exact: true }),
  ).toBeEnabled();
}
async function press(page: Page, info: TestInfo, name: string) {
  const b = page.getByRole("button", { name, exact: true });
  if (info.project.name === "android") await b.tap();
  else await b.click();
}
async function speak(page: Page, info: TestInfo) {
  await press(page, info, "Tap to talk");
  await expect(
    page.getByRole("button", { name: "Send answer", exact: true }),
  ).toBeEnabled();
  await page.waitForTimeout(300); // actual minimum recording duration, not a playback/rendering bypass
  await press(page, info, "Send answer");
}
async function noOverlap(page: Page) {
  await expect
    .poll(() => page.evaluate(() => (window as any).voiceTest.overlaps))
    .toBe(0);
  expect(
    await page.evaluate(() => (window as any).voiceTest.activeTracks),
  ).toBe(0);
}
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
    await page
      .getByRole("button", { name: "Open Tickets", exact: true })
      .click();
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

async function pending(page: Page) {
  return page.evaluate(async () => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const r = indexedDB.open("voice-teacher-pending-v1", 1);
      r.onsuccess = () => resolve(r.result);
      r.onerror = () => reject(r.error);
    });
    const rows: any[] = await new Promise((resolve, reject) => {
      const r = db.transaction("pending").objectStore("pending").getAll();
      r.onsuccess = () => resolve(r.result);
      r.onerror = () => reject(r.error);
    });
    db.close();
    return rows.map((r) => ({
      key: r.key,
      upload: r.upload?.request_id,
      bytes: r.upload?.recording.size,
      finish: r.finish?.request_id,
      containsGrant: JSON.stringify(r).includes("synthetic-client-token"),
    }));
  });
}
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
    await page.reload();
    await page
      .getByRole("button", { name: "Open Tickets", exact: true })
      .click();
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
