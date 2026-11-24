"""
Combined bot: message-proxy webhooks, per-user profiles, VC text-to-speech,
and a customisable verify panel that collects a user's TikTok handle into a
log channel.

Requirements:
    pip install discord.py gTTS PyNaCl aiohttp
    ffmpeg must be installed and on PATH (for TTS playback).
"""

import asyncio
import datetime
import io
import json
import random
import re
import time
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from gtts import gTTS

import os
TOKEN = os.environ["TOKEN"]

# Fallback storage/verify channels, only used if an admin hasn't run /setstorage
# or /setverify yet in a given server. 0 means "not set" — leave as 0 and just
# use the slash commands after inviting the bot; no need to edit these.
STORAGE_CHANNEL_ID = 0
VERIFY_LOG_CHANNEL_ID = 0

# Optional: role to hand out once someone submits the verify form. Leave as
# None to skip auto-roling and just log the submission.
VERIFIED_ROLE_ID: Optional[int] = None

PROFILE_FILE = "profiles.json"
AVATAR_CACHE_SECONDS = 3600

# Fill in your own presets for /profile random, e.g.:
# PROFILE_PRESETS = [
#     {"name": "Shadow", "avatar_url": "https://example.com/shadow.png"},
#     {"name": "Sunny", "avatar_url": "https://example.com/sunny.png"},
# ]
PROFILE_PRESETS: list[dict] = []

VERIFY_FILE = "verified.json"
VERIFY_ROLE_FILE = "verify_role.json"

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True  # needed to assign the verified role


# ================================================================== profile storage
def load_profiles() -> dict:
    try:
        with open(PROFILE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_profiles() -> None:
    with open(PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2)


profiles: dict = load_profiles()
avatar_cache: dict[int, tuple[str, float]] = {}


def pkey(guild_id: int, user_id: int) -> str:
    return f"{guild_id}:{user_id}"


def load_verified() -> dict:
    try:
        with open(VERIFY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_verified() -> None:
    with open(VERIFY_FILE, "w", encoding="utf-8") as f:
        json.dump(verified, f, indent=2)


verified: dict = load_verified()  # "guild:user" -> {"tiktok": ..., "verified_at": ...}


def load_verify_role() -> dict:
    try:
        with open(VERIFY_ROLE_FILE, "r", encoding="utf-8") as f:
            return {int(k): v for k, v in json.load(f).items()}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_verify_role() -> None:
    with open(VERIFY_ROLE_FILE, "w", encoding="utf-8") as f:
        json.dump(verify_role_config, f, indent=2)


verify_role_config: dict[int, int] = load_verify_role()  # guild_id -> role_id


def load_id_map(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return {int(k): v for k, v in json.load(f).items()}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_id_map(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


VERIFY_SUBMIT_CHANNEL_FILE = "verify_submit_channel.json"
VERIFYUSER_LOG_CHANNEL_FILE = "verifyuser_log_channel.json"
STORAGE_CHANNEL_FILE = "storage_channel.json"
ROLE_ANNOUNCE_FILE = "role_announce.json"


def load_role_announce() -> dict:
    try:
        with open(ROLE_ANNOUNCE_FILE, "r", encoding="utf-8") as f:
            return {int(k): v for k, v in json.load(f).items()}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_role_announce() -> None:
    with open(ROLE_ANNOUNCE_FILE, "w", encoding="utf-8") as f:
        json.dump(role_announce_config, f, indent=2)


# guild_id -> {"role_id", "channel_id", "message"}
role_announce_config: dict[int, dict] = load_role_announce()

WARNINGS_FILE = "warnings.json"
MOD_ACTIONS_FILE = "mod_actions.json"
BLOCKWORDS_FILE = "blockwords.json"
BLOCKINVITES_FILE = "blockinvites.json"
RELAY_BLOCKLIST_FILE = "relay_blocklist.json"
MYTTS_FILE = "mytts.json"
TTS_MAXLEN_FILE = "tts_maxlen.json"
SUGGEST_CHANNEL_FILE = "suggest_channel.json"
STARBOARD_FILE = "starboard.json"
WELCOME_FILE = "welcome.json"
LEAVEMSG_FILE = "leavemsg.json"


def load_json_file(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json_file(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


warnings_data: dict = load_json_file(WARNINGS_FILE, {})  # "guild:user" -> [ {reason, by, at}, ... ]
mod_actions: dict = load_json_file(MOD_ACTIONS_FILE, {})  # "guild:user" -> [ {type, reason, by, at}, ... ]


def log_mod_action(guild_id: int, user_id: int, action_type: str, reason: Optional[str], moderator) -> None:
    key = pkey(guild_id, user_id)
    mod_actions.setdefault(key, []).append(
        {
            "type": action_type,
            "reason": reason or "No reason given",
            "by": str(moderator),
            "at": discord.utils.utcnow().isoformat(),
        }
    )
    save_json_file(MOD_ACTIONS_FILE, mod_actions)
blockwords: dict = load_json_file(BLOCKWORDS_FILE, {})  # "guild_id" -> [word, ...]
blockinvites: dict = load_json_file(BLOCKINVITES_FILE, {})  # "guild_id" -> True/False
relay_blocklist: dict = load_json_file(RELAY_BLOCKLIST_FILE, {})  # "guild_id" -> [channel_id, ...]
mytts_lang: dict = load_json_file(MYTTS_FILE, {})  # "guild:user" -> lang code
tts_maxlen: dict = load_json_file(TTS_MAXLEN_FILE, {})  # "guild_id" -> int
suggest_channel: dict = load_json_file(SUGGEST_CHANNEL_FILE, {})  # "guild_id" -> channel_id
starboard_config: dict = load_json_file(STARBOARD_FILE, {})  # "guild_id" -> {"channel_id","threshold"}
starboard_posted: dict[int, int] = {}  # original message_id -> starboard message_id (in-memory only)
welcome_config: dict = load_json_file(WELCOME_FILE, {})  # "guild_id" -> {"channel_id","message"}
leavemsg_config: dict = load_json_file(LEAVEMSG_FILE, {})  # "guild_id" -> {"channel_id","message"}
INVITE_RE = re.compile(r"(discord\.gg/|discord(?:app)?\.com/invite/)[\w-]+", re.IGNORECASE)

verify_submit_channel: dict[int, int] = load_id_map(VERIFY_SUBMIT_CHANNEL_FILE)  # guild_id -> channel_id
verifyuser_log_channel: dict[int, int] = load_id_map(VERIFYUSER_LOG_CHANNEL_FILE)  # guild_id -> channel_id
storage_channel_config: dict[int, int] = load_id_map(STORAGE_CHANNEL_FILE)  # guild_id -> channel_id


# ================================================================== voice (TTS only)
voice_clients: dict[int, discord.VoiceClient] = {}
tts_channels: set[int] = set()
tts_lang: dict[int, str] = {}  # guild_id -> gTTS language code, default "en"

# Maps a relayed (webhook) message id -> the id of the user who originally sent it,
# so a ❌ reaction can be checked against the right person before deleting.
relay_authors: dict[int, int] = {}
CANCEL_EMOJIS = ("❌", "❌️")

# For /edit and /snipe.
relay_content: dict[int, dict] = {}  # message_id -> {"channel_id", "author_id", "content"}
user_last_relay: dict[tuple[int, int], dict] = {}  # (channel_id, user_id) -> {"message_id", "thread_id"}
last_snipe: dict[int, dict] = {}  # channel_id -> {"author_id", "content", "deleted_at"}

# For /afk.
afk_users: dict[str, dict] = {}  # "guild:user" -> {"note", "since"}


# ================================================================== bot
class CombinedBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.session: Optional[aiohttp.ClientSession] = None
        self.webhooks: dict[int, discord.Webhook] = {}

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        self.tree.add_command(profile_group)
        self.tree.add_command(verify_group)
        self.tree.add_command(blockword_group)
        self.add_view(VerifyView())  # keeps the Verify button working after a restart
        self.add_view(VerifyReviewView())  # keeps Approve/Deny working after a restart
        await self.tree.sync()

    async def close(self):
        if self.session:
            await self.session.close()
        await super().close()


client = CombinedBot()


async def get_webhook(channel: discord.TextChannel) -> discord.Webhook:
    if channel.id in client.webhooks:
        return client.webhooks[channel.id]
    for wh in await channel.webhooks():
        if wh.user == client.user:
            client.webhooks[channel.id] = wh
            return wh
    wh = await channel.create_webhook(name="Message Proxy")
    client.webhooks[channel.id] = wh
    return wh


async def get_storage_channel(guild_id: int) -> discord.abc.Messageable:
    channel_id = storage_channel_config.get(guild_id, STORAGE_CHANNEL_ID)
    if not channel_id:
        raise RuntimeError("No storage channel set — an admin needs to run /setstorage first.")
    return client.get_channel(channel_id) or await client.fetch_channel(channel_id)


async def resolve_avatar(profile: dict, member: discord.Member) -> str:
    msg_id = profile.get("avatar_msg")
    if msg_id:
        cached = avatar_cache.get(msg_id)
        if cached and time.time() - cached[1] < AVATAR_CACHE_SECONDS:
            return cached[0]
        try:
            ch = await get_storage_channel(member.guild.id)
            msg = await ch.fetch_message(msg_id)
            url = msg.attachments[0].url
            avatar_cache[msg_id] = (url, time.time())
            return url
        except (discord.HTTPException, IndexError):
            pass
    return profile.get("avatar_url") or member.display_avatar.url


# ================================================================== proxy helpers
async def build_reply_line(message: discord.Message) -> str:
    ref = message.reference
    if not ref or not ref.message_id:
        return ""
    target = ref.resolved if isinstance(ref.resolved, discord.Message) else None
    if target is None:
        try:
            target = await message.channel.fetch_message(ref.message_id)
        except discord.HTTPException:
            return ""

    snippet = target.content.replace("\n", " ")
    snippet = re.sub(r"<@[!&]?\d+>", "@user", snippet)
    snippet = discord.utils.escape_mentions(snippet)
    if len(snippet) > 60:
        snippet = snippet[:57] + "..."
    if not snippet and (target.attachments or target.stickers):
        snippet = "*attachment*"

    name = discord.utils.escape_markdown(target.author.display_name)
    return f"-# ↪ [{name}]({target.jump_url}) {snippet}\n"


async def build_files(message: discord.Message) -> tuple[list[discord.File], list[str]]:
    files: list[discord.File] = []
    notes: list[str] = []

    for att in message.attachments:
        data = await att.read()
        files.append(
            discord.File(
                io.BytesIO(data),
                filename=att.filename,
                description=att.description,
                spoiler=att.is_spoiler(),
            )
        )

    for sticker in message.stickers:
        if sticker.format is discord.StickerFormatType.lottie:
            notes.append(f"*[sticker: {sticker.name}]*")
            continue
        async with client.session.get(sticker.url) as resp:
            if resp.status != 200:
                notes.append(f"*[sticker: {sticker.name}]*")
                continue
            ext = "gif" if sticker.format is discord.StickerFormatType.gif else "png"
            files.append(discord.File(io.BytesIO(await resp.read()), filename=f"{sticker.name}.{ext}"))

    return files[:10], notes


async def proxy_message(message: discord.Message):
    channel = message.channel
    thread = None
    if isinstance(channel, discord.Thread):
        thread = channel
        channel = channel.parent
    if not isinstance(channel, discord.TextChannel):
        return

    if not (message.content or message.attachments or message.stickers):
        return

    try:
        webhook = await get_webhook(channel)
        files, notes = await build_files(message)
        reply_line = await build_reply_line(message)

        text = reply_line + (message.content or "")
        if notes:
            text += ("\n" if text and not text.endswith("\n") else "") + " ".join(notes)

        embeds = [e for e in message.embeds if e.type == "rich" and not e.url]

        profile = profiles.get(pkey(message.guild.id, message.author.id), {})
        username = profile.get("name") or message.author.display_name
        avatar_url = await resolve_avatar(profile, message.author)

        base = dict(
            username=username[:80],
            avatar_url=avatar_url,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
            wait=True,
        )
        if thread:
            base["thread"] = thread

        chunks = [text[i:i + 2000] for i in range(0, len(text), 2000)] or [None]
        for i, chunk in enumerate(chunks):
            last = i == len(chunks) - 1
            sent = await webhook.send(
                content=chunk,
                files=files if last else [],
                embeds=embeds if last else [],
                **base,
            )
            relay_authors[sent.id] = message.author.id
            relay_content[sent.id] = {
                "channel_id": message.channel.id,
                "author_id": message.author.id,
                "content": chunk or "",
            }
            user_last_relay[(message.channel.id, message.author.id)] = {
                "message_id": sent.id,
                "thread_id": thread.id if thread else None,
            }

        await message.delete()

    except discord.Forbidden:
        print("Missing permissions (need Manage Webhooks + Manage Messages).")
    except discord.HTTPException as e:
        print(f"Failed to proxy message: {e}")


# ================================================================== profile commands
profile_group = app_commands.Group(
    name="profile", description="Customise how your messages appear in this server", guild_only=True
)

PROFILE_SLOTS_FILE = "profile_slots.json"
PROFILE_ACTIVE_FILE = "profile_active.json"
MAX_PROFILE_SLOTS = 30

profile_slots: dict = load_json_file(PROFILE_SLOTS_FILE, {})  # "guild:user" -> {slot_name: {name, avatar_url/avatar_msg}}
profile_active_slot: dict = load_json_file(PROFILE_ACTIVE_FILE, {})  # "guild:user" -> slot_name currently in use


def valid_name(name: str) -> Optional[str]:
    if not 1 <= len(name) <= 80:
        return "Name must be 1-80 characters."
    if any(bad in name.lower() for bad in ("discord", "clyde")):
        return 'Webhook names can\'t contain "discord" or "clyde".'
    return None


def valid_slot(slot: str) -> Optional[str]:
    if not 1 <= len(slot) <= 32:
        return "Profile slot names must be 1-32 characters."
    return None


async def build_avatar_fields(
    interaction: discord.Interaction, key: str, data: dict, avatar: Optional[discord.Attachment], avatar_url: Optional[str]
) -> Optional[str]:
    """Validates + stores an avatar into `data` in place. Returns an error message, or None on success."""
    if avatar and not (avatar.content_type or "").startswith("image/"):
        return "That attachment isn't an image."
    if avatar_url and not avatar_url.startswith(("http://", "https://")):
        return "Avatar link must start with http:// or https://"

    if avatar:
        try:
            ch = await get_storage_channel(interaction.guild_id)
            stored = await ch.send(content=key, file=await avatar.to_file())
        except RuntimeError as e:
            return str(e)
        except discord.HTTPException:
            return "I couldn't store that avatar — check my permissions in the storage channel."
        data["avatar_msg"] = stored.id
        data.pop("avatar_url", None)
    elif avatar_url:
        data["avatar_url"] = avatar_url
        data.pop("avatar_msg", None)
    return None


@profile_group.command(name="set", description="Set your custom name and/or avatar")
@app_commands.describe(
    name="Your display name", avatar="Upload an avatar image", avatar_url="Or a permanent image link"
)
async def profile_set(
    interaction: discord.Interaction,
    name: Optional[str] = None,
    avatar: Optional[discord.Attachment] = None,
    avatar_url: Optional[str] = None,
):
    if not (name or avatar or avatar_url):
        await interaction.response.send_message("Give me a name and/or an avatar.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    if name:
        err = valid_name(name)
        if err:
            await interaction.followup.send(err, ephemeral=True)
            return
    if avatar and not (avatar.content_type or "").startswith("image/"):
        await interaction.followup.send("That attachment isn't an image.", ephemeral=True)
        return
    if avatar_url and not avatar_url.startswith(("http://", "https://")):
        await interaction.followup.send("Avatar link must start with http:// or https://", ephemeral=True)
        return

    key = pkey(interaction.guild_id, interaction.user.id)
    data = profiles.get(key, {})

    if name:
        data["name"] = name
    if avatar:
        try:
            ch = await get_storage_channel(interaction.guild_id)
            stored = await ch.send(content=key, file=await avatar.to_file())
        except RuntimeError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        except discord.HTTPException:
            await interaction.followup.send(
                "I couldn't store that avatar — check my permissions in the storage channel.",
                ephemeral=True,
            )
            return
        data["avatar_msg"] = stored.id
        data.pop("avatar_url", None)
    elif avatar_url:
        data["avatar_url"] = avatar_url
        data.pop("avatar_msg", None)

    profiles[key] = data
    save_profiles()
    await interaction.followup.send("Profile updated! Use /profile view to preview it.", ephemeral=True)


@profile_group.command(name="create", description="Save a new named relay profile (up to 30 per person)")
@app_commands.describe(
    slot="A short name for this profile, e.g. 'formal' or 'gremlin mode'",
    name="Display name for this profile",
    avatar="Upload an avatar image",
    avatar_url="Or a permanent image link",
)
async def profile_create(
    interaction: discord.Interaction,
    slot: str,
    name: Optional[str] = None,
    avatar: Optional[discord.Attachment] = None,
    avatar_url: Optional[str] = None,
):
    if not (name or avatar or avatar_url):
        await interaction.response.send_message("Give this profile a name and/or an avatar.", ephemeral=True)
        return
    slot_err = valid_slot(slot)
    if slot_err:
        await interaction.response.send_message(slot_err, ephemeral=True)
        return
    if name:
        name_err = valid_name(name)
        if name_err:
            await interaction.response.send_message(name_err, ephemeral=True)
            return

    await interaction.response.defer(ephemeral=True)
    key = pkey(interaction.guild_id, interaction.user.id)
    slots = profile_slots.setdefault(key, {})

    if slot not in slots and len(slots) >= MAX_PROFILE_SLOTS:
        await interaction.followup.send(
            f"You've hit the {MAX_PROFILE_SLOTS}-profile limit — delete one with /profile delete first.",
            ephemeral=True,
        )
        return

    data = dict(slots.get(slot, {}))
    if name:
        data["name"] = name
    err = await 
