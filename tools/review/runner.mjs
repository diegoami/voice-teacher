import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { checked, preflight, reviewArgs, modelFamily } from './cli.mjs';
import { adapter } from './smoke.mjs';
import { policyHash } from './sandbox.mjs';
import { criteriaFromTask, parseReport, reviewBrief } from './report.mjs';
import { watchProcess, stopOwned } from './process.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const gitEnv = { PATH: process.env.PATH, HOME: '/nonexistent', GIT_CONFIG_NOSYSTEM: '1',
  GIT_CONFIG_GLOBAL: '/dev/null', GIT_TERMINAL_PROMPT: '0' };
function git(cwd, args) { return checked('git', ['-c', 'core.hooksPath=/dev/null', '-C', cwd, ...args], { env: gitEnv }); }
export const writeJSON = (p, v) => fs.writeFileSync(p, JSON.stringify(v, null, 2) + '\n', { mode: 0o600 });
export const readJSON = (p) => JSON.parse(fs.readFileSync(p, 'utf8'));

// Run from accepted tooling, never from the candidate's copy. Source may be a
// trusted local checkout or the operator-selected remote. No credentials in spec.
export function prepare(spec) {
  reviewArgs(spec);
  if (!/^[a-f0-9]{40}$/.test(spec.base) || !/^[a-f0-9]{40}$/.test(spec.head) ||
      !/^T\d{2}$/.test(spec.task) || !Number.isSafeInteger(spec.pr) || spec.pr < 1 ||
      !/^[\w.-]+\/[\w.-]+$/.test(spec.repo)) throw new Error('Invalid pinned PR identity');
  if ('apiKey' in spec) throw new Error('Credentials must not be stored in specs');
  const root = path.resolve(spec.artifacts);
  fs.mkdirSync(root, { mode: 0o700 }); // exclusive: never reuse a run/runtime
  const meta = { ...spec, artifacts: root, variant: 'provider default', reviewerFamily: modelFamily(spec.model),
    policyHash: policyHash(path.join(here, 'policy.json')) };
  try {
    const workspace = path.join(root, 'candidate');
    checked('git', ['-c', 'core.hooksPath=/dev/null', 'clone', '--no-local', '--no-checkout', '--', spec.source, workspace], { env: gitEnv });
    git(workspace, ['fetch', '--no-tags', 'origin', spec.base, spec.head]);
    git(workspace, ['checkout', '--detach', spec.head]);
    if (git(workspace, ['rev-parse', 'HEAD']).trim() !== spec.head ||
        git(workspace, ['rev-parse', `${spec.base}^{commit}`]).trim() !== spec.base ||
        git(workspace, ['status', '--porcelain']).trim()) throw new Error('Checkout identity mismatch');
    meta.mergeBase = git(workspace, ['merge-base', spec.base, spec.head]).trim();
    const task = git(workspace, ['show', `${spec.base}:docs/tasks/${spec.task}.md`]);
    meta.criteria = criteriaFromTask(task);
    const patch = git(workspace, ['diff', '--no-ext-diff', '--no-textconv', '--binary', spec.base, spec.head]);
    if (!patch.trim()) throw new Error('Empty review patch');
    fs.mkdirSync(path.join(root, 'runtime'), { mode: 0o700 });
    fs.copyFileSync(path.join(here, 'policy.json'), path.join(root, 'policy.json'));
    fs.writeFileSync(path.join(root, 'patch.diff'), patch, { mode: 0o600 });
    fs.writeFileSync(path.join(root, 'brief.md'), reviewBrief(meta, task, patch, spec.evidence ?? 'No implementer evidence supplied.'), { mode: 0o600 });
    writeJSON(path.join(root, 'meta.json'), meta);
    writeJSON(path.join(root, 'result.json'), { status: 'prepared', eligible: false });
    return meta;
  } catch (e) {
    const redact = (value) => process.env.MINIMAX_API_KEY ? String(value ?? '').split(process.env.MINIMAX_API_KEY).join('[REDACTED]') : String(value ?? '');
    writeJSON(path.join(root, 'preparation-error.json'), { error: redact(e.message), status: e.status ?? null,
      signal: e.signal ?? null, stdout: redact(e.stdout), stderr: redact(e.stderr) });
    writeJSON(path.join(root, 'result.json'), { status: 'preparation-failed', eligible: false, error: redact(e.message) });
    throw e;
  }
}

export function sessionRecord(runtime, sessionID) {
  if (!/^ses_[\w-]+$/.test(sessionID ?? '')) throw new Error('Missing native session identity');
  const script = `import sqlite3,json,pathlib,sys
p=pathlib.Path(sys.argv[1]).resolve()
c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)
c.row_factory=sqlite3.Row
r=c.execute('select id,agent,model,directory,idle_outcome from session_v2 where id=?',(sys.argv[2],)).fetchone()
if r is None: raise RuntimeError('native session missing')
d=dict(r);d['model']=json.loads(d['model'])
m=c.execute("select data from session_message where session_id=? and type='assistant' order by seq desc limit 1",(sys.argv[2],)).fetchone()
a=json.loads(m[0]) if m else {}
d['final']='\\n'.join(p.get('text','') for p in a.get('content',[]) if p.get('type')=='text')
d['messageAgent']=a.get('agent');d['messageModel']=a.get('model');d['finish']=a.get('finish')
print(json.dumps(d))`;
  return JSON.parse(checked('/usr/bin/python3', ['-c', script,
    path.join(runtime, 'data/opencode/opencode.db'), sessionID], { env: { PATH: '/usr/bin:/bin' } }));
}

export function validateIdentity(record, meta) {
  const slash = meta.model.indexOf('/');
  const matches = (m) => m?.id === meta.model.slice(slash + 1) && m?.providerID === meta.model.slice(0, slash);
  if (record.agent !== 'reviewer' || record.messageAgent !== 'reviewer' || !matches(record.model) ||
      !matches(record.messageModel) || record.directory !== '/workspace' || record.idle_outcome !== 'succeeded' ||
      record.finish !== 'stop') throw new Error('Native model/agent/session did not complete as requested');
}

async function startBroker(root) {
  const socket = path.join(root, 'egress.sock');
  const child = spawn('/usr/bin/python3', [path.join(here, 'egress.py'), socket],
    { env: { PATH: '/usr/bin:/bin' }, stdio: ['ignore', 'ignore', 'pipe'], detached: true });
  let error = ''; child.stderr.setEncoding('utf8'); child.stderr.on('data', (s) => { if (error.length < 4096) error += s; });
  let spawnError; child.on('error', (e) => { spawnError = e.code; });
  const started = Date.now();
  while (!fs.existsSync(socket)) {
    if (spawnError || child.exitCode !== null || Date.now() - started > 5000) {
      if (child.pid) stopOwned(child.pid, 'SIGKILL');
      fs.writeFileSync(path.join(root, 'broker-error.log'), error, { mode: 0o600 });
      throw new Error(`Egress broker failed (${spawnError ?? child.exitCode ?? 'startup deadline'})`);
    }
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  return { socket, child };
}

export async function execute(root, { binary, apiKey = process.env.MINIMAX_API_KEY, bounds = {} } = {}) {
  root = fs.realpathSync(root);
  const meta = readJSON(path.join(root, 'meta.json'));
  if (readJSON(path.join(root, 'result.json')).status !== 'prepared') throw new Error('Run is not fresh/prepared');
  writeJSON(path.join(root, 'result.json'), { status: 'running', eligible: false });
  let broker;
  const redact = (s) => apiKey ? String(s).split(apiKey).join('[REDACTED]') : String(s);
  try {
    if (!apiKey || !meta.model.startsWith('minimax-coding-plan/')) throw new Error('Selected provider is not configured for the verified egress path');
    const workspace = path.join(root, 'candidate');
    if (git(workspace, ['rev-parse', 'HEAD']).trim() !== meta.head || git(workspace, ['status', '--porcelain']).trim()) {
      throw new Error('Prepared checkout changed');
    }
    const policy = path.join(root, 'policy.json');
    if (policyHash(policy) !== meta.policyHash || meta.policyHash !== policyHash(path.join(here, 'policy.json'))) throw new Error('Policy changed');
    broker = await startBroker(root);
    const a = adapter({ workspace, runtime: path.join(root, 'runtime'), policy,
      binary, brief: path.join(root, 'brief.md'), proxySocket: broker.socket, apiKey });
    const config = a.invoke(['debug', 'config']);
    if (!config.includes('/etc/opencode/opencode.json') || !config.includes('voice-teacher-review-policy-v1')) throw new Error('Trusted policy not loaded');
    fs.writeFileSync(path.join(root, 'effective-config.json'), config, { mode: 0o600 });
    const checkedCLI = preflight({ ...meta, brief: '/brief.md' }, a.invoke);
    writeJSON(path.join(root, 'preflight.json'), checkedCLI);
    const command = ['/bin/sh', '-c',
      'socat TCP-LISTEN:18080,bind=127.0.0.1,reuseaddr,fork UNIX-CONNECT:/egress.sock & exec /opt/opencode "$@"',
      'review-cli', ...checkedCLI.args];
    const status = await watchProcess('/usr/bin/bwrap', [...a.prefix, ...command],
      { directory: root, env: a.env, secret: apiKey, ...bounds });
    if (status.reason || status.code !== 0) throw new Error(`Incomplete model process: ${status.reason}`);
    const record = sessionRecord(path.join(root, 'runtime'), status.sessionID);
    validateIdentity(record, meta);
    writeJSON(path.join(root, 'session.json'), { ...record, final: undefined });
    const text = redact(record.final);
    fs.writeFileSync(path.join(root, 'review.md'), text, { mode: 0o600 });
    const report = parseReport(text, meta);
    const result = { status: 'complete', eligible: report.verdict === 'approve',
      verdict: report.verdict, sessionID: status.sessionID, model: meta.model, head: meta.head, base: meta.base };
    writeJSON(path.join(root, 'result.json'), result);
    return result;
  } catch (e) {
    writeJSON(path.join(root, 'result.json'), { status: 'failed', eligible: false, error: redact(e.message) });
    throw new Error(`Review failed; retained diagnostics: ${root}`);
  } finally {
    if (broker?.child.pid) stopOwned(broker.child.pid, 'SIGKILL');
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [mode, file, binary] = process.argv.slice(2);
  if (mode === 'prepare' || mode === 'prepare-local') {
    const spec = readJSON(file);
    if (mode === 'prepare') {
      const { livePR } = await import('./github.mjs');
      const current = livePR(spec.repo, spec.pr);
      if (current.state !== 'open') throw new Error('PR is closed');
      Object.assign(spec, { base: current.base, head: current.head });
    }
    const meta = prepare(spec);
    console.log(JSON.stringify({ artifacts: meta.artifacts, base: meta.base, head: meta.head,
      criteria: meta.criteria, model: meta.model, eligible: false }, null, 2));
  }
  else if (mode === 'execute') console.log(JSON.stringify(await execute(file, { binary }), null, 2));
  else throw new Error('Usage: node runner.mjs prepare|prepare-local <spec.json> | execute <run-directory> <verified-opencode-binary>');
}
