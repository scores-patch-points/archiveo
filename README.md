# archiveo

Link to the exact words. Add a document by **typing its address or uploading a file**, **highlight** the words you want, and a link to exactly that text appears at once, ready to copy. It opens right on those words for anyone. It can also search archives to find the source, and it runs as a modal on another page.

The page speaks in words, quotations and places in the document ("12 words", "40% of the way through"), never in bytes. A link does hold exact byte positions, because that is what keeps it pointing at the same words, but you never read, type or choose them; they are described under *For developers* below.

One static site, no build step, no server. `index.html` is the whole app.

## Publish it (GitHub Pages)

Push this folder to a repository and turn on Pages (Settings, Pages, deploy from the `main` branch, root). Everything is relative, so it works at `https://you.github.io/archiveo/`. `.nojekyll` is already here.

```
index.html          the app
embed.js            host-page helper: opens archiveo as a modal
demo.html           a host page that uses embed.js
vendor/alhazen.js   scores-patch-points/Alhazen @ 5ca3278, unmodified (see vendor/ALHAZEN.txt)
test/               unit tests: node test/run.cjs
```

Run it locally with any static server, for example `python3 -m http.server 8962` in this folder.

## What it does

**Add, highlight, link.** One box takes a link (or words, to search the archives); an Upload button, or dropping a file anywhere on the page, takes a file from your computer. Either way you land in a reader. Highlight any text and a bar pinned to the bottom quotes what you highlighted and counts its words, shows the link to exactly that text (with a little of the text around it, so it reads in place), and offers **Copy link** and **Keep in list**. Opening that link shows the passage highlighted in its context. The reader pages through the document and says where you are as a share of the whole; a slider jumps to any point. **Find words in this document** lists every match with its own **Copy link**.

The list on the left names each passage by its own opening words and counts its words, so nothing in it is a number you have to decode. There is no hex view and no box for typing a range: highlight the words instead. Files that are not text (a picture, a PDF) say so rather than showing their contents.

**Uploaded files.** A file you upload is read in your browser and never sent anywhere. It is named by the SHA-256 of its bytes (`u=local:<hash>`, plus its file name as `n=`), so a link to it identifies the exact bytes, and whoever opens the link is asked to upload the same file; a different file is refused. That makes the link a verifiable citation, but not something a stranger can open without the file. A file up to 100 MB is held in memory.

## For developers: how a link is built

**Spans in the URL.** `#u=<link>&s=1000-1199:label&s=-512` is source `u`, a labeled range, and the last 512 bytes. This is what highlighting writes for you; the page itself never asks anyone to type it. Ranges are inclusive like an HTTP `Range` header, accept hex (`0x400-0x4ff`), `start+length`, `start-` (to the end) and `-n` (the last n). `e=` sets a source's encoding, `c=` adds context bytes, `v=text` opens the plain-text view (`v=hex`, from older links, also opens it), `f=` the open part, `q=`/`p=`/`m=` a search. The full grammar is in the page under "For developers: how a link is built".

**Layout.** Documents sit in the left panel. Open one and the panel becomes that document's passages, with the passage as a quotation in the middle. Light and dark follow the system and can be toggled.

**The span as the original wrote it.** The default view keeps the line breaks, indentation, blank lines, tabs and page breaks of the text, and chooses a fixed-width face only when the layout depends on one (a table, aligned columns, a ruled box; Alhazen's `readGridFromText` makes that call). HTML is rebuilt through an allow-list: nothing runs, loads or inherits styles, and elements the page hid stay hidden. "Plain text" shows the passage as text, with the words around it if you ask.

**Encodings.** Each source is read in the encoding the *file* declares (an HTML or XML declaration, Project Gutenberg's header line), else a byte-order mark, else what the bytes show, else UTF-8. A server's `charset=utf-8` is treated as a default, not evidence: archive.org says UTF-8 for every text file, including Gutenberg files that are ISO-8859-1. Single-byte encodings (Windows-125x, ISO-8859-x, KOI8) are supported; `e=` overrides detection.

**Search.** Type words instead of a link. Providers, each one small object in `index.html` (`PROVIDERS`):

| Provider | Finds | Opens as |
|---|---|---|
| Internet Archive | titles, authors, descriptions | an item, then pick a file (plain text first) |
| Inside the books | full text of scanned books on archive.org | the item, with the query pre-filled in find |
| Library of Congress | digitized books with machine-readable text | its full-text file |
| Wikimedia | Wikisource, Wikipedia, Wikibooks, Wikiquote | a **pinned revision** of the page |
| Git archives | GITenberg (Project Gutenberg), Standard Ebooks | a file **pinned to a commit** |

Inside a document, **Find** scans the whole file (up to 64 MB) and turns each hit into a passage you can copy a link to or keep in the list.

**Permanence.** A span is only meaningful if the file never changes, so each source is marked *Permanent* or *Can change*. Wiki pages open at a revision, git files at a commit SHA, archive.org and LOC files at their archive addresses. A GitHub link that follows a branch can be pinned to its current commit with one click. Note that Wikimedia's HTML for a revision is regenerated when their parser changes, so for strict byte stability prefer archive.org or Gutenberg files.

## As a modal on another page

```html
<script src="https://you.github.io/archiveo/embed.js"></script>
<script>
  Archiveo.open({
    url: "https://archive.org/download/bucolica19917gut/19917-8.txt",
    spans: ["800-1099", { start: 52952, end: 53040, label: "Colophon" }],
    action: "Insert citation",
    onSelect: result => console.log(result.sources, result.link)
  }).closed.then(result => { /* last chosen result, or null */ });
</script>
```

`Archiveo.open` accepts `url`+`spans` or `sources`, or `search` (+ `provider`), plus `focus`, `ctx`, `view`, `enc`, `theme` and `action`. It opens a native `<dialog>` holding archiveo in an iframe, with Escape, backdrop click, scroll lock and focus return handled. The page lays itself out for the frame, not the window: its own panes scroll, and under 720 px the left panel becomes a drawer.

Without the helper, embed `index.html?embed=1&host=<your origin>` in an iframe (`allow="clipboard-write"`) and speak `postMessage` with `{ archiveo: 1, type, ... }`:

- the app sends `ready`, `state` (on every change), `select` (the primary button; carries `sources`, spans with `start`/`end`/`length`/`token`/`label`, and a standalone `link`) and `close` (Escape or the close button);
- the host sends `open` (the same fields as the helper's options) and `theme` (`light` | `dark` | `auto`).

The app only accepts messages from its parent window and, once it knows the host origin (the `host=` parameter, else the referrer), only from that origin, and only posts to it. A proxy setting is never read from a link or a message.

## Backing a span up to the Wayback Machine

`gateway/` is a small service for your own VM that backs text up to the Wayback Machine with no archive.org account: it hosts the text as a file for a few seconds, the Wayback Machine captures it, the capture is read back and checked, and **the file is deleted from the VM's disk as soon as the capture is available**. It reuses an existing public route for the temporary page and keeps its API private behind an SSH tunnel, so nothing in nginx changes. In Settings, give archiveo the gateway's address and key, then press **Back up to Wayback** on a span; the page counts down to the moment it is available. Whatever is sent becomes public and permanent. See `gateway/README.md` for what was measured, the limits, and how to deploy.

## Reading other sites (CORS)

A page can only read bytes from hosts that send CORS headers. archive.org, the Library of Congress, `raw.githubusercontent.com`, GitHub's API and Wikimedia's REST/API endpoints do. For others, Settings has a CORS proxy template (`https://your-proxy.example/?url={url}`), off by default because the proxy sees every link you load. Servers that ignore `Range` still work: the page reads from the start up to the span (at most 64 MiB).

## What was checked, and what does not work

Verified from a browser on 2026-11-24: search and file reads for archive.org (catalog and full text), the Library of Congress, Wikimedia and GitHub; `Range` on archive.org and `raw.githubusercontent.com` (206). The LOC and Wikimedia endpoints ignore `Range`, which the fallback handles.

Not usable directly:

- **Wayback Machine**: its CDX API and captures send no CORS headers, so a browser page cannot read them.
- **Wikimedia raw wikitext** (`action=raw`) sends no CORS headers; revision-pinned HTML is used instead.
- **Common Crawl's index** timed out (504) and **gutenberg.org** answered 503 during testing; Gutenberg texts are reachable through archive.org and GITenberg.
- **`holodeck-proxy`** (the org's relay) answered `429 / error 1027` on `/search` and `/raw`, which is Cloudflare's "Worker exceeded its quota". It also drops `Range`. It was not made a dependency.

Searches go from the visitor's browser straight to the provider chosen (archive.org, loc.gov, a Wikimedia site, api.github.com). GitHub's unauthenticated search allows 10 requests a minute; the page says so if it is limited.

## Tests

```
node test/run.cjs
```

Covers the span grammar, route parsing and serialisation, the UTF-8 decoder's byte offsets, encoding detection, layout choice, permanence rules, link rewriting, search options and the find-in-file scanner (checked against a naive search with chunk boundaries cutting through matches). It does not cover the DOM, which was checked by hand in a browser.
