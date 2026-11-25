// Runs the pure functions of index.html (route parsing, span grammar, decoding, encoding detection,
// layout choice, permanence, find-in-file scanning) against test/cases.js. No DOM, no network.
//   node test/run.cjs
'use strict';
const fs = require('fs');
const path = require('path');
const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const m = /<script>\n\(\(\) => \{([\s\S]*?)\n\}\)\(\);\n<\/script>/.exec(html);
if (!m) throw new Error('could not find the app script in index.html');
const js = m[1];
const between = (a, b) => { const i = js.indexOf(a), j = js.indexOf(b); if (i < 0 || j < 0 || j < i) throw new Error(`section markers not found: ${a} .. ${b}`); return js.slice(i, j); };
const code = [
  between('const n0 =', '/* ---------- span grammar'),
  between('/* ---------- span grammar', '/* ---------- source links'),
  between('/* ---------- source links', '/* ---------- settings'),
  between('/* ---------- decoding', '/* ---------- the span as the original wrote it'),
  between('/* ---------- the span as the original wrote it', '/* ---------- state'),
  between('/* ---------- find in a file', 'async function* streamFile'),
].join('\n');
const head = `
const assert = require('assert');
const location = { href: 'https://x.github.io/repo/index.html', protocol: 'https:' };
const types = new Map();
const PROVIDER_IDS = ['ia', 'iafts', 'loc', 'wiki', 'gh'];
const getJson = async () => ({}), commit = () => {}, getSize = async () => null, dataFor = () => ({ state: 'loading', waiters: new Set() });
global.window = { Alhazen: require(${JSON.stringify(path.join(root, 'vendor', 'alhazen.js'))}) };
`;
const cases = fs.readFileSync(path.join(__dirname, 'cases.js'), 'utf8');
const file = path.join(require('os').tmpdir(), `archiveo-test-${process.pid}.cjs`);
fs.writeFileSync(file, head + code + '\n' + cases);
try { require(file); } finally { setTimeout(() => fs.rmSync(file, { force: true }), 1000); }
