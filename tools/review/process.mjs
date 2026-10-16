import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';

function redactedLog(file, secret) {
  const fd = fs.openSync(file, 'wx', 0o600);
  let pending = '';
  return {
    append(s) {
      if (!secret) { fs.writeSync(fd, s); return; }
      pending += s;
      while (pending.length >= secret.length) {
        const index = pending.indexOf(secret);
        if (index === 0) { fs.writeSync(fd, '[REDACTED]'); pending = pending.slice(secret.length); }
        else {
          const n = index < 0 ? pending.length - secret.length + 1 : index;
          fs.writeSync(fd, pending.slice(0, n)); pending = pending.slice(n);
        }
      }
    },
    close() { fs.writeSync(fd, pending); fs.closeSync(fd); },
  };
}

// Detached group belongs exclusively to this invocation. Never use pkill or a
// global process-name search. bwrap additionally owns a private PID namespace.
export function stopOwned(pid, signal = 'SIGTERM') {
  try { process.kill(-pid, signal); } catch (e) { if (e.code !== 'ESRCH') throw e; }
}

export async function watchProcess(exe, args, { directory, env, startupMs = 120_000,
  idleMs = 240_000, totalMs = 900_000, maxBytes = 16 * 1024 * 1024, secret = '' }) {
  for (const ms of [startupMs, idleMs, totalMs, maxBytes]) {
    if (!Number.isSafeInteger(ms) || ms <= 0) throw new Error('Invalid process bound');
  }
  const stdout = redactedLog(path.join(directory, 'stdout.jsonl'), secret);
  const stderr = redactedLog(path.join(directory, 'stderr.log'), secret);
  const started = Date.now();
  let activity = started, sessionID, reason, pending = '', bytes = 0, killTimer;
  const child = spawn(exe, args, { env, stdio: ['ignore', 'pipe', 'pipe'], detached: true });
  const stop = (why) => {
    if (reason) return;
    reason = why;
    if (child.pid) {
      stopOwned(child.pid);
      killTimer = setTimeout(() => stopOwned(child.pid, 'SIGKILL'), 250);
    }
  };
  const onSignal = () => stop('operator-interrupted');
  process.on('SIGTERM', onSignal); process.on('SIGINT', onSignal);
  const timer = setInterval(() => {
    if (Date.now() - started >= totalMs) stop('total-deadline');
    else if (!sessionID && Date.now() - started >= startupMs) stop('startup-deadline');
    else if (sessionID && Date.now() - activity >= idleMs) stop('idle-deadline');
  }, Math.max(5, Math.min(1000, startupMs / 4, idleMs / 4, totalMs / 4)));
  const receive = (s, isError) => {
    bytes += Buffer.byteLength(s);
    if (bytes > maxBytes) { stop('output-limit'); return; }
    if (isError) { stderr.append(s); return; }
    stdout.append(s); pending += s;
    let end;
    while ((end = pending.indexOf('\n')) >= 0) {
      const line = pending.slice(0, end); pending = pending.slice(end + 1);
      try {
        const d = JSON.parse(line);
        if (['step_start', 'text', 'tool_use', 'step_finish', 'error'].includes(d.type) &&
            typeof d.sessionID === 'string' && /^ses_[\w-]+$/.test(d.sessionID)) {
          if (sessionID && d.sessionID !== sessionID) stop('multiple-sessions');
          sessionID = d.sessionID; activity = Date.now();
          if (d.type === 'error') stop('cli-error');
        }
      } catch { /* unstructured output does not keep the job alive */ }
    }
  };
  child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
  child.stdout.on('data', (s) => receive(s, false)); child.stderr.on('data', (s) => receive(s, true));
  const result = await new Promise((resolve) => {
    child.on('error', (e) => { reason = `spawn-${e.code}`; });
    child.on('close', (code, signal) => resolve({ code, signal }));
  });
  clearInterval(timer); clearTimeout(killTimer);
  // Kill surviving descendants even when the leader exited first.
  if (child.pid) stopOwned(child.pid, 'SIGKILL');
  process.off('SIGTERM', onSignal); process.off('SIGINT', onSignal);
  stdout.close(); stderr.close();
  const status = { ...result, sessionID: sessionID ?? null, reason: reason ??
    (result.code !== 0 ? 'nonzero-exit' : !sessionID ? 'no-session' : null), elapsedMs: Date.now() - started };
  fs.writeFileSync(path.join(directory, 'process.json'), JSON.stringify(status, null, 2), { mode: 0o600 });
  return status;
}
