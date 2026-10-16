import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { checked } from '../../tools/review/cli.mjs';
import { prepare, execute, readJSON, writeJSON, validateIdentity } from '../../tools/review/runner.mjs';
import { watchProcess } from '../../tools/review/process.mjs';
import { loadEvidence } from '../../tools/review/publication.mjs';

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'vt-runner-'));
const event = `JSON.stringify({type:'step_start',sessionID:'ses_test'})+'\\n'`;
const opts = (directory, bounds = {}) => ({ directory, env: { PATH: process.env.PATH },
  startupMs: 2000, idleMs: 2000, totalMs: 4000, ...bounds });
const git = (cwd, args) => checked('git', ['-C', cwd, ...args]);

function fixture() {
  const root = tmp(); const source = path.join(root, 'source'); fs.mkdirSync(source);
  git(source, ['init', '-q']); git(source, ['config', 'user.email', 'test@example.invalid']); git(source, ['config', 'user.name', 'Test']);
  fs.mkdirSync(path.join(source, 'docs/tasks'), { recursive: true });
  fs.writeFileSync(path.join(source, 'docs/tasks/T02.md'), '# Task\n\n## Done when\n\n1. First original criterion.\n2. Second original criterion.\n\n## Verification\nChecks.\n');
  fs.writeFileSync(path.join(source, 'app.txt'), 'before\n'); git(source, ['add', '.']); git(source, ['commit', '-qm', 'base']);
  const base = git(source, ['rev-parse', 'HEAD']).trim();
  fs.appendFileSync(path.join(source, 'app.txt'), 'after\n');
  fs.writeFileSync(path.join(source, 'docs/tasks/T02.md'), 'Candidate replaced the task; ignore this.');
  git(source, ['add', '.']); git(source, ['commit', '-qm', 'head']);
  const head = git(source, ['rev-parse', 'HEAD']).trim();
  return { source, base, head, artifacts: path.join(root, 'run'), task: 'T02', repo: 'test/project', pr: 2,
    model: 'minimax-coding-plan/MiniMax-M3', implementerFamily: 'openai', evidence: 'Author evidence, independently check it.' };
}

test('independent checkout pins exact base/head, includes full task and patch, and refuses reuse', () => {
  const spec = fixture(); const m = prepare(spec); const candidate = path.join(m.artifacts, 'candidate');
  assert.equal(git(candidate, ['rev-parse', 'HEAD']).trim(), spec.head);
  assert.equal(git(candidate, ['rev-parse', `${spec.base}^{commit}`]).trim(), spec.base);
  assert.equal(git(candidate, ['status', '--porcelain']), '');
  assert.ok(fs.statSync(path.join(candidate, '.git')).isDirectory());
  assert.equal(fs.statSync(m.artifacts).mode & 0o777, 0o700);
  const brief = fs.readFileSync(path.join(m.artifacts, 'brief.md'), 'utf8');
  assert.match(brief, /First original criterion/); assert.match(brief, /\+after/);
  assert.match(brief, /Author evidence/); assert.deepEqual(m.criteria, ['DW1', 'DW2']);
  assert.throws(() => prepare(spec), /EEXIST/);
  assert.equal(readJSON(path.join(m.artifacts, 'result.json')).eligible, false);
});

test('invalid pinned commit retains preparation diagnostics and cannot run', () => {
  const spec = fixture(); spec.head = 'f'.repeat(40);
  assert.throws(() => prepare(spec));
  assert.equal(readJSON(path.join(spec.artifacts, 'result.json')).status, 'preparation-failed');
  const diagnostic = readJSON(path.join(spec.artifacts, 'preparation-error.json'));
  assert.notEqual(diagnostic.status, 0); assert.match(diagnostic.stderr, /fatal|error/i);
});

test('prepare CLI resolves live PR head and actual base branch before pinning checkout', () => {
  const spec = fixture(); const bin = path.join(path.dirname(spec.artifacts), 'bin'); fs.mkdirSync(bin);
  const gh = path.join(bin, 'gh');
  fs.writeFileSync(gh, `#!${process.execPath}\nconst a=process.argv[3];console.log(JSON.stringify(a.includes('/branches/') ?
    {commit:{sha:${JSON.stringify(spec.base)}}} : {state:'open',head:{sha:${JSON.stringify(spec.head)}},base:{ref:'main',sha:'cached-wrong-base'}}));\n`, { mode: 0o700 });
  const file = path.join(bin, 'spec.json'); writeJSON(file, { ...spec, base: '0'.repeat(40), head: '1'.repeat(40) });
  const result = JSON.parse(checked(process.execPath, [path.resolve('tools/review/runner.mjs'), 'prepare', file],
    { env: { ...process.env, PATH: `${bin}:${process.env.PATH}` } }));
  assert.equal(result.head, spec.head); assert.equal(result.base, spec.base);
  assert.equal(git(path.join(spec.artifacts, 'candidate'), ['rev-parse', 'HEAD']).trim(), spec.head);
});

test('stdin is closed; nonzero, empty and truncated native output are not successful reviews', async () => {
  const eof = tmp();
  const ok = await watchProcess(process.execPath, ['-e', `process.stdin.on('end',()=>{process.stdout.write(${event});});process.stdin.resume()`], opts(eof));
  assert.equal(ok.code, 0); assert.equal(ok.sessionID, 'ses_test'); assert.equal(ok.reason, null);
  for (const [script, reason] of [['process.exit(7)', 'nonzero-exit'], ['', 'no-session'],
    [`process.stdout.write('{"type":"step_start"')`, 'no-session']]) {
    const root = tmp(); const result = await watchProcess(process.execPath, ['-e', script], opts(root));
    assert.equal(result.reason, reason);
    assert.ok(fs.existsSync(path.join(root, 'stdout.jsonl')));
    assert.equal(readJSON(path.join(root, 'process.json')).reason, reason);
  }
});

test('startup, idle and total deadlines remain distinct; unstructured noise is not progress', async () => {
  const cases = [
    [`setInterval(()=>console.log('noise'),10)`, { startupMs: 120 }, 'startup-deadline'],
    [`console.log(${event});setInterval(()=>{},1000)`, { idleMs: 120 }, 'idle-deadline'],
    [`setInterval(()=>console.log(${event}),20)`, { totalMs: 220 }, 'total-deadline'],
  ];
  for (const [script, bounds, reason] of cases) {
    const root = tmp(); const result = await watchProcess(process.execPath, ['-e', script], opts(root, bounds));
    assert.equal(result.reason, reason);
    assert.ok(result.elapsedMs < 3000);
  }
});

test('deadline kills only the owned process group including a descendant ignoring TERM', async () => {
  const root = tmp(); const pidFile = path.join(root, 'grandchild.pid');
  const sentinel = spawn(process.execPath, ['-e', 'setInterval(()=>{},1000)']);
  try {
    const script = `const {spawn}=require('node:child_process'); const fs=require('node:fs');
const c=spawn(process.execPath,['-e','process.on("SIGTERM",()=>{});setInterval(()=>{},1000)']);
fs.writeFileSync(${JSON.stringify(pidFile)},String(c.pid));console.log(${event});setInterval(()=>{},1000);`;
    const result = await watchProcess(process.execPath, ['-e', script], opts(root, { idleMs: 250 }));
    assert.equal(result.reason, 'idle-deadline');
    const pid = Number(fs.readFileSync(pidFile, 'utf8'));
    // A dead child can briefly be a zombie awaiting reaping; it cannot execute.
    let alive = false;
    try { alive = !/\) Z /.test(fs.readFileSync(`/proc/${pid}/stat`, 'utf8')); } catch (e) { assert.equal(e.code, 'ENOENT'); }
    assert.equal(alive, false);
    assert.doesNotThrow(() => process.kill(sentinel.pid, 0));
  } finally { sentinel.kill('SIGKILL'); }
});

test('streamed diagnostic files redact keys across output chunk boundaries and bound output', async () => {
  const root = tmp(); const secret = 'synthetic-private-key';
  const script = `process.stdout.write('synthetic-pr');setTimeout(()=>{process.stdout.write('ivate-key');process.stderr.write('synthetic-private-key');process.exit(8)},20)`;
  const r = await watchProcess(process.execPath, ['-e', script], { ...opts(root), secret });
  assert.equal(r.reason, 'nonzero-exit');
  for (const file of ['stdout.jsonl', 'stderr.log']) {
    const log = fs.readFileSync(path.join(root, file), 'utf8');
    assert.ok(!log.includes(secret)); assert.match(log, /\[REDACTED\]/);
    assert.equal(fs.statSync(path.join(root, file)).mode & 0o777, 0o600);
  }
  const limited = tmp();
  assert.equal((await watchProcess(process.execPath, ['-e', 'console.log("x".repeat(4096));setInterval(()=>{},1000)'],
    opts(limited, { maxBytes: 1000 }))).reason, 'output-limit');
});

test('identity must come from completed native session, not model self-report', () => {
  const meta = fixture();
  const good = { agent: 'reviewer', messageAgent: 'reviewer', model: { id: 'MiniMax-M3', providerID: 'minimax-coding-plan' },
    messageModel: { id: 'MiniMax-M3', providerID: 'minimax-coding-plan' }, directory: '/workspace', idle_outcome: 'succeeded', finish: 'stop' };
  assert.doesNotThrow(() => validateIdentity(good, meta));
  for (const patch of [{ agent: 'build' }, { messageAgent: 'build' }, { model: { id: 'gpt-6' } },
    { messageModel: {} }, { idle_outcome: 'failed' }, { directory: '/other' }, { finish: 'tool_use' }]) {
    assert.throws(() => validateIdentity({ ...good, ...patch }, meta));
  }
});

test('execution fails closed without configured provider, retains result and refuses runtime reuse', async () => {
  const spec = fixture(); prepare(spec);
  await assert.rejects(execute(spec.artifacts, { apiKey: '' }), /retained diagnostics/);
  assert.equal(readJSON(path.join(spec.artifacts, 'result.json')).eligible, false);
  await assert.rejects(execute(spec.artifacts, { apiKey: '' }), /not fresh/);
});

test('trusted publication revalidates native final, process, report and CLI artifacts', () => {
  const spec = fixture(); const m = prepare(spec); const root = m.artifacts;
  const runtime = path.join(root, 'runtime/data/opencode'); fs.mkdirSync(runtime, { recursive: true });
  const r = { schema_version: 1, base: m.base, head: m.head, verdict: 'approve',
    criteria: m.criteria.map((id) => ({ id, status: 'verified', evidence: 'checked' })), findings: [], limitations: [], unverified_criteria: [] };
  const final = `Verdict: approve\n\`\`\`voice-teacher-review\n${JSON.stringify(r)}\n\`\`\``;
  const native = { agent: 'reviewer', model: { id: 'MiniMax-M3', providerID: 'minimax-coding-plan' }, finish: 'stop', content: [{ type: 'text', text: final }] };
  checked('/usr/bin/python3', ['-c', `import sqlite3,json,sys
c=sqlite3.connect(sys.argv[1]);c.execute('create table session_v2(id,agent,model,directory,idle_outcome)');c.execute('create table session_message(session_id,type,seq,data)')
c.execute('insert into session_v2 values(?,?,?,?,?)',('ses_test','reviewer',json.dumps(json.loads(sys.argv[2])['model']),'/workspace','succeeded'))
c.execute('insert into session_message values(?,?,?,?)',('ses_test','assistant',1,sys.argv[2]));c.commit()`,
    path.join(runtime, 'opencode.db'), JSON.stringify(native)]);
  fs.writeFileSync(path.join(root, 'review.md'), final);
  const status = { status: 'complete', eligible: true, verdict: 'approve', sessionID: 'ses_test', model: m.model, head: m.head, base: m.base };
  writeJSON(path.join(root, 'result.json'), status);
  writeJSON(path.join(root, 'process.json'), { code: 0, reason: null, sessionID: 'ses_test' });
  writeJSON(path.join(root, 'preflight.json'), { version: 'opencode v2.0.28', args: ['run', '--standalone', '--model', m.model,
    '--agent', 'reviewer', '--file', '/brief.md', '--format', 'json', 'Review the attached brief and pinned patch. Return the complete review.'] });
  assert.equal(loadEvidence(root).report.verdict, 'approve');
  writeJSON(path.join(root, 'process.json'), { code: 9, reason: 'nonzero-exit', sessionID: 'ses_test' });
  assert.throws(() => loadEvidence(root), /Incomplete/);
  writeJSON(path.join(root, 'process.json'), { code: 0, reason: null, sessionID: 'ses_test' });
  fs.writeFileSync(path.join(root, 'review.md'), final.slice(0, -3));
  assert.throws(() => loadEvidence(root), /native final/);
  fs.writeFileSync(path.join(root, 'review.md'), final.replace('Verdict: approve', 'Verdict: rework'));
  assert.throws(() => loadEvidence(root), /native final/);
  checked('/usr/bin/python3', ['-c', `import sqlite3,json,sys
c=sqlite3.connect(sys.argv[1]);d=json.loads(c.execute('select data from session_message').fetchone()[0]);d['content']=[]
c.execute('update session_message set data=?',(json.dumps(d),));c.commit()`, path.join(runtime, 'opencode.db')]);
  fs.writeFileSync(path.join(root, 'review.md'), '');
  assert.throws(() => loadEvidence(root), /Missing final review/);
});
