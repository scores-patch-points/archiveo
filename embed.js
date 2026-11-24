/*! archiveo embed helper
 *
 * Put this on the page that wants the modal:
 *
 *   <script src="https://you.github.io/archiveo/embed.js"></script>
 *   <script>
 *     Archiveo.open({
 *       url: "https://archive.org/download/bucolica19917gut/19917-8.txt",
 *       spans: ["800-1099", { start: 52952, end: 53040, label: "Colophon" }],
 *       onSelect: result => console.log(result.sources, result.link)
 *     });
 *   </script>
 *
 * It opens a native <dialog> holding archiveo in an iframe, wires up Escape, a backdrop click,
 * scroll lock and focus return, and talks to the app over postMessage. Messages are only
 * accepted from the iframe's own window and origin, and only sent to that origin.
 *
 * Options
 *   src            where archiveo is hosted (default: the folder this script was loaded from)
 *   url, spans     one source and its spans; spans are "100-199:label" strings or
 *                  { start, end } | { start, len } | { start } (to the end) | { len } (last n bytes), plus label
 *   sources        [{ url, spans, enc? }] instead of url + spans
 *   search         open on a search instead (a string), with provider: 'ia' | 'iafts' | 'loc' | 'wiki' | 'gh'
 *   focus          { source: 0, part: 1 } to land on a part ('b' is the file browser), or 'index'
 *   ctx, view, enc context bytes; view is 'doc' (the span as the original formatted it, the default), 'text' or 'hex';
 *                  enc forces an encoding for every source (otherwise it is detected from the file)
 *   theme          'light' | 'dark' | 'auto'
 *   action         label for the primary button (default "Use spans")
 *   hash           a ready-made archiveo #fragment, used instead of the options above
 *   closeOnSelect  close after the user presses the primary button (default true)
 *   onReady, onChange(state), onSelect(result), onClose(lastResult)
 *
 * Returns { close(), send(msg), iframe, dialog, closed } where `closed` resolves with the last
 * result the user chose, or null if they closed without choosing.
 */
(function (root) {
  'use strict';

  var HERE = (document.currentScript && document.currentScript.src) || '';
  var DEFAULT_SRC = HERE ? new URL('./', HERE).href : '';

  var CSS =
    'dialog.archiveo-dialog{padding:0;border:0;border-radius:10px;width:min(1120px,96vw);height:min(780px,92vh);' +
    'max-width:none;max-height:none;overflow:hidden;background:#0e0e0e;box-shadow:0 24px 70px rgba(0,0,0,.5)}' +
    'dialog.archiveo-dialog::backdrop{background:rgba(8,8,6,.62);backdrop-filter:blur(2px)}' +
    'dialog.archiveo-dialog iframe{display:block;width:100%;height:100%;border:0;background:transparent}' +
    '@media (max-width:720px){dialog.archiveo-dialog{width:100vw;height:100vh;height:100dvh;max-height:100dvh;border-radius:0}}';

  function injectCss() {
    if (document.getElementById('archiveo-embed-css')) return;
    var s = document.createElement('style');
    s.id = 'archiveo-embed-css';
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function open(opts) {
    opts = opts || {};
    var src = opts.src || DEFAULT_SRC;
    if (!src) throw new Error('Archiveo.open: pass { src } with the URL where archiveo is hosted.');

    var u = new URL(src, location.href);
    var appOrigin = u.origin;
    u.search = '';
    u.hash = '';
    u.searchParams.set('embed', '1');
    u.searchParams.set('host', location.origin);
    if (opts.theme === 'light' || opts.theme === 'dark') u.searchParams.set('theme', opts.theme);
    if (opts.action) u.searchParams.set('action', String(opts.action).slice(0, 30));
    if (opts.hash) u.hash = String(opts.hash).replace(/^#/, '');

    injectCss();
    var dialog = document.createElement('dialog');
    dialog.className = 'archiveo-dialog';
    dialog.setAttribute('aria-label', opts.title || 'archiveo');
    var iframe = document.createElement('iframe');
    iframe.title = 'archiveo';
    iframe.allow = 'clipboard-write';
    iframe.src = u.href;
    dialog.appendChild(iframe);
    document.body.appendChild(dialog);

    var last = null, done = false, resolveClosed;
    var closed = new Promise(function (r) { resolveClosed = r; });
    var prevOverflow = document.documentElement.style.overflow;

    function send(msg) {
      if (iframe.contentWindow) iframe.contentWindow.postMessage(Object.assign({ archiveo: 1 }, msg), appOrigin);
    }
    function onMessage(e) {
      if (e.source !== iframe.contentWindow || e.origin !== appOrigin) return;
      var m = e.data;
      if (!m || m.archiveo !== 1) return;
      if (m.type === 'ready') {
        if (!opts.hash) {
          var open = { type: 'open' };
          ['url', 'spans', 'sources', 'search', 'provider', 'focus', 'ctx', 'view', 'enc'].forEach(function (k) { if (opts[k] != null) open[k] = opts[k]; });
          if (open.url || open.sources || open.search) send(open);
        }
        if (opts.onReady) opts.onReady(handle);
        iframe.focus();
      } else if (m.type === 'state') {
        if (opts.onChange) opts.onChange(m);
      } else if (m.type === 'select') {
        last = m;
        if (opts.onSelect) opts.onSelect(m);
        if (opts.closeOnSelect !== false) close();
      } else if (m.type === 'close') {
        close();
      }
    }
    function close() {
      if (done) return;
      done = true;
      window.removeEventListener('message', onMessage);
      if (dialog.open) dialog.close();
      dialog.remove();
      document.documentElement.style.overflow = prevOverflow;
      if (opts.onClose) opts.onClose(last);
      resolveClosed(last);
    }

    window.addEventListener('message', onMessage);
    dialog.addEventListener('close', close);                          // Escape pressed on the host page
    dialog.addEventListener('click', function (e) { if (e.target === dialog) close(); });   // backdrop
    document.documentElement.style.overflow = 'hidden';
    if (dialog.showModal) dialog.showModal(); else dialog.setAttribute('open', '');

    var handle = { close: close, send: send, iframe: iframe, dialog: dialog, closed: closed };
    return handle;
  }

  root.Archiveo = { open: open };
})(window);
