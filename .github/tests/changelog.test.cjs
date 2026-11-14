const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const source = readFileSync(join(__dirname, '../workflows/changelog.yml'), 'utf8').split('          script: |\n')[1].split('\n').map(l => l.slice(12)).join('\n');
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
const run = new AsyncFunction('context', 'github', 'core', source);
const base = '## [Unreleased]\n\n## [1.0] - 2026-11-12\n### Added\n- Old feature.\n';
const valid = base.replace('## [Unreleased]', '## [Unreleased]\n### Added\n- New feature.');
async function check(head, { before = base, paths = ['src/app.js'], labels = [], count, site = valid } = {}) {
  let failed = false;
  const context = { repo: {}, payload: { pull_request: { number: 1, labels: labels.map(name => ({name})), changed_files: count ?? paths.length, base: {sha:'base'}, head:{sha:'head'} } } };
  const github = { paginate: async () => paths.map(filename => typeof filename === 'string' ? { filename } : filename), rest: {
    pulls: { listFiles: null }, repos: { getContent: async ({path,ref}) => ({data: {encoding:'base64', content:Buffer.from(ref === 'base' ? before : path === 'website/CHANGELOG.md' ? site : head).toString('base64')}}) }
  }};
  try { await run(context, github, {setFailed: () => { failed = true; }}); } catch { failed = true; }
  return failed;
}
for (const [name, head, options, failed] of [
  ['blank line', base+'\n', {}, true],
  ['whitespace only', base.replace('Old feature.', 'Old   feature. '), {}, true],
  ['empty bullet', base.replace('[Unreleased]', '[Unreleased]\n-   '), {}, true],
  ['historical edit', base.replace('Old feature.', 'Edited old feature.'), {}, true],
  ['moved entry', '## [Unreleased]\n### Added\n- Old feature.\n## [1.0] - 2026-11-12\n', {}, true],
  ['new entry', valid, {}, false],
  ['new dated release', base.replace('## [1.0]', '## [1.1] - 2026-11-14\n### Added\n- New feature.\n## [1.0]'), {}, false],
  ['old dated section addition', base+'- Another old release item.\n', {}, true],
  ['label skip', base, {labels:['no-changelog']}, false],
  ['path skip', base, {paths:['docs/guide.md','.github/workflows/ci.yml','tests/example.js']}, false],
  ['mixed docs and product', base, {paths:['docs/guide.md','src/app.js']}, true],
  ['profile in scope', base, {paths:['profile/README.md']}, true],
  ['renamed product in scope', base, {paths:[{filename:'tests/app.js',previous_filename:'src/app.js'}]}, true],
  ['incomplete list', valid, {count:3001}, true],
  ['first changelog', valid, {before:''}, false],
  ['historical edit plus new entry', valid.replace('Old feature.', 'Edited old feature.'), {}, true],
]) test(name, async () => assert.equal(await check(head, options), failed));
if (source.includes('knowledge/')) {
  test('site changes need site entry', async () => assert.equal(await check(valid,{paths:['website/public/open.html'],site:base}),true));
  test('mixed root/site requires both', async () => assert.equal(await check(base,{paths:['src/app.js','website/public/open.html']}),true));
  test('mixed root/site accepts both', async () => assert.equal(await check(valid,{paths:['src/app.js','website/public/open.html']}),false));
  test('knowledge docs skip', async () => assert.equal(await check(base,{paths:['knowledge/index.md']}),false));
}

const note = content => base.replace('## [Unreleased]', '## [Unreleased]\n### Added\n' + content);
const dated = content => base + '\n## [1.1] - 2026-11-14\n### Added\n' + content;
for (const [name, head, options, failed] of [
  ['HTML comment bullet', note('<!--\n- Hidden note.\n-->'), {}, true],
  ['unclosed HTML comment', dated('<!--\n- Hidden note.'), {}, true],
  ['comment containing headings', base + '\n<!--\n## [1.1] - 2026-11-14\n### Added\n- Hidden note.\n-->', {}, true],
  ['inline comment only', note('- <!-- Hidden note. -->'), {}, true],
  ['backtick fenced bullet', note('```markdown\n- Example note.\n```'), {}, true],
  ['tilde fenced bullet', note('~~~markdown\n- Example note.\n~~~'), {}, true],
  ['unclosed backtick fence', dated('```\n- Example note.'), {}, true],
  ['unclosed tilde fence', dated('~~~\n- Example note.'), {}, true],
  ['fenced fake headings', base + '\n```\n## [1.1] - 2026-11-14\n### Added\n- Example note.\n```', {}, true],
  ['wrong fence character does not close', note('```\n~~~\n- Example note.\n```'), {}, true],
  ['short fence does not close', note('````\n```\n- Example note.\n````'), {}, true],
  ['empty emphasis bullet', note('- ** **'), {}, true],
  ['empty underscore bullet', note('- __ __'), {}, true],
  ['empty inline code bullet', note('- ` `'), {}, true],
  ['empty strikethrough bullet', note('- ~~ ~~'), {}, true],
  ['punctuation-only bullet', note('- !?...'), {}, true],
  ['no category', base.replace('## [Unreleased]', '## [Unreleased]\n- New note.'), {}, true],
  ['nonstandard category', note('- New note.').replace('### Added','### Notes'), {}, true],
  ['wrong category depth', note('- New note.').replace('### Added','#### Added'), {}, true],
  ['unbracketed version', dated('- New note.').replace('## [1.1]','## 1.1'), {}, true],
  ['outside release heading', '- New note.\n'+base, {}, true],
  ['release resets category', base+'\n## [1.1] - 2026-11-14\n- New note.\n', {}, true],
  ['markup and case changes are not new', note('- **OLD FEATURE.**'), {}, true],
  ['wrapped old entry is not new', note('- Old\n  feature.'), {}, true],
  ['comments cannot edit an old entry', valid.replace('Old feature.','Old <!-- feature -->.'), {}, true],
  ['commented old entry plus new entry', valid.replace('- Old feature.','<!-- - Old feature. -->'), {}, true],
  ['fenced old entry plus new entry', valid.replace('- Old feature.','```\n- Old feature.\n```'), {}, true],
  ['visible note after closed fence', note('```\n- Example note.\n```\n- Visible note.'), {}, false],
  ['visible text with inline comment', note('- Visible <!-- hidden --> note.'), {}, false],
  ['visible emphasized note', note('- **Visible note.**'), {}, false],
  ['numeric note', note('- 42'), {}, false],
  ['unicode alphanumeric note', note('- 新功能'), {}, false],
  ['plus bullet', note('+ Visible note.'), {}, false],
  ['asterisk bullet', note('* Visible note.'), {}, false],
]) test(name, async () => assert.equal(await check(head, options), failed));
for (const category of ['Added','Changed','Deprecated','Removed','Fixed','Security'])
  test(`standard category ${category}`, async () => assert.equal(await check(note('- Visible note.').replace('### Added',`### ${category}`)),false));
