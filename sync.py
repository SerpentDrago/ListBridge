import os
import re
import sys
import site
import time
import json
import logging
import traceback

# 1. Configure logging on Line 1 BEFORE any third-party imports so crashes are ALWAYS logged to sync.log
DATA_DIR = os.environ.get("DATA_DIR", "/data" if os.path.exists("/data") else "/app")
os.makedirs(DATA_DIR, exist_ok=True)

LOG_FILE = os.path.join(DATA_DIR, "sync.log")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
ALEXA_AUTH_FILE = os.path.join(DATA_DIR, "alexa_auth.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)

def patch_pyalexatodo_cleanly():
    """
    Safely patches pyalexatodo 0.2.0 typing bugs in site-packages (or /app/libs)
    by reading the full file into memory BEFORE opening for write.
    """
    search_dirs = ["/app/libs"] + site.getsitepackages()
    for base_dir in search_dirs:
        pkg_dir = os.path.join(base_dir, "pyalexatodo")
        if not os.path.exists(pkg_dir):
            continue
        for root, _, files in os.walk(pkg_dir):
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                fpath = os.path.join(root, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    code = f.read()

                lines = [
                    ln for ln in code.splitlines()
                    if ln.strip() not in ("from __future__ import annotations", "import typing", "import builtins")
                ]
                clean_code = "\n".join(lines)
                clean_code = clean_code.replace("ListInfo[ListInfo]", "typing.List[ListInfo]")
                clean_code = clean_code.replace("builtins.list[", "typing.List[")
                clean_code = re.sub(r"(?<![\w\.])list\[", "typing.List[", clean_code)

                patched_code = "from __future__ import annotations\nimport typing\n" + clean_code + "\n"
                compile(patched_code, fpath, "exec")
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(patched_code)

try:
    patch_pyalexatodo_cleanly()
    import asyncio
    import inspect
    import requests
    import gkeepapi
    from aiohttp import ClientSession
    from aioamazondevices.api import AmazonEchoApi
    from pyalexatodo.api import AlexaToDoAPI
    from pyanylist import AnyListClient
except Exception as boot_err:
    logging.error(f"STARTUP ERROR: {boot_err}\n{traceback.format_exc()}")
    time.sleep(60)
    sys.exit(1)

logging.getLogger("gkeepapi").setLevel(logging.ERROR)
logging.getLogger("aioamazondevices").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# --- ENVIRONMENT VARIABLES ---
ANYLIST_EMAIL = os.environ.get("ANYLIST_EMAIL", "").strip()
ANYLIST_PASSWORD = os.environ.get("ANYLIST_PASSWORD", "").strip()
GKEEP_EMAIL = os.environ.get("GKEEP_EMAIL", "").strip()
GKEEP_APP_PASSWORD = os.environ.get("GKEEP_APP_PASSWORD", "").strip()

ALEXA_EMAIL = os.environ.get("ALEXA_EMAIL", "").strip()
ALEXA_PASSWORD = os.environ.get("ALEXA_PASSWORD", "").strip()
ALEXA_OTP_SECRET = os.environ.get("ALEXA_OTP_SECRET", "").strip()

RAW_LISTS = os.environ.get("LIST_NAMES") or os.environ.get("LIST_NAME", "Grocery")
LIST_NAMES = [name.strip() for name in RAW_LISTS.split(",") if name.strip()]

RAW_ALEXA_MAP = os.environ.get("ALEXA_LIST_MAP", "")
ALEXA_LIST_MAP = {}
for pair in RAW_ALEXA_MAP.split(","):
    if ":" in pair:
        k, v = pair.split(":", 1)
        ALEXA_LIST_MAP[k.strip()] = v.strip()

SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL", 60))


class SaveDataConfig:
    def __init__(self, path=DATA_DIR, callback=None):
        self.path = path
        self.callback = callback
        self.enabled = False


class DirectAlexaAdapter:
    """Uses authenticated AmazonEchoApi + AlexaToDoAPI with verified completion persistence."""
    def __init__(self, email, password, otp_secret):
        self.email = email
        self.password = password
        self.otp_secret = otp_secret
        self.lists_cache = {}
        self._cycle_data = {}
        self._logged_lists_once = False

    def _get_otp(self):
        if not self.otp_secret:
            return ""
        secret = self.otp_secret.strip().replace(" ", "")
        if len(secret) == 6 and secret.isdigit():
            return secret
        import pyotp
        return pyotp.TOTP(secret).now()

    def _load_auth(self):
        if os.path.exists(ALEXA_AUTH_FILE):
            try:
                with open(ALEXA_AUTH_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def _save_auth(self, data=None, *args, **kwargs):
        if data and isinstance(data, dict):
            with open(ALEXA_AUTH_FILE, "w") as f:
                json.dump(data, f)

    async def _run_with_todo_api(self, coro_func):
        async with ClientSession() as session:
            stored_data = self._load_auth()
            sig = inspect.signature(AmazonEchoApi.__init__)

            kwargs = {}
            for pname, param in sig.parameters.items():
                if pname == "self":
                    continue
                elif pname == "client_session":
                    kwargs[pname] = session
                elif pname == "login_email":
                    kwargs[pname] = self.email
                elif pname == "login_password":
                    kwargs[pname] = self.password
                elif pname == "login_data":
                    kwargs[pname] = stored_data
                elif pname == "save_data":
                    kwargs[pname] = SaveDataConfig(path=DATA_DIR, callback=None)
                elif param.default is inspect.Parameter.empty:
                    kwargs[pname] = None

            amazon_api = AmazonEchoApi(**kwargs)
            try:
                if stored_data:
                    try:
                        await amazon_api.login.login_mode_stored_data()
                    except Exception as e:
                        logging.warning(f"Stored Alexa session expired ({e}), re-authenticating with OTP...")
                        auth_data = await amazon_api.login.login_mode_interactive(self._get_otp())
                        self._save_auth(auth_data)
                else:
                    logging.info("Performing initial Alexa login with OTP secret...")
                    auth_data = await amazon_api.login.login_mode_interactive(self._get_otp())
                    self._save_auth(auth_data)

                todo_api = AlexaToDoAPI(amazon_api)
                return await coro_func(todo_api)
            finally:
                if hasattr(amazon_api, "close"):
                    await amazon_api.close()

    def _resolve_list_id(self, list_name):
        target = ALEXA_LIST_MAP.get(list_name, list_name).strip().lower()
        for k, v in self.lists_cache.items():
            if k.lower() == target:
                return v
        if target in ("grocery", "groceries", "shopping", "shopping list", "shop"):
            for k, v in self.lists_cache.items():
                if k.lower() in ("grocery", "groceries", "shop", "shopping list", "shopping"):
                    return v
        return None

    async def _fetch_items_for_list(self, todo_api, lid):
        items = []
        if hasattr(todo_api, "get_list_items_batched"):
            async for batch in todo_api.get_list_items_batched(lid):
                if isinstance(batch, list):
                    items.extend(batch)
                else:
                    items.append(batch)
        else:
            items = await todo_api.get_list_items(lid)
            if not isinstance(items, list):
                items = getattr(items, "items", getattr(items, "list", []))
        return items

    def refresh_lists_and_items(self, list_names):
        async def _fetch(todo_api):
            lists = await todo_api.get_lists()
            self.lists_cache = {}
            debug_summary = []

            for l in lists:
                lname_raw = getattr(l, "name", None) or getattr(l, "title", None) or ""
                lid_raw = (
                    getattr(l, "id", None)
                    or getattr(l, "item_id", None)
                    or getattr(l, "itemId", None)
                    or getattr(l, "list_id", None)
                )
                if lname_raw and lid_raw:
                    clean_name = str(lname_raw).strip()
                    lid_str = str(lid_raw).strip()
                    debug_summary.append(f"{clean_name} (id={lid_str})")
                    self.lists_cache[clean_name] = lid_str

            if not self._logged_lists_once:
                logging.info(f"Alexa Lists discovered: {debug_summary}")
                for lname in list_names:
                    lid = self._resolve_list_id(lname)
                    matched = [k for k, v in self.lists_cache.items() if v == lid]
                    logging.info(f"[{lname}] Locked onto Alexa list {matched} (id={lid})")
                self._logged_lists_once = True

            results = {}
            for lname in list_names:
                lid = self._resolve_list_id(lname)
                if not lid:
                    logging.error(f"[{lname}] Alexa list not found. Available Alexa lists: {list(self.lists_cache.keys())}")
                    results[lname] = (None, None)
                    continue

                items = await self._fetch_items_for_list(todo_api, lid)
                nodes, state = {}, {}
                for item in items:
                    val = (getattr(item, "value", None) or getattr(item, "name", None) or getattr(item, "text", None) or "").strip()
                    if not val:
                        continue
                    checked = bool(getattr(item, "completed", getattr(item, "checked", False)))
                    nodes.setdefault(val, []).append(item)
                    if val not in state or not checked:
                        state[val] = checked
                results[lname] = (nodes, state)
            return results

        self._cycle_data = asyncio.run(self._run_with_todo_api(_fetch))

    def get_items(self, list_name):
        return self._cycle_data.get(list_name, (None, None))

    def add_item(self, list_name, name, checked=False):
        lid = self._resolve_list_id(list_name)
        async def _add(todo_api):
            try:
                res = await todo_api.add_item(lid, name)
                if checked:
                    new_item = res if (hasattr(res, "id") or hasattr(res, "item_id") or hasattr(res, "itemId")) else None
                    if not new_item and hasattr(todo_api, "get_item_by_name"):
                        new_item = await todo_api.get_item_by_name(lid, name)
                    if new_item:
                        await self._toggle_async(todo_api, lid, new_item, True)
                return True
            except Exception as e:
                logging.error(f"[{list_name}] Alexa add_item failed for '{name}': {e}\n{traceback.format_exc()}")
                return False
        return bool(asyncio.run(self._run_with_todo_api(_add)))

    async def _toggle_async(self, todo_api, lid, item_obj, checked):
        item_id = getattr(item_obj, "id", None) or getattr(item_obj, "item_id", None) or getattr(item_obj, "itemId", None)
        version = int(getattr(item_obj, "version", 1) or 1)
        val = getattr(item_obj, "value", None) or getattr(item_obj, "name", None) or ""

        # Step 1: Try pyalexatodo's built-in set_item_checked_status
        try:
            await todo_api.set_item_checked_status(lid, item_id, bool(checked), version)
        except Exception as e:
            logging.warning(f"pyalexatodo set_item_checked_status raised for '{val}': {e}")

        # Step 2: Check whether Amazon ACTUALLY updated `completed` on the item
        refreshed_items = await self._fetch_items_for_list(todo_api, lid)
        current_item = next(
            (it for it in refreshed_items if (getattr(it, "id", None) or getattr(it, "item_id", None)) == item_id),
            None
        )
        if current_item is not None:
            actual_checked = bool(getattr(current_item, "completed", getattr(current_item, "checked", False)))
            if actual_checked == bool(checked):
                return True
            version = int(getattr(current_item, "version", version) or version)
            item_obj = current_item

        # Step 3: Send complete PUT payload with `value`, `completed`, `listId`, `id`, `version`, and `type`
        if hasattr(todo_api, "_http_request"):
            if hasattr(item_obj, "model_dump"):
                payload = item_obj.model_dump(by_alias=True, exclude_none=True)
            elif hasattr(item_obj, "dict"):
                payload = item_obj.dict(by_alias=True, exclude_none=True)
            else:
                payload = {}

            payload["id"] = item_id
            payload["listId"] = lid
            payload["value"] = val
            payload["completed"] = bool(checked)
            payload["version"] = version
            payload.setdefault("type", "TASK")

            sig = inspect.signature(todo_api._http_request)
            req_kwargs = {"method": "PUT", "endpoint": f"/api/namedLists/{lid}/item/{item_id}"}
            if "data" in sig.parameters:
                req_kwargs["data"] = payload
            elif "json_data" in sig.parameters:
                req_kwargs["json_data"] = payload
            elif "input_data" in sig.parameters:
                req_kwargs["input_data"] = payload

            try:
                await todo_api._http_request(**req_kwargs)
            except Exception as put_err:
                logging.error(f"Alexa full PUT failed for '{val}': {put_err}")
                return False

            refreshed_items2 = await self._fetch_items_for_list(todo_api, lid)
            current_item2 = next(
                (it for it in refreshed_items2 if (getattr(it, "id", None) or getattr(it, "item_id", None)) == item_id),
                None
            )
            if current_item2 is not None:
                actual_checked2 = bool(getattr(current_item2, "completed", getattr(current_item2, "checked", False)))
                if actual_checked2 == bool(checked):
                    return True

        logging.warning(f"Alexa API refused to persist completed={checked} for '{val}'. Preserving state to prevent ping-pong.")
        return False

    def set_checked(self, list_name, item_objs, name, checked):
        lid = self._resolve_list_id(list_name)
        objs = item_objs if isinstance(item_objs, list) else [item_objs]
        async def _check(todo_api):
            all_ok = True
            for obj in objs:
                ok = await self._toggle_async(todo_api, lid, obj, checked)
                if not ok:
                    all_ok = False
            return all_ok
        return bool(asyncio.run(self._run_with_todo_api(_check)))

    def delete_item(self, list_name, item_objs, name):
        lid = self._resolve_list_id(list_name)
        objs = item_objs if isinstance(item_objs, list) else [item_objs]
        async def _del(todo_api):
            all_ok = True
            for obj in objs:
                item_id = getattr(obj, "id", None) or getattr(obj, "item_id", None) or getattr(obj, "itemId", None)
                version = int(getattr(obj, "version", 1) or 1)
                try:
                    await todo_api.delete_item(lid, item_id, version)
                except Exception as e:
                    logging.error(f"Alexa delete_item failed for '{name}': {e}")
                    all_ok = False
            return all_ok
        return bool(asyncio.run(self._run_with_todo_api(_del)))


def load_all_states():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                alexa_init = bool(data.get("alexa_initialized", False))
                if "lists" in data and isinstance(data["lists"], dict):
                    return data["lists"], alexa_init
                if "items" in data and LIST_NAMES:
                    old_items = data["items"]
                    if isinstance(old_items, list):
                        old_items = {name: False for name in old_items if name}
                    return {LIST_NAMES[0]: old_items}, False
        except Exception as e:
            logging.error(f"Error reading state file: {e}")
    return {}, False

def save_all_states(lists_dict, alexa_initialized=True):
    with open(STATE_FILE, "w") as f:
        json.dump({
            "alexa_initialized": alexa_initialized,
            "lists": lists_dict
        }, f, indent=2)

def get_keep_list(keep, target_name):
    for note in keep.all():
        if isinstance(note, gkeepapi.node.List) and note.title == target_name:
            return note
    logging.info(f"[{target_name}] Creating new list in Google Keep...")
    return keep.createList(target_name)

def is_anylist_item_checked(item):
    for attr in ("is_checked", "checked", "crossed_off", "is_crossed_off"):
        if hasattr(item, attr):
            return bool(getattr(item, attr))
    return False

def sync_single_list(list_name, keep, al_client, al_lists_map, alexa_adapter, prev_state, alexa_was_initialized):
    a_list = al_lists_map.get(list_name)
    if not a_list:
        logging.error(f"[{list_name}] List not found in AnyList.")
        return prev_state, False, alexa_was_initialized

    k_list = get_keep_list(keep, list_name)
    keep_changed = False

    keep_nodes, keep_state = {}, {}
    for item in k_list.items:
        name = item.text.strip()
        if not name:
            continue
        keep_nodes.setdefault(name, []).append(item)
        if name not in keep_state or not item.checked:
            keep_state[name] = bool(item.checked)

    any_nodes, any_state = {}, {}
    for item in a_list.items:
        name = item.name.strip()
        if not name:
            continue
        checked = is_anylist_item_checked(item)
        any_nodes.setdefault(name, []).append(item)
        if name not in any_state or not checked:
            any_state[name] = checked

    alexa_enabled = alexa_adapter is not None
    alexa_nodes, alexa_state = {}, {}
    if alexa_enabled:
        a_nodes, a_state = alexa_adapter.get_items(list_name)
        if a_nodes is None:
            alexa_enabled = False
        else:
            alexa_nodes, alexa_state = a_nodes, a_state

    new_state = {}
    all_names = set(keep_state.keys()) | set(any_state.keys()) | set(alexa_state.keys()) | set(prev_state.keys())

    for name in all_names:
        in_k = name in keep_state
        in_a = name in any_state
        in_x = name in alexa_state if alexa_enabled else False
        in_p = name in prev_state

        deleted_from_keep_or_any = in_p and (not in_k or not in_a)
        deleted_from_alexa = in_p and alexa_enabled and alexa_was_initialized and (not in_x)

        if deleted_from_keep_or_any or deleted_from_alexa:
            if in_k:
                logging.info(f"[{list_name}] Deleting '{name}' from Google Keep...")
                for node in keep_nodes[name]:
                    node.delete()
                keep_changed = True
            if in_a:
                logging.info(f"[{list_name}] Deleting '{name}' from AnyList...")
                for node in any_nodes[name]:
                    al_client.delete_item(a_list.id, node.id)
            if in_x:
                logging.info(f"[{list_name}] Deleting '{name}' from Alexa...")
                alexa_adapter.delete_item(list_name, alexa_nodes[name], name)
            continue

        if not (in_k or in_a or in_x):
            continue

        current_checks = {}
        if in_k: current_checks["k"] = keep_state[name]
        if in_a: current_checks["a"] = any_state[name]
        if in_x and (alexa_was_initialized or not in_p):
            current_checks["x"] = alexa_state[name]

        if in_p:
            p_chk = prev_state[name]
            changed_vals = [val for val in current_checks.values() if val != p_chk]
            target_chk = changed_vals[0] if changed_vals else p_chk
        else:
            if in_k and in_a and keep_state[name] == any_state[name]:
                target_chk = keep_state[name]
            elif (in_k and not keep_state[name]) or (in_a and not any_state[name]):
                target_chk = False
            else:
                target_chk = any(current_checks.values())

        if not in_k:
            logging.info(f"[{list_name}] Adding '{name}' to Google Keep...")
            k_list.add(name, target_chk)
            keep_changed = True
        elif any(bool(node.checked) != target_chk for node in keep_nodes[name]):
            logging.info(f"[{list_name}] {'Crossing off' if target_chk else 'Unchecking'} '{name}' in Google Keep...")
            for node in keep_nodes[name]:
                node.checked = target_chk
            keep_changed = True

        if not in_a:
            logging.info(f"[{list_name}] Adding '{name}' to AnyList...")
            new_item = al_client.add_item(a_list.id, name)
            if target_chk:
                al_client.cross_off_item(a_list.id, new_item.id)
        elif any(is_anylist_item_checked(node) != target_chk for node in any_nodes[name]):
            if target_chk:
                logging.info(f"[{list_name}] Crossing off '{name}' in AnyList...")
                for node in any_nodes[name]:
                    if not is_anylist_item_checked(node):
                        al_client.cross_off_item(a_list.id, node.id)
            else:
                logging.info(f"[{list_name}] Unchecking '{name}' in AnyList...")
                for node in any_nodes[name]:
                    if is_anylist_item_checked(node):
                        al_client.uncheck_item(a_list.id, node.id)

        alexa_added_or_present = in_x
        alexa_item_ok = True

        if alexa_enabled:
            if not in_x:
                if not target_chk:
                    logging.info(f"[{list_name}] Adding '{name}' to Alexa...")
                    alexa_item_ok = alexa_adapter.add_item(list_name, name, target_chk)
                    if alexa_item_ok:
                        alexa_added_or_present = True
            elif alexa_state[name] != target_chk:
                logging.info(f"[{list_name}] {'Crossing off' if target_chk else 'Unchecking'} '{name}' in Alexa...")
                alexa_item_ok = alexa_adapter.set_checked(list_name, alexa_nodes[name], name, target_chk)

        if alexa_enabled and not alexa_added_or_present:
            continue

        new_state[name] = target_chk

    return new_state, keep_changed, (alexa_was_initialized or alexa_enabled)


def main():
    logging.info(f"Starting 3-Way Sync for {len(LIST_NAMES)} list(s): {LIST_NAMES}")

    keep = gkeepapi.Keep()
    keep.authenticate(GKEEP_EMAIL, GKEEP_APP_PASSWORD)
    al_client = AnyListClient.login(ANYLIST_EMAIL, ANYLIST_PASSWORD)

    alexa_adapter = None
    if ALEXA_EMAIL and ALEXA_PASSWORD:
        logging.info("Alexa Sync Mode: Direct Amazon API + pyalexatodo enabled.")
        alexa_adapter = DirectAlexaAdapter(ALEXA_EMAIL, ALEXA_PASSWORD, ALEXA_OTP_SECRET)
    else:
        logging.info("Alexa credentials not provided. Running 2-Way Sync (AnyList <-> Google Keep).")

    while True:
        try:
            keep.sync()
            al_lists = al_client.get_lists()
            al_lists_map = {l.name.strip(): l for l in al_lists}

            if alexa_adapter:
                try:
                    alexa_adapter.refresh_lists_and_items(LIST_NAMES)
                except Exception as alexa_err:
                    logging.error(f"Alexa fetch failed (Keep & AnyList will still sync): {alexa_err}\n{traceback.format_exc()}")

            all_states, alexa_init = load_all_states()
            any_keep_changes = False
            new_alexa_init = alexa_init

            for list_name in LIST_NAMES:
                prev_list_state = all_states.get(list_name, {})
                updated_state, keep_changed, list_alexa_init = sync_single_list(
                    list_name, keep, al_client, al_lists_map, alexa_adapter, prev_list_state, alexa_init
                )
                all_states[list_name] = updated_state
                if keep_changed:
                    any_keep_changes = True
                if list_alexa_init:
                    new_alexa_init = True

            if any_keep_changes:
                keep.sync()

            save_all_states(all_states, alexa_initialized=new_alexa_init)

        except Exception as e:
            logging.error(f"Error during sync cycle: {e}\n{traceback.format_exc()}")

        time.sleep(SYNC_INTERVAL)

if __name__ == "__main__":
    try:
        main()
    except Exception as fatal_err:
        logging.error(f"Unhandled exception in main(): {fatal_err}\n{traceback.format_exc()}")
        time.sleep(60)
