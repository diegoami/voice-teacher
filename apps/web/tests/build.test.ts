import { it, expect } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
function files(root: string): string[] {
  return readdirSync(root, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? files(join(root, e.name)) : [join(root, e.name)],
  );
}
it("production assets exclude provider/operator credentials and private API payloads", () => {
  const paths = files("dist");
  expect(paths.some((p) => p.endsWith("index.html"))).toBe(true);
  for (const p of paths) {
    expect(p).not.toMatch(/(?:^|\/)\.env(?:\.|$)|\.(?:sqlite(?:3)?|db)$/i);
    if (!p.endsWith(".png")) {
      const text = readFileSync(p, "utf8");
      expect(text).not.toMatch(
        /ELEVENLABS_API_KEY|OPENROUTER_API_KEY|VOICE_TEACHER_OPERATOR_TOKEN|RAW_PRIVATE_BACKEND_DETAILS/,
      );
      for (const name of [
        "ELEVENLABS_API_KEY",
        "OPENROUTER_API_KEY",
        "VOICE_TEACHER_OPERATOR_TOKEN",
      ]) {
        const secret = process.env[name];
        if (secret && secret.length >= 16)
          expect(
            text.includes(secret),
            "configured credential must not occur in a built asset",
          ).toBe(false);
      }
    }
  }
});
