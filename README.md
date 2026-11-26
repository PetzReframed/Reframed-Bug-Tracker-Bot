# Reframed Bug Tracker Bot

Posts the crash reports, bug reports and recovered error reports of a
[Reframed](https://github.com/PetzReframed/Reframed) server to a Discord channel.

The game server stores every report a player sends in a folder of its own. This bot reads that folder and posts each
new report once: what kind it is, its code, when the server received it, the start of its text, and the stored files
(the full text, and the screenshot and saved-data ZIP when the player attached them).

| Kind | Code | Sent from |
| --- | --- | --- |
| Crash report | `RF-…` | the window that opens when the game stops |
| Bug report | `BUG-…` | Help > Report a Bug…, written by the player |
| Recovered error report | `ERR-…` | the same window in its calm form, for an error the game recovered from and went on |

It has no commands and listens to nothing: it only sends messages. It needs no change to the game server and opens no
port. Reports stored while the bot was stopped are posted when it starts again.

## What a post looks like

> **Crash report** `RF-1A2B3C4D` received 23 November 2026 10:15
> ```
> Area: Family Room
> Message: …
> ```
> 📎 RF-1A2B3C4D.log 📎 RF-1A2B3C4D.png 📎 RF-1A2B3C4D-saved-data.zip

The text of a report is written by the game and, for a bug report, by the player. It is posted inside a code block and
can mention nobody.

## Set-up

1. **Create the bot.** In the [Discord Developer Portal](https://discord.com/developers/applications) create an
   application, open **Bot** and copy the token. No privileged intents are needed.
2. **Invite it** to your server with the permissions **View Channel**, **Send Messages** and **Attach Files** for the
   channel the reports go to (OAuth2 > URL Generator > scope `bot`).
3. **Copy the channel's ID**: turn on Developer Mode in Discord (Settings > Advanced), right-click the channel and
   choose Copy Channel ID.
4. **Configure and start**, on the machine that runs the game server:

   ```sh
   cp .env.example .env      # fill in DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID and REPORTS_HOST_DIR
   docker compose pull
   docker compose up -d
   docker compose logs -f
   ```

`REPORTS_HOST_DIR` is the game server's report folder on the host: the `reports` folder inside the game's data folder
(`PETZ_DATA_DIR` in the game's `.env`). The game server must have reports turned on (`PETZ_CRASH_REPORTS_ENABLED=true`).

The game server's container keeps that folder private to its own user (UID/GID 10001), so this image runs as the same
user. The folder is mounted read only; the bot keeps its own list of posted reports in the `state` volume.

## Settings

All settings are in `.env`; [.env.example](.env.example) describes each.

| Setting | Default | Meaning |
| --- | --- | --- |
| `DISCORD_BOT_TOKEN` | required | The bot's token. |
| `DISCORD_CHANNEL_ID` | required | The channel to post in. |
| `REPORTS_HOST_DIR` | required | The game server's report folder on the host (used by `compose.yaml`). |
| `POLL_SECONDS` | `15` | How often the folder is looked at. |
| `POST_EXISTING` | `false` | Whether reports already stored at the bot's first start are posted. |
| `ATTACH_SCREENSHOT` | `true` | Upload a report's screenshot. |
| `ATTACH_SAVED_DATA` | `true` | Upload a report's saved-data ZIP. |
| `MAX_FILE_BYTES` | `10485760` | The largest file uploaded; a larger one stays on the server and the post says so. |

The saved-data ZIP holds the reporting player's pets and settings. Everyone who can read the channel can download it:
use a private channel, or set `ATTACH_SAVED_DATA=false`.

## Behaviour

- A report is posted once. The list of posted reports survives restarts; a report deleted on the server is forgotten.
- Reports are posted oldest first. When Discord does not take a message (no connection, a rate limit, a wrong token
  or channel), the reason is logged and the same report is tried again on the next look; nothing is skipped.
- A report whose text the server is still writing is left for the next look.
- When Discord refuses an upload for its size, the report is posted with its text alone and a line saying that the
  files are kept on the server.
- The token is never logged.

## Development

The bot is Python with no dependencies outside the standard library.

```sh
python -m unittest discover -s tests -t .
docker build -t reframed-bug-tracker-bot .
```

The tests make a report folder as the game server writes one and stand in for Discord; they need no token and no
network.

Pushes to `main` publish `ghcr.io/petzreframed/reframed-bug-tracker-bot:main`; a tag `v…` publishes that tag and
`latest` (see [.github/workflows/build.yml](.github/workflows/build.yml)).
