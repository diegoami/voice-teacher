import { checked } from './cli.mjs';

// Trusted host only. API payloads go to stdin, never through shell interpolation.
export const github = (args, payload) => JSON.parse(checked('gh', args,
  payload ? { input: JSON.stringify(payload), stdio: ['pipe', 'pipe', 'pipe'] } : {}));

export function livePR(repo, pr, gh = github) {
  if (!/^[\w.-]+\/[\w.-]+$/.test(repo) || !Number.isSafeInteger(pr) || pr < 1) throw new Error('Invalid PR');
  const p = gh(['api', `repos/${repo}/pulls/${pr}`]);
  const branch = gh(['api', `repos/${repo}/branches/${encodeURIComponent(p.base.ref)}`]);
  return { head: p.head.sha, base: branch.commit.sha, state: p.state, baseBranch: p.base.ref };
}
