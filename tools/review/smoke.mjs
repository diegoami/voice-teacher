// Supervised T01 adapter, not the T02 review lifecycle/publisher.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { checked, preflight } from './cli.mjs';
import { sandboxArgs, sandboxEnvironment, policyHash } from './sandbox.mjs';

export function adapter({ workspace, runtime, binary, brief, policy, proxySocket, apiKey }) {
  const prefix = sandboxArgs({ workspace, runtime, binary, brief, policy, proxySocket });
  const env = sandboxEnvironment(apiKey);
  // No shell interpolation, inherited credentials, or stdin; bwrap's PID namespace
  // terminates descendants when its init process is killed. No unsandboxed fallback.
  const invoke = (args, timeout = 30_000) => {
    try {
      const command = proxySocket ? ['/bin/sh', '-c',
        'socat TCP-LISTEN:18080,bind=127.0.0.1,reuseaddr,fork UNIX-CONNECT:/egress.sock & exec /opt/opencode "$@"',
        'review-cli', ...args] : ['/opt/opencode', ...args];
      return checked('/usr/bin/bwrap', [...prefix, ...command], { env, timeout });
    } catch (error) {
      const redact = (value) => apiKey ? String(value ?? '').split(apiKey).join('[REDACTED]') : value;
      const diagnostic = runtime + '-failure-' + randomUUID() + '.json';
      fs.writeFileSync(diagnostic, JSON.stringify({ args, status: error.status, signal: error.signal,
        stdout: redact(error.stdout), stderr: redact(error.stderr) }, null, 2), { mode: 0o600 });
      throw new Error(`Incomplete CLI run; diagnostic retained: ${diagnostic}`);
    }
  };
  return { invoke, prefix, env };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const [mode, specFile] = process.argv.slice(2);
  if (!['preflight', 'agents', 'config', 'review', 'probe'].includes(mode) || !specFile) {
    throw new Error('Usage: node smoke.mjs preflight|agents|config|review|probe <trusted-spec.json>');
  }
  const spec = JSON.parse(fs.readFileSync(specFile, 'utf8'));
  // A spec contains paths/model identity only. The sole provider secret stays in env.
  if ('apiKey' in spec) throw new Error('Do not store provider secrets in a spec');
  const a = adapter({ ...spec, apiKey: process.env.MINIMAX_API_KEY });
  if (mode === 'probe') {
    const script = String.raw`
import os, pathlib, subprocess, socket
p=pathlib.Path('/workspace/probe-target.txt')
for label, action in [
 ('direct_source_write', lambda: p.write_text('changed')),
 ('indirect_source_write', lambda: subprocess.run(['sh','-c','printf changed > /workspace/probe-target.txt'], check=True, capture_output=True)),
 ('trusted_policy_write', lambda: pathlib.Path('/etc/opencode/opencode.json').write_text('{}')),
]:
 try:
  action()
  raise SystemExit(label + ': UNEXPECTED SUCCESS')
 except (OSError, subprocess.CalledProcessError):
  print(label + ': denied')
for p in ['/home/diego/.ssh', '/home/diego/.config/gh', '/run/user', '/mnt/c']:
 assert not pathlib.Path(p).exists(), p
assert not any(k in os.environ for k in ['GH_TOKEN','GITHUB_TOKEN','SSH_AUTH_SOCK','DBUS_SESSION_BUS_ADDRESS'])
assert pathlib.Path('/workspace/probe-target.txt').read_text() == 'original\n'
pathlib.Path('/scratch/test-output').write_text('scratch permitted')
r=subprocess.run(['gh','api','--method','POST','repos/voice-teacher-isolation-probe/nonexistent/issues','-f','title=probe'], capture_output=True, text=True)
assert r.returncode != 0 and ('GH_TOKEN' in r.stderr or 'gh auth login' in r.stderr), 'GitHub write did not fail for missing authentication'
print('github_write: denied (no authentication)')
try:
 socket.create_connection(('1.1.1.1', 443), timeout=1)
 raise SystemExit('direct_network: UNEXPECTED SUCCESS')
except OSError:
 print('direct_network: denied')
print('host_credentials: absent; scratch_write: allowed')
`;
    console.log(checked('/usr/bin/bwrap', [...a.prefix, '/usr/bin/python3', '-c', script], { env: a.env }));
  } else if (mode === 'agents' || mode === 'config') {
    console.log(a.invoke(['debug', mode]));
  } else {
    const result = preflight({ ...spec, brief: '/brief.md' }, a.invoke);
    if (mode === 'preflight') console.log(JSON.stringify({ ...result, policyHash: policyHash(spec.policy) }, null, 2));
    else {
      if (!process.env.MINIMAX_API_KEY) throw new Error('MiniMax credential is unavailable; no review started');
      console.log(a.invoke(result.args, 600_000));
    }
  }
}
