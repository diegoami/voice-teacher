import { test, expect } from "@playwright/test";
import { server } from "./support/server";
import { media, press, speak, open } from "./support/voice";

test("free-conversation: source-free topic and preference survive browser and server restart", async ({
  page,
}, info) => {
  const service = await server();
  try {
    await media(page);
    await page.goto(service.origin);
    await page.getByLabel("Pairing code").fill(service.code);
    await press(page, info, "Connect and pair");
    await page.getByLabel("Practise a topic without a lesson").check();
    await page
      .getByLabel("Conversation topic", { exact: true })
      .fill("Train travel");
    await page
      .getByLabel("Correction preference")
      .selectOption("end_of_session");
    await press(page, info, "Start practice");
    await expect(
      page.getByRole("button", { name: "Tap to talk", exact: true }),
    ).toBeEnabled();
    const sid = await page.evaluate(
      () =>
        JSON.parse(
          localStorage.getItem("voice-teacher:v1:browser-learner:sessions")!,
        )[0].start.session_id,
    );
    for (const text of [
      "Я хочу їхати до Львова.",
      "Завтра вранці.",
      "Один квиток, будь ласка.",
    ]) {
      await page.evaluate((transcript) => {
        (window as any).voiceTest.transcript = transcript;
      }, text);
      await speak(page, info);
      await expect(
        page.getByRole("button", { name: "Tap to talk", exact: true }),
      ).toBeEnabled();
    }
    await press(page, info, "Pause session");
    await expect(
      page.getByRole("button", { name: "Continue session", exact: true }),
    ).toBeEnabled();
    await service.restart();
    await page.reload();
    await page
      .getByRole("button", { name: "Open Train travel", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Session ready" }),
    ).toContainText("Train travel");
    await expect(
      page.getByRole("region", { name: "Session ready" }),
    ).toContainText("Feedback at the end");
    await press(page, info, "Continue session");
    await expect(
      page.getByRole("button", { name: "Tap to talk", exact: true }),
    ).toBeEnabled();
    const saved = await service.inspect(sid);
    expect(saved.snapshot.mode).toBe("free_conversation");
    expect(saved.snapshot.topic).toBe("Train travel");
    expect(saved.snapshot.engine_state.data.lesson.correction_style).toBe(
      "end_of_session",
    );
    expect(
      saved.events.filter((e: any) => e.event_type === "turn.accepted"),
    ).toHaveLength(3);
    await press(page, info, "Load history and progress");
    await expect(
      page.getByRole("region", { name: "History and progress" }),
    ).toContainText("Train travel");
  } finally {
    await service.stop();
  }
});

for (const mode of ["guided_conversation", "repetition", "free_conversation"]) {
  test(`free-conversation: select ${mode} with a lesson`, async ({
    page,
  }, info) => {
    const service = await server();
    try {
      await media(page);
      await open(page, mode, service);
      if (mode === "free_conversation") {
        await expect(
          page.getByRole("region", { name: "Session ready" }),
        ).toContainText("Light immediate correction");
      }
    } finally {
      await service.stop();
    }
  });
}
