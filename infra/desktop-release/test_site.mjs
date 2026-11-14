import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const path = process.argv[2] || 'sites/aira-download/app.js';
const source = fs.readFileSync(path, 'utf8').split('// Published installers are independent of the HTML deployment.')[1];
assert.ok(source, 'Website must consume independently published installer metadata');
const context = vm.createContext({
  fetch: async () => ({ ok: false }), AbortSignal,
});
vm.runInContext(source, context);
const record = (version, windows) => {
  const filename = windows ? `AIRA-Setup-${version}.exe` : `AIRA-${version}-apple-silicon.dmg`;
  return { version, filename, bytes: 1234567, sha256: 'a'.repeat(64), url: 'https://51.250.81.70/downloads/' + filename };
};
const metadata = { schema: 1, platforms: {
  'windows-x64': record('0.3.11', true), 'macos-arm64': record('0.3.11', false),
} };
const plan = context.planReleaseLinks(metadata);
assert.equal(plan.length, 2);
assert.equal(plan[0].url, metadata.platforms['windows-x64'].url);
assert.match(plan[0].text, /0\.3\.11 · 2 МБ/);
for (const mutate of [
  (data) => { data.platforms['windows-x64'].url = 'https://foreign.invalid/installer.exe'; },
  (data) => { data.platforms['macos-arm64'].version = '<script>'; },
  (data) => { delete data.platforms['macos-arm64']; },
  (data) => { data.platforms['windows-x64'].bytes = -1; },
]) {
  const invalid = structuredClone(metadata);
  mutate(invalid);
  assert.throws(() => context.planReleaseLinks(invalid));
}
console.log('Release metadata updates both download links; malformed metadata never replaces them.');
