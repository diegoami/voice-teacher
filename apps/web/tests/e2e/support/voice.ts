import { expect, Page, TestInfo } from "@playwright/test";
const token = "synthetic-client-token-".repeat(3),
  code = "synthetic-pair-code-".repeat(3);
export async function media(page: Page) {
  await page.addInitScript(() => {
    const state = {
      transcript: "synthetic recording",
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
            data: new Blob(state.empty ? [] : [state.transcript], {
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
export async function fake(page: Page) {
  const uploads: {
      id: string;
      revision: number;
      bytes: string;
      type: string;
    }[] = [],
    controls: any[] = [];
  const receipts = new Map<string, any>();
  let pendingAnswer: any = null;
  let current: any = null,
    mode = "guided_conversation",
    failure = "",
    starts = 0;
  let multiple = false,
    statusDown = false;
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
        if (failure !== "pending") {
          current = pendingAnswer;
          receipts.set(id, {
            request_id: id,
            status: "ready",
            revision: current.revision,
          });
        }
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
        if (["finish-before", "control-before"].includes(failure)) {
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
            done: body.operation === "finish",
            status:
              body.operation === "finish"
                ? "finished"
                : body.operation === "pause"
                  ? "paused"
                  : "active",
            teacher:
              body.operation === "finish"
                ? [{ text: "Заняття закінчено.", kind: "close" }]
                : current.teacher,
            audio_ids: body.operation === "finish" ? [] : current.audio_ids,
          };
          result = current;
          if (failure === "tts") {
            status = 502;
            result = { error: { message: "RAW_PRIVATE_BACKEND_DETAILS" } };
          }
          if (["finish-after", "control-after"].includes(failure)) {
            failure = "";
            statusDown = true;
            await route.abort("failed");
            return;
          }
        }
      } else if (path.includes("/requests/")) {
        result = receipts.get(path.split("/").at(-1)!);
        if (!result) {
          status = 404;
          result = {};
        }
      } else if (path.startsWith("/api/v1/sessions/")) {
        if (statusDown) {
          await route.abort("failed");
          return;
        }
        if (
          failure === "tts" &&
          url.searchParams.get("prepare_audio") !== "false"
        ) {
          status = 502;
          result = {};
        } else result = current;
      } else status = 404;
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
    current: () => current,
    setMultiple: () => {
      multiple = true;
    },
    setFailure: (v: string) => {
      failure = v;
    },
    reconnect: () => {
      statusDown = false;
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
export async function open(
  page: Page,
  mode = "guided_conversation",
  service?: { origin: string; code: string },
) {
  await page.goto(service?.origin ?? "/");
  await page.getByLabel("Pairing code").fill(service?.code ?? code);
  await page.getByRole("button", { name: "Connect and pair" }).click();
  await page.getByLabel("Lesson source").selectOption("alpha");
  await page
    .getByRole("combobox", { name: "Course", exact: true })
    .selectOption("basics");
  await page
    .getByLabel("Lesson or topic")
    .selectOption(service ? "lesson-1" : "ticket");
  await page
    .getByRole("radio", {
      name:
        mode === "repetition"
          ? "Repetition"
          : mode === "free_conversation"
            ? "Free conversation"
            : "Guided conversation",
      exact: false,
    })
    .check();
  await page.getByRole("button", { name: "Start practice" }).click();
  await expect(
    page.getByRole("button", { name: "Tap to talk", exact: true }),
  ).toBeEnabled();
}
export async function navigateTo(page: Page, name: string) {
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  await expect(nav).toBeVisible();
  {
    const link = nav.getByRole("link", { name, exact: true });
    if ((await link.getAttribute("aria-current")) !== "page")
      await link.click();
  }
}
export async function press(page: Page, info: TestInfo, name: string) {
  if (name.startsWith("Open ")) await navigateTo(page, "Lessons");
  else if (
    /^(Load history|Refresh history|Evidence for|View original)/.test(name)
  )
    await navigateTo(page, "History");
  else if (/^(Load backup|Refresh backup|Disconnect)/.test(name))
    await navigateTo(page, "Settings");
  else if (
    /^(Tap to talk|Send answer|Finish session|Pause session|Continue session|Play teacher|Stop playback|Recover saved|Discard pending)/.test(
      name,
    )
  )
    await navigateTo(page, "Practice");
  const b = page.getByRole("button", { name, exact: true });
  if (info.project.name === "android") await b.tap();
  else await b.click();
}
export async function speak(page: Page, info: TestInfo) {
  await press(page, info, "Tap to talk");
  await expect(
    page.getByRole("button", { name: "Send answer", exact: true }),
  ).toBeEnabled();
  await page.waitForTimeout(300); // actual minimum recording duration, not a playback/rendering bypass
  await press(page, info, "Send answer");
}
export async function noOverlap(page: Page) {
  await expect
    .poll(() => page.evaluate(() => (window as any).voiceTest.overlaps))
    .toBe(0);
  expect(
    await page.evaluate(() => (window as any).voiceTest.activeTracks),
  ).toBe(0);
}
export async function pending(page: Page) {
  return page.evaluate(async () => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const r = indexedDB.open("voice-teacher-pending-v1");
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
      finish:
        r.control?.operation === "finish" ? r.control.request_id : undefined,
      control: r.control?.operation,
      containsGrant: JSON.stringify(r).includes("synthetic-client-token"),
    }));
  });
}
