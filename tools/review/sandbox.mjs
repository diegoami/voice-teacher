import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';

const canonicalDirectory = (p) => {
  const real = fs.realpathSync(p);
  if (!fs.statSync(real).isDirectory()) throw new Error('Expected directory');
  return real;
};

// This is a separate, empty-root mount namespace, not a credential deny list.
// Only a selected provider key enters; no host home, sockets, GitHub auth or agents.
export function sandboxArgs({ workspace, runtime, policy, binary, brief, proxySocket }) {
  workspace = canonicalDirectory(workspace);
  runtime = canonicalDirectory(runtime);
  if (runtime === workspace || runtime.startsWith(workspace + '/') || workspace.startsWith(runtime + '/')) throw new Error('Runtime must be separate from candidate checkout');
  policy = fs.realpathSync(policy);
  binary = fs.realpathSync(binary);
  brief = fs.realpathSync(brief);
  for (const p of [policy, binary, brief]) {
    if (p.startsWith(workspace + '/')) throw new Error('Trusted inputs must be outside candidate checkout');
    if (p.startsWith(runtime + '/')) throw new Error('Trusted inputs must be outside writable runtime');
  }
  const args = ['--unshare-user', '--unshare-pid', '--unshare-ipc', '--unshare-uts', '--unshare-net',
    '--die-with-parent', '--new-session', '--cap-drop', 'ALL',
    '--ro-bind', '/usr', '/usr'];
  for (const p of ['/bin', '/sbin', '/lib', '/lib64']) {
    if (!fs.existsSync(p)) continue;
    const s = fs.lstatSync(p);
    args.push(...(s.isSymbolicLink() ? ['--symlink', fs.readlinkSync(p), p] : ['--ro-bind', p, p]));
  }
  args.push('--dir', '/etc');
  for (const p of ['/etc/ssl', '/etc/resolv.conf', '/etc/hosts', '/etc/nsswitch.conf']) {
    if (fs.existsSync(p)) args.push('--ro-bind', p, p);
  }
  args.push('--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--dir', '/home',
    '--bind', runtime, '/runtime', '--dir', '/runtime/home', '--ro-bind', workspace, '/workspace',
    '--ro-bind', binary, '/opt/opencode', '--ro-bind', brief, '/brief.md',
    '--ro-bind', policy, '/etc/opencode/opencode.json',
    '--dir', '/scratch', '--tmpfs', '/scratch');
  if (proxySocket) {
    proxySocket = fs.realpathSync(proxySocket);
    if (!fs.statSync(proxySocket).isSocket()) throw new Error('Expected trusted egress socket');
    args.push('--ro-bind', proxySocket, '/egress.sock');
  }
  // Hide executable project configuration, including plugins/agents. A trusted empty
  // config is mounted over each direct config if present. The diff still contains it.
  for (const file of ['opencode.json', 'opencode.jsonc']) {
    if (fs.lstatSync(path.join(workspace, file), { throwIfNoEntry: false })?.isSymbolicLink()) throw new Error('Candidate config symlink refused');
    if (fs.existsSync(path.join(workspace, file))) args.push('--ro-bind', '/dev/null', `/workspace/${file}`);
  }
  for (const dir of ['.opencode', '.agents', '.claude']) {
    if (fs.lstatSync(path.join(workspace, dir), { throwIfNoEntry: false })?.isSymbolicLink()) throw new Error('Candidate config symlink refused');
    if (fs.existsSync(path.join(workspace, dir))) args.push('--tmpfs', `/workspace/${dir}`, '--remount-ro', `/workspace/${dir}`);
  }
  const env = {
    HOME: '/runtime/home', XDG_CONFIG_HOME: '/runtime/config', XDG_DATA_HOME: '/runtime/data',
    XDG_CACHE_HOME: '/runtime/cache', XDG_STATE_HOME: '/runtime/state',
    TMPDIR: '/scratch', PATH: '/usr/bin:/bin', LANG: 'C.UTF-8',
    GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null', GIT_TERMINAL_PROMPT: '0',
    OPENCODE_DISABLE_PROJECT_CONFIG: '1',
    HTTP_PROXY: 'http://127.0.0.1:18080', HTTPS_PROXY: 'http://127.0.0.1:18080',
    NO_PROXY: 'localhost,127.0.0.1,::1',
  };
  for (const [key, value] of Object.entries(env)) args.push('--setenv', key, value);
  args.push('--chdir', '/workspace', '--');
  return args;
}

export function sandboxEnvironment(apiKey) {
  // Caller must use this instead of inheriting process.env. No GitHub credentials,
  // auth sockets, alternative XDG paths or injected runtime options enter.
  return { PATH: '/usr/bin:/bin', ...(apiKey ? { MINIMAX_API_KEY: apiKey } : {}) };
}

export function policyHash(file) {
  return createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}
