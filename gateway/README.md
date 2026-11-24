# archiveo gateway

Backs text up to the Internet Archive's Wayback Machine **without an archive.org account**. It hosts the text as a page for a few seconds, asks the Wayback Machine to capture that page, waits until the capture is available, reads it back to check it is byte-identical, **deletes the page from disk**, and streams progress so archiveo can show a countdown. Python 3 standard library only. It runs on your VM and changes nothing in nginx.

```
POST /backup   Authorization: Bearer <key>   {"text": "..."}   -> NDJSON progress lines, ending in "done" or "error"
GET  /auth     Authorization: Bearer <key>   -> 200 if the key is right (starts nothing)
GET  /health
```

A progress line looks like `{"phase":"waiting","eta_s":12.4,"message":"..."}`. Phases: `hosting`, `capturing`, `waiting`, `verifying`, then `done` (with `capture.url`, `capture.raw`, `capture.timestamp`, `capture.verified`, `capture.deleted`) or `error`. `eta_s` is `null` once the usual time has passed, and the page then says it is taking longer.

## How it is wired (and what it does not touch)

- **The API is private.** It listens on the VM's loopback port 8850 only. From your Mac, `./gateway/tunnel.sh` forwards `http://localhost:8850` to it over SSH. There is no public endpoint that can publish anything.
- **Temporary pages use a route that already exists.** Each one is written as `/srv/samples/_archiveo/<24-character id>.txt`, which `https://watch.hyphae.social/samples/` already publishes (plain text, no directory listing). That is where the Wayback Machine fetches it. No nginx change, no new domain.
- The file starts with a UTF-8 byte-order mark, because that route sends `text/plain` with no charset and browsers would otherwise guess wrong for non-ASCII text. The gateway verifies the archive holds the mark plus your text, byte for byte.

## When the page is deleted

The page leaves the disk **as soon as the capture is listed by the archive and read back identical**, and on every failure or timeout. The `done` event carries `deleted: true` only after the gateway has checked the disk. Backstops: a restart deletes any leftovers (only 24-character `.txt` and `.tmp-` names, never anyone else's files in that folder), `systemctl stop` runs the same cleanup (`ExecStopPost`), and a sweeper removes anything older than 15 minutes.

## What was measured (2026-11-24, real captures)

- Wayback's anonymous **`POST https://web.archive.org/save`** (the form's own request) works with no login. The shortcut `GET /save/<url>` is dropped by the server, and the job-status endpoint demands a login even with the cookie the save sets, so neither is used.
- In five real runs the crawler fetched the page 1 to 4 s after submission in three, and the capture took roughly 45 to 60 s in the other two. The archive queues anonymous saves, so the countdown's 15 s estimate is a guess and says "slower than usual" once it is passed. The last run, after the fixes below, took 3.7 s from hosting to done.
- **Replay endpoints cache "not there yet".** The first design polled `/web/2/<url>` and, in one run, never saw a capture that had existed since second four, because its early miss was cached for minutes. The gateway now asks the CDX index (and the availability API) with a throwaway parameter on every request. Both listed the capture within about 3 s when tried by hand.
- One network error while polling used to abort a capture (and delete the page before the crawler arrived). Polling now tolerates up to six consecutive errors.
- A late-arriving capture crashed the verify step (arithmetic on a `null` countdown). Fixed, with a test that fails against the old code, and any unexpected exception now ends the stream with an explicit `error` event.
- The stored copy of a 133-byte test page was identical to what was sent, and its public address returned 404 afterwards.

## Things to know before using it

- **Everything sent becomes public and permanent.** Deleting the page does not delete the capture; removal means emailing the Internet Archive. The captured address contains the temporary page's address.
- One capture at a time, at least 10 s apart, 256 KiB of text at most, and a key of 24+ characters (constant-time comparison). Logs hold request lines and status codes only, never content or the key.
- The existing `/samples/` route sends `Cache-Control: public, max-age=86400` and `Access-Control-Allow-Origin: *` for everything in the folder. That is harmless for a page that exists for seconds, but it is why the folder should hold nothing else of yours.
- If the VM's address or the domain is blocked for the Wayback Machine, captures fail with a clear error.

## Try it without touching archive.org

```
python3 gateway/dev.py 6          # gateway on :8850 plus a stand-in archive that takes 6 s
python3 gateway/test_server.py    # 26 tests against the stand-in
```

The stand-in reproduces the failures seen for real: a poisoned replay cache, index lag, dropped connections, a refused save, gzip replays, a capture found after the usual time, and an unexpected exception. In archiveo, Settings, "Wayback backup gateway": address `http://localhost:8850`, key `dev-key-dev-key-dev-key-dev-key-0000`.

## Deploy and use (the VM is the `hyphae` host)

1. SSH must work unattended: `ssh -o BatchMode=yes hyphae true`. If the key your `hyphae` entry in `~/.ssh/config` points at has a passphrase, load it into the agent with `ssh-add <that key>`, or make that survive restarts with `UseKeychain yes` and `ssh-add --apple-use-keychain <that key>`.
2. `./gateway/deploy.sh` copies the files to `/mnt/watch/archiveo-gateway`, writes a 0600 env file and key (generated into `gateway/.key`, gitignored, never printed), installs the systemd unit and starts it. It needs passwordless `sudo` for `install` and `systemctl`, which the VM has. `./gateway/deploy.sh --check` shows the service, its health and the pages folder.
3. `./gateway/tunnel.sh` on your Mac, and leave it running while you use it.
4. In archiveo, Settings, "Wayback backup gateway": address `http://localhost:8850`, and the key from `gateway/.key` (`pbcopy < gateway/.key`). **Test**, then **Back up to Wayback** on a span.

`GATEWAY_ORIGINS` (comma-separated) lists the sites allowed to call it from a browser; the default is the GitHub Pages site and the local dev server. `nginx-gateway.conf` is optional and unused: it is only for exposing the API publicly, which the default setup avoids.
