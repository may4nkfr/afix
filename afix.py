import sys
import asyncio
import json
import os
import random
import time
import re
import glob
import logging
import contextvars
import zipfile
import tempfile
import shutil
from types import SimpleNamespace

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.tl import types
from telethon.tl.functions.messages import SendReactionRequest, EditChatDefaultBannedRightsRequest, EditChatTitleRequest, GetStickerSetRequest, ImportChatInviteRequest
from telethon.tl.functions.channels import EditTitleRequest, InviteToChannelRequest, EditAdminRequest, JoinChannelRequest, LeaveChannelRequest
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.chatlists import CheckChatlistInviteRequest
from telethon.tl.types import ReactionEmoji, ChatAdminRights, InputStickerSetShortName

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logging.basicConfig(level=logging.CRITICAL)
logging.getLogger("telethon").setLevel(logging.CRITICAL)
logging.getLogger("asyncio").setLevel(logging.CRITICAL)

original_unraisablehook = sys.unraisablehook
def custom_unraisablehook(unraisable):
    exc_str = str(unraisable.exc_value)
    obj_str = str(unraisable.object)
    if "GeneratorExit" in exc_str or "Connection" in obj_str or "Task" in obj_str: return
    original_unraisablehook(unraisable)
sys.unraisablehook = custom_unraisablehook

# ==========================================
#              BOT CONFIGURATION
# ==========================================
BOT_TOKEN = "8974738827:AAHD-0HWIJurnEea1F_LaqxIpxDfk-keh3o"  

MASTER_OWNER = 8870796161
PREFIX = "."
P = re.escape(PREFIX)

DATA_DIR = "sessions/data"
SESSIONS_DIR = "sessions"
CREDS_FILE = os.path.join(DATA_DIR, "session_creds.json")
HOSTERS_FILE = os.path.join(DATA_DIR, "hosters.json")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(SESSIONS_DIR, exist_ok=True)

NORMAL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
MAPPED = "𝘼𝘽𝘾𝘿𝙀𝙁𝙂𝙃𝙄𝙅𝙆𝙇𝙈𝙉𝙊𝙋𝙌𝙍𝙎𝙏𝙐𝑑𝑒𝑓𝙔𝙕𝙖𝙗𝙘𝙙𝙚𝙛𝙜𝙝𝙞𝙟𝙠𝙡𝙢𝙣𝙤𝙥𝙦𝙧𝙨𝙩𝙪𝙫𝙬𝙭𝙮𝙯"
FMAP = str.maketrans(NORMAL, MAPPED)
RANDOM_EMOJIS = ['✅', '❓', '💤', '💢', '🔥', '🖤', '⭐', '👻', '💗', "🩷", "👾", "🕷️"]

TEXTS = [
    "chup rndyke", "terimakichut chup", "teri ma rndy hy beta", "chup mc",
    "teri ma k hath todh k tere baap k muh me fasadunga randyke", "lode se utr mc",
    "ma rndy teri", "chup chap chud tmkc", "chal rndyke", "ha ha teri ma rndy aage bata",
    "chup tmkc", "chup rndyke tommy", "terimakabosda", "teri ma rndy", "lun mt chus mera",
    "ary chup randike", "makichut teri", "nikal madarchd", 
    "apni ma mat chuda muje swipe kr k", "teri ma ka bhsda", "chup oye gashti k bache",
    "chop chop terimahogiyesb", "pglhcyalore", "ammi jaan kesi hai apki", "oy hijde khana kha ke aa kamzor",
    "ny ny me kuch ny janta bs teri ma rndy ey", "teri maka bund kala q ey",
    "chal chal chal teri ma rndy", "tuto chup rndyk", "chup  मादर𝒄𝒉𝒐𝒅 🤣?",
    "terito bhen chudegi", "teri mako ily rey🌚😂", "chal av lode se utr", "leave le tu rndyke pasand nai aya meko",
]
MENTION_TEXTS = ["{mention} chup rndyk", "mc pgl wgl h ky tag krrha {mention}", "ary {mention} rndyk don't tag", "chup randyk {mention}"]

bot_state = {}
active_wizards = {}  
support_tickets = {}  # owner_user_id -> ticket_user_id while replying
active_clients = {}  # dict tracking {session_name: client}

# ==========================================
#          CREDENTIAL STORAGE HELPERS
# ==========================================
def load_session_creds():
    return load_json(CREDS_FILE, {})

async def save_session_cred(session_name, api_id, api_hash):
    creds = load_session_creds()
    creds[session_name] = {"api_id": api_id, "api_hash": api_hash}
    await async_save_json(CREDS_FILE, creds)

async def remove_session_cred(session_name):
    creds = load_session_creds()
    if session_name in creds:
        del creds[session_name]
        await async_save_json(CREDS_FILE, creds)

# ==========================================
#          AUTO CLEANUP CONTROLLER
# ==========================================
tracked_responses = contextvars.ContextVar("tracked_responses", default=None)

def auto_clean(delay=3):
    def decorator(func):
        async def wrapper(event):
            responses_list = []
            token = tracked_responses.set(responses_list)
            try:
                await func(event)
            finally:
                tracked_responses.reset(token)
                await asyncio.sleep(delay)
                try:
                    await event.delete()
                except:
                    pass
                for msg in responses_list:
                    try:
                        await msg.delete()
                    except:
                        pass
        return wrapper
    return decorator

def fmt(text, mode=None):
    t = str(text).translate(FMAP)
    em = random.choice(RANDOM_EMOJIS)
    if mode == 'start': return f"✓ {t} {em}"
    elif mode == 'stop': return f"✗ {t} {em}"
    return f"{t} {em}"

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f: return type(default)(json.load(f))
    except: return default

async def async_save_json(path, data):
    def _write():
        with open(path, "w", encoding="utf-8") as f:
            json.dump(list(data) if isinstance(data, set) else data, f)
    await asyncio.to_thread(_write)

def load_hoster_ids():
    data = load_json(HOSTERS_FILE, [])
    result = []
    for value in data:
        try:
            uid = int(value)
            if uid > 0 and uid not in result:
                result.append(uid)
        except (TypeError, ValueError):
            pass
    return result

async def add_hoster_id(user_id):
    hosters = load_hoster_ids()
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return
    if uid > 0 and uid not in hosters:
        hosters.append(uid)
        await async_save_json(HOSTERS_FILE, hosters)

def _safe_zip_member(name):
    name = name.replace("\\", "/")
    return not (name.startswith("/") or name.startswith("../") or "/../" in name)

def _session_path(session_name):
    return os.path.join(SESSIONS_DIR, f"{session_name}.session")

async def create_session_export():
    """Create one portable ZIP containing every hosted .session plus credentials/data."""
    sessions = []
    for filename in os.listdir(SESSIONS_DIR):
        if not filename.endswith(".session"):
            continue
        name = filename[:-8]
        if name == "joy_hoster_bot":
            continue
        full = os.path.join(SESSIONS_DIR, filename)
        if os.path.isfile(full):
            sessions.append((name, full))
    if not sessions:
        raise FileNotFoundError("No userbot .session files found.")

    export_path = os.path.join(DATA_DIR, f"joy_all_sessions_{int(time.time())}.zip")
    manifest = {
        "format": "joy_individual_sessions_zip",
        "format_version": 1,
        "created_at": int(time.time()),
        "session_count": len(sessions)
    }

    def _build():
        with zipfile.ZipFile(export_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("backup_manifest.json", json.dumps(manifest, indent=2))
            for name, full in sessions:
                zf.write(full, arcname=f"sessions/{name}.session")
            if os.path.exists(CREDS_FILE):
                zf.write(CREDS_FILE, arcname="data/session_creds.json")
            if os.path.exists(HOSTERS_FILE):
                zf.write(HOSTERS_FILE, arcname="data/hosters.json")
            # Preserve per-session persistent configuration so imported sessions behave the same.
            if os.path.isdir(DATA_DIR):
                for root, _, files in os.walk(DATA_DIR):
                    for filename in files:
                        full = os.path.join(root, filename)
                        if full == export_path or filename.endswith(".zip"):
                            continue
                        rel = os.path.relpath(full, DATA_DIR).replace("\\", "/")
                        if rel in {"session_creds.json", "hosters.json"}:
                            continue
                        zf.write(full, arcname=f"data/{rel}")
    await asyncio.to_thread(_build)
    return export_path, len(sessions)

async def start_imported_session(session_name, creds, max_retries=3):
    """Start one imported authorized session with retries and useful failure details."""
    if session_name == "joy_hoster_bot":
        return "skipped", "hoster bot session"
    if session_name in active_clients:
        return "already_running", ""

    path = _session_path(session_name)
    if not os.path.isfile(path):
        return "missing", "session file not found"

    info = creds.get(session_name, {}) if isinstance(creds, dict) else {}
    api_id = info.get("api_id", 32962486)
    api_hash = info.get("api_hash", "a352a4c3668c16a313e564c92cc04ea1")

    try:
        api_id = int(api_id)
        api_hash = str(api_hash).strip()
        if not api_hash:
            return "failed", "empty API hash"
    except Exception as e:
        return "failed", f"invalid API credentials: {e}"

    last_error = "unknown error"

    for attempt in range(1, max_retries + 1):
        client = TelegramClient(
            os.path.join(SESSIONS_DIR, session_name),
            api_id,
            api_hash,
            connection_retries=3,
            retry_delay=2,
            auto_reconnect=True,
        )
        try:
            await asyncio.wait_for(client.connect(), timeout=30)

            authorized = await asyncio.wait_for(
                client.is_user_authorized(), timeout=20
            )
            if not authorized:
                await client.disconnect()
                return "unauthorized", "Telegram session is not authorized"

            # get_me() here also verifies that the restored session is usable.
            await asyncio.wait_for(client.get_me(), timeout=20)
            await register_handlers(client, session_name)

            active_clients[session_name] = client
            asyncio.create_task(
                client.run_until_disconnected(),
                name=f"session_runner_{session_name}"
            )
            return "started", ""

        except asyncio.TimeoutError:
            last_error = f"timeout on attempt {attempt}/{max_retries}"
        except FloodWaitError as e:
            last_error = f"FloodWait: {e.seconds}s"
            await asyncio.sleep(min(e.seconds, 60))
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"

        try:
            await client.disconnect()
        except Exception:
            pass

        if attempt < max_retries:
            await asyncio.sleep(2 * attempt)

    return "failed", last_error


async def import_session_export(export_path):
    """Restore every session from a ZIP and attempt to start every restored session."""
    restored = 0
    started = 0
    already = 0
    failed = 0
    unauthorized = 0
    missing = 0
    skipped = 0
    failures = []

    with tempfile.TemporaryDirectory(prefix="joy_import_") as temp_dir:
        def _extract():
            with zipfile.ZipFile(export_path, "r") as zf:
                bad = [
                    m.filename for m in zf.infolist()
                    if not _safe_zip_member(m.filename)
                ]
                if bad:
                    raise RuntimeError("Unsafe ZIP path detected.")

                try:
                    manifest = json.loads(
                        zf.read("backup_manifest.json").decode("utf-8")
                    )
                except Exception:
                    raise RuntimeError(
                        "Invalid backup: backup_manifest.json is missing."
                    )

                if manifest.get("format") != "joy_individual_sessions_zip":
                    raise RuntimeError("This is not a valid Joy session backup.")

                zf.extractall(temp_dir)
                return manifest

        manifest = await asyncio.to_thread(_extract)

        src_sessions = os.path.join(temp_dir, "sessions")
        if not os.path.isdir(src_sessions):
            raise RuntimeError("Backup contains no sessions directory.")

        imported_creds = {}
        creds_path = os.path.join(temp_dir, "data", "session_creds.json")
        if os.path.exists(creds_path):
            try:
                with open(creds_path, encoding="utf-8") as f:
                    imported_creds = json.load(f)
                if not isinstance(imported_creds, dict):
                    imported_creds = {}
            except Exception:
                imported_creds = {}

        imported_creds.pop("joy_hoster_bot", None)
        current_creds = load_session_creds()
        current_creds.update(imported_creds)
        await async_save_json(CREDS_FILE, current_creds)

        hosters_path = os.path.join(temp_dir, "data", "hosters.json")
        if os.path.exists(hosters_path):
            try:
                with open(hosters_path, encoding="utf-8") as f:
                    incoming = json.load(f)
                merged = load_hoster_ids()
                for value in incoming if isinstance(incoming, list) else []:
                    try:
                        uid = int(value)
                        if uid > 0 and uid not in merged:
                            merged.append(uid)
                    except Exception:
                        pass
                await async_save_json(HOSTERS_FILE, merged)
            except Exception:
                pass

        names = sorted({
            filename[:-8]
            for filename in os.listdir(src_sessions)
            if filename.endswith(".session")
            and filename[:-8] != "joy_hoster_bot"
        })

        expected = manifest.get("session_count")
        if isinstance(expected, int) and expected != len(names):
            # Don't abort: the actual ZIP contents are what can safely be restored.
            logging.warning(
                "Backup manifest says %s sessions but ZIP contains %s.",
                expected, len(names)
            )

        # Restore session files first. Never overwrite a session that is already live.
        for name in names:
            src = os.path.join(src_sessions, f"{name}.session")
            dst = _session_path(name)

            if name in active_clients:
                already += 1
                continue

            try:
                shutil.copy2(src, dst)
                restored += 1
            except Exception as e:
                failed += 1
                failures.append(f"{name}: restore error: {type(e).__name__}: {e}")

        # Restore persistent per-session data.
        src_data = os.path.join(temp_dir, "data")
        if os.path.isdir(src_data):
            for root, _, files in os.walk(src_data):
                rel_root = os.path.relpath(root, src_data)
                dest_root = (
                    DATA_DIR if rel_root == "."
                    else os.path.join(DATA_DIR, rel_root)
                )
                os.makedirs(dest_root, exist_ok=True)

                for filename in files:
                    if filename in {"session_creds.json", "hosters.json"}:
                        continue
                    if filename.endswith(".zip"):
                        continue
                    try:
                        shutil.copy2(
                            os.path.join(root, filename),
                            os.path.join(dest_root, filename)
                        )
                    except Exception:
                        pass

        # Important: attempt EVERY session, even if one fails.
        for index, name in enumerate(names, 1):
            if name in active_clients:
                continue

            # Small stagger prevents a large ZIP from opening many Telegram
            # connections at exactly the same moment.
            if index > 1:
                await asyncio.sleep(1.0)

            result, reason = await start_imported_session(
                name, current_creds, max_retries=3
            )

            if result == "started":
                started += 1
            elif result == "already_running":
                already += 1
            elif result == "unauthorized":
                unauthorized += 1
                failures.append(f"{name}: unauthorized")
            elif result == "missing":
                missing += 1
                failures.append(f"{name}: session file missing")
            elif result == "skipped":
                skipped += 1
            else:
                failed += 1
                failures.append(f"{name}: {reason}")

    return {
        "restored": restored,
        "started": started,
        "already": already,
        "unauthorized": unauthorized,
        "missing": missing,
        "failed": failed,
        "skipped": skipped,
        "total": len(names),
        "failures": failures,
    }

async def edit_or_reply(event, text):
    msg = None
    try:
        if getattr(event, 'out', False) or getattr(event, 'is_channel', False):
            try: msg = await event.edit(text)
            except: msg = await event.reply(text)
        else:
            msg = await event.reply(text)
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds)
        msg = await event.reply(text)
    except Exception:
        try: msg = await event.reply(text)
        except: pass

    if msg:
        current_list = tracked_responses.get()
        if current_list is not None:
            current_list.append(msg)
    return msg

async def delete_event_safely(event, client_id):
    try:
        if getattr(event, 'out', False) or getattr(event, 'sender_id', None) == client_id or getattr(event, 'is_channel', False):
            await event.delete()
    except: pass

# ==========================================
#          USERBOT LOGIC ENGINE
# ==========================================

async def run_selected_command_in_all_groups(client, source_event, command_name, command_text=None):
    """Run only the selected commands in every group where this userbot is present."""
    source_chat = getattr(source_event, "chat_id", None)
    if not source_chat:
        return 0

    try:
        dialogs = await client.get_dialogs()
    except Exception:
        return 0

    count = 0
    for dialog in dialogs:
        entity = getattr(dialog, "entity", None)
        chat_id = getattr(entity, "id", None)
        if not chat_id or chat_id == source_chat:
            continue

        # Only groups/supergroups, never private chats or channels.
        if not (getattr(dialog, "is_group", False) or getattr(dialog, "is_channel", False)):
            continue
        if getattr(dialog, "is_channel", False) and not getattr(dialog, "is_group", False):
            continue

        try:
            # Send the same command as a fresh outgoing message.
            await client.send_message(chat_id, command_text or command_name)
            count += 1
        except Exception:
            continue

    return count

async def register_handlers(client, session_name):
    me = await client.get_me()
    bots_file = os.path.join(DATA_DIR, f"bots_{session_name}.json")
    subs_file = os.path.join(DATA_DIR, f"subs_{session_name}.json")
    silence_file = os.path.join(DATA_DIR, f"silence_{session_name}.json")
    react_file = os.path.join(DATA_DIR, f"react_{session_name}.json")
    
    if not os.path.exists(bots_file): await async_save_json(bots_file, [])
            
    if client not in bot_state:
        bot_state[client] = {
            "swipe": {}, "slidespam": {}, "spam": {}, "stickerspam": {},      
            "reply": {}, "mention_users": set(), "auto_sticker": {},
            "reactall": {}, "minereact": {}, "lockname": {}, "locks": {},            
            "filters": {}, "purgefrom": {}, "ms": {}, "autoreply": {},
            "subs": set(load_json(subs_file, [])),
            "silenced": set(load_json(silence_file, [])),
            "user_react": load_json(react_file, {}),
            "afk": False, "afk_reason": "", "afk_start": 0.0,
            "ghost": False, "muteall_chats": set(), "protected_users": set(),
            "original_name": None, "original_photo": None, "original_bio": None, "dl_cp_path": None,
            "cp_count": 0, "delay": 0.5, "session_bots": load_json(bots_file, []),
            "reading": True
        }
    
    state = bot_state[client]

    # Normalize persisted/legacy silence data to a global user-id set.
    if isinstance(state.get("silenced"), dict):
        merged_silenced = set()
        for values in state["silenced"].values():
            if isinstance(values, (list, tuple, set)):
                for value in values:
                    try:
                        merged_silenced.add(int(value))
                    except (TypeError, ValueError):
                        pass
        state["silenced"] = merged_silenced
    elif not isinstance(state.get("silenced"), set):
        try:
            state["silenced"] = {int(x) for x in state.get("silenced", [])}
        except Exception:
            state["silenced"] = set()


    async def is_allowed(event):
        if getattr(event, 'out', False): return True
        sender_id = getattr(event, 'sender_id', None)
        if sender_id in [MASTER_OWNER, me.id] or sender_id in state["subs"]: 
            return True
        if getattr(event, 'is_channel', False) and getattr(event.message, 'post', False):
            try:
                chat = await event.get_chat()
                if getattr(chat, 'creator', False) or getattr(chat, 'admin_rights', None): return True
            except: pass
        return False

    async def auto_typing(chat_id):
        try:
            async with client.action(chat_id, "typing"): await asyncio.sleep(state["delay"])
        except Exception: 
            await asyncio.sleep(state["delay"])

    async def fast_delete(chat_id, msg_id):
        try: await client.delete_messages(chat_id, [msg_id], revoke=True)
        except: pass

    async def get_targets(event):
        targets = []
        args_text = event.pattern_match.group(1) if event.pattern_match and len(event.pattern_match.groups()) > 0 else ""
        text_rem = (args_text or "").strip()
        if getattr(event.message, 'entities', None):
            for ent in event.message.entities:
                if isinstance(ent, (types.MessageEntityMention, types.MessageEntityMentionName)):
                    uid = ent.user_id if isinstance(ent, types.MessageEntityMentionName) else event.raw_text[ent.offset:ent.offset+ent.length]
                    try:
                        user = await client.get_entity(uid)
                        if user and user not in targets: targets.append(user)
                    except:
                        if isinstance(uid, int) or (isinstance(uid, str) and uid.lstrip('-').isdigit()):
                            fake_uid = int(uid)
                            fake = SimpleNamespace(id=fake_uid, first_name=f"Target {fake_uid}", last_name="", username=None, bot=False, premium=False, verified=False)
                            if fake not in targets: targets.append(fake)
        if not targets and event.is_reply:
            try:
                reply = await event.get_reply_message()
                target_id = getattr(reply, 'sender_id', None) or getattr(reply, 'chat_id', None)
                if target_id:
                    fake = SimpleNamespace(id=target_id, first_name=f"Target {target_id}", last_name="", username=None, bot=False, premium=False, verified=False)
                    targets.append(fake)
            except: pass
        if not targets and text_rem:
            for part in text_rem.split():
                try:
                    uid = int(part) if part.lstrip('-').isdigit() else part
                    user = await client.get_entity(uid)
                    if user and user not in targets: targets.append(user)
                except:
                    if isinstance(part, str) and part.lstrip('-').isdigit():
                        fake_uid = int(part)
                        fake = SimpleNamespace(id=fake_uid, first_name=f"Target {fake_uid}", last_name="", username=None, bot=False, premium=False, verified=False)
                        if fake not in targets: targets.append(fake)
        if targets and text_rem:
            for u in targets:
                if getattr(u, 'username', None): text_rem = re.sub(rf"@{u.username}", "", text_rem, flags=re.IGNORECASE)
                text_rem = re.sub(rf"\b{u.id}\b", "", text_rem)
        return targets, text_rem.strip()

    @client.on(events.NewMessage(pattern=rf"^{P}ping(?:\s+)?$"))
    @auto_clean(delay=3)
    async def ping_cmd(event):
        if not await is_allowed(event): return
        start = time.time()
        msg = await edit_or_reply(event, f"🏓 {fmt('Ping...')}")
        end = time.time()
        ping_time = round((end - start) * 1000, 2)
        await msg.edit(f"🏓 **{fmt('Pong!')}**\n⚡ {'Speed:'.translate(FMAP)} {ping_time}ms\n")

    @client.on(events.NewMessage(pattern=rf"^{P}delay(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def delay_cmd(event):
        if not await is_allowed(event):
            return

        value = event.pattern_match.group(1)
        if value is None or not value.strip():
            current = state["delay"]
            return await edit_or_reply(
                event,
                f"{fmt(f'Current delay: {current:.2f}s', None)}\\n"
                f"{fmt('Use .delay <seconds> (0.1 - 30)', None)}"
            )

        try:
            new_delay = float(value.strip())
        except ValueError:
            return await edit_or_reply(
                event,
                f"{fmt('Invalid delay. Example: .delay 1 or .delay 0.5', 'stop')}"
            )

        if not 0.1 <= new_delay <= 30:
            return await edit_or_reply(
                event,
                f"{fmt('Delay must be between 0.1 and 30 seconds.', 'stop')}"
            )

        state["delay"] = new_delay
        await edit_or_reply(
            event,
            f"{fmt(f'Delay set to {new_delay:.2f}s for .spm and .slidespam.', 'start')}"
        )

    @client.on(events.NewMessage(pattern=rf"^{P}stopreading(?:\s+)?$"))
    @auto_clean(delay=3)
    async def stopreading_cmd(event):
        if not await is_allowed(event): return
        state["reading"] = False
        await edit_or_reply(event, f"{fmt('Passive Listener Paused! Ignoring all incoming messages.', 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}startreading(?:\s+)?$"))
    @auto_clean(delay=3)
    async def startreading_cmd(event):
        if not await is_allowed(event): return
        state["reading"] = True
        await edit_or_reply(event, f"{fmt('Passive Listener Resumed! Actively reading messages.', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}(?:cmds|commands)(?:\s+)?$"))
    async def help_menu(event):
        if not await is_allowed(event): return
        help_text = f"""
        🩷 {fmt(' KENG USERBOT')}

💬 **{'SPAMMERS & REPLIES'.translate(FMAP)}**
✘ `.slidespam` [text] (reply or mention)
✘ `.spm` <text>
✘ `.delay` <seconds> (controls .spm/.slidespam; `.delay` to check)
✘ `.ms` <text> (reply/mention)
✘ `.stickerspam` (reply)
✘ `.stopslidespam` / `.stopspam` / `.stopms` / `.stopstickerspam`
✘ `.swipe` <text> / `.stopswipe`
✘ `.autoreply` <text> / `.stopautoreply`
✘ `.reply` (per-group target) / `.stopreply`
✘ `.mention` (global target) / `.stopmention`
✘ `.sticker` <mention> (reply to sticker) / `.stopsticker`
✘ `.filter` <name> (reply) / `.stop <name>`
✘ `.filters` / `.stopall` / `.killall`

🎭 **{'FUN & REACTIONS'.translate(FMAP)}**
✘ `.tts` <text>
✘ `.react` <emoji> / `.stopreact`
✘ `.minereact` <emoji> / `.stopminereact`
✘ `.reactall` <emoji> / `.stopreactall`

🛡️ **{'GROUP MANAGEMENT'.translate(FMAP)}**
✘ `.kick` / `.ban` / `.unban` <reply/mention>
✘ `.silence` / `.unsilence` <reply/mention>
✘ `.silencelist` / `.muteall` / `.unmuteall`
✘ `.protect` / `.unprotect` / `.promote` / `.demote`
✘ `.lockname` <text> / `.unlockname`
✘ `.lock` <pic/video/media/links/files/sticker/gif> / `.unlock`
✘ `.locks`
✘ `.join` <link/username> / `.leave`

👤 **{'USER & PROFILE'.translate(FMAP)}**
✘ `.info` <reply or mention>
✘ `.profile` <reply/mention/id>
✘ `.tagall` [text]
✘ `.save` (reply)
✘ `.cppack` <pack link or name>
✘ `.cp` <reply/mention> / `.nrml`
✘ `.afk` [reason] / `.back`
✘ `.ghost`
✘ `.faketyping` <secs> / `.countdown` <secs>
✘ `.stopreading` / `.startreading`

🧹 **{'CLEANUP'.translate(FMAP)}**
✘ `.delmine` / `.delall` / `.purge` (reply)
✘ `.purgefrom` (reply) / `.purgeto` (reply)

🤖 **{'BOT CONTROL'.translate(FMAP)}**
✘ `.addbots` <user1, user2> / `.delbots`
✘ `.listbots`
✘ `.invitebots` / `.promotebots` / `.removebots`
✘ `.broadcast` <folder link> (reply to msg)

👑 **{'SUDO SYSTEM'.translate(FMAP)}**
✘ `.sudo` / `.delsudo` <reply/mention>
✘ `.sudolist`"""
        await edit_or_reply(event, help_text)

    @client.on(events.NewMessage(pattern=rf"^{P}killall(?:\s+)?$"))
    @auto_clean(delay=3)
    async def killall_cmd(event):
        if not await is_allowed(event): return
        for chat in list(state["spam"].keys()): state["spam"][chat].cancel()
        for chat in list(state["stickerspam"].keys()): state["stickerspam"][chat].cancel()
        for chat in list(state["slidespam"].keys()):
            for uid, task in list(state["slidespam"][chat].items()): task.cancel()
        for chat in list(state["ms"].keys()):
            for uid, task in list(state["ms"][chat].items()): task.cancel()
        state["spam"].clear()
        state["stickerspam"].clear()
        state["slidespam"].clear()
        state["ms"].clear()
        for key in ["swipe", "auto_sticker", "reply", "filters", "locks", "lockname", "reactall", "minereact", "purgefrom", "autoreply", "mention_users", "silenced"]:
            state[key].clear()
        await edit_or_reply(event, f"{fmt('KILLED ALL TASKS GLOBALLY', 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}protect(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def protect_cmd(event):
        if not await is_allowed(event): return
        targets, _ = await get_targets(event)
        if not targets: return await edit_or_reply(event, f"{fmt('Reply or mention users to protect', None)}")
        for u in targets: state["protected_users"].add(u.id)
        await edit_or_reply(event, f"{fmt(f'{len(targets)} Targets Protected from bans/locks', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}unprotect(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def unprotect_cmd(event):
        if not await is_allowed(event): return
        targets, _ = await get_targets(event)
        if not targets: return await edit_or_reply(event, f"{fmt('Reply or mention users to unprotect', None)}")
        for u in targets: state["protected_users"].discard(u.id)
        await edit_or_reply(event, f"{fmt(f'{len(targets)} Targets Unprotected', 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}sudo(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def sudo_cmd(event):
        if getattr(event, 'sender_id', None) not in [MASTER_OWNER, me.id]: return
        targets, _ = await get_targets(event)
        if not targets: return await edit_or_reply(event, f"{fmt('Reply or provide usernames/IDs', None)}")
        for u in targets: state["subs"].add(u.id)
        await async_save_json(subs_file, state["subs"])
        await edit_or_reply(event, f"{fmt(f'{len(targets)} Targets added to sudoers', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}delsudo(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def delsudo_cmd(event):
        if getattr(event, 'sender_id', None) not in [MASTER_OWNER, me.id]: return
        targets, _ = await get_targets(event)
        removed = 0
        for u in targets:
            if u.id in state["subs"]:
                state["subs"].remove(u.id)
                removed += 1
        await async_save_json(subs_file, state["subs"])
        await edit_or_reply(event, f"{fmt(f'{removed} Targets removed from sudoers', 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}(?:listsudo|sudolist)(?:\s+)?$"))
    @auto_clean(delay=3)
    async def listsudo_cmd(event):
        if getattr(event, 'sender_id', None) not in [MASTER_OWNER, me.id]: return
        if not state["subs"]: return await edit_or_reply(event, f"{fmt('No sudoers found', None)}")
        msg = f"**{fmt('SUDOERS LIST', 'start')}**\n\n"
        for uid in state["subs"]:
            try:
                user = await client.get_entity(uid)
                name = getattr(user, 'first_name', f'User {uid}')
                msg += f"• [{name.translate(FMAP)}](tg://user?id={uid}) ({uid})\n"
            except:
                msg += f"• [{'User'.translate(FMAP)} {uid}](tg://user?id={uid}) ({uid})\n"
        await edit_or_reply(event, msg)

    @client.on(events.NewMessage(pattern=rf"^{P}profile(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def profile_cmd(event):
        if not await is_allowed(event): return
        targets, _ = await get_targets(event)
        if not targets: return await edit_or_reply(event, f"{fmt('Reply, mention, or provide ID', None)}")
        u = targets[0]
        try:
            full = await client(GetFullUserRequest(u.id))
            bio = full.full_user.about or 'No Bio'
            name = f"{u.first_name or ''} {u.last_name or ''}".strip()
            msg = (
                f"👤 **{'Name:'.translate(FMAP)}** {name.translate(FMAP)}\n"
                f"🆔 **{'ID:'.translate(FMAP)}** {u.id}\n"
                f"📝 **{'Bio:'.translate(FMAP)}** {bio.translate(FMAP)}\n"
            )
            await edit_or_reply(event, msg)
        except Exception:
            await edit_or_reply(event, f"{fmt('Error fetching profile!', 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}cp(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def cp_cmd(event):
        if not await is_allowed(event): return
        targets, _ = await get_targets(event)
        if not targets: return await edit_or_reply(event, f"{fmt('Reply or mention someone!', None)}")
        target = targets[0]
        st = await edit_or_reply(event, f"{fmt('Processing profile copy...', 'start')}")
        if state["original_name"] is None:
            state["original_name"] = (me.first_name or "") + (" " + me.last_name if me.last_name else "")
            try:
                full_me = await client(GetFullUserRequest(me))
                state["original_bio"] = full_me.full_user.about or ""
            except: state["original_bio"] = ""
            try: 
                orig_path = f"orig_{me.id}_{time.time()}.jpg"
                dl_orig = await client.download_profile_photo('me', file=orig_path)
                if dl_orig and os.path.exists(dl_orig): state["original_photo"] = dl_orig
            except: state["original_photo"] = None
        try:
            full_target = await client(GetFullUserRequest(target.id))
            target_bio = full_target.full_user.about or ""
            await st.edit(f"{fmt('Applying changes...', 'start')}")
            await client(UpdateProfileRequest(first_name=target.first_name or "", last_name=target.last_name or "", about=target_bio[:70]))
            photo_path = f"cp_{target.id}_{time.time()}.jpg"
            dl_path = await client.download_profile_photo(target.id, file=photo_path)
            if dl_path and os.path.exists(dl_path):
                uploaded = await client.upload_file(dl_path)
                await client(UploadProfilePhotoRequest(file=uploaded))
                state["cp_count"] += 1 
                state["dl_cp_path"] = dl_path 
            await st.edit(f"{fmt('Profile & Bio Copied Successfully!', 'start')}")
        except Exception as e: await st.edit(f"{fmt(f'Error: {e}', 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}nrml(?:\s+)?$"))
    @auto_clean(delay=3)
    async def nrml_cmd(event):
        if not await is_allowed(event): return
        if state["original_name"] is None: return await edit_or_reply(event, f"{fmt('No saved profile', 'stop')}")
        try:
            names = state["original_name"].split(' ', 1)
            await client(UpdateProfileRequest(first_name=names[0], last_name=names[1] if len(names) > 1 else "", about=state["original_bio"] or ""))
            if state["cp_count"] > 0:
                photos = await client.get_profile_photos('me', limit=state["cp_count"])
                if photos: await client(DeletePhotosRequest(photos))
            if state["dl_cp_path"] and os.path.exists(state["dl_cp_path"]):
                try: os.remove(state["dl_cp_path"])
                except: pass
            if state["original_photo"] and os.path.exists(state["original_photo"]):
                uploaded = await client.upload_file(state["original_photo"])
                await client(UploadProfilePhotoRequest(file=uploaded))
                try: os.remove(state["original_photo"])
                except: pass
            state["original_name"], state["original_photo"], state["original_bio"], state["cp_count"], state["dl_cp_path"] = None, None, None, 0, None
            await edit_or_reply(event, f"{fmt('Original Profile Restored & Files Cleaned', 'start')}")
        except Exception as e: await edit_or_reply(event, f"{fmt(f'Error: {e}', 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}spm(?:\s+([\s\S]+))?$"))
    async def spm_cmd(event):
        if not await is_allowed(event): return
        text = event.pattern_match.group(1)
        if not text: 
            msg = await edit_or_reply(event, f"{fmt('Provide text to spam', None)}")
            await asyncio.sleep(3)
            try: await event.delete()
            except: pass
            try: await msg.delete()
            except: pass
            return
        chat_id = event.chat_id
        delay_value = state["delay"]
        if chat_id in state["spam"]:
            state["spam"][chat_id].cancel()

        async def worker():
            while True:
                try:
                    await client.send_message(chat_id, text)
                    await asyncio.sleep(delay_value)
                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds)
                except asyncio.CancelledError:
                    break
                except Exception:
                    await asyncio.sleep(1)

        state["spam"][chat_id] = asyncio.create_task(worker())
        await delete_event_safely(event, me.id)

    @client.on(events.NewMessage(pattern=rf"^{P}stopspam(?:\s+)?$"))
    @auto_clean(delay=3)
    async def stopspam_cmd(event):
        if not await is_allowed(event): return
        if event.chat_id in state["spam"]:
            state["spam"][event.chat_id].cancel()
            del state["spam"][event.chat_id]
            await edit_or_reply(event, f"{fmt('Spam Stopped', 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}slidespam(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def slidespam_cmd(event):
        if not await is_allowed(event): return
        targets, custom_text = await get_targets(event)
        if not targets: return await edit_or_reply(event, f"{fmt('Reply or mention users to lock SlideSpam', None)}")
        chat_id = event.chat_id
        if chat_id not in state["slidespam"]: state["slidespam"][chat_id] = {}
        for u in targets:
            uid = u.id
            if uid in state["slidespam"][chat_id]: state["slidespam"][chat_id][uid].cancel()
            delay_value = state["delay"]

            async def worker(target_uid=uid):
                while True:
                    try:
                        await auto_typing(chat_id)
                        text_to_send = custom_text if custom_text else random.choice(TEXTS)
                        await client.send_message(
                            chat_id,
                            text_to_send,
                            reply_to=event.reply_to_msg_id if event.is_reply else None
                        )
                        await asyncio.sleep(delay_value + random.uniform(0.5, 1.5))
                    except FloodWaitError as e:
                        await asyncio.sleep(e.seconds)
                    except asyncio.CancelledError:
                        break
                    except Exception:
                        await asyncio.sleep(1)
            state["slidespam"][chat_id][uid] = asyncio.create_task(worker(uid))
        await edit_or_reply(event, f"{fmt(f'SlideSpam Activated for {len(targets)} targets', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}stopslidespam(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def stop_slidespam(event):
        if not await is_allowed(event): return
        chat_id = event.chat_id
        targets, _ = await get_targets(event)
        if targets:
            for u in targets:
                if chat_id in state["slidespam"] and u.id in state["slidespam"][chat_id]:
                    state["slidespam"][chat_id][u.id].cancel()
                    del state["slidespam"][chat_id][u.id]
            await edit_or_reply(event, f"{fmt('SlideSpam Stopped for Target', 'stop')}")
        else:
            if chat_id in state["slidespam"]:
                for uid, task in list(state["slidespam"][chat_id].items()): task.cancel()
                state["slidespam"][chat_id].clear()
            await edit_or_reply(event, f"{fmt('SlideSpam Stopped Fully', 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}react(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def react_on(event):
        if not await is_allowed(event): return
        targets, custom_text = await get_targets(event)
        if not targets: return await edit_or_reply(event, f"{fmt('Reply or mention users to react', None)}")
        emoji = custom_text.strip()
        if not emoji: return await edit_or_reply(event, f"{fmt('Provide an emoji to react', None)}")
        for u in targets: state["user_react"][str(u.id)] = emoji
        await async_save_json(react_file, state["user_react"])
        await edit_or_reply(event, f"{fmt(f'React Locked for {len(targets)} targets', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}stopreact(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def react_off(event):
        if not await is_allowed(event): return
        targets, _ = await get_targets(event)
        if not targets: return await edit_or_reply(event, f"{fmt('Reply or mention users to stop react', None)}")
        count = 0
        for u in targets:
            if str(u.id) in state["user_react"]:
                del state["user_react"][str(u.id)]
                count += 1
        await async_save_json(react_file, state["user_react"])
        await edit_or_reply(event, f"{fmt(f'React stopped for {count} targets', 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}ms(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def ms_cmd(event):
        if not await is_allowed(event): return
        targets, custom_text = await get_targets(event)
        if not targets: return await edit_or_reply(event, f"{fmt('Reply or mention users to use MS', None)}")
        chat_id = event.chat_id
        texts_to_use = [t.strip() for t in custom_text.split(',')] if custom_text else TEXTS
        if chat_id not in state["ms"]: state["ms"][chat_id] = {}
        reply_id = event.reply_to_msg_id if event.is_reply else None
        for u in targets:
            uid = u.id
            if uid in state["ms"][chat_id]: state["ms"][chat_id][uid].cancel()
            async def worker(target_uid=uid, t_user=u):
                name = getattr(t_user, 'first_name', 'User/Channel') or 'User/Channel'
                mention_str = f"[{name}](tg://user?id={target_uid})"
                while True:
                    try:
                        raw_msg = random.choice(texts_to_use)
                        msg_to_send = raw_msg.replace("{mention}", mention_str)
                        if "{mention}" not in raw_msg:
                            msg_to_send = f"{mention_str} {msg_to_send}"
                        await client.send_message(chat_id, msg_to_send, reply_to=reply_id)
                        await asyncio.sleep(0.1)
                    except FloodWaitError as e: await asyncio.sleep(e.seconds)
                    except asyncio.CancelledError: break
                    except Exception: await asyncio.sleep(0.5)
            state["ms"][chat_id][uid] = asyncio.create_task(worker(uid, u))
        await edit_or_reply(event, f"{fmt(f'MS Activated for {len(targets)} targets', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}stopms(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def stop_ms(event):
        if not await is_allowed(event): return
        chat_id = event.chat_id
        targets, _ = await get_targets(event)
        stopped = False
        if targets:
            for u in targets:
                if chat_id in state["ms"] and u.id in state["ms"][chat_id]:
                    state["ms"][chat_id][u.id].cancel()
                    del state["ms"][chat_id][u.id]
                    stopped = True
        else:
            if chat_id in state["ms"]:
                for uid, task in list(state["ms"][chat_id].items()): task.cancel()
                state["ms"][chat_id].clear()
                stopped = True
        if stopped: await edit_or_reply(event, f"{fmt('MS Stopped', 'stop')}")
        else: await edit_or_reply(event, f"{fmt('No active MS for target', None)}")

    @client.on(events.NewMessage(pattern=rf"^{P}stickerspam(?:\s+)?$"))
    async def stickerspam_cmd(event):
        if not await is_allowed(event): return
        if not event.is_reply:
            msg = await edit_or_reply(event, f"{fmt('Reply to a sticker to spam it', None)}")
            await asyncio.sleep(3)
            try: await event.delete(); await msg.delete()
            except: pass
            return
        reply = await event.get_reply_message()
        if not reply.media or not hasattr(reply.media, 'document'): 
            msg = await edit_or_reply(event, f"{fmt('Not a valid sticker', None)}")
            await asyncio.sleep(3)
            try: await event.delete(); await msg.delete()
            except: pass
            return
        chat_id = event.chat_id
        if chat_id in state["stickerspam"]: state["stickerspam"][chat_id].cancel()
        async def worker():
            while True:
                try:
                    await client.send_message(chat_id, file=reply.media)
                    await asyncio.sleep(state["delay"])
                except FloodWaitError as e: await asyncio.sleep(e.seconds)
                except asyncio.CancelledError: break
                except Exception: break
        state["stickerspam"][chat_id] = asyncio.create_task(worker())
        await delete_event_safely(event, me.id)

    @client.on(events.NewMessage(pattern=rf"^{P}stopstickerspam(?:\s+)?$"))
    @auto_clean(delay=3)
    async def stopstickerspam_cmd(event):
        if not await is_allowed(event): return
        chat_id = event.chat_id
        if chat_id in state["stickerspam"]:
            state["stickerspam"][chat_id].cancel()
            del state["stickerspam"][chat_id]
            await edit_or_reply(event, f"{fmt('Sticker Spam', 'stop')}")
        else: await edit_or_reply(event, f"{fmt('No Active Sticker Spam', None)}")

    @client.on(events.NewMessage(pattern=rf"^{P}swipe(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def swipe_cmd(event):
        if not await is_allowed(event): return
        text = event.pattern_match.group(1)
        if not text: return await edit_or_reply(event, f"{fmt('Please provide text!', None)}")
        state["swipe"][event.chat_id] = text
        await edit_or_reply(event, f"{fmt('Swipe Auto-Reply', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}stopswipe(?:\s+)?$"))
    @auto_clean(delay=3)
    async def stop_swipe(event):
        if not await is_allowed(event): return
        if event.chat_id in state["swipe"]:
            del state["swipe"][event.chat_id]
            await edit_or_reply(event, f"{fmt('Swipe', 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}autoreply(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def autoreply_cmd(event):
        if not await is_allowed(event): return
        targets, custom_text = await get_targets(event)
        if not targets or not custom_text: 
            return await edit_or_reply(event, f"{fmt('Please provide a user and text!', None)}")
        chat_id = event.chat_id
        if chat_id not in state["autoreply"]: state["autoreply"][chat_id] = {}
        for u in targets: state["autoreply"][chat_id][u.id] = custom_text
        await edit_or_reply(event, f"{fmt(f'Custom Auto-Reply set for {len(targets)} targets', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}stopautoreply(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def stopautoreply_cmd(event):
        if not await is_allowed(event): return
        targets, _ = await get_targets(event)
        chat_id = event.chat_id
        if not targets: return await edit_or_reply(event, f"{fmt('Provide a user to stop replying to!', None)}")
        stopped = 0
        for u in targets:
            if chat_id in state["autoreply"] and u.id in state["autoreply"][chat_id]:
                del state["autoreply"][chat_id][u.id]
                stopped += 1
        await edit_or_reply(event, f"{fmt(f'Auto-reply stopped for {stopped} targets', 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}reply(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def reply_on(event):
        if not await is_allowed(event): return
        targets, _ = await get_targets(event)
        if not targets: return await edit_or_reply(event, f"{fmt('Reply or mention users to lock Reply', None)}")
        chat_id = event.chat_id
        if chat_id not in state["reply"]: state["reply"][chat_id] = {}
        for u in targets: state["reply"][chat_id][u.id] = {"count": 0, "my_msgs":[]}
        await edit_or_reply(event, f"{fmt(f'Reply Locked for {len(targets)} targets', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}stopreply(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def reply_off(event):
        if not await is_allowed(event): return
        chat_id = event.chat_id
        targets, _ = await get_targets(event)
        if targets:
            count = 0
            for u in targets:
                if chat_id in state["reply"] and u.id in state["reply"][chat_id]:
                    del state["reply"][chat_id][u.id]
                    count += 1
            if not state["reply"].get(chat_id): 
                if chat_id in state["reply"]: del state["reply"][chat_id]
            await edit_or_reply(event, f"{fmt(f'Reply stopped for {count} targets', 'stop')}")
        else: await edit_or_reply(event, f"{fmt('Reply or mention users to stop Reply', None)}")

    @client.on(events.NewMessage(pattern=rf"^{P}mention(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def mention_add(event):
        if not await is_allowed(event): return
        targets, _ = await get_targets(event)
        if not targets: return await edit_or_reply(event, f"{fmt('Reply or mention users to abuse them', None)}")
        for u in targets: state["mention_users"].add(u.id)
        await edit_or_reply(event, f"{fmt(f'Auto-Mention Abuse started for {len(targets)} targets', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}stopmention(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def mention_remove(event):
        if not await is_allowed(event): return
        targets, _ = await get_targets(event)
        if not targets: return await edit_or_reply(event, f"{fmt('Reply or mention users to stop abusing', None)}")
        for u in targets:
            if u.id in state["mention_users"]: state["mention_users"].remove(u.id)
        await edit_or_reply(event, f"{fmt(f'Auto-Mention Abuse stopped for {len(targets)} targets', 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}sticker(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def autosticker_cmd(event):
        if not await is_allowed(event): return
        if not event.is_reply: return await edit_or_reply(event, f"{fmt('Reply to a sticker to use this', None)}")
        reply = await event.get_reply_message()
        if not reply.document: return await edit_or_reply(event, f"{fmt('Reply must be a sticker', None)}")
        targets, _ = await get_targets(event)
        if not targets: return await edit_or_reply(event, f"{fmt('Mention users to target', None)}")
        chat_id = event.chat_id
        for t in targets: state["auto_sticker"].setdefault(chat_id, {})[t.id] = reply.media
        await edit_or_reply(event, f"{fmt(f'Auto-sticker enabled for {len(targets)} targets', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}stopsticker(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def stopautosticker_cmd(event):
        if not await is_allowed(event): return
        targets, _ = await get_targets(event)
        chat_id = event.chat_id
        if not targets:
            if chat_id in state["auto_sticker"]:
                del state["auto_sticker"][chat_id]
                return await edit_or_reply(event, f"{fmt('Auto-sticker stopped for all in this chat', 'stop')}")
            else: return await edit_or_reply(event, f"{fmt('No active auto-stickers here', None)}")
        else:
            count = 0
            for t in targets:
                if chat_id in state["auto_sticker"] and t.id in state["auto_sticker"][chat_id]:
                    del state["auto_sticker"][chat_id][t.id]
                    count += 1
            await edit_or_reply(event, f"{fmt(f'Auto-sticker stopped for {count} targets', 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}filter(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def filter_cmd(event):
        if not await is_allowed(event): return
        if not event.is_reply: return await edit_or_reply(event, f"{fmt('Reply to a message to save as filter', None)}")
        name = event.pattern_match.group(1)
        if not name: return await edit_or_reply(event, f"{fmt('Provide a filter name!', None)}")
        reply = await event.get_reply_message()
        chat = event.chat_id
        name = name.strip().lower()
        state["filters"].setdefault(chat, {})[name] = reply
        await edit_or_reply(event, f"{fmt(f'Filter {name} saved successfully!', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}stop\s+(.+)$"))
    @auto_clean(delay=3)
    async def stopfilter_cmd(event):
        if not await is_allowed(event): return
        name = event.pattern_match.group(1)
        if not name: return
        chat = event.chat_id
        name = name.strip().lower()
        if chat in state["filters"] and name in state["filters"][chat]:
            del state["filters"][chat][name]
            await edit_or_reply(event, f"{fmt(f'Filter {name} stopped.', 'stop')}")
        else: await edit_or_reply(event, f"{fmt(f'Filter {name} not found.', None)}")

    @client.on(events.NewMessage(pattern=rf"^{P}filters(?:\s+)?$"))
    @auto_clean(delay=3)
    async def filters_cmd(event):
        if not await is_allowed(event): return
        chat = event.chat_id
        if chat not in state["filters"] or not state["filters"][chat]:
            return await edit_or_reply(event, f"{fmt('No filters in this chat.', None)}")
        msg = f"**{fmt('CHAT FILTERS', 'start')}**\n\n"
        for name in state["filters"][chat]: msg += f"• {name}\n"
        await edit_or_reply(event, msg)

    @client.on(events.NewMessage(pattern=rf"^{P}stopall(?:\s+)?$"))
    @auto_clean(delay=3)
    async def stopall_cmd(event):
        if not await is_allowed(event): return
        chat = event.chat_id
        if chat in state["spam"]:
            state["spam"][chat].cancel()
            del state["spam"][chat]
        if chat in state["stickerspam"]:
            state["stickerspam"][chat].cancel()
            del state["stickerspam"][chat]
        if chat in state["slidespam"]:
            for task in list(state["slidespam"][chat].values()): task.cancel()
            state["slidespam"][chat].clear()
            del state["slidespam"][chat]
        if chat in state["ms"]:
            for task in list(state["ms"][chat].values()): task.cancel()
            state["ms"][chat].clear()
            del state["ms"][chat]
        for key in ["swipe", "auto_sticker", "reply", "filters", "locks", "lockname", "reactall", "minereact", "purgefrom", "autoreply"]:
            if chat in state[key]: del state[key][chat]
        await edit_or_reply(event, f"{fmt('Terminated all tasks, locks, and filters in this group.', 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}cppack(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def cppack_cmd(event):
        if not await is_allowed(event): return
        link = event.pattern_match.group(1)
        if not link: return await edit_or_reply(event, f"{fmt('Provide a sticker pack link or name!', None)}")
        pack_name = link.split('/')[-1]
        st = await edit_or_reply(event, f"{fmt('Fetching sticker pack...', None)}")
        try: pack = await client(GetStickerSetRequest(stickerset=InputStickerSetShortName(short_name=pack_name), hash=0))
        except Exception as e: return await st.edit(f"{fmt(f'Failed to fetch pack: {e}', 'stop')}")
        await st.edit(f"{fmt(f'Copying {len(pack.documents)} stickers...', 'start')}")
        try:
            cmd = '/newpack'
            is_animated = getattr(pack.set, 'animated', False)
            is_video = getattr(pack.set, 'video', False) or getattr(pack.set, 'videos', False)
            if is_animated: cmd = '/newanimated'
            elif is_video: cmd = '/newvideo'
            async with client.conversation('@Stickers') as conv:
                await conv.send_message(cmd)
                await conv.get_response()
                pack_title = f"{pack.set.title} Kanged"
                await conv.send_message(pack_title)
                await conv.get_response()
                doc_to_emoji = {}
                for p in pack.packs:
                    for doc_id in p.documents:
                        if doc_id not in doc_to_emoji: doc_to_emoji[doc_id] = p.emoticon
                count = 0
                for doc in pack.documents:
                    emoji = doc_to_emoji.get(doc.id, "✨")
                    ext = ".tgs" if is_animated else (".webm" if is_video else ".webp")
                    dl_path = f"kang_{doc.id}{ext}"
                    await client.download_media(doc, file=dl_path)
                    if os.path.exists(dl_path):
                        await conv.send_file(dl_path, force_document=True)
                        resp = await conv.get_response()
                        os.remove(dl_path)
                        if "Sorry, the file type is invalid" in resp.text: continue
                        await conv.send_message(emoji)
                        await conv.get_response()
                        count += 1
                await conv.send_message('/publish')
                await conv.get_response()
                await conv.send_message('/skip')
                await conv.get_response()
                short_name = f"maf_{me.id}_{random.randint(10000, 99999)}"
                await conv.send_message(short_name)
                resp = await conv.get_response()
                if "Sorry, this short name is already taken" in resp.text:
                    short_name = f"maf_{me.id}_{random.randint(100000, 999999)}"
                    await conv.send_message(short_name)
                    await conv.get_response()
                await st.edit(f"{fmt('Pack Copied Successfully!', 'start')}\n{fmt('Total Stickers:', None)} {count}\n{fmt('Link:', None)} t.me/addstickers/{short_name}")
            await client.delete_dialog('@Stickers')
        except Exception as e: await st.edit(f"{fmt(f'Error copying pack: {e}', 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}afk(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def afk_cmd(event):
        if not await is_allowed(event): return
        args = event.pattern_match.group(1)
        state["afk"] = True
        state["afk_reason"] = args.strip() if args else ""
        state["afk_start"] = time.time()
        reason = f" | {state['afk_reason']}" if state['afk_reason'] else ""
        await edit_or_reply(event, f"{fmt(f'AFK MODE ON{reason}', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}back(?:\s+)?$"))
    @auto_clean(delay=3)
    async def back_cmd(event):
        if not await is_allowed(event): return
        if not state["afk"]: return await edit_or_reply(event, f"{fmt('You were not AFK!', None)}")
        elapsed = int(time.time() - state["afk_start"])
        mins, secs = divmod(elapsed, 60)
        state["afk"] = False
        state["afk_reason"] = ""
        await edit_or_reply(event, f"{fmt(f'Welcome back! Away for {mins}m {secs}s', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}ghost(?:\s+)?$"))
    @auto_clean(delay=3)
    async def ghost_cmd(event):
        if not await is_allowed(event): return
        state["ghost"] = not state["ghost"]
        await edit_or_reply(event, f"{fmt('GHOST MODE', 'start' if state['ghost'] else 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}purgefrom(?:\s+)?$"))
    @auto_clean(delay=3)
    async def purgefrom_cmd(event):
        if not await is_allowed(event): return
        if not event.is_reply: return await edit_or_reply(event, f"{fmt('Reply to a message to set start point!', None)}")
        reply = await event.get_reply_message()
        state["purgefrom"][event.chat_id] = reply.id
        await edit_or_reply(event, f"{fmt('Purge start point set.', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}purgeto(?:\s+)?$"))
    async def purgeto_cmd(event):
        if not await is_allowed(event): return
        if not event.is_reply: 
            msg = await edit_or_reply(event, f"{fmt('Reply to a message to set end point!', None)}")
            await asyncio.sleep(3)
            try: await event.delete(); await msg.delete()
            except: pass
            return
        chat = event.chat_id
        if chat not in state.get("purgefrom", {}): 
            msg = await edit_or_reply(event, f"{fmt('Use .purgefrom first!', None)}")
            await asyncio.sleep(3)
            try: await event.delete(); await msg.delete()
            except: pass
            return
        reply = await event.get_reply_message()
        start_id = state["purgefrom"][chat]
        end_id = reply.id
        if start_id > end_id: start_id, end_id = end_id, start_id
        st = await edit_or_reply(event, f"{fmt('Purging messages...', 'start')}")
        msg_ids = []
        count = 0
        async for msg in client.iter_messages(chat, min_id=start_id-1, max_id=end_id+1):
            msg_ids.append(msg.id)
            if len(msg_ids) >= 100:
                try:
                    await client.delete_messages(chat, msg_ids)
                    count += len(msg_ids)
                except: pass
                msg_ids = []
        if msg_ids:
            try:
                await client.delete_messages(chat, msg_ids)
                count += len(msg_ids)
            except: pass
        del state["purgefrom"][chat]
        note = await client.send_message(chat, f"{fmt(f'Purged {count} messages!', 'start')}")
        await asyncio.sleep(3)
        try: await note.delete()
        except: pass
        try: await event.delete(); await st.delete()
        except: pass

    @client.on(events.NewMessage(pattern=rf"^{P}purge(?:\s+)?$"))
    async def purge_cmd(event):
        if not await is_allowed(event): return
        if not event.is_reply:
            msg = await edit_or_reply(event, f"{fmt('Reply to a message to purge downwards!', None)}")
            await asyncio.sleep(3)
            try: await event.delete(); await msg.delete()
            except: pass
            return
        reply_msg = await event.get_reply_message()
        st = await edit_or_reply(event, f"{fmt('Purging messages...', 'start')}")
        msg_ids = []
        count = 0
        async for msg in client.iter_messages(event.chat_id, min_id=reply_msg.id - 1):
            msg_ids.append(msg.id)
            if len(msg_ids) >= 100:
                try:
                    await client.delete_messages(event.chat_id, msg_ids)
                    count += len(msg_ids)
                except: pass
                msg_ids = []
        if msg_ids:
            try:
                await client.delete_messages(event.chat_id, msg_ids)
                count += len(msg_ids)
            except: pass
        note = await client.send_message(event.chat_id, f"{fmt(f'Purged {count} messages!', 'start')}")
        await asyncio.sleep(3)
        try: await note.delete()
        except: pass
        try: await event.delete(); await st.delete()
        except: pass

    @client.on(events.NewMessage(pattern=rf"^{P}delmine(?:\s+)?$"))
    async def delmine_cmd(event):
        if not await is_allowed(event): return
        chat = event.chat_id
        st = await edit_or_reply(event, f"{fmt('Deleting my messages...', 'start')}")
        msg_ids = []
        count = 0
        async for msg in client.iter_messages(chat, from_user='me'):
            msg_ids.append(msg.id)
            if len(msg_ids) >= 100:
                try:
                    await client.delete_messages(chat, msg_ids)
                    count += len(msg_ids)
                except: pass
                msg_ids = []
        if msg_ids:
            try:
                await client.delete_messages(chat, msg_ids)
                count += len(msg_ids)
            except: pass
        try:
            msg = await client.send_message(chat, f"{fmt(f'Successfully deleted {count} of my messages.', 'start')}")
            await asyncio.sleep(3)
            await msg.delete()
            if getattr(st, 'out', False): await st.delete()
            await event.delete()
        except: pass

    @client.on(events.NewMessage(pattern=rf"^{P}delall(?:\s+)?$"))
    async def delall_cmd(event):
        if not await is_allowed(event): return
        chat = event.chat_id
        st = await edit_or_reply(event, f"{fmt('Deleting chat history...', 'start')}")
        msg_ids = []
        count = 0
        async for msg in client.iter_messages(chat):
            msg_ids.append(msg.id)
            if len(msg_ids) >= 100:
                try:
                    await client.delete_messages(chat, msg_ids)
                    count += len(msg_ids)
                except: pass
                msg_ids = []
        if msg_ids:
            try:
                await client.delete_messages(chat, msg_ids)
                count += len(msg_ids)
            except: pass
        try:
            msg = await client.send_message(chat, f"{fmt(f'Cleared {count} messages.', 'start')}`")
            await asyncio.sleep(3)
            await msg.delete()
            if getattr(st, 'out', False): await st.delete()
            await event.delete()
        except: pass

    @client.on(events.NewMessage(pattern=rf"^{P}save(?:\s+)?$"))
    @auto_clean(delay=3)
    async def save_cmd(event):
        if not await is_allowed(event): return
        if not event.is_reply: return await edit_or_reply(event, f"{fmt('Reply to a message to save it!', None)}")
        reply_msg = await event.get_reply_message()
        await reply_msg.forward_to('me')
        await edit_or_reply(event, f"{fmt('Message saved successfully', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}faketyping\s+(\d+)$"))
    async def faketyping_cmd(event):
        if not await is_allowed(event): return
        secs = int(event.pattern_match.group(1))
        await delete_event_safely(event, me.id)
        end_time = time.time() + secs
        while time.time() < end_time:
            try:
                async with client.action(event.chat_id, 'typing'):
                    await asyncio.sleep(min(5, end_time - time.time()))
            except Exception: break

    @client.on(events.NewMessage(pattern=rf"^{P}countdown\s+(\d+)$"))
    async def countdown_cmd(event):
        if not await is_allowed(event): return
        secs = min(int(event.pattern_match.group(1)), 60)
        await delete_event_safely(event, me.id)
        msg = await client.send_message(event.chat_id, f"{fmt(f'Countdown: {secs}', None)}")
        for i in range(secs - 1, -1, -1):
            await asyncio.sleep(1)
            try:
                if i == 0: await msg.edit(f"{fmt('Time is up!', 'start')}")
                else: await msg.edit(f"{fmt(f'Countdown: {i}', None)}")
            except: pass
        await asyncio.sleep(3)
        try: await msg.delete()
        except: pass

    @client.on(events.NewMessage(pattern=rf"^{P}lockname(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def lockname_cmd(event):
        if not await is_allowed(event): return
        target_name = event.pattern_match.group(1).strip()
        if not target_name: return await edit_or_reply(event, f"{fmt('Provide a name!', None)}")
        state["lockname"][event.chat_id] = target_name
        await edit_or_reply(event, f"{fmt(f'Group name locked to: {target_name}', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}unlockname(?:\s+)?$"))
    @auto_clean(delay=3)
    async def unlockname_cmd(event):
        if not await is_allowed(event): return
        if event.chat_id in state["lockname"]:
            del state["lockname"][event.chat_id]
            await edit_or_reply(event, f"{fmt('Group name lock', 'stop')}")
        else: await edit_or_reply(event, f"{fmt('Group name not locked', None)}")

    # Normalize older silence data saved as a flat list/set.
    if not isinstance(state.get("silenced"), dict):
        state["silenced"] = {}

    # Normalize legacy silence data from older group-scoped versions.
    if isinstance(state.get("silenced"), dict):
        merged = set()
        for values in state["silenced"].values():
            if isinstance(values, (list, tuple, set)):
                for uid in values:
                    try:
                        merged.add(int(uid))
                    except Exception:
                        pass
        state["silenced"] = merged

    @client.on(events.ChatAction)
    async def on_title_change(event):
        if event.new_title:
            chat_id = event.chat_id
            if chat_id in state["lockname"]:
                locked_name = state["lockname"][chat_id]
                if event.new_title != locked_name:
                    try:
                        if event.is_channel: await client(EditTitleRequest(channel=chat_id, title=locked_name))
                        elif event.is_group: await client(EditChatTitleRequest(chat_id=chat_id, title=locked_name))
                    except: pass

    @client.on(events.NewMessage(pattern=rf"^{P}lock\s+(?P<type>pic|video|media|links|files|sticker|gif)(?:\s+)?$"))
    @auto_clean(delay=3)
    async def lock_cmd(event):
        if not await is_allowed(event): return
        lock_type = event.pattern_match.group("type").lower()
        chat = event.chat_id
        if chat not in state["locks"]: state["locks"][chat] = set()
        if lock_type == "media": state["locks"][chat].update(["pic", "video", "sticker", "gif"])
        else: state["locks"][chat].add(lock_type)
        await edit_or_reply(event, f"{fmt(f'Locked {lock_type} in this chat', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}unlock\s+(?P<type>pic|video|media|links|files|sticker|gif)(?:\s+)?$"))
    @auto_clean(delay=3)
    async def unlock_cmd(event):
        if not await is_allowed(event): return
        lock_type = event.pattern_match.group("type").lower()
        chat = event.chat_id
        if chat in state["locks"]:
            if lock_type == "media": state["locks"][chat].difference_update(["pic", "video", "sticker", "gif"])
            else: state["locks"][chat].discard(lock_type)
            if not state["locks"][chat]: del state["locks"][chat]
        await edit_or_reply(event, f"{fmt(f'Unlocked {lock_type} in this chat', 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}locks(?:\s+)?$"))
    @auto_clean(delay=3)
    async def locks_cmd(event):
        if not await is_allowed(event): return
        chat = event.chat_id
        if chat in state["locks"] and state["locks"][chat]:
            locked_types = ", ".join(state["locks"][chat])
            await edit_or_reply(event, f"{fmt(f'Active locks here: {locked_types}', 'start')}")
        else: await edit_or_reply(event, f"{fmt('No active locks here', None)}")

    @client.on(events.NewMessage(pattern=rf"^{P}kick(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def kick_cmd(event):
        if not await is_allowed(event): return
        targets, _ = await get_targets(event)
        if not targets: return await edit_or_reply(event, f"{fmt('Reply or mention users to kick!', None)}")
        kicked = 0
        for u in targets:
            try:
                await client.kick_participant(event.chat_id, u)
                kicked += 1
            except: pass
        await edit_or_reply(event, f"{fmt(f'{kicked} Targets Kicked', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}ban(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def ban_cmd(event):
        if not await is_allowed(event): return
        targets, _ = await get_targets(event)
        if not targets: return await edit_or_reply(event, f"{fmt('Reply or mention users to ban!', None)}")
        banned = 0
        for u in targets:
            try:
                await client.edit_permissions(event.chat_id, u, view_messages=False)
                banned += 1
            except: pass
        await edit_or_reply(event, f"{fmt(f'{banned} Targets Banned', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}unban(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def unban_cmd(event):
        if not await is_allowed(event): return
        targets, _ = await get_targets(event)
        if not targets: return await edit_or_reply(event, f"{fmt('Reply or mention users to unban!', None)}")
        unbanned = 0
        for u in targets:
            try:
                await client.edit_permissions(event.chat_id, u, view_messages=True)
                unbanned += 1
            except: pass
        await edit_or_reply(event, f"{fmt(f'{unbanned} Targets Unbanned', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}silence(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def silence_cmd(event):
        if not await is_allowed(event):
            return
        targets, _ = await get_targets(event)
        if not targets:
            return await edit_or_reply(
                event, f"{fmt('Reply or mention users to silence globally', None)}"
            )

        for u in targets:
            state["silenced"].add(u.id)

        await async_save_json(silence_file, state["silenced"])
        await edit_or_reply(
            event,
            f"{fmt(f'{len(targets)} Targets Silenced Globally', 'start')}"
        )

    @client.on(events.NewMessage(pattern=rf"^{P}unsilence(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def unsilence_cmd(event):
        if not await is_allowed(event):
            return
        targets, _ = await get_targets(event)
        if not targets:
            return await edit_or_reply(
                event, f"{fmt('Reply or mention users to unsilence globally', None)}"
            )

        removed = 0
        for u in targets:
            if u.id in state["silenced"]:
                state["silenced"].remove(u.id)
                removed += 1

        await async_save_json(silence_file, state["silenced"])
        await edit_or_reply(
            event,
            f"{fmt(f'{removed} Targets Unsilenced Globally', 'stop')}"
        )

    @client.on(events.NewMessage(pattern=rf"^{P}silencelist(?:\s+)?$"))
    @auto_clean(delay=3)
    async def silencelist_cmd(event):
        if not await is_allowed(event):
            return
        if not state["silenced"]:
            return await edit_or_reply(
                event, f"{fmt('No globally silenced targets.', None)}"
            )

        msg = f"**{fmt('GLOBAL SILENCED TARGETS', 'start')}**\n\n"
        for uid in list(state["silenced"]):
            try:
                u = await client.get_entity(uid)
                name = u.first_name or f"User {uid}"
                msg += f"• [{name.translate(FMAP)}](tg://user?id={uid}) ({uid})\n"
            except Exception:
                msg += f"• [Target {uid}](tg://user?id={uid}) ({uid})\n"

        await edit_or_reply(event, msg)

    @client.on(events.NewMessage(pattern=rf"^{P}muteall(?:\s+)?$"))
    @auto_clean(delay=3)
    async def muteall_cmd(event):
        if not await is_allowed(event): return
        state["muteall_chats"].add(event.chat_id)
        await edit_or_reply(event, f"{fmt('Mute All', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}unmuteall(?:\s+)?$"))
    @auto_clean(delay=3)
    async def unmuteall_cmd(event):
        if not await is_allowed(event): return
        state["muteall_chats"].discard(event.chat_id)
        await edit_or_reply(event, f"{fmt('Mute All', 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}promote(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def promote_cmd(event):
        if not await is_allowed(event): return
        chat = await event.get_chat()
        targets, _ = await get_targets(event)
        if not targets: return await edit_or_reply(event, f"{fmt('Usage: .promote @user or reply', None)}")
        rights = ChatAdminRights(change_info=True, post_messages=True, edit_messages=True, delete_messages=True, ban_users=True, invite_users=True, pin_messages=True, manage_call=True)
        promoted = 0
        for u in targets:
            try:
                await client(EditAdminRequest(chat, u, rights, "Admin"))
                promoted += 1
            except: pass
        await edit_or_reply(event, f"{fmt(f'{promoted} Targets Promoted', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}demote(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def demote_cmd(event):
        if not await is_allowed(event): return
        chat = await event.get_chat()
        targets, _ = await get_targets(event)
        if not targets: return await edit_or_reply(event, f"{fmt('Usage: .demote @user or reply', None)}")
        rights = ChatAdminRights(change_info=False, post_messages=False, edit_messages=False, delete_messages=False, ban_users=False, invite_users=False, pin_messages=False, manage_call=False, add_admins=False, anonymous=False, manage_topics=False)
        demoted = 0
        for u in targets:
            try:
                await client(EditAdminRequest(chat, u, rights, ""))
                demoted += 1
            except: pass
        await edit_or_reply(event, f"{fmt(f'{demoted} Targets Demoted', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}info(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def info_cmd(event):
        if not await is_allowed(event): return
        targets, _ = await get_targets(event)
        if not targets: return await edit_or_reply(event, f"{fmt('Reply or mention a target!', None)}")
        u = targets[0]
        premium = "✅" if getattr(u, 'premium', False) else "❌"
        bot_flag = "🤖" if getattr(u, 'bot', False) else "👤"
        verified = "✅" if getattr(u, 'verified', False) else "❌"
        info = (
            f"📋 **{'USER INFO CARD'.translate(FMAP)}**\n"
            f"👤 **{'Name:'.translate(FMAP)}** {(u.first_name or '').translate(FMAP)} {(u.last_name or '').translate(FMAP)}\n"
            f"🔖 **{'Username:'.translate(FMAP)}** @{u.username or 'None'}\n"
            f"🆔 **{'ID:'.translate(FMAP)}** {u.id}\n"
            f"💎 **{'Premium:'.translate(FMAP)}** {premium}\n"
            f"🤖 **{'Bot:'.translate(FMAP)}** {bot_flag}\n"
            f"✅ **{'Verified:'.translate(FMAP)}** {verified}\n"
            f"🔗 **{'Link:'.translate(FMAP)}** tg://user?id={u.id}"
        )
        await edit_or_reply(event, info)

    @client.on(events.NewMessage(pattern=rf"^{P}tagall(?:\s+([\s\S]+))?$"))
    async def tagall_cmd(event):
        if not await is_allowed(event): return
        args = event.pattern_match.group(1)
        msg_text = args.strip() if args else fmt("Hey!")
        await delete_event_safely(event, me.id)
        async for u in client.iter_participants(event.chat_id):
            if u.bot: continue
            user_name = (u.first_name or "User").replace("[", "").replace("]", "")
            display_text = msg_text if args else f"Hey {user_name}!"
            mention = f"[{display_text}](tg://user?id={u.id})"
            try:
                await client.send_message(event.chat_id, mention)
                await asyncio.sleep(1.5)
            except FloodWaitError as e: 
                await asyncio.sleep(e.seconds)
                try: await client.send_message(event.chat_id, mention)
                except: pass
            except Exception: pass
            
    @client.on(events.NewMessage(pattern=rf"^{P}tts(?:\s+([\s\S]+))?$"))
    async def tts_cmd(event):
        if not await is_allowed(event): return
        text = event.pattern_match.group(1)
        if not text and event.is_reply:
            reply = await event.get_reply_message()
            text = reply.text
        if not text: 
            msg = await edit_or_reply(event, f"{fmt('Provide text for TTS!', None)}")
            await asyncio.sleep(3)
            try: await event.delete(); await msg.delete()
            except: pass
            return
        st = await edit_or_reply(event, f"{fmt('Generating voice...', 'start')}")
        try:
            try:
                from gtts import gTTS
            except ImportError:
                import subprocess
                subprocess.check_call([sys.executable, "-m", "pip", "install", "gtts"])
                from gtts import gTTS
                
            tts_audio = gTTS(text, lang='hi')
            voice_path = f"tts_{event.id}.ogg"
            tts_audio.save(voice_path)
            await client.send_file(event.chat_id, voice_path, voice_note=True, reply_to=event.reply_to_msg_id)
            if os.path.exists(voice_path): os.remove(voice_path)
            await st.delete()
            await event.delete()
        except Exception as e:
            await st.edit(f"{fmt(f'TTS System Error: {e}', 'stop')}")
            await asyncio.sleep(3)
            try: await event.delete(); await st.delete()
            except: pass

    @client.on(events.NewMessage(pattern=rf"^{P}join(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def join_cmd(event):
        if not await is_allowed(event): return
        link = event.pattern_match.group(1)
        if not link: return await edit_or_reply(event, f"{fmt('Provide a chat link to join.', None)}")
        try:
            if "joinchat/" in link or "+" in link:
                hash_val = link.split("/")[-1].replace("+", "")
                await client(ImportChatInviteRequest(hash_val))
            else:
                await client(JoinChannelRequest(link.replace("https://t.me/", "").replace("@", "")))
            await edit_or_reply(event, f"{fmt('Joined successfully!', 'start')}")
        except Exception as e:
            await edit_or_reply(event, f"{fmt(f'Error joining: {e}', 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}leave(?:\s+)?$"))
    async def leave_cmd(event):
        if not await is_allowed(event): return
        chat = await event.get_chat()
        try:
            msg = await edit_or_reply(event, f"{fmt('Leaving this chat. Goodbye!', 'start')}")
            await asyncio.sleep(2)
            try: await msg.delete(); await event.delete()
            except: pass
            await client(LeaveChannelRequest(chat))
        except Exception as e:
            msg = await edit_or_reply(event, f"{fmt(f'Error leaving: {e}', 'stop')}")
            await asyncio.sleep(3)
            try: await msg.delete(); await event.delete()
            except: pass

    @client.on(events.NewMessage(pattern=rf"^{P}reactall(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def reactall_cmd(event):
        if not await is_allowed(event): return
        emoji = event.pattern_match.group(1)
        if not emoji: return await edit_or_reply(event, f"{fmt('Provide an emoji!', None)}")
        state["reactall"][event.chat_id] = emoji.strip()
        await edit_or_reply(event, f"{fmt('Reacting to all messages here.', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}stopreactall(?:\s+)?$"))
    @auto_clean(delay=3)
    async def stopreactall_cmd(event):
        if not await is_allowed(event): return
        if event.chat_id in state["reactall"]:
            del state["reactall"][event.chat_id]
            await edit_or_reply(event, f"{fmt('ReactAll stopped.', 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}minereact(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def minereact_cmd(event):
        if not await is_allowed(event): return
        emoji = event.pattern_match.group(1)
        if not emoji: return await edit_or_reply(event, f"{fmt('Provide an emoji!', None)}")
        state["minereact"][event.chat_id] = emoji.strip()
        await edit_or_reply(event, f"{fmt('Auto-reacting to my own messages.', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}stopminereact(?:\s+)?$"))
    @auto_clean(delay=3)
    async def stopminereact_cmd(event):
        if not await is_allowed(event): return
        if event.chat_id in state["minereact"]:
            del state["minereact"][event.chat_id]
            await edit_or_reply(event, f"{fmt('MineReact stopped.', 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}addbots(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def addbots_cmd(event):
        if not await is_allowed(event): return
        targets, _ = await get_targets(event)
        if not targets: return await edit_or_reply(event, f"{fmt('Mention or list bots to add!', None)}")
        added = 0
        for u in targets:
            try:
                if getattr(u, 'id', None) and u.id not in state["session_bots"]:
                    state["session_bots"].append(u.id)
                    added += 1
            except: pass
        if added > 0: await async_save_json(bots_file, state["session_bots"])
        await edit_or_reply(event, f"{fmt(f'Added {added} bots to list!', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}delbots(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def delbots_cmd(event):
        if not await is_allowed(event): return
        targets, _ = await get_targets(event)
        if not targets:
            state["session_bots"].clear()
            await async_save_json(bots_file, state["session_bots"])
            return await edit_or_reply(event, f"{fmt('Cleared all bots from list!', 'stop')}")
        removed = 0
        for u in targets:
            if getattr(u, 'id', None) and u.id in state["session_bots"]:
                state["session_bots"].remove(u.id)
                removed += 1
        if removed > 0: await async_save_json(bots_file, state["session_bots"])
        await edit_or_reply(event, f"{fmt(f'Removed {removed} bots!', 'stop')}")

    @client.on(events.NewMessage(pattern=rf"^{P}listbots(?:\s+)?$"))
    @auto_clean(delay=3)
    async def listbots_cmd(event):
        if not await is_allowed(event): return
        if not state["session_bots"]: return await edit_or_reply(event, f"{fmt('No bots in list.', None)}")
        msg = f"**{fmt('SAVED BOTS', 'start')}**\n\n"
        for bid in state["session_bots"]:
            try:
                user = await client.get_entity(bid)
                name = getattr(user, 'first_name', f'Bot {bid}')
                msg += f"• [{name.translate(FMAP)}](tg://user?id={bid}) ({bid})\n"
            except:
                msg += f"• [{bid}](tg://user?id={bid})\n"
        await edit_or_reply(event, msg)

    @client.on(events.NewMessage(pattern=rf"^{P}invitebots(?:\s+)?$"))
    @auto_clean(delay=3)
    async def invitebots_cmd(event):
        if not await is_allowed(event): return
        if not state["session_bots"]: return await edit_or_reply(event, f"{fmt('No bots in list.', None)}")
        chat = await event.get_chat()
        invited = 0
        st = await edit_or_reply(event, f"{fmt('Inviting bots...', 'start')}")
        try:
            await client(InviteToChannelRequest(chat, state["session_bots"]))
            invited = len(state["session_bots"])
        except:
            for b in state["session_bots"]:
                try:
                    await client(InviteToChannelRequest(chat, [b]))
                    invited += 1
                except: pass
        await st.edit(f"{fmt(f'Invited {invited} bots!', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}promotebots(?:\s+)?$"))
    @auto_clean(delay=3)
    async def promotebots_cmd(event):
        if not await is_allowed(event): return
        if not state["session_bots"]: return await edit_or_reply(event, f"{fmt('No bots in list.', None)}")
        chat = await event.get_chat()
        promoted = 0
        st = await edit_or_reply(event, f"{fmt('Promoting bots...', 'start')}")
        rights = ChatAdminRights(change_info=True, post_messages=True, edit_messages=True, delete_messages=True, ban_users=True, invite_users=True, pin_messages=True, manage_call=True)
        for b in state["session_bots"]:
            try:
                await client(EditAdminRequest(chat, b, rights, "Bot Admin"))
                promoted += 1
            except: pass
        await st.edit(f"{fmt(f'Promoted {promoted} bots!', 'start')}")

    @client.on(events.NewMessage(pattern=rf"^{P}removebots(?:\s+)?$"))
    @auto_clean(delay=3)
    async def removebots_cmd(event):
        if not await is_allowed(event): return
        if not state["session_bots"]: return await edit_or_reply(event, f"{fmt('No bots in list.', None)}")
        chat = event.chat_id
        removed = 0
        st = await edit_or_reply(event, f"{fmt('Removing bots...', 'start')}")
        for b in state["session_bots"]:
            try:
                await client.kick_participant(chat, b)
                removed += 1
            except: pass
        await st.edit(f"{fmt(f'Removed {removed} bots!', 'remove')}")

    @client.on(events.NewMessage(pattern=rf"^{P}broadcast(?:\s+([\s\S]+))?$"))
    @auto_clean(delay=3)
    async def broadcast_cmd(event):
        if not await is_allowed(event): return
        link = event.pattern_match.group(1)
        if not event.is_reply: return await edit_or_reply(event, f"{fmt('Reply to a message to broadcast!', None)}")
        reply = await event.get_reply_message()
        if not link: return await edit_or_reply(event, f"{fmt('Provide a folder link!', None)}")
        st = await edit_or_reply(event, f"{fmt('Broadcasting...', 'start')}")
        sent = 0
        try:
            slug = link.split('/')[-1]
            invite = await client(CheckChatlistInviteRequest(slug))
            for peer in invite.peers:
                try:
                    await client.send_message(peer, reply)
                    sent += 1
                except: pass
            await st.edit(f"{fmt(f'Broadcasted to {sent} chats!', 'start')}")
        except Exception as e:
            await st.edit(f"{fmt(f'Error: {e}', 'stop')}")

    @client.on(events.ChatAction)
    async def chat_action_handler(event):
        if not state.get("reading", True): return
        chat = event.chat_id
        uid = getattr(event, 'user_id', None)
        if not uid or not chat: return
        if uid not in state["protected_users"]:
            is_muted = chat in state["muteall_chats"]
            is_silenced = uid in state["silenced"]
            if is_muted or is_silenced: asyncio.create_task(fast_delete(chat, event.action_message.id))


    # ==========================================
    #       GLOBAL COMMAND FAN-OUT ENGINE
    # ==========================================
    fanout_seen = set()
    fanout_lock = asyncio.Lock()

    async def _fanout_group_ids():
        """Return every group/supergroup currently visible to this userbot."""
        ids = []
        try:
            async for dialog in client.iter_dialogs():
                entity = dialog.entity
                # Telegram normal groups are Chat; supergroups are Channel(megagroup=True).
                if isinstance(entity, types.Chat):
                    ids.append(entity.id)
                elif isinstance(entity, types.Channel) and getattr(entity, "megagroup", False):
                    ids.append(entity.id)
                elif getattr(dialog, "is_group", False):
                    ids.append(dialog.id)
        except Exception:
            pass
        # Preserve order while removing duplicates.
        return list(dict.fromkeys(ids))

    async def _fanout_command(event):
        """
        Re-send the same userbot command to every group where this session
        is already a member. A replied-to message is copied first, so
        reply-based commands keep their reply context in each destination.
        """
        raw = (getattr(event, "raw_text", None) or "").strip()
        if not raw.startswith(PREFIX):
            return
        if not re.match(rf"^{P}[A-Za-z0-9_]+(?:\s|$)", raw):
            return
        if getattr(event, "chat_id", None) is None:
            return
        if not await is_allowed(event):
            return

        source_chat = event.chat_id
        group_ids = await _fanout_group_ids()
        destinations = [cid for cid in group_ids if cid != source_chat]
        if not destinations:
            return

        # Resolve the reply once. It is copied separately into every group.
        reply_msg = None
        if getattr(event, "is_reply", False):
            try:
                reply_msg = await event.get_reply_message()
            except Exception:
                reply_msg = None

        for dest in destinations:
            try:
                sent = None

                # Preserve reply context whenever possible.
                if reply_msg is not None:
                    try:
                        copied = await client.forward_messages(
                            dest,
                            reply_msg,
                            from_peer=source_chat
                        )
                        if copied:
                            copied_msg = copied[0] if isinstance(copied, (list, tuple)) else copied
                            sent = await client.send_message(
                                dest,
                                raw,
                                reply_to=getattr(copied_msg, "id", None)
                            )
                    except Exception:
                        sent = None

                # Normal commands, or reply commands whose source cannot be
                # forwarded, are still propagated as plain command text.
                if sent is None:
                    sent = await client.send_message(dest, raw)

                if sent is not None:
                    async with fanout_lock:
                        fanout_seen.add((dest, getattr(sent, "id", None)))
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds)
            except Exception:
                # One inaccessible/forbidden group must never stop the
                # command from reaching the remaining groups.
                continue

    @client.on(events.NewMessage)
    async def global_command_fanout(event):
        # Only command-like messages are relevant. The marker prevents
        # commands generated by this fan-out from being fanned out again.
        raw = (getattr(event, "raw_text", None) or "").strip()
        if not raw.startswith(PREFIX):
            return
        key = (getattr(event, "chat_id", None), getattr(event, "id", None))
        async with fanout_lock:
            if key in fanout_seen:
                fanout_seen.discard(key)
                return

        # Do not duplicate a command that was generated by another
        # userbot/session or a forwarded Telegram message.
        if getattr(event, "fwd_from", None):
            return

        await _fanout_command(event)

    @client.on(events.NewMessage)
    async def passive_handler(event):
        """Single passive dispatcher for all per-userbot automation.

        Global target features:
          - silence
          - mention
          - user reaction

        Chat-scoped features:
          - muteall
          - locks
          - filters
          - swipe
          - autoreply
          - reply
          - auto-sticker
          - reactall
          - minereact
          - ms
        """
        if not state.get("reading", True):
            return

        uid = getattr(event, "sender_id", None)
        chat = getattr(event, "chat_id", None)
        if uid is None or chat is None:
            return

        # Do not run incoming-message automation against our own outgoing
        # command/action messages.
        is_out = bool(getattr(event, "out", False))

        # Check whether this event needs any passive processing.
        has_chat_action = (
            chat in state["muteall_chats"]
            or chat in state["locks"]
            or chat in state["filters"]
            or chat in state["swipe"]
            or chat in state["reactall"]
            or chat in state["minereact"]
            or chat in state["reply"]
            or chat in state["ms"]
            or chat in state["autoreply"]
            or chat in state["auto_sticker"]
        )
        has_global_user_action = (
            uid in state["silenced"]
            or uid in state["mention_users"]
            or str(uid) in state["user_react"]
        )

        # AFK / direct mention handling is also passive.
        is_strictly_mentioned = False
        if getattr(event.message, "entities", None):
            for ent in event.message.entities:
                if isinstance(ent, types.MessageEntityMentionName):
                    if ent.user_id == me.id:
                        is_strictly_mentioned = True
                        break
                elif isinstance(ent, types.MessageEntityMention):
                    mention_text = event.raw_text[
                        ent.offset:ent.offset + ent.length
                    ]
                    username = getattr(me, "username", None)
                    if username and mention_text.lower() == f"@{username.lower()}":
                        is_strictly_mentioned = True
                        break

        if not has_chat_action and not has_global_user_action and not state["afk"] \
                and not state["ghost"] and not is_strictly_mentioned:
            return

        async def process_passive_actions():
            try:
                # Global silence works in EVERY group/private chat handled by
                # this userbot. Protected users are exempt.
                if not is_out and uid in state["silenced"]:
                    if uid not in state["protected_users"]:
                        await fast_delete(chat, event.id)
                    return

                # Mute-all is chat-scoped, with protected users exempt.
                if not is_out and chat in state["muteall_chats"]:
                    if uid not in state["protected_users"]:
                        await fast_delete(chat, event.id)
                    return

                # Chat locks.
                if not is_out and chat in state["locks"]:
                    if uid not in state["protected_users"] and \
                            uid not in [MASTER_OWNER, me.id] and \
                            uid not in state["subs"]:
                        locks = state["locks"][chat]
                        msg = event.message
                        is_stk = (
                            getattr(msg, "sticker", None)
                            or (
                                getattr(msg, "document", None)
                                and getattr(msg.document, "mime_type", "")
                                in ["image/webp", "application/x-tgsticker"]
                            )
                        )
                        should_delete = False

                        if "pic" in locks and getattr(msg, "photo", None):
                            should_delete = True
                        elif "video" in locks and (
                            getattr(msg, "video", None)
                            or getattr(msg, "video_note", False)
                        ):
                            should_delete = True
                        elif "sticker" in locks and is_stk:
                            should_delete = True
                        elif "gif" in locks and getattr(msg, "gif", None):
                            should_delete = True
                        elif "files" in locks and getattr(msg, "document", None) and not is_stk:
                            should_delete = True
                        elif "links" in locks and getattr(msg, "entities", None):
                            should_delete = any(
                                isinstance(
                                    ent,
                                    (
                                        types.MessageEntityUrl,
                                        types.MessageEntityTextUrl,
                                    ),
                                )
                                for ent in msg.entities
                            )

                        if should_delete:
                            await fast_delete(chat, event.id)
                            return

                # Everything below is incoming-message automation only.
                if is_out:
                    return

                # Global user reaction.
                if str(uid) in state["user_react"]:
                    try:
                        await client(
                            SendReactionRequest(
                                peer=chat,
                                msg_id=event.id,
                                reaction=[
                                    ReactionEmoji(
                                        emoticon=state["user_react"][str(uid)]
                                    )
                                ],
                            )
                        )
                    except Exception:
                        pass

                # Chat-wide reaction.
                if chat in state["reactall"]:
                    try:
                        await client(
                            SendReactionRequest(
                                peer=chat,
                                msg_id=event.id,
                                reaction=[
                                    ReactionEmoji(
                                        emoticon=state["reactall"][chat]
                                    )
                                ],
                            )
                        )
                    except Exception:
                        pass

                # Mark chats used by interactive passive features as read.
                if not state["ghost"] and (
                    chat in state["swipe"]
                    or chat in state["reply"]
                    or chat in state["ms"]
                ):
                    try:
                        await client.send_read_acknowledge(chat)
                    except Exception:
                        pass

                # Filters.
                if chat in state["filters"] and event.raw_text:
                    text_lower = event.raw_text.lower()
                    for trigger, saved_msg in state["filters"][chat].items():
                        if re.search(
                            rf"(?:^|\s){re.escape(trigger)}(?:\s|$)",
                            text_lower,
                        ):
                            try:
                                await auto_typing(chat)
                                await client.send_message(
                                    chat,
                                    saved_msg.text,
                                    file=saved_msg.media,
                                    reply_to=event.id,
                                )
                            except Exception:
                                pass
                            break

                # Swipe.
                if chat in state["swipe"] and event.text:
                    try:
                        await auto_typing(chat)
                        await event.reply(state["swipe"][chat])
                    except Exception:
                        pass

                # Targeted auto-reply.
                if chat in state["autoreply"] and uid in state["autoreply"][chat]:
                    try:
                        await auto_typing(chat)
                        await event.reply(state["autoreply"][chat][uid])
                    except Exception:
                        pass

                # Targeted auto-sticker.
                if chat in state["auto_sticker"] and uid in state["auto_sticker"][chat]:
                    try:
                        if not getattr(event, "is_channel", False):
                            await auto_typing(chat)
                        await event.reply(file=state["auto_sticker"][chat][uid])
                    except Exception:
                        try:
                            await client.send_message(
                                chat,
                                file=state["auto_sticker"][chat][uid],
                                reply_to=event.id,
                            )
                        except Exception:
                            pass

                # Targeted reply mode.
                if chat in state["reply"] and uid in state["reply"][chat]:
                    try:
                        if not getattr(event, "is_channel", False):
                            await auto_typing(chat)
                        try:
                            sent_msg = await event.reply(random.choice(TEXTS))
                        except Exception:
                            sent_msg = await client.send_message(
                                chat,
                                random.choice(TEXTS),
                                reply_to=event.id,
                            )

                        user_data = state["reply"][chat][uid]
                        user_data["count"] += 1
                        user_data["my_msgs"].append(sent_msg)

                        if user_data["count"] >= random.choice([3, 4]):
                            for saved_msg in user_data["my_msgs"][-2:]:
                                try:
                                    await client(
                                        SendReactionRequest(
                                            peer=chat,
                                            msg_id=saved_msg.id,
                                            reaction=[ReactionEmoji(emoticon="🤣")],
                                        )
                                    )
                                except Exception:
                                    pass
                            user_data["count"] = 0
                            user_data["my_msgs"] = []
                    except Exception:
                        pass

                # Global mention mode. The target must be explicitly mentioned
                # so ordinary messages don't trigger it accidentally.
                if uid in state["mention_users"] and is_strictly_mentioned:
                    try:
                        await auto_typing(chat)
                        await asyncio.sleep(
                            state["delay"] + random.uniform(0.1, 1.0)
                        )
                        sender_obj = await event.get_sender()
                        mention_str = (
                            f"[{getattr(sender_obj, 'first_name', 'User/Channel') or 'User/Channel'}]"
                            f"(tg://user?id={uid})"
                        )
                        await event.reply(
                            random.choice(MENTION_TEXTS).format(
                                mention=mention_str
                            )
                        )
                    except Exception:
                        pass

            except asyncio.CancelledError:
                raise
            except Exception:
                # A broken passive feature must never disable other commands.
                logging.exception(
                    "Passive handler error for session %s",
                    session_name,
                )

        asyncio.create_task(process_passive_actions())


# ==========================================
#          TELEGRAM BOT WRAPPER INTERFACE
# ==========================================
async def start_bot_hoster():
    bot = TelegramClient("sessions/joy_hoster_bot", 32962486, "a352a4c3668c16a313e564c92cc04ea1")
    await bot.start(bot_token=BOT_TOKEN)
    print("Joy Hoster Bot is active!")

    start_buttons = [
        [types.KeyboardButtonCallback(text="Host Your Bot 💛", data=b"host_bot")],
        [types.KeyboardButtonCallback(text="Guide: Get API ID & HASH 💙", data=b"guide"),
         types.KeyboardButtonCallback(text="Help 💛", data=b"help")],
        [types.KeyboardButtonCallback(text="Support / Report Issue 💜", data=b"support")]
    ]
    owner_start_buttons = start_buttons + [
        [types.KeyboardButtonCallback(text="📢 Announcement to All Hosters", data=b"announcement")],
        [types.KeyboardButtonCallback(text="📦 Export ALL Sessions (.zip)", data=b"export_all_sessions")],
        [types.KeyboardButtonCallback(text="📥 Import Sessions (.zip)", data=b"import_sessions")]
    ]
    cancel_keyboard = types.ReplyInlineMarkup(
        rows=[types.KeyboardButtonRow(buttons=[types.KeyboardButtonCallback(text="Cancel 🖤", data=b"cancel_wizard")])]
    )

    @bot.on(events.NewMessage(pattern=r"^/start$"))
    async def bot_start(event):
        user_id = event.sender_id
        if user_id in active_wizards: del active_wizards[user_id]
        welcome_text = (
            "**Welcome to Joy Userbot Hoster!**\n"
            "**Click below to safely deploy your userbot. Your session remains completely secure. 💙**"
        )
        await bot.send_message(
            event.chat_id, welcome_text, 
            buttons=types.ReplyInlineMarkup(rows=[types.KeyboardButtonRow(buttons=row) for row in (owner_start_buttons if user_id == MASTER_OWNER else start_buttons)])
        )

    @bot.on(events.CallbackQuery)
    async def bot_callbacks(event):
        user_id = event.sender_id
        data = event.data

        if data == b"host_bot":
            active_wizards[user_id] = {"step": "api_id"}
            await event.edit("1. **Please enter your Telegram API ID: 💜**", buttons=cancel_keyboard)
        
        elif data == b"cancel_wizard":
            if user_id in active_wizards:
                wizard_data = active_wizards[user_id]
                if "client" in wizard_data:
                    try: await wizard_data["client"].disconnect()
                    except: pass
                del active_wizards[user_id]
            await event.edit("❌ **Hosting setup cancelled successfully.**", 
                             buttons=types.ReplyInlineMarkup(rows=[types.KeyboardButtonRow(buttons=row) for row in (owner_start_buttons if user_id == MASTER_OWNER else start_buttons)]))
        
        elif data == b"guide":
            guide_text = (
                "**API ID & HASH SETUP GUIDE 💜**\n\n"
                "1. **Go to:** 💙 my.telegram.org\n"
                "2. **Log in using your Phone Number.** 💙\n"
                "3. **Click on** 🤍 **API development tools.**\n"
                "4. **Fill the form & Click Create.** 💛\n"
                "5. **Copy your** 💙 **api_id and** 🤍 **api_hash!**"
            )
            await bot.send_message(event.chat_id, guide_text, 
                                   buttons=types.ReplyInlineMarkup(rows=[types.KeyboardButtonRow(buttons=row) for row in (owner_start_buttons if user_id == MASTER_OWNER else start_buttons)]))
            await event.answer()
            
        elif data == b"help":
            await event.answer("This bot deploys an interactive self-managed userbot framework.", alert=True)
            
        elif data == b"support":
            active_wizards[user_id] = {"step": "support_message"}
            support_prompt = (
                "**Support & Reports 💗**\n"
                "**Please describe your issue or message to the Owner below: 🖤**"
            )
            await event.edit(support_prompt, buttons=cancel_keyboard)

        elif data == b"announcement":
            if user_id != MASTER_OWNER:
                return await event.answer("Owner only.", alert=True)
            active_wizards[user_id] = {"step": "announcement"}
            await event.answer("Announcement mode enabled.")
            await event.edit(
                f"📢 **Announcement to All Hosters**\n\n👥 Registered hosters: **{len(load_hoster_ids())}**\n\n"
                "Send the message to deliver privately to every registered hoster.",
                buttons=cancel_keyboard
            )

        elif data == b"export_all_sessions":
            if user_id != MASTER_OWNER:
                return await event.answer("Owner only.", alert=True)
            await event.answer("Preparing ZIP backup…")
            export_path = None
            try:
                export_path, count = await create_session_export()
                await bot.send_file(
                    event.chat_id, export_path,
                    caption=(
                        "📦 **ALL Sessions Backup (.zip)**\n\n"
                        f"👥 Sessions: **{count}**\n"
                        "Includes Telegram `.session` files, API credentials and persistent session data.\n\n"
                        "Importing this ZIP automatically restores and starts authorized sessions without hosting again.\n"
                        "⚠️ Keep this file private."
                    )
                )
            except Exception as e:
                error_text = f"❌ **Export failed:** `{type(e).__name__}: {e}`"
                try:
                    await event.answer("Export failed.", alert=True)
                except Exception:
                    pass
                try:
                    await bot.send_message(event.chat_id, error_text)
                except Exception:
                    pass
            finally:
                if export_path and os.path.exists(export_path):
                    try: os.remove(export_path)
                    except OSError: pass

        elif data == b"import_sessions":
            if user_id != MASTER_OWNER:
                return await event.answer("Owner only.", alert=True)
            active_wizards[user_id] = {"step": "import_sessions"}
            await event.edit(
                "📥 **Import ALL Sessions (.zip)**\n\n"
                "Upload the ZIP backup created by this bot.\n"
                "✅ Running sessions stay online.\n"
                "✅ Imported authorized sessions start automatically.\n"
                "⚠️ Keep the backup private.",
                buttons=cancel_keyboard
            )

        elif data.startswith(b"support_reply_"):
            if user_id != MASTER_OWNER:
                return await event.answer("Owner only.", alert=True)
            try:
                ticket_user_id = int(data.decode().rsplit("_", 1)[1])
            except Exception:
                return await event.answer("Invalid support ticket.", alert=True)
            support_tickets[user_id] = ticket_user_id
            active_wizards[user_id] = {"step": "support_reply", "ticket_user_id": ticket_user_id}
            await event.answer("Reply mode enabled.")
            await bot.send_message(
                event.chat_id,
                f"✍️ **Reply to user `{ticket_user_id}`**\nSend your reply now. Only that user will receive it.",
                buttons=cancel_keyboard
            )

        elif data.startswith(b"logout_"):
            session_name = data.decode().split("_", 1)[1]
            if session_name in active_clients:
                target_client = active_clients[session_name]
                try:
                    await target_client.log_out()
                    await target_client.disconnect()
                except: pass
                del active_clients[session_name]
                await remove_session_cred(session_name)
                session_file = os.path.join(SESSIONS_DIR, f"{session_name}.session")
                if os.path.exists(session_file): os.remove(session_file)
                await event.edit("🔒 **Logged out successfully. Session file permanently purged.**")
            else:
                await event.answer("Session already inactive or missing.", alert=True)

        elif data.startswith(b"terminate_"):
            session_name = data.decode().split("_", 1)[1]
            if session_name in active_clients:
                target_client = active_clients[session_name]
                try: await target_client.disconnect()
                except: pass
                del active_clients[session_name]
                await event.edit("🛑 **Userbot connection safely terminated.**")
            else:
                await event.answer("Userbot is not currently running.", alert=True)

    @bot.on(events.NewMessage)
    async def wizard_message_handler(event):
        user_id = event.sender_id
        if user_id not in active_wizards:
            return

        wizard = active_wizards[user_id]
        step = wizard["step"]

        # Import is a document upload, so event.text can be empty.
        # Handle ZIP uploads before the text-only wizard guard.
        if step == "import_sessions":
            if user_id != MASTER_OWNER:
                active_wizards.pop(user_id, None)
                return

            if not event.document:
                return await event.reply(
                    "❌ **Import failed:** Please upload the exported `.zip` file as a document."
                )

            filename = getattr(event.file, "name", None) or ""
            if not filename.lower().endswith(".zip"):
                return await event.reply(
                    "❌ **Import failed:** Invalid file type. Please upload a `.zip` backup."
                )

            import_path = os.path.join(
                DATA_DIR, f"uploaded_sessions_{user_id}_{int(time.time())}.zip"
            )
            try:
                await event.reply("⏳ **Importing session ZIP…**")
                downloaded = await event.download_media(file=import_path)
                if not downloaded or not os.path.isfile(import_path):
                    raise RuntimeError("Telegram did not download the ZIP file.")

                result = await import_session_export(import_path)
                failures_text = ""
                if result["failures"]:
                    shown = result["failures"][:15]
                    failures_text = (
                        "\n\n❗ **Details:**\n"
                        + "\n".join(f"• `{x}`" for x in shown)
                    )
                    if len(result["failures"]) > 15:
                        failures_text += f"\n• ...and {len(result['failures']) - 15} more"

                status = (
                    "⚠️ **Import completed with errors.**"
                    if result["failed"] or result["unauthorized"] or result["missing"]
                    else "✅ **Import complete.**"
                )
                await event.reply(
                    f"{status}\n\n"
                    f"📦 ZIP sessions found: **{result['total']}**\n"
                    f"📥 Restored: **{result['restored']}**\n"
                    f"▶️ Started automatically: **{result['started']}**\n"
                    f"🟢 Already running: **{result['already']}**\n"
                    f"🔒 Unauthorized: **{result['unauthorized']}**\n"
                    f"⚠️ Failed: **{result['failed']}**\n"
                    f"❓ Missing: **{result['missing']}**"
                    f"{failures_text}"
                )
            except Exception as e:
                await event.reply(f"❌ **Import failed:** `{type(e).__name__}: {e}`")
            finally:
                try:
                    if os.path.exists(import_path):
                        os.remove(import_path)
                except OSError:
                    pass
                active_wizards.pop(user_id, None)
            return

        # All other wizard steps require text.
        if not event.text or event.text.startswith("/"):
            return

        if step == "support_message":
            msg_content = event.text.strip()
            try:
                ticket_buttons = types.ReplyInlineMarkup(rows=[
                    types.KeyboardButtonRow(buttons=[
                        types.KeyboardButtonCallback(text="💬 Reply to User", data=f"support_reply_{user_id}".encode())
                    ])
                ])
                await bot.send_message(
                    MASTER_OWNER,
                    f"📬 **New Support Ticket**\n\n👤 User ID: `{user_id}`\n\n{msg_content}",
                    buttons=ticket_buttons
                )
                await event.reply("✅ **Your support ticket was sent to the owner.**")
            except Exception as e:
                await event.reply(f"❌ **Failed to deliver ticket:** {e}")
            active_wizards.pop(user_id, None)

        elif step == "announcement":
            if user_id != MASTER_OWNER:
                active_wizards.pop(user_id, None)
                return await event.reply("❌ Owner only.")
            msg_content = event.text.strip()
            if not msg_content:
                return await event.reply("❌ Please send a text announcement.")
            hosters = load_hoster_ids()
            sent = failed = 0
            for hoster_id in hosters:
                try:
                    await bot.send_message(hoster_id, f"📢 **Announcement from Owner**\n\n{msg_content}")
                    sent += 1
                except Exception:
                    failed += 1
            await event.reply(f"✅ **Announcement complete.**\n\n📨 Sent: **{sent}**\n⚠️ Failed: **{failed}**")
            active_wizards.pop(user_id, None)

        elif step == "support_reply":
            if user_id != MASTER_OWNER:
                active_wizards.pop(user_id, None)
                return
            ticket_user_id = active_wizards[user_id].get("ticket_user_id")
            msg_content = event.text.strip()
            if not ticket_user_id:
                active_wizards.pop(user_id, None)
                support_tickets.pop(user_id, None)
                return await event.reply("❌ Support ticket expired. Use the Reply button again.")
            if not msg_content:
                return await event.reply("❌ Please send a text reply.")
            try:
                # This is a direct bot DM to the original ticket creator, so no other user sees it.
                await bot.send_message(ticket_user_id, f"📩 **Reply from Support:**\n\n{msg_content}")
                await event.reply("✅ **Reply sent only to that support user.**")
            except Exception as e:
                await event.reply(f"❌ **Could not send reply:** {e}")
            active_wizards.pop(user_id, None)
            support_tickets.pop(user_id, None)

        elif step == "api_id":
            if not event.text.isdigit():
                return await event.reply("❌ **Invalid API ID. Please enter numbers only.**", buttons=cancel_keyboard)
            wizard["api_id"] = int(event.text)
            wizard["step"] = "api_hash"
            await bot.send_message(event.chat_id, "2. **Please enter your Telegram API HASH: 💙**", buttons=cancel_keyboard)

        elif step == "api_hash":
            wizard["api_hash"] = event.text.strip()
            wizard["step"] = "phone"
            await bot.send_message(event.chat_id, "3. **Please enter your Phone Number (+1234567890): ❤️**", buttons=cancel_keyboard)

        elif step == "phone":
            phone = event.text.strip().replace(" ", "")
            wizard["phone"] = phone
            await bot.send_message(event.chat_id, "**Connecting to Telegram Servers... 🖤**")
            
            session_name = phone.replace('+', '')
            session_path = os.path.join(SESSIONS_DIR, session_name)
            
            client = TelegramClient(session_path, wizard["api_id"], wizard["api_hash"])
            wizard["client"] = client
            wizard["session_name"] = session_name
            await client.connect()

            if not await client.is_user_authorized():
                try:
                    await client.send_code_request(phone)
                    wizard["step"] = "otp"
                    await bot.send_message(event.chat_id, "4. **A code has been sent. Enter OTP with spaces (e.g., 1 2 3 4 5): 🖤**", buttons=cancel_keyboard)
                except Exception as e:
                    await bot.send_message(event.chat_id, f"❌ **Connection Error:** {e}\nStarting over.")
                    del active_wizards[user_id]
            else:
                me = await client.get_me()
                deploy_keyboard = types.ReplyInlineMarkup(rows=[
                    types.KeyboardButtonRow(buttons=[
                        types.KeyboardButtonCallback(text="Logout 🤍", data=f"logout_{session_name}".encode()),
                        types.KeyboardButtonCallback(text="Terminate 🛑", data=f"terminate_{session_name}".encode())
                    ])
                ])
                await save_session_cred(session_name, wizard["api_id"], wizard["api_hash"])
                await bot.send_message(event.chat_id, f"**Userbot successfully deployed for {me.first_name}! 🤍**\n\n**Your bot is now completely active. Type `.cmds` in any chat to see your commands. ❤️**", buttons=deploy_keyboard)
                await register_handlers(client, session_name)
                asyncio.create_task(client.run_until_disconnected())
                active_clients[session_name] = client
                await add_hoster_id(user_id)
                del active_wizards[user_id]

        elif step == "otp":
            otp_code = event.text.replace(" ", "").strip()
            client = wizard["client"]
            session_name = wizard["session_name"]
            try:
                await client.sign_in(wizard["phone"], otp_code)
                me = await client.get_me()
                deploy_keyboard = types.ReplyInlineMarkup(rows=[
                    types.KeyboardButtonRow(buttons=[
                        types.KeyboardButtonCallback(text="Logout 🤍", data=f"logout_{session_name}".encode()),
                        types.KeyboardButtonCallback(text="Terminate 🛑", data=f"terminate_{session_name}".encode())
                    ])
                ])
                await save_session_cred(session_name, wizard["api_id"], wizard["api_hash"])
                await bot.send_message(event.chat_id, f"**Userbot successfully deployed for {me.first_name}! 🤍**\n\n**Your bot is now completely active. Type `.help` in any chat to see your commands. ❤️**", buttons=deploy_keyboard)
                await register_handlers(client, session_name)
                asyncio.create_task(client.run_until_disconnected())
                active_clients[session_name] = client
                await add_hoster_id(user_id)
                del active_wizards[user_id]
            except SessionPasswordNeededError:
                wizard["step"] = "password"
                await bot.send_message(event.chat_id, "🔒 **Two-Step Verification active. Enter password:**", buttons=cancel_keyboard)
            except Exception as e:
                await bot.send_message(event.chat_id, f"❌ **Sign-in Failed:** {e}\nAborting registration flow.")
                del active_wizards[user_id]

        elif step == "password":
            client = wizard["client"]
            session_name = wizard["session_name"]
            try:
                await client.sign_in(password=event.text.strip())
                me = await client.get_me()
                deploy_keyboard = types.ReplyInlineMarkup(rows=[
                    types.KeyboardButtonRow(buttons=[
                        types.KeyboardButtonCallback(text="Logout 🤍", data=f"logout_{session_name}".encode()),
                        types.KeyboardButtonCallback(text="Terminate 🛑", data=f"terminate_{session_name}".encode())
                    ])
                ])
                await save_session_cred(session_name, wizard["api_id"], wizard["api_hash"])
                await bot.send_message(event.chat_id, f"**Userbot successfully deployed for {me.first_name}! 🤍**\n\n**Your bot is now completely active. Type `.help` in any chat to see your commands. ❤️**", buttons=deploy_keyboard)
                await register_handlers(client, session_name)
                asyncio.create_task(client.run_until_disconnected())
                active_clients[session_name] = client
                await add_hoster_id(user_id)
                del active_wizards[user_id]
            except Exception as e:
                await bot.send_message(event.chat_id, f"❌ **Password Incorrect or Error:** {e}")

    await bot.run_until_disconnected()


# ==========================================
#          BOOTSTRAP / BOOT SYSTEM
# ==========================================
async def load_existing_sessions():
    print("\n--- LOADING EXISTING SESSIONS ---")
    session_files = glob.glob(os.path.join(SESSIONS_DIR, "*.session"))
    creds = load_session_creds()
    
    # Fallback default credentials if missing in JSON
    DEFAULT_API_ID = 32962486
    DEFAULT_API_HASH = "a352a4c3668c16a313e564c92cc04ea1"

    for s_file in session_files:
        session_name = os.path.basename(s_file).replace('.session', '')
        if session_name == "joy_hoster_bot": continue 
        session_path = os.path.join(SESSIONS_DIR, session_name)
        
        # Pull saved credentials or use fallbacks
        saved_info = creds.get(session_name, {})
        api_id = saved_info.get("api_id", DEFAULT_API_ID)
        api_hash = saved_info.get("api_hash", DEFAULT_API_HASH)

        client = TelegramClient(
            session_path,
            int(api_id),
            str(api_hash),
            connection_retries=3,
            retry_delay=2,
            auto_reconnect=True,
        )
        try:
            await client.connect()
            if await client.is_user_authorized():
                me = await client.get_me()
                print(f"✅ Loaded Active Session: {me.first_name} (ID: {me.id})")
                await register_handlers(client, session_name)
                asyncio.create_task(client.run_until_disconnected())
                active_clients[session_name] = client
            else:
                await client.disconnect()
        except Exception as e:
            print(f"❌ Failed to load session {session_name}: {e}")

async def main():
    if BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("❌ Error: Set your real BOT_TOKEN at line 37 before starting.")
        return
    await load_existing_sessions()
    await start_bot_hoster()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 System Interrupted. Shutting down active threads.")
