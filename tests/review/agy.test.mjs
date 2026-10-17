import test from "node:test";
import assert from "node:assert/strict";
import { parseAgyResult } from "../../tools/review/agy.mjs";

test("a successful static agy report never becomes merge approval", () => {
  const meta = { base: "a".repeat(40), head: "b".repeat(40) };
  const report = {
    base: meta.base,
    head: meta.head,
    assessment: "no_issues_found",
    findings: [],
    unverified: ["All tests and real phone acceptance not run"],
  };
  const result = parseAgyResult(
    {
      status: "SUCCESS",
      conversation_id: "00000000-0000-4000-8000-000000000001",
      num_turns: 1,
      response: JSON.stringify(report),
    },
    meta,
  );
  assert.equal(result.eligible, false);
});

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import {
  agyArgs,
  prepareAgy,
  runAgy,
  AGY_SETTINGS,
} from "../../tools/review/agy.mjs";
const meta = {
  base: "a".repeat(40),
  head: "b".repeat(40),
  model: "claude-sonnet-5-5-medium",
};
const valid = () => ({
  status: "SUCCESS",
  conversation_id: "00000000-0000-4000-8000-000000000001",
  num_turns: 1,
  response: JSON.stringify({
    base: meta.base,
    head: meta.head,
    assessment: "no_issues_found",
    findings: [],
    unverified: ["Acceptance tests not run; real-phone acceptance not run"],
  }),
});

test("explicit Sonnet selection rejects same-family, unknown model and implicit variant", () => {
  const args = agyArgs(meta.model, "openai", "Pinned data; $(not shell)");
  assert.deepEqual(args.slice(-2), ["--print", "Pinned data; $(not shell)"]);
  assert.ok(!args.includes("--dangerously-skip-permissions"));
  assert.ok(args.includes("240s"));
  for (const model of [
    "claude-sonnet",
    "gemini-4-argon-high",
    "claude-sonnet-5-5-medium#high",
  ])
    assert.throws(() => agyArgs(model, "openai", "brief"));
  assert.throws(() => agyArgs(meta.model, "anthropic", "brief"));
});

for (const damage of [
  "failed",
  "empty",
  "multiple-turns",
  "wrong-head",
  "missing-tests",
  "bad-finding",
  "conflicting-assessment",
]) {
  test("invalid report is rejected: " + damage, () => {
    const envelope = valid(),
      report = JSON.parse(envelope.response);
    if (damage === "failed") envelope.status = "ERROR";
    if (damage === "empty") envelope.response = "";
    if (damage === "multiple-turns") envelope.num_turns = 2;
    if (damage === "wrong-head") report.head = "c".repeat(40);
    if (damage === "missing-tests") report.unverified = ["Phone not run"];
    if (damage === "bad-finding") {
      report.assessment = "issues_found";
      report.findings = [
        {
          path: "app.py",
          line: 0,
          severity: "blocking",
          summary: "defect",
          evidence: "proof",
        },
      ];
    }
    if (damage === "conflicting-assessment") report.assessment = "issues_found";
    if (damage !== "empty") envelope.response = JSON.stringify(report);
    assert.throws(() => parseAgyResult(envelope, meta));
  });
}

test("policy denies writes, commands, external web and MCP independently from the prompt", () => {
  assert.deepEqual(AGY_SETTINGS.permissions.allow, ["read_file(/workspace)"]);
  for (const rule of [
    "write_file(*)",
    "command(*)",
    "unsandboxed(*)",
    "mcp(*)",
    "read_url(*)",
    "execute_url(*)",
  ])
    assert.ok(AGY_SETTINGS.permissions.deny.includes(rule));
});

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "agy-review-unit-"));
  const source = path.join(root, "source");
  fs.mkdirSync(source);
  const git = (...args) =>
    execFileSync(
      "git",
      ["-c", "core.hooksPath=/dev/null", "-C", source, ...args],
      {
        encoding: "utf8",
        env: {
          PATH: process.env.PATH,
          GIT_CONFIG_NOSYSTEM: "1",
          GIT_CONFIG_GLOBAL: "/dev/null",
        },
      },
    ).trim();
  git("init", "-q", "--template=");
  git("config", "user.name", "Synthetic");
  git("config", "user.email", "synthetic@example.invalid");
  fs.mkdirSync(path.join(source, "docs/tasks"), { recursive: true });
  fs.writeFileSync(
    path.join(source, "docs/tasks/T33.md"),
    "# Task\n\n## Done when\n\n1. Preserve history.\n",
  );
  fs.writeFileSync(path.join(source, "app.py"), "old\n");
  git("add", ".");
  git("commit", "-qm", "base");
  const base = git("rev-parse", "HEAD");
  fs.writeFileSync(path.join(source, "app.py"), "new\n");
  git("add", ".");
  git("commit", "-qm", "head");
  const head = git("rev-parse", "HEAD");
  return {
    root,
    source,
    git,
    spec: {
      task: "T33",
      source,
      base,
      head,
      model: meta.model,
      implementerFamily: "openai",
      artifacts: path.join(root, "review"),
    },
  };
}

test("packet uses committed bytes, excludes checkout metadata, pins identities and refuses reuse", () => {
  const f = fixture();
  fs.writeFileSync(
    path.join(f.source, "app.py"),
    "UNCOMMITTED PRIVATE SENTINEL",
  );
  const value = prepareAgy(f.spec);
  assert.equal(
    fs.readFileSync(
      path.join(f.spec.artifacts, "packet/source/app.py"),
      "utf8",
    ),
    "new\n",
  );
  assert.ok(!fs.existsSync(path.join(f.spec.artifacts, "packet/.git")));
  assert.equal(value.head, f.spec.head);
  assert.equal(value.family, "anthropic");
  assert.equal(fs.statSync(f.spec.artifacts).mode & 0o777, 0o700);
  assert.throws(() => prepareAgy(f.spec));
});

test("symlink source entries and unresolved revisions are refused", () => {
  const f = fixture();
  fs.symlinkSync("/etc/passwd", path.join(f.source, "linked"));
  f.git("add", ".");
  f.git("commit", "-qm", "symlink");
  assert.throws(() =>
    prepareAgy({ ...f.spec, head: f.git("rev-parse", "HEAD") }),
  );
  assert.equal(
    JSON.parse(fs.readFileSync(path.join(f.spec.artifacts, "result.json")))
      .eligible,
    false,
  );
  const second = fixture();
  assert.throws(() => prepareAgy({ ...second.spec, head: "e".repeat(40) }));
});

test("changed packet fails before authentication or model execution and stays single-use", async () => {
  const f = fixture();
  prepareAgy(f.spec);
  fs.appendFileSync(
    path.join(f.spec.artifacts, "packet/patch.diff"),
    "tampered",
  );
  await assert.rejects(
    () =>
      runAgy(f.spec.artifacts, {
        binary: "/nonexistent",
        credential: "/nonexistent",
      }),
    /packet changed/,
  );
  assert.equal(
    JSON.parse(fs.readFileSync(path.join(f.spec.artifacts, "result.json")))
      .eligible,
    false,
  );
  await assert.rejects(() => runAgy(f.spec.artifacts, {}), /single-use/);
});

test("agy egress permits only the observed provider/authentication services", () => {
  const script = `import importlib.util,sys
sys.path.insert(0,sys.argv[1])
spec=importlib.util.spec_from_file_location('agy_egress',sys.argv[1]+'/agy-egress.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
allowed={'daily-cloudcode-pa.googleapis.com:443','oauth2.googleapis.com:443','www.googleapis.com:443','lh3.googleusercontent.com:443'}
assert m.egress.ALLOWED==allowed
for target in allowed: assert m.egress.authority(('CONNECT '+target+' HTTP/1.1\\r\\n\\r\\n').encode())==target[:-4]
for target in ['api.github.com:443','127.0.0.1:443','daily-cloudcode-pa.googleapis.com.evil:443','daily-cloudcode-pa.googleapis.com:80']:
 try:m.egress.authority(('CONNECT '+target+' HTTP/1.1\\r\\n\\r\\n').encode())
 except ValueError:pass
 else:raise AssertionError(target)
print('4 explicit services accepted; unrelated/malformed targets denied')`;
  const tools = path.resolve("tools/review");
  const output = execFileSync("python3", ["-c", script, tools], {
    encoding: "utf8",
  });
  assert.match(output, /unrelated\/malformed targets denied/);
});

test("documented structured output can accompany native display metadata without rewriting it", () => {
  const envelope = valid();
  const report = JSON.parse(envelope.response);
  envelope.structured_output = report;
  envelope.response = JSON.stringify({
    ...report,
    toolAction: "Submitting review",
    toolSummary: "Reviewing pinned packet",
  });
  const original = envelope.response;
  assert.equal(parseAgyResult(envelope, meta).eligible, false);
  assert.equal(envelope.response, original);
  envelope.structured_output = { ...report, head: "c".repeat(40) };
  assert.throws(() => parseAgyResult(envelope, meta), /disagree/);
});
