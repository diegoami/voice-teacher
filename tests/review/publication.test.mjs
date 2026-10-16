import test from 'node:test';
import assert from 'node:assert/strict';
import { parseReport, criteriaFromTask, reviewBrief } from '../../tools/review/report.mjs';
import { publishEvidence } from '../../tools/review/publication.mjs';

const meta = { repo: 'owner/project', pr: 5, task: 'T02', base: 'a'.repeat(40), head: 'b'.repeat(40),
  criteria: ['DW1', 'DW2', 'DW3'], model: 'minimax-coding-plan/MiniMax-M3', implementerFamily: 'openai',
  reviewerFamily: 'minimax', variant: 'provider default', policyHash: 'c'.repeat(64) };
function report() {
  return { schema_version: 1, base: meta.base, head: meta.head, verdict: 'approve',
    criteria: meta.criteria.map((id) => ({ id, status: 'verified', evidence: 'Ran the named check: passed' })),
    findings: [], limitations: [], unverified_criteria: [] };
}
function text(r, verdict = r.verdict) { return `Acceptance checks and limitations: none unverified.\nVerdict: ${verdict}\n\n\`\`\`voice-teacher-review\n${JSON.stringify(r)}\n\`\`\``; }

test('task criteria come from the complete numbered acceptance section', () => {
  assert.deepEqual(criteriaFromTask('## Done when\n\n1. A\n2. B\n\n## Verification\n1. unrelated'), ['DW1', 'DW2']);
  assert.throws(() => criteriaFromTask('nothing'));
});

test('missing, duplicate, truncated and contradictory reports cannot approve', () => {
  const mutations = [
    (r) => { r.criteria.pop(); },
    (r) => { r.criteria[2] = r.criteria[0]; },
    (r) => { r.criteria[0].evidence = ''; },
    (r) => { r.criteria[0].status = 'not_run'; },
    (r) => { r.unverified_criteria = ['DW2']; },
    (r) => { r.head = 'd'.repeat(40); },
    (r) => { r.criteria[0].status = 'corroborated'; r.criteria[0].corroboration = 'made-up'; },
    (r) => { r.findings = [{ id: 'F1', severity: 'blocking', path: 'x', line: 1, summary: 'bug', evidence: 'repro' }]; },
  ];
  for (const mutate of mutations) {
    const r = report(); mutate(r); assert.throws(() => parseReport(text(r), meta));
  }
  for (const s of ['', text(report()).slice(0, -3), text(report()) + '\ntrailing',
    text(report(), 'rework'), 'Verdict: rework\n' + text(report()),
    'Conditional approval\n' + text(report()), text(report()).replace('Verdict:', 'Result:')]) {
    assert.throws(() => parseReport(s, meta));
  }
  assert.equal(parseReport(text(report()), meta).verdict, 'approve');
});

test('not-run remains unverified; operator-only checks require named corroboration', () => {
  const r = report();
  r.criteria[2] = { id: 'DW3', status: 'corroborated', corroboration: 'phone', evidence: 'Operator phone check' };
  const m = { ...meta, corroborations: [{ id: 'phone', criterion: 'DW3', verifier: 'operator', evidence: 'Device and measured result' }] };
  assert.equal(parseReport(text(r), m).verdict, 'approve');
  r.verdict = 'rework'; r.criteria[2].status = 'not_run'; r.unverified_criteria = ['DW3'];
  assert.equal(parseReport(text(r), meta).verdict, 'rework');
});

test('brief demonstrates exact named corroboration without pretending the model ran it', () => {
  const m = { ...meta, corroborations: [{ id: 'operator-check', criterion: 'DW3', verifier: 'operator', evidence: 'Measured result' }] };
  const brief = reviewBrief(m, 'Full task', 'full patch', 'implementer results');
  assert.match(brief, /"corroboration": "operator-check"/);
  assert.match(brief, /criterion covered by named corroboration is not also unverified/);
});

function fakeGH({ staleBefore = false, staleAfter = false, baseChanges = false } = {}) {
  let posted = false; const writes = [];
  const gh = (args, input) => {
    if (args.includes('POST')) { posted = true; writes.push(input); return { id: 42, html_url: 'https://example.test/review' }; }
    if (args.includes('PATCH')) { writes.push(input); return {}; }
    if (args[1].includes('/branches/')) return { commit: { sha: baseChanges ? 'f'.repeat(40) : meta.base } };
    return { state: 'open', head: { sha: staleBefore || (staleAfter && posted) ? 'e'.repeat(40) : meta.head },
      base: { ref: 'main', sha: '0'.repeat(40) } }; // cached pull base SHA is intentionally wrong
  };
  return { gh, writes };
}
function evidence() {
  const r = report(); return { meta, report: r, text: text(r), result: { sessionID: 'ses_test' }, preflight: { version: 'opencode v2.0.28' } };
}

test('stale head or actual target branch prevents publication before any write', () => {
  for (const options of [{ staleBefore: true }, { baseChanges: true }]) {
    const f = fakeGH(options);
    assert.throws(() => publishEvidence(evidence(), { gh: f.gh, dryRun: false }), /Stale/);
    assert.equal(f.writes.length, 0);
  }
});

test('dry-run retains complete identity/report and never writes; publisher does not merge', () => {
  const f = fakeGH(); const r = publishEvidence(evidence(), { gh: f.gh });
  assert.equal(r.published, false); assert.equal(f.writes.length, 0);
  for (const value of [meta.model, meta.head, 'ses_test', 'limitations', 'voice-teacher-review']) assert.ok(r.body.includes(value));
  const live = publishEvidence(evidence(), { gh: f.gh, dryRun: false });
  assert.equal(live.eligible, true); assert.equal(f.writes.length, 1);
  assert.equal(f.writes[0].body, r.body);
});

test('head changed while posting invalidates and annotates historical comment', () => {
  const f = fakeGH({ staleAfter: true });
  const r = publishEvidence(evidence(), { gh: f.gh, dryRun: false });
  assert.equal(r.eligible, false); assert.equal(r.stale, true);
  assert.match(f.writes[1].body, /^\*\*OUTDATED/);
});
