import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { checked, preflight, reviewArgs, modelFamily } from '../../tools/review/cli.mjs';
import { sandboxArgs, sandboxEnvironment } from '../../tools/review/sandbox.mjs';

const options = { model: 'minimax-coding-plan/MiniMax-M3', implementerFamily: 'openai' };
function fake({ version = 'opencode v2.0.28', help = '--standalone --model --agent --file --format', models = options.model } = {}) {
  const calls = [];
  const invoke = (args) => {
    calls.push(args);
    if (args[0] === '--version') return version;
    if (args[0] === 'models') return models;
    if (args[0] === 'run' && args[1] === '--help') return help;
    throw new Error('Billed run attempted in preflight');
  };
  return { calls, invoke };
}

test('invalid identity and unsupported flags stop before invoking CLI', () => {
  for (const patch of [{ model: undefined }, { model: 'openrouter/openai/gpt-6.1-sol' },
    { model: 'provider/mystery' }, { implementerFamily: 'unknown' },
    { extraFlags: ['--auto'] }, { model: options.model + '#unknown' }]) {
    const f = fake();
    assert.throws(() => preflight({ ...options, ...patch }, f.invoke));
    assert.equal(f.calls.length, 0);
  }
});

test('provider routes do not change underlying family', () => {
  assert.equal(modelFamily('openrouter/minimax/minimax-m3'), 'minimax');
  assert.equal(modelFamily('opencode/minimax-m3'), 'minimax');
  assert.throws(() => reviewArgs({ ...options, implementerFamily: 'minimax' }), /different/);
});

test('compatible fake CLI preflight constructs only the inspected invocation', () => {
  const f = fake();
  const result = preflight(options, f.invoke);
  assert.deepEqual(result.args.slice(0, 10), ['run', '--standalone', '--model', options.model,
    '--agent', 'reviewer', '--file', '/brief.md', '--format', 'json']);
  assert.equal(result.reviewerFamily, 'minimax');
  assert.deepEqual(f.calls, [['--version'], ['run', '--help'], ['models']]);
});

test('changed CLI version, missing flag and absent model fail without a billed run', () => {
  for (const params of [{ version: 'opencode v2.1.0' }, { help: '--model --agent --file --format' },
    { models: 'opencode/minimax-m3' }]) {
    const f = fake(params);
    assert.throws(() => preflight(options, f.invoke));
    assert.ok(f.calls.every((args) => args[0] !== 'run' || args[1] === '--help'));
  }
});

test('CLI subprocess closes stdin and reports nonzero/timeout failures', () => {
  assert.equal(checked(process.execPath, ['-e', 'process.stdin.on("end",()=>process.stdout.write("EOF"));process.stdin.resume()']), 'EOF');
  assert.throws(() => checked(process.execPath, ['-e', 'process.exit(2)']), /CLI check failed/);
  assert.throws(() => checked(process.execPath, ['-e', 'setInterval(()=>{},1000)'], { timeout: 30 }), /CLI check failed/);
});

test('sandbox uses allowlisted mounts and environment; masks project configuration', () => {
  const top = fs.mkdtempSync(path.join(os.tmpdir(), 'vt-cli-test-'));
  const workspace = path.join(top, 'candidate'), runtime = path.join(top, 'runtime');
  fs.mkdirSync(workspace); fs.mkdirSync(runtime);
  fs.mkdirSync(path.join(workspace, '.opencode'));
  fs.writeFileSync(path.join(workspace, 'opencode.json'), '{}');
  const policy = path.join(top, 'policy.json'), brief = path.join(top, 'brief.md');
  fs.writeFileSync(policy, '{}'); fs.writeFileSync(brief, 'review');
  const args = sandboxArgs({ workspace, runtime, policy, brief, binary: process.execPath });
  assert.ok(args.includes('--unshare-pid'));
  assert.ok(args.includes('--unshare-net'));
  assert.ok(args.includes('/workspace/.opencode'));
  assert.ok(args.includes('/workspace/opencode.json'));
  assert.ok(!args.includes('/home/diego'));
  assert.ok(!args.includes('--dev-bind'));
  assert.ok(!args.includes('--ro-bind-try'));
  assert.deepEqual(sandboxEnvironment('test-provider-key'), { PATH: '/usr/bin:/bin', MINIMAX_API_KEY: 'test-provider-key' });
  assert.ok(!args.includes('test-provider-key'));
  assert.throws(() => sandboxArgs({ workspace, runtime: top, policy, brief, binary: process.execPath }), /separate/);
  assert.throws(() => sandboxArgs({ workspace, runtime, policy: path.join(workspace, 'opencode.json'), brief, binary: process.execPath }), /Trusted/);
  fs.symlinkSync(policy, path.join(workspace, 'opencode.jsonc'));
  assert.throws(() => sandboxArgs({ workspace, runtime, policy, brief, binary: process.execPath }), /symlink/);
});

test('fake executable integration rejects incompatible help without invoking a billed run', () => {
  const top = fs.mkdtempSync(path.join(os.tmpdir(), 'vt-fake-cli-'));
  const script = path.join(top, 'fake.mjs'), calls = path.join(top, 'calls.jsonl');
  fs.writeFileSync(script, `import fs from 'node:fs';
const a=process.argv.slice(2); fs.appendFileSync(${JSON.stringify(calls)},JSON.stringify(a)+'\\n');
if(a[0]==='--version')console.log('opencode v2.0.28');
else if(a[1]==='--help')console.log('--model --agent --file --format');
else { console.error('BILLED RUN');process.exit(9); }`);
  assert.throws(() => preflight(options, (a) => checked(process.execPath, [script, ...a])), /Unsupported CLI flag/);
  assert.deepEqual(fs.readFileSync(calls, 'utf8').trim().split('\n').map(JSON.parse), [['--version'], ['run', '--help']]);
});
