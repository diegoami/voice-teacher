// Trusted host-side publisher. This module is never invoked in the model job.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { reviewArgs, SUPPORTED_VERSION } from './cli.mjs';
import { github, livePR } from './github.mjs';
import { readJSON, writeJSON, sessionRecord, validateIdentity } from './runner.mjs';
import { parseReport } from './report.mjs';

export { github, livePR } from './github.mjs';

export function checkCurrent(meta, current) {
  if (current.state !== 'open' || current.head !== meta.head || current.base !== meta.base) {
    throw new Error('Stale or closed PR: reviewed base/head no longer current');
  }
}

export function loadEvidence(root) {
  const meta = readJSON(path.join(root, 'meta.json'));
  const result = readJSON(path.join(root, 'result.json'));
  const process = readJSON(path.join(root, 'process.json'));
  const preflight = readJSON(path.join(root, 'preflight.json'));
  if (result.status !== 'complete' || result.head !== meta.head || result.base !== meta.base || result.model !== meta.model ||
      process.code !== 0 || process.reason !== null || !process.sessionID || result.sessionID !== process.sessionID ||
      preflight.version !== `opencode v${SUPPORTED_VERSION}` ||
      JSON.stringify(preflight.args) !== JSON.stringify(reviewArgs({ ...meta, brief: '/brief.md' }))) {
    throw new Error('Incomplete, failed or inconsistent run artifacts');
  }
  const native = sessionRecord(path.join(root, 'runtime'), process.sessionID);
  validateIdentity(native, meta);
  const text = fs.readFileSync(path.join(root, 'review.md'), 'utf8');
  if (native.final !== text) throw new Error('Published report does not match the native final response');
  const report = parseReport(text, meta);
  if (report.verdict !== result.verdict || result.eligible !== (report.verdict === 'approve')) throw new Error('Contradictory stored verdict');
  return { meta, result, report, text, preflight };
}

export function publicationBody({ meta, result, text, preflight }) {
  return `Independent model review — ${meta.task}\n\n` +
    `Reviewed head: \`${meta.head}\`\nBase: \`${meta.base}\`\n` +
    `Reviewer: \`${meta.model}\`; family: ${meta.reviewerFamily}; variant: ${meta.variant}.\n` +
    `Implementer family: ${meta.implementerFamily}. CLI: ${preflight.version}; agent: reviewer.\n` +
    `Session: \`${result.sessionID}\`. Policy SHA-256: \`${meta.policyHash}\`.\n\n` +
    `This is a report comment tied to the commit above. It is not a GitHub branch-protection approval ` +
    `or permission to merge. A new head invalidates its approval for the current PR. ` +
    `The main session must reconcile findings and recheck the live head before merging.\n\n` +
    `Operator corroborations: ${JSON.stringify(meta.corroborations ?? [])}\n\n---\n\n${text}`;
}

export function publishEvidence(evidence, { gh = github, dryRun = true } = {}) {
  const { meta, report } = evidence;
  checkCurrent(meta, livePR(meta.repo, meta.pr, gh));
  const body = publicationBody(evidence);
  if (body.length > 60_000) throw new Error('Complete review exceeds comment limit; retain locally rather than truncate');
  if (dryRun) return { published: false, eligible: report.verdict === 'approve', body };
  // Structured API stdin: no shell interpolation or provider credentials.
  const posted = gh(['api', `repos/${meta.repo}/issues/${meta.pr}/comments`, '--method', 'POST', '--input', '-'], { body });
  try { checkCurrent(meta, livePR(meta.repo, meta.pr, gh)); }
  catch (e) {
    gh(['api', `repos/${meta.repo}/issues/comments/${posted.id}`, '--method', 'PATCH', '--input', '-'],
      { body: `**OUTDATED — base/head changed during publication; no current approval.**\n\n${body}` });
    return { published: true, eligible: false, stale: true, url: posted.html_url };
  }
  return { published: true, eligible: report.verdict === 'approve', stale: false, url: posted.html_url };
}

export function publish(root, { dryRun = true, gh = github } = {}) {
  try {
    const evidence = loadEvidence(root);
    const outcome = publishEvidence(evidence, { dryRun, gh });
    if (dryRun) fs.writeFileSync(path.join(root, 'publication-preview.md'), outcome.body, { mode: 0o600 });
    const { body, ...summary } = outcome;
    writeJSON(path.join(root, 'publication.json'), summary);
    return summary;
  } catch (e) {
    writeJSON(path.join(root, 'publication.json'), { published: false, eligible: false, error: e.message });
    throw e;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [mode, root] = process.argv.slice(2);
  if (!['preview', 'publish'].includes(mode)) throw new Error('Usage: node publication.mjs preview|publish <run-directory>');
  console.log(JSON.stringify(publish(root, { dryRun: mode === 'preview' }), null, 2));
}
