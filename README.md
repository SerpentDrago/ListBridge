# AnyList <-> Google Keep <-> Amazon Alexa (3-Way List Sync)

A lightweight, self-contained Docker daemon that maintains real-time 3-way synchronization between **AnyList**, **Google Keep**, and **Amazon Alexa** lists.

## Features
- **True 3-Way Sync:** Syncs item additions, checkmarks/cross-offs, unchecks, and deletions across all three services.
- **Crossed-Off History Preservation:** Crossed-off items stay crossed off rather than being deleted, and duplicate entries are grouped so they never ping-pong.
- **Multi-List Support:** Sync a single list (e.g. `Grocery`) or multiple lists via comma-separated `LIST_NAMES` (`Grocery,Hardware,Costco`).
- **Self-Contained Image:** All dependencies (`gkeepapi`, `pyanylist`, `aioamazondevices`, `pyalexatodo`, `pyotp`) and upstream typing fixes are pre-baked into the Docker image at build time.
- **Automatic Session Persistence:** Caches your Amazon OAuth session in `/data/alexa_auth.json` and uses your `ALEXA_OTP_SECRET` to automatically re-authenticate if Amazon rotates tokens.

## Environment Variables

| Variable | Default | Required | Description |
| :--- | :--- | :--- | :--- |
| `LIST_NAMES` | `Grocery` | Yes | Comma-separated list of list names to sync across all 3 platforms |
| `SYNC_INTERVAL` | `60` | Yes | Seconds between sync cycles |
| `ANYLIST_EMAIL` | — | Yes | Your AnyList account email |
| `ANYLIST_PASSWORD` | — | Yes | Your AnyList account password |
| `GKEEP_EMAIL` | — | Yes | Your Google account email |
| `GKEEP_APP_PASSWORD` | — | Yes | Your Google Keep `aas_et/...` Master Token or App Password |
| `ALEXA_EMAIL` | — | Optional | Your Amazon account email (if omitted, runs in 2-way AnyList/Keep mode) |
| `ALEXA_PASSWORD` | — | Optional | Your Amazon account password |
| `ALEXA_OTP_SECRET` | — | Optional | Your Amazon 2FA Authenticator Base32 Secret Key |
| `ALEXA_LIST_MAP` | `""` | Optional | Optional mapping if list names differ in Alexa (e.g. `Groceries:Shop`) |
| `DATA_DIR` | `/data` | Optional | Persistent directory inside container for `state.json`, `alexa_auth.json`, and `sync.log` |

## Unraid Installation

1. Copy `unraid/my-anylist-keep-alexa-sync.xml` to `/boot/config/plugins/dockerMan/templates-user/my-anylist-keep-alexa-sync.xml` on your Unraid server.
2. In the Unraid WebGUI, go to **Docker** -> **Add Container** -> select **anylist-keep-alexa-sync** under **User Templates**.
3. Fill in your credentials and click **Apply**.
