// Assertions for the pure functions in index.html. test/run.cjs supplies the code under test.
const R = parseRange;
assert.deepStrictEqual(R('1000-1199'), {kind:'range',start:1000,end:1199});
assert.deepStrictEqual(R('1000+200'), {kind:'range',start:1000,end:1199});
assert.deepStrictEqual(R('0x400-0x4ff'), {kind:'range',start:1024,end:1279});
assert.deepStrictEqual(R('4096-'), {kind:'open',start:4096});
assert.deepStrictEqual(R('-512'), {kind:'suffix',len:512});
assert.strictEqual(R('9-3'), null); assert.strictEqual(R('abc'), null); assert.strictEqual(R('1000+0'), null); assert.strictEqual(R('-0'), null);
assert.strictEqual(R('99999999999999999999-99999999999999999999'), null);
// round-trip a label with awkward characters
const lab = 'a b,c:d%e';
assert.deepStrictEqual(parseSpanToken(spanToken({kind:'range',start:10,end:20,label:lab})), {kind:'range',start:10,end:20,label:lab});
// routes + focus
let st = parseRoute('#u=https://archive.org/download/x/y.txt&s=0-9:one&s=20-29,40-49&e=latin1&f=1.2&c=64&v=text');
assert.strictEqual(st.sources[0].spans.length,3); assert.deepStrictEqual(st.focus,{si:0,part:1}); assert.strictEqual(st.ctx,64);
st.focus = resolveFocus(st.focus, st.sources);
assert.strictEqual(toHash(st), 'u=https://archive.org/download/x/y.txt&s=0-9:one&s=20-29&s=40-49&e=latin1&f=1.2&c=64&v=text');
// links made when there was a hex view still open, as plain text
assert.strictEqual(parseRoute('#u=https://a.test/f&s=1-2&v=hex').view, 'text'); assert.strictEqual(toHash(parseRoute('#u=https://a.test/f&s=1-2&v=hex')).includes('v=hex'), false);
// single source, default part: f is omitted; any other state writes f
let one = parseRoute('#u=https://a.test/f&s=1-2&s=5-6'); one.focus = resolveFocus(one.focus, one.sources);
assert.deepStrictEqual(one.focus,{si:0,part:null}); assert.strictEqual(toHash(one),'u=https://a.test/f&s=1-2&s=5-6');
one.focus = {si:0,part:0}; assert.strictEqual(toHash(one),'u=https://a.test/f&s=1-2&s=5-6');   // part 0 is the default part
one.focus = {si:0,part:1}; assert.ok(toHash(one).endsWith('&f=1.2'));
one.focus = {si:0,part:'b'}; assert.ok(toHash(one).endsWith('&f=1.b'));
one.focus = null; assert.ok(toHash(one).endsWith('&f=0'));
// explicit index survives a round trip; two sources default to the index (no f)
let two = parseRoute('#u=https://a.test/f&u=https://b.test/g&s=1-2'); two.focus = resolveFocus(two.focus, two.sources);
assert.strictEqual(two.focus, null); assert.strictEqual(toHash(two), 'u=https://a.test/f&u=https://b.test/g&s=1-2');
let back = parseRoute('#'+toHash(two)); assert.strictEqual(resolveFocus(back.focus, back.sources), null);
two.focus = {si:1,part:null}; back = parseRoute('#'+toHash(two)); assert.deepStrictEqual(resolveFocus(back.focus, back.sources), {si:1,part:0});
// a focus index past the end falls back safely
let bad = parseRoute('#u=https://a.test/f&f=9.9'); assert.deepStrictEqual(resolveFocus(bad.focus, bad.sources), {si:0,part:null});
// a source with no spans defaults to the file browser
assert.strictEqual(partOf({spans:[]}, null), 'b'); assert.strictEqual(partOf({spans:[1,2]}, null), 0); assert.strictEqual(partOf({spans:[1,2]}, 7), 0); assert.strictEqual(partOf({spans:[1,2]}, 1), 1);
// URL with its own query, ampersand, percent survives
const tricky = 'https://example.com/a%20b.txt?x=1&y=2#frag+z';
st = parseRoute('#u=' + encUrl(tricky) + '&s=5-9'); assert.strictEqual(st.sources[0].url, tricky);
// shorthand and the @ in a path
st = parseRoute('#https://a.test/f.txt@0-99,200-299:x'); assert.strictEqual(st.sources[0].url,'https://a.test/f.txt'); assert.strictEqual(st.sources[0].spans[1].label,'x');
st = parseRoute('#https://a.test/me@home/file.txt'); assert.strictEqual(st.sources[0].spans.length,0);
// host-supplied (untrusted) spans
assert.deepStrictEqual(spanFromHost({start:5,end:9,label:'x'}), {kind:'range',start:5,end:9,label:'x'});
assert.deepStrictEqual(spanFromHost({start:5,len:10}), {kind:'range',start:5,end:14,label:''});
assert.deepStrictEqual(spanFromHost({start:5}), {kind:'open',start:5,label:''});
assert.deepStrictEqual(spanFromHost({len:5}), {kind:'suffix',len:5,label:''});
assert.deepStrictEqual(spanFromHost('10-20:hi'), {kind:'range',start:10,end:20,label:'hi'});
for (const badv of [null, 7, {start:-1,end:3}, {start:5,end:2}, {start:'5',end:'9'}, {start:1.5,end:3}, {start:Infinity,end:Infinity}, {}, []]) assert.strictEqual(spanFromHost(badv), null, JSON.stringify(badv));
assert.strictEqual(spanFromHost({start:1,end:2,label:'x'.repeat(500)}).label.length, 200);
// UTF-8 decoder with exact offsets
const enc = new TextEncoder();
const sample = 'héllo wörld — 日本語 😀 end\r\nline2 ñ'; const b = enc.encode(sample);
let d = decodeText(b,'utf8'); assert.strictEqual(d.text, sample); assert.strictEqual(d.invalid, 0);
let byte = 0; for (let ci = 0; ci < d.text.length; ) { const cp = d.text.codePointAt(ci), w = cp>0xFFFF?2:1; assert.strictEqual(d.offs[ci], byte); if (w===2) assert.strictEqual(d.offs[ci+1], byte); byte += enc.encode(String.fromCodePoint(cp)).length; ci += w; }
assert.strictEqual(d.offs[d.text.length], b.length);
d = decodeText(new Uint8Array([0x41,0xE4,0x42,0xC0,0x80,0xED,0xA0,0x80]),'utf8'); assert.strictEqual(d.invalid, 6);
d = decodeText(new Uint8Array([0x6b,0xE4,0x69]),'latin1'); assert.strictEqual(d.text,'käi');
d = decodeText(enc.encode('a😀b'),'utf8'); assert.deepStrictEqual([...d.offs],[0,1,1,5,6]); assert.strictEqual(lower(d.offs,2),3);
assert.deepStrictEqual(edgeNotes(enc.encode('日本').subarray(1)), ['starts partway through a character, so its first letter may look wrong']);
assert.deepStrictEqual(edgeNotes(enc.encode('日本').subarray(0,4)), ['ends partway through a character, so its last letter may look wrong']);
// binary sniffing for quote cards
assert.strictEqual(looksBinary(enc.encode('plain text with\nnewlines\r\n and tabs\t')), false);
assert.strictEqual(looksBinary(new Uint8Array([0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a,0,0,0,0x0d,0x49,0x48,0x44,0x52,0,0,0,1])), true);
assert.strictEqual(looksBinary(new Uint8Array(0)), false);
// people read words, never bytes: sizes, word counts, quotations and places
assert.strictEqual(fmtSize(0), 'under 1 KB'); assert.strictEqual(fmtSize(999), 'under 1 KB'); assert.strictEqual(fmtSize(41200), '41 KB'); assert.strictEqual(fmtSize(2500000), '2.5 MB');
assert.strictEqual(wordCount('teach the woods to echo'), 5); assert.strictEqual(wordCount('  \n '), 0); assert.strictEqual(wordCount("don't stop — it's here"), 4);
assert.strictEqual(words(1), '1 word'); assert.strictEqual(words(23), '23 words'); assert.strictEqual(words(1200, false), 'about 1,200 words');
assert.strictEqual(quoteOf('teach the woods to echo'), 'teach the woods to echo');
assert.strictEqual(quoteOf('Tityrus, you lie under the spreading beech and tune a woodland muse on a slender reed, while we leave our native land'), 'Tityrus, you lie under the spreading … leave our native land');
assert.strictEqual(quoteOf('  one\n\n two\t three '), 'one two three');
assert.strictEqual(openingOf('Tityrus, you lie under the spreading beech and tune a woodland muse'), 'Tityrus, you lie under the spreading beech…');
assert.strictEqual(openingOf('short one'), 'short one');
assert.strictEqual(placeIn(0, 1000), 'at the very start'); assert.strictEqual(placeIn(400, 1000), '40% of the way through'); assert.strictEqual(placeIn(995, 1000), 'at the very end'); assert.strictEqual(placeIn(5, null), '');

// --- per-source encoding: e= belongs to the u= before it
let en = parseRoute('#u=https://a.test/f&s=1-2&e=latin1&u=https://b.test/g&s=3-4&f=0');
assert.deepStrictEqual(en.sources.map(s=>s.enc), ['latin1', null]);
assert.strictEqual(toHash(Object.assign(en,{focus:null})), 'u=https://a.test/f&s=1-2&e=latin1&u=https://b.test/g&s=3-4');
assert.deepStrictEqual(en.sources.map(encOf), ['latin1','utf8']);
// an e= before any u= is a default for every source
en = parseRoute('#e=latin1&u=https://a.test/f&u=https://b.test/g');
assert.deepStrictEqual(en.sources.map(s=>s.enc), ['latin1','latin1']);
// single-source links with a trailing e= (the old style) still mean that source
en = parseRoute('#u=https://a.test/f&s=1-2&e=latin1'); assert.strictEqual(en.sources[0].enc,'latin1');


assert.strictEqual(lineEnds('a\r\nb\rc\nd'), 'a\nb\nc\nd');
assert.strictEqual(trimBlankLines('\n\n  Tityrus.\n\n\n'), '  Tityrus.');              // blank lines go, the first line's indentation stays
assert.strictEqual(trimBlankLines('a\n\n\nb'), 'a\n\n\nb');                              // inner blank lines are the author's
assert.strictEqual(trimBlankLines('   \n\t\nword  \n  \n'), 'word  ');
// layout: prose keeps the reading face, tables/indentation/ruled boxes take the fixed-width one
const prose = 'Tityrus! Sinä vaan lepäilet tuuhian saksantammen suojassa ja soittelet\nhienolla huilullasi maaseutuisia lauluja; me jätämme isänmaamme alueen\nja ihanat kedot; me pakenemme syntymätienoiltamme.';
assert.strictEqual(needsMono(prose), false);
assert.strictEqual(needsMono('Sentence one.  Sentence two.  Sentence three.\nMore text here.'), false);   // two spaces after a full stop is not a column
assert.strictEqual(needsMono('Name        Qty   Price\nApples        3    1.20\nPears        12    0.75\nPlums         7    2.10'), true);
assert.strictEqual(needsMono('    Sing, O muse,\n        of the wrath\n    of Achilles'), true);
assert.strictEqual(needsMono('+------+------+\n| a    | b    |\n+------+------+'), true);
assert.strictEqual(needsMono('one\ttwo\tthree\nfour\tfive\tsix'), true);
// kind detection
types.set('https://a.test/p', 'text/html; charset=utf-8'); assert.strictEqual(docKind({url:'https://a.test/p'}, enc.encode('<p>hi</p>'), '<p>hi</p>'), 'html');
assert.strictEqual(docKind({url:'https://a.test/x.htm'}, enc.encode('anything'), 'anything'), 'html');
assert.strictEqual(docKind({url:'https://a.test/x.txt'}, enc.encode('<div>look</div>'), '<div>look</div>'), 'html');      // sniffed
assert.strictEqual(docKind({url:'https://a.test/x.txt'}, enc.encode('1 < 2 and 3 > 2'), '1 < 2 and 3 > 2'), 'text');
assert.strictEqual(docKind({url:'https://a.test/x.bin'}, new Uint8Array([0,1,2,3,4,5,6,7,8,0,0,1]), ''), 'binary');




// --- search in the route
let sr = parseRoute('#q=virgil%20eclogues&p=iafts&m=all&u=https://a.test/f&f=0');
assert.deepStrictEqual(sr.search, {q:'virgil eclogues', p:'iafts', m:'all'});
sr.focus = resolveFocus(sr.focus, sr.sources, sr.search); assert.strictEqual(sr.focus, null);
assert.strictEqual(toHash(sr), 'u=https://a.test/f&q=virgil%20eclogues&p=iafts&m=all');            // f=0 is implied while a search is open
let sr2 = parseRoute('#u=https://a.test/f&q=hello'); sr2.focus = resolveFocus(sr2.focus, sr2.sources, sr2.search); assert.strictEqual(sr2.focus, null);
assert.strictEqual(toHash(sr2), 'u=https://a.test/f&q=hello');
assert.strictEqual(parseRoute('#q=x&p=nonsense').search.p, 'ia');                                  // unknown provider falls back
assert.strictEqual(parseRoute('#q=%20%20').search, null);
// --- encoding a search needle for a source
assert.deepStrictEqual([...encodeNeedle('käi','latin1')], [0x6b,0xE4,0x69]);
assert.strictEqual(encodeNeedle('日本','latin1'), null);
assert.deepStrictEqual([...encodeNeedle('ä','utf8')], [0xC3,0xA4]);
// --- scanChunks against a naive scan, with chunk boundaries everywhere
async function* split(buf, sizes) { let i = 0, k = 0; while (i < buf.length) { const n = sizes[k++ % sizes.length]; yield buf.slice(i, i + n); i += n; } }
function naive(buf, needle, matchCase) {
  const h2 = matchCase ? buf : lowerAscii(buf), n2 = matchCase ? needle : lowerAscii(needle), out = [];
  for (let i = 0; i + n2.length <= h2.length; ) { let ok = true; for (let j = 0; j < n2.length; j++) if (h2[i + j] !== n2[j]) { ok = false; break; } if (ok) { out.push(i); i += n2.length; } else i++; }
  return out;
}
(async () => {
  const text = 'the Tityrus and TITYRUS met tityrus; ' + 'Tit' + 'yrus again, '.repeat(7) + 'xyz tityrusTITYRUS aaaa'.repeat(3) + ' end Tityrus';
  const buf = enc.encode(text), needle = enc.encode('tityrus');
  for (const matchCase of [false, true]) {
    const want = naive(buf, needle, matchCase);
    for (const sizes of [[1],[2],[3],[7],[5,1,9],[64],[1000],[4,4,4,13,2]]) {
      for (const K of [0, 5, 30]) {
        const out = await scanChunks(split(buf, sizes), needle, { matchCase, K });
        assert.deepStrictEqual(out.matches.map(m => m.a), want, `offsets sizes=${sizes} K=${K} case=${matchCase}`);
        for (const m of out.matches) {
          assert.deepStrictEqual([...m.hit], [...buf.slice(m.a, m.b + 1)]);
          if (K >= 5) {
            assert.deepStrictEqual([...m.before], [...buf.slice(Math.max(0, m.a - K), m.a)], `before @${m.a} sizes=${sizes} K=${K}`);
            assert.deepStrictEqual([...m.after], [...buf.slice(m.b + 1, m.b + 1 + K)], `after @${m.a} sizes=${sizes} K=${K}`);
          }
        }
      }
    }
  }
  // limits: max stops early and reports incomplete; cap stops after enough bytes; empty needle is a no-op
  let r = await scanChunks(split(buf, [10]), needle, { max: 2 }); assert.strictEqual(r.matches.length, 2); assert.strictEqual(r.complete, false);
  r = await scanChunks(split(buf, [10]), needle, { cap: 30 }); assert.strictEqual(r.complete, false); assert.ok(r.scanned >= 30 && r.scanned < buf.length);
  r = await scanChunks(split(buf, [10]), new Uint8Array(0)); assert.strictEqual(r.matches.length, 0);
  // a needle spanning the last bytes of the file still counts
  r = await scanChunks(split(enc.encode('xxxxTityrus'), [3]), needle, {}); assert.deepStrictEqual(r.matches.map(m => m.a), [4]);
  // a match with fewer than K bytes of file after it still reports the short context
  r = await scanChunks(split(enc.encode('abc tityrus d'), [2]), needle, { K: 60 }); assert.strictEqual(String.fromCharCode(...r.matches[0].after), ' d');
  })();

// --- encodings
assert.strictEqual(encFromLabel('ISO-8859-1'), 'latin1'); assert.strictEqual(encFromLabel('UTF-8'), 'utf8'); assert.strictEqual(encFromLabel('windows-1252'), 'latin1');
assert.strictEqual(encFromLabel('Windows_1251'), 'windows-1251'); assert.strictEqual(encFromLabel('ISO_8859-2'), 'iso-8859-2'); assert.strictEqual(encFromLabel('shift_jis'), null); assert.strictEqual(encFromLabel(''), null); assert.strictEqual(encFromLabel(undefined), null);
assert.strictEqual(encOf({}), 'utf8'); assert.strictEqual(encOf({ autoEnc: 'latin1' }), 'latin1'); assert.strictEqual(encOf({ enc: 'utf8', autoEnc: 'latin1' }), 'utf8');   // an explicit choice beats detection
let ee = parseRoute('#u=https://a.test/f&e=windows-1251&u=https://b.test/g&e=nonsense'); assert.deepStrictEqual(ee.sources.map(x => x.enc), ['windows-1251', null]);
ee.focus = null; assert.strictEqual(toHash(ee), 'u=https://a.test/f&e=windows-1251&u=https://b.test/g');   // two sources: the index is the default view, so no f=
// a character cut at either edge is not an encoding error; a stray 8-bit byte is
assert.strictEqual(invalidInside(enc.encode('日本').subarray(1)), 0); assert.strictEqual(invalidInside(enc.encode('日本').subarray(0, 4)), 0);
assert.strictEqual(invalidInside(Uint8Array.from([0x53, 0x69, 0x6e, 0xE4, 0x20, 0x76])), 1); assert.strictEqual(invalidInside(enc.encode('plain ascii')), 0);
const gut = Uint8Array.from([...enc.encode('Character set encoding: ISO-8859-1\r\n\r\nSin'), 0xE4, ...enc.encode(' vaan')]);
assert.strictEqual(decodeText(gut, 'latin1').text.endsWith('Sinä vaan'), true);
assert.strictEqual(decodeText(Uint8Array.from([0xE4, 0x92]), 'windows-1251').text.length, 2);
assert.deepStrictEqual([...encodeNeedle('Привет', 'windows-1251')], [0xCF, 0xF0, 0xE8, 0xE2, 0xE5, 0xF2]);
assert.strictEqual(encodeNeedle('日本', 'windows-1251'), null);
// --- permanence
assert.strictEqual(permanence('https://raw.githubusercontent.com/o/r/18cbd7fd1b4607581a20b273e898a3c25e059e78/a.txt').ok, true);
let pm = permanence('https://raw.githubusercontent.com/o/r/master/a.txt'); assert.strictEqual(pm.ok, false); assert.strictEqual(pm.pin, 'github');
assert.strictEqual(permanence('https://en.wikisource.org/api/rest_v1/page/html/Foo_(1908)%2FBar/9026765').ok, true);
assert.strictEqual(permanence('https://en.wikisource.org/api/rest_v1/page/html/Foo').ok, false);       // no revision: the live page
assert.strictEqual(permanence('https://archive.org/download/x/y.txt').ok, true); assert.strictEqual(permanence('https://ia800000.us.archive.org/0/items/x/y.txt').ok, true);
assert.strictEqual(permanence('https://example.com/a.txt').ok, false); assert.strictEqual(permanence('not a url'), null);
assert.strictEqual(srcName('https://en.wikisource.org/api/rest_v1/page/html/Eclogues_of_Virgil_(1908)%2FEclogue_4/9026765'), 'Eclogues of Virgil (1908)/Eclogue 4 (revision 9026765)');
assert.strictEqual(srcName('https://archive.org/download/x/a%20b.txt'), 'a b.txt');
// --- normalizing links
let ns = newSource('https://github.com/GITenberg/Bucolica_19917'); normalize(ns); assert.strictEqual(ns.needPicker, 'GITenberg/Bucolica_19917'); assert.strictEqual(ns.pickerKind, 'gh');
ns = newSource('https://github.com/o/r/blob/main/docs/a.txt'); normalize(ns); assert.strictEqual(ns.url, 'https://raw.githubusercontent.com/o/r/main/docs/a.txt'); assert.strictEqual(ns.needPicker, null); assert.strictEqual(permanence(ns.url).pin, 'github');
ns = newSource('https://archive.org/details/bucolica19917gut'); normalize(ns); assert.strictEqual(ns.needPicker, 'bucolica19917gut'); assert.strictEqual(ns.pickerKind, 'ia');
ns = newSource('https://archive.org/details/x/y.txt'); normalize(ns); assert.strictEqual(ns.url, 'https://archive.org/download/x/y.txt'); assert.strictEqual(ns.needPicker, null);
ns = newSource('http://example.com/a.txt'); normalize(ns); assert.strictEqual(ns.url, 'https://example.com/a.txt');
ns = newSource('javascript:alert(1)'); normalize(ns); assert.ok(ns.error);
// --- search options travel in the link and cannot name arbitrary hosts (providers validate them)
let so = parseRoute('#q=bucolica&p=wiki&m=la.wikisource.org'); assert.deepStrictEqual(so.search, { q: 'bucolica', p: 'wiki', m: 'la.wikisource.org' });
assert.strictEqual(parseRoute('#q=x&m=' + encodeURIComponent('evil.com/x?y')).search.m, '');              // not an option-shaped value
const optOf2 = (prov, m) => prov.options ? (prov.options.some(o => o[0] === m) ? m : prov.defaultOption) : '';
assert.strictEqual(optOf2({ options: [['a', 'A'], ['b', 'B']], defaultOption: 'a' }, 'evil.com'), 'a');
// --- uploaded files: addressed by content hash, held in memory, never fetched as a URL
const H64 = 'a'.repeat(64);
let lf = newSource('local:' + H64); normalize(lf);
assert.strictEqual(lf.error, null); assert.strictEqual(lf.url, 'local:' + H64); assert.strictEqual(lf.needFile, true);      // known by hash, but the file itself is not here yet
localFiles.set(H64, { name: 'poem.txt', bytes: new Uint8Array(3), type: 'text/plain' }); localNames.set(H64, 'poem.txt');
lf = newSource('local:' + H64); normalize(lf); assert.strictEqual(lf.needFile, false);
assert.strictEqual(srcName('local:' + H64), 'poem.txt'); assert.strictEqual(srcHost('local:' + H64), 'this computer'); assert.strictEqual(permanence('local:' + H64).ok, true);
assert.strictEqual(localId('local:' + H64), H64); assert.strictEqual(localId('local:xyz'), null); assert.strictEqual(localId('https://a.test/local:' + H64), null);
let badLocal = newSource('local:xyz'); normalize(badLocal); assert.ok(badLocal.error);                                    // not a hash, so not a file
assert.strictEqual(srcName('local:' + 'b'.repeat(64)), 'uploaded file');                                                   // a hash we know nothing else about
// the file's name travels in the link, and nothing else about the visitor's computer does
let up = parseRoute('#u=local:' + H64 + '&n=poem%20one.txt&s=1-5'); assert.strictEqual(up.sources[0].name, 'poem one.txt');
up.focus = resolveFocus(up.focus, up.sources, up.search); assert.strictEqual(toHash(up), 'u=local:' + H64 + '&n=poem%20one.txt&s=1-5');
assert.strictEqual(toHash(parseRoute('#u=https://a.test/f&n=ignored&s=1-2')).includes('n='), false);                          // a name only means something for an uploaded file
// --- a link to just the highlighted text
const sl = newSource('https://archive.org/download/x/y.txt');
assert.strictEqual(spanLink(sl, { kind: 'range', start: 843, end: 860, label: '' }, 160), 'https://x.github.io/repo/index.html#u=https://archive.org/download/x/y.txt&s=843-860&c=160');
sl.enc = 'latin1'; assert.ok(spanLink(sl, { kind: 'range', start: 1, end: 2, label: '' }).endsWith('&s=1-2&e=latin1'));
const sl2 = newSource('local:' + H64); sl2.name = 'a b.txt';
assert.ok(spanLink(sl2, { kind: 'range', start: 0, end: 0, label: '' }).includes('&n=a%20b.txt&s=0-0'));
// opening the link gives back the same source, span, name and context
const reopened = parseRoute('#' + spanLink(sl2, { kind: 'range', start: 5, end: 9, label: '' }, 160).split('#')[1]);
assert.deepStrictEqual(reopened.sources[0].spans[0], { kind: 'range', start: 5, end: 9, label: '' }); assert.strictEqual(reopened.ctx, 160);
assert.strictEqual(reopened.sources[0].name, 'a b.txt'); assert.strictEqual(reopened.sources[0].url, 'local:' + H64);
const reopened2 = parseRoute('#' + spanLink(sl, { kind: 'range', start: 843, end: 860, label: '' }, 160).split('#')[1]);
assert.strictEqual(reopened2.sources[0].url, 'https://archive.org/download/x/y.txt'); assert.strictEqual(reopened2.sources[0].spans[0].end, 860); assert.strictEqual(reopened2.sources[0].enc, 'latin1');
console.log('all pure-function tests passed');
