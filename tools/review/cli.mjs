import { spawnSync } from 'node:child_process';

export const SUPPORTED_VERSION = '2.0.28';
const families = new Set(['openai', 'anthropic', 'google', 'minimax']);

export function modelFamily(model) {
  if (typeof model !== 'string' || !/^[\w.-]+\/[\w./~-]+$/.test(model)) {
    throw new Error('Supply an explicit provider/model without a variant; variants are not verified yet');
  }
  const name = model.slice(model.indexOf('/') + 1).split('/').at(-1).replace(/^~/, '').toLowerCase();
  if (/^minimax-m\d/.test(name)) return 'minimax';
  if (/^gpt-\d|^o[134](?:-|$)/.test(name)) return 'openai';
  if (/^claude-/.test(name)) return 'anthropic';
  if (/^gemini-/.test(name)) return 'google';
  throw new Error(`Unknown model family: ${model}`);
}

export function reviewArgs({ model, implementerFamily, brief = '/brief.md', extraFlags = [] }) {
  if (!families.has(implementerFamily)) throw new Error('Unknown implementer family');
  if (modelFamily(model) === implementerFamily) throw new Error('Reviewer must have a different model family');
  if (extraFlags.length) throw new Error('Unsupported invocation flags');
  return ['run', '--standalone', '--model', model, '--agent', 'reviewer', '--file', brief,
    '--format', 'json', 'Review the attached brief and pinned patch. Return the complete review.'];
}

export function checked(exe, args, options = {}) {
  const result = spawnSync(exe, args, { encoding: 'utf8', timeout: 30_000,
    maxBuffer: 16 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'], ...options });
  if (result.error || result.status !== 0) {
    // Do not echo arbitrary CLI output: it may contain credentials or private input.
    throw Object.assign(new Error(`CLI check failed (${result.error?.code ?? result.status}): ${args[0]}`),
      { stdout: result.stdout, stderr: result.stderr, status: result.status, signal: result.signal });
  }
  return result.stdout;
}

// invoke must already run inside the trusted OS boundary, including these non-billed checks.
export function preflight(options, invoke) {
  const args = reviewArgs(options);
  const version = invoke(['--version']).trim();
  if (version !== `opencode v${SUPPORTED_VERSION}`) throw new Error(`Unsupported CLI version: ${version}`);
  const help = invoke(['run', '--help']);
  for (const flag of ['--standalone', '--model', '--agent', '--file', '--format']) {
    if (!new RegExp(`(?:^|\\s)${flag}(?:\\s|,|$)`, 'm').test(help)) {
      throw new Error(`Unsupported CLI flag: ${flag}`);
    }
  }
  const listed = invoke(['models']).split(/\r?\n/).map((line) => line.trim());
  if (!listed.includes(options.model)) throw new Error('Requested model is not in the live CLI catalogue');
  return { version, args, reviewerFamily: modelFamily(options.model) };
}
