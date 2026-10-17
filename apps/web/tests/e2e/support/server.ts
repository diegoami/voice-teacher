import { spawn, ChildProcess } from "node:child_process";
import { mkdtemp, readFile, writeFile, unlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "node:net";

const here = dirname(fileURLToPath(import.meta.url));
const repo =
  process.env.VOICE_TEACHER_TEST_REPO ?? resolve(here, "../../../../..");
const python =
  process.env.VOICE_TEACHER_TEST_PYTHON ?? join(repo, ".venv/bin/python");
export async function server(options: { completion?: boolean } = {}) {
  const root = await mkdtemp(
    join(
      process.env.VOICE_TEACHER_TEST_TMP ?? tmpdir(),
      "voice-teacher-browser-",
    ),
  );
  const socket = createServer();
  await new Promise<void>((r) => socket.listen(0, "127.0.0.1", r));
  const port = (socket.address() as { port: number }).port;
  await new Promise<void>((r, j) => socket.close((e) => (e ? j(e) : r())));
  const origin = "http://127.0.0.1:" + port;
  let child: ChildProcess | undefined,
    output = "",
    code = "",
    pid = 0;
  async function start() {
    child = spawn(
      python,
      [
        join(repo, "tests/integration/browser_server.py"),
        "--data",
        root,
        "--assets",
        resolve(here, "../../../dist"),
        "--port",
        String(port),
        ...(options.completion ? ["--completion-fixture"] : []),
      ],
      {
        env: {
          ...process.env,
          PYTHONDONTWRITEBYTECODE: "1",
          PYTHONPATH: [join(repo, "server"), repo, process.env.PYTHONPATH]
            .filter(Boolean)
            .join(":"),
        },
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    output = "";
    child.stdout!.on("data", (b) => {
      output += b;
    });
    child.stderr!.on("data", (b) => {
      output += b;
    });
    let error: Error | undefined;
    child.on("error", (e) => {
      error = e;
    });
    for (let i = 0; i < 120; i++) {
      if (error || child.exitCode !== null || child.signalCode !== null)
        throw new Error(
          "Synthetic server failed: " + (error?.message ?? output),
        );
      try {
        const ready = JSON.parse(
          await readFile(join(root, "ready.json"), "utf8"),
        );
        if (ready.pid === child.pid && (await fetch(origin + "/healthz")).ok) {
          code = ready.code;
          pid = ready.pid;
          return;
        }
      } catch {}
      await new Promise((r) => setTimeout(r, 50));
    }
    await stop();
    throw new Error("Synthetic server startup timed out: " + output);
  }
  async function stop() {
    const old = child;
    if (!old || old.exitCode !== null || old.signalCode !== null) return;
    await new Promise<void>((r) => {
      old.once("exit", () => r());
      old.kill("SIGKILL");
    });
  }
  await start();
  return {
    root,
    origin,
    get code() {
      return code;
    },
    get pid() {
      return pid;
    },
    stop,
    async arm(stage: string) {
      await writeFile(join(root, "arm.json"), JSON.stringify({ stage }));
    },
    async arrived() {
      try {
        return JSON.parse(await readFile(join(root, "arrived.json"), "utf8"));
      } catch {
        return null;
      }
    },
    async restart() {
      await stop();
      await unlink(join(root, "arm.json")).catch(() => {});
      await start();
    },
    async inspect(session: string) {
      const script =
        "import json,sys;from voice_teacher.storage import Store;s=Store(sys.argv[1]);print(json.dumps({'snapshot':s.session('browser-learner',sys.argv[2]),'events':s.events('browser-learner',sys.argv[2])}))";
      const p = spawn(python, ["-c", script, join(root, "runtime"), session], {
        env: {
          ...process.env,
          PYTHONDONTWRITEBYTECODE: "1",
          PYTHONPATH: [join(repo, "server"), repo, process.env.PYTHONPATH]
            .filter(Boolean)
            .join(":"),
        },
        stdio: ["ignore", "pipe", "pipe"],
      });
      let result = "",
        errors = "";
      p.stdout.on("data", (b) => (result += b));
      p.stderr.on("data", (b) => (errors += b));
      await new Promise<void>((r, j) => {
        p.on("error", j);
        p.on("exit", (c) => (c === 0 ? r() : j(new Error(errors))));
      });
      return JSON.parse(result);
    },
    async changeSourceAndProfile() {
      const path = join(root, "alpha/voice-teacher.json");
      const raw = JSON.parse(await readFile(path, "utf8"));
      raw.courses[0].lessons[0].guided_steps[0].teacher = {
        display: "Updated unrelated instruction",
        speech: "Updated unrelated instruction",
      };
      raw.courses[0].items[0].item_revision++;
      await writeFile(path, JSON.stringify(raw));
      const p = spawn(
        python,
        [
          "-c",
          "import sys;from voice_teacher.storage import Store;Store(sys.argv[1]).save_learner('browser-learner',{'level':'C1'})",
          join(root, "runtime"),
        ],
        {
          env: {
            ...process.env,
            PYTHONDONTWRITEBYTECODE: "1",
            PYTHONPATH: [join(repo, "server"), repo, process.env.PYTHONPATH]
              .filter(Boolean)
              .join(":"),
          },
          stdio: "ignore",
        },
      );
      await new Promise<void>((r, j) => {
        p.on("error", j);
        p.on("exit", (c) =>
          c === 0 ? r() : j(new Error("fixture profile update failed")),
        );
      });
    },
  };
}
