# YouTube Music Cleanup

A Windows app for your YouTube Music playlists. It does two jobs:

- **Clean up a playlist.** It swaps music videos for the song version of the
  same track. Songs download as audio only, so a playlist downloaded to your
  phone takes much less space.
- **Curate new music.** New songs go into an *Inbox* playlist. The app checks
  what you've listened to, moves the ones you keep to a *Rotation* playlist, and
  clears out the ones you don't. An optional Obsidian vault keeps a note per song.

It only edits playlists. It never downloads music or videos. Every change asks
you to confirm first, and you can undo it from the History screen.

YouTube and YouTube Music share playlists, so the playlists you made on YouTube
show up here too.

## Install

You need Python 3.11 or later once, to build the app. After that, the app runs
on its own.

In PowerShell, from this folder:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

```powershell
powershell -ExecutionPolicy Bypass -File packaging\install-shortcut.ps1
```

The first command builds `dist\YouTube Music Cleanup.exe`. The second copies it
to `%LOCALAPPDATA%\Programs\YouTube Music Cleanup` and adds **YouTube Music
Cleanup** to the Start menu. To remove both, run the second command again with
`-Uninstall`.

To run the app without building it:

```powershell
pip install -e ".[app]"
ytm-hygiene-app
```

Started from a folder that already holds `browser.json` or `ytm-hygiene.toml`,
such as this one after using the command line, the app uses the files there
instead of `%APPDATA%\ytm-hygiene`.

## Set up the app

The first time you open the app, it shows the **Setup** screen. It has three
steps.

1. **Sign in to YouTube Music.** The app signs in with a copy of your browser's
   request headers, not your password. The screen shows how to copy them from
   Chrome, Edge or Firefox. Paste them and press **Sign in**. The app checks
   them with one request and saves them only if they work.
2. **Choose your Obsidian vault.** This step is optional. Skip it if you don't
   use Obsidian.
3. **Choose your Inbox and Rotation playlists.** Pick them by name, or press
   **Create Inbox for me** and **Create Rotation for me**. This step is only
   needed for the Inbox screen.

If the app later says it can't read your playlists, your sign-in has expired.
Open **Setup** and sign in again.

## Clean up a playlist

1. Open **Clean up a playlist** and press **Choose a playlist**.
2. Pick a playlist and press **Check this playlist**. The app saves a backup
   first, then looks for the song version of each video. This takes about a
   second per video.
3. Look over the results:
   - **Ready to swap:** sure matches, already ticked.
   - **Please check these:** possible matches with a reason, such as "one is a
     live version". Press **Open** to listen to either one. Choose **Looks
     right** to tick it, or **Wrong** to leave it out.
   - **No song version found:** nothing to swap. Fan remixes and unreleased
     tracks usually end up here.
4. Press **Swap** and confirm. Each swap puts the song in the same spot as the
   video. The app swaps 20 songs at a time; press **Swap** again for the rest.

## Curate your Inbox

Add new songs you want to try to your Inbox playlist, then listen as usual.
Every few days, open **Inbox** and press **Check what I've listened to**.

An Inbox song is decided by the first rule that matches:

| What happened | Result |
|---|---|
| Thumbs up | Moves to Rotation |
| Thumbs down | Removed from the Inbox |
| Heard in 2 separate checks | Moves to Rotation |
| Never heard, after 3 checks and 30 days in the Inbox | Removed from the Inbox |
| Heard in 1 check, then not again for 3 checks and 30 days | Removed from the Inbox |

Each check counts toward these rules, so checking twice in one afternoon
doesn't help. Untick any change you don't want, then press **Apply** and
confirm.

With an Obsidian vault, each song gets a note in `Music/Songs/`. You can set
`status` in a note to `keeper` or `rejected` yourself, and the next check
proposes that move. Anything you write in the body of a note is kept.

## Get suggestions from Claude

1. Open **Get suggestions** and press **Copy my taste summary**. It lists the
   songs you kept and the ones you rejected.
2. Paste it into a chat with Claude and ask for songs you might like, one
   `Artist - Title` per line.
3. Paste Claude's reply into the app and press **Find songs**.
4. Untick any you don't want, then press **Add to Inbox** and confirm.

Songs you already have a note for are skipped, so a rejected song never comes
back.

## Undo a change

Open **History**. It lists every swap, Inbox change and suggestion run, newest
first. Press **Undo** on a run and confirm to put your playlists back the way
they were before it. A run can be undone once.

## Where your files are

The app keeps its files in `%APPDATA%\ytm-hygiene`:

- `browser.json`: your sign-in. It lets the app act as you on YouTube Music,
  so don't share it.
- `ytm-hygiene.toml`: your settings.
- `backups\`: a copy of each playlist before the app changes it.
- `undo-*.json`: the record History uses to undo a run.

The app makes a few requests per action and never checks anything in the
background. It uses an unofficial YouTube Music API on your account, so it
keeps the number of requests low.

## Command line and development

Every screen also has a command. See the
[command-line reference](docs/cli.md), which also explains how songs are
matched.

To run the tests:

```powershell
python -m pytest -q
```
