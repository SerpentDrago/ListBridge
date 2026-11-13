# ListBridge

**ListBridge** is a lightweight, self-hosted 3-way synchronization daemon that bridges **AnyList**, **Google Keep**, and **Amazon Alexa** shopping and to-do lists. 

Following Amazon's deprecation of third-party Alexa list skill APIs, ListBridge restores seamless voice-to-list integration by authenticating directly with Amazon's device backend alongside AnyList and Google Keep. Whether you tell an Echo device *"Alexa, add milk to my Grocery list"*, check off an item in Google Keep, or organize your shopping trip in AnyList, ListBridge keeps all three platforms in sync automatically.

---

## ✨ Features

* **True 3-Way Synchronization:** Bi-directional syncing between AnyList, Google Keep, and Amazon Alexa lists (or 2-way sync between AnyList and Google Keep if Alexa credentials are omitted).
* **Full Lifecycle State Tracking:** Synchronizes new item additions, checked/crossed-off statuses, unchecking/restoring items, and permanent deletions across all connected platforms.
* **Crossed-Off History Preservation:** Crossed-off items in AnyList and Google Keep stay neatly checked off rather than being destructively wiped, while avoiding cluttering your active Alexa list with old history items.
* **Ping-Pong & Duplicate Protection:** Intelligently groups duplicate entries and verifies remote state changes before committing to `state.json`, preventing sync loops.
* **Automatic 2FA Session Management:** Uses your Amazon Base32 TOTP secret (`pyotp`) to perform initial login and automatically refresh expired session tokens stored in `/data/alexa_auth.json`.
* **Multi-List Support:** Sync a single primary list (e.g., `Grocery`) or multiple lists simultaneously (e.g., `Grocery,Costco,Hardware`) with optional custom list name mapping.

---

## 🚀 Installation on Unraid

### Method 1: Unraid XML Template (Recommended)

1. Download the Unraid template file [`my-ListBridge.xml`](https://raw.githubusercontent.com/SerpentDrago/ListBridge/main/unraid/my-ListBridge.xml) from the `unraid/` folder of this repository.
2. Copy `my-ListBridge.xml` to your Unraid USB flash drive at:
   ```text
   /boot/config/plugins/dockerMan/templates-user/my-ListBridge.xml
   ```
   *(You can do this via the Unraid Web Terminal, SMB share `/flash/config/plugins/dockerMan/templates-user/`, or the Unraid File Manager).*
3. In the Unraid WebUI, navigate to the **Docker** tab and click **Add Container** at the bottom.
4. From the **Template** dropdown menu, select **`ListBridge`** (under **User Templates**).
5. Fill in your account credentials and desired list name(s), then click **Apply**.

### Method 2: Manual Unraid Container Setup

If you prefer to configure the container manually in the Unraid GUI without the XML file:
1. Go to **Docker** -> **Add Container**.
2. Set **Name** to `ListBridge`.
3. Set **Repository** to `ghcr.io/serpentdrago/listbridge:latest`.
4. Add a **Path** mapping:
   * **Container Path:** `/data`
   * **Host Path:** `/mnt/user/appdata/anylist-keep-sync` (or `/mnt/user/appdata/listbridge`)
5. Add the environment variables listed in the [Configuration Reference](#-configuration--environment-variables) below and click **Apply**.

---

## 🐳 Standard Docker Installation

### Docker Compose (`docker-compose.yml`)

```yaml
services:
  listbridge:
    image: ghcr.io/serpentdrago/listbridge:latest
    container_name: ListBridge
    restart: unless-stopped
    environment:
      - TZ=America/New_York
      - LIST_NAMES=Grocery
      - SYNC_INTERVAL=60
      - ANYLIST_EMAIL=your_anylist_email@example.com
      - ANYLIST_PASSWORD=your_anylist_password
      - GKEEP_EMAIL=your_google_email@gmail.com
      - GKEEP_APP_PASSWORD=aas_et/your_google_master_token
      - ALEXA_EMAIL=your_amazon_email@example.com
      - ALEXA_PASSWORD=your_amazon_password
      - ALEXA_OTP_SECRET=YOUR_AMAZON_2FA_BASE32_SECRET
      - ALEXA_LIST_MAP=
      - DATA_DIR=/data
    volumes:
      - ./data:/data
```

Start the container with:
```bash
docker compose up -d
```

### Docker CLI (`docker run`)

```bash
docker run -d \
  --name=ListBridge \
  --restart unless-stopped \
  -e TZ="America/New_York" \
  -e LIST_NAMES="Grocery" \
  -e SYNC_INTERVAL="60" \
  -e ANYLIST_EMAIL="your_anylist_email@example.com" \
  -e ANYLIST_PASSWORD="your_anylist_password" \
  -e GKEEP_EMAIL="your_google_email@gmail.com" \
  -e GKEEP_APP_PASSWORD="aas_et/your_google_master_token" \
  -e ALEXA_EMAIL="your_amazon_email@example.com" \
  -e ALEXA_PASSWORD="your_amazon_password" \
  -e ALEXA_OTP_SECRET="YOUR_AMAZON_2FA_BASE32_SECRET" \
  -e ALEXA_LIST_MAP="" \
  -e DATA_DIR="/data" \
  -v /path/to/host/appdata:/data:rw \
  ghcr.io/serpentdrago/listbridge:latest
```

---

## ⚙️ Configuration & Environment Variables

| Variable | Default | Required | Description |
| :--- | :--- | :---: | :--- |
| `LIST_NAMES` | `Grocery` | **Yes** | Comma-separated list of list names to sync across platforms (e.g., `Grocery` or `Grocery,Hardware`). |
| `SYNC_INTERVAL` | `60` | **Yes** | Time in seconds between sync cycles (`60` recommended to avoid rate-limiting). |
| `ANYLIST_EMAIL` | *(none)* | **Yes** | Your AnyList account email address. |
| `ANYLIST_PASSWORD` | *(none)* | **Yes** | Your AnyList account password. |
| `GKEEP_EMAIL` | *(none)* | **Yes** | Your Google account email address. |
| `GKEEP_APP_PASSWORD` | *(none)* | **Yes** | Your Google OAuth Master Token (`aas_et/...`) required by `gkeepapi`. |
| `ALEXA_EMAIL` | *(none)* | *Optional* | Your Amazon account email address. *(Leave blank for 2-way AnyList <-> Keep sync only).* |
| `ALEXA_PASSWORD` | *(none)* | *Optional* | Your Amazon account password. |
| `ALEXA_OTP_SECRET` | *(none)* | *Optional* | Your Amazon 2FA Authenticator Base32 Secret Key (used to generate 6-digit TOTP codes automatically). |
| `ALEXA_LIST_MAP` | *(blank)* | *Optional* | Optional mapping if a list has a different name in Alexa (Format: `AnyListName:AlexaName`, e.g., `Groceries:Shop`). Leave blank when list names match 1-to-1. |
| `DATA_DIR` | `/data` | *Optional* | Internal container path where persistent state and auth files are stored. |

---

## 🔑 How to Obtain Required Credentials

### 1. Google Keep Master Token (`GKEEP_APP_PASSWORD`)
Google Keep requires an OAuth Master Token (`aas_et/...`) to authenticate via `gkeepapi`. You can generate one using [gpsoauth-java / gkeepapi token tools](https://github.com/simon-weber/gpsoauth) or by running:
```bash
docker run --rm -it --entrypoint /bin/sh python:3.12-slim -c "pip install gpsoauth && python"
```
Follow the standard [gkeepapi Master Token instructions](https://gkeepapi.readthedocs.io/en/latest/#obtaining-a-master-token) to obtain your `aas_et/...` string.

### 2. Amazon 2FA OTP Secret (`ALEXA_OTP_SECRET`)
To allow ListBridge to log in headlessly and automatically renew expired Amazon sessions without manual intervention:
1. Log in to your Amazon Account -> **Login & Security** -> **Two-Step Verification (2SV) Settings**.
2. Under **Authenticator App**, click **Add new app**.
3. Click **"Can't scan the barcode?"** to reveal your **Base32 Secret Key** (a string of uppercase letters and numbers like `KFDTLHYAVQJIJFTY...`).
4. Copy that secret key (without spaces) into `ALEXA_OTP_SECRET`, and scan the QR code with your normal authenticator app to finish registering it with Amazon.

---

## 📂 Persistent Storage (`/data`)

ListBridge stores three files inside your mounted `/data` directory:
* **`state.json`**: Tracks the last known synchronized state of each list and item so ListBridge knows whether an item was newly added, checked/unchecked, or deleted since the previous cycle.
* **`alexa_auth.json`**: Stores your authenticated Amazon device session cookies/tokens so it doesn't need to perform an interactive OTP login on every cycle.
* **`sync.log`**: Persistent log file mirroring container standard output for easy troubleshooting.

---

## 🛠️ Building Locally from Source

If you want to build and run the Docker image locally:

```bash
git clone https://github.com/SerpentDrago/ListBridge.git
cd ListBridge
docker build -t listbridge:local .
```

---

## 📜 License

MIT License — feel free to fork, modify, and adapt for your own self-hosted smart home setup!