# ================================================================== economy / leveling / games
# This file is loaded by main.py via exec(), sharing its globals (client, discord,
# app_commands, pkey, load_json_file, save_json_file, etc. are all already available).

ECONOMY_FILE = "economy.json"
DAILY_FILE = "daily.json"
XP_FILE = "xp.json"
SHOP_FILE = "shop.json"

economy_data: dict = load_json_file(ECONOMY_FILE, {})  # "guild:user" -> balance (int)
daily_claims: dict = load_json_file(DAILY_FILE, {})  # "guild:user" -> iso timestamp of last claim
xp_data: dict = load_json_file(XP_FILE, {})  # "guild:user" -> {"xp": int, "level": int}
shop_items: dict = load_json_file(SHOP_FILE, {})  # "guild_id" -> {item_name: {"price": int, "role_id": int|None}}

xp_cooldown: dict[str, float] = {}  # "guild:user" -> last XP-award timestamp (in-memory only)
XP_COOLDOWN_SECONDS = 60
DAILY_COOLDOWN_SECONDS = 24 * 3600


def get_balance(guild_id: int, user_id: int) -> int:
    return economy_data.get(pkey(guild_id, user_id), 0)


def add_balance(guild_id: int, user_id: int, amount: int) -> int:
    key = pkey(guild_id, user_id)
    economy_data[key] = economy_data.get(key, 0) + amount
    save_json_file(ECONOMY_FILE, economy_data)
    return economy_data[key]


def xp_for_level(level: int) -> int:
    return 100 * level * level  # simple increasing curve


# ---------------------------------------------------------------- economy commands
@client.tree.command(name="balance", description="Check your (or someone else's) coin balance")
@app_commands.describe(user="Whose balance to check (defaults to you)")
async def balance_cmd(interaction: discord.Interaction, user: Optional[discord.Member] = None):
    target = user or interaction.user
    bal = get_balance(interaction.guild_id, target.id)
    await interaction.response.send_message(f"💰 {target.mention} has **{bal}** coins.")


@client.tree.command(name="daily", description="Claim your daily coins")
async def daily_cmd(interaction: discord.Interaction):
    key = pkey(interaction.guild_id, interaction.user.id)
    last = daily_claims.get(key)
    if last:
        elapsed = time.time() - last
        if elapsed < DAILY_COOLDOWN_SECONDS:
            remaining = DAILY_COOLDOWN_SECONDS - elapsed
            hours = int(remaining // 3600)
            minutes = int((remaining % 3600) // 60)
            await interaction.response.send_message(
                f"You've already claimed today. Try again in {hours}h {minutes}m.", ephemeral=True
            )
            return

    amount = random.randint(50, 150)
    new_balance = add_balance(interaction.guild_id, interaction.user.id, amount)
    daily_claims[key] = time.time()
    save_json_file(DAILY_FILE, daily_claims)
    await interaction.response.send_message(f"💰 You claimed **{amount}** coins! Balance: **{new_balance}**.")


@client.tree.command(name="gamble", description="Bet coins on a 50/50 coin flip")
@app_commands.describe(amount="How many coins to bet")
async def gamble_cmd(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 1000000]):
    bal = get_balance(interaction.guild_id, interaction.user.id)
    if amount > bal:
        await interaction.response.send_message(f"You only have **{bal}** coins.", ephemeral=True)
        return

    won = random.random() < 0.5
    delta = amount if won else -amount
    new_balance = add_balance(interaction.guild_id, interaction.user.id, delta)
    if won:
        await interaction.response.send_message(f"🪙 Heads! You won **{amount}** coins. Balance: **{new_balance}**.")
    else:
        await interaction.response.send_message(f"🪙 Tails. You lost **{amount}** coins. Balance: **{new_balance}**.")


shop_group = app_commands.Group(name="shop", description="Buy roles and items with your coins", guild_only=True)


@shop_group.command(name="list", description="See what's for sale")
async def shop_list(interaction: discord.Interaction):
    items = shop_items.get(str(interaction.guild_id), {})
    if not items:
        await interaction.response.send_message("The shop is empty.", ephemeral=True)
        return
    lines = [f"**{name}** — {data['price']} coins" for name, data in items.items()]
    await interaction.response.send_message("🛒 **Shop:**\n" + "\n".join(lines))


@shop_group.command(name="buy", description="Buy an item from the shop")
@app_commands.describe(name="The item's name, exactly as shown in /shop list")
async def shop_buy(interaction: discord.Interaction, name: str):
    items = shop_items.get(str(interaction.guild_id), {})
    item = items.get(name)
    if not item:
        await interaction.response.send_message("No item with that name.", ephemeral=True)
        return
    bal = get_balance(interaction.guild_id, interaction.user.id)
    if bal < item["price"]:
        await interaction.response.send_message(f"That costs {item['price']} coins — you have {bal}.", ephemeral=True)
        return

    add_balance(interaction.guild_id, interaction.user.id, -item["price"])
    if item.get("role_id"):
        role = interaction.guild.get_role(item["role_id"])
        if role:
            try:
                await interaction.user.add_roles(role, reason=f"Bought {name} from /shop")
            except discord.Forbidden:
                pass
    await interaction.response.send_message(f"✅ Bought **{name}** for {item['price']} coins.")


@shop_group.command(name="add", description="Add an item to the shop")
@app_commands.describe(name="Item name", price="Cost in coins", role="A role to grant on purchase (optional)")
@app_commands.checks.has_permissions(administrator=True)
async def shop_add(interaction: discord.Interaction, name: str, price: app_commands.Range[int, 1, 1000000], role: Optional[discord.Role] = None):
    items = shop_items.setdefault(str(interaction.guild_id), {})
    items[name] = {"price": price, "role_id": role.id if role else None}
    save_json_file(SHOP_FILE, shop_items)
    await interaction.response.send_message(f"Added **{name}** ({price} coins) to the shop.", ephemeral=True)


@shop_add.error
async def shop_add_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You need Administrator to do that.", ephemeral=True)
    else:
        print(f"/shop add error: {error}")


@shop_group.command(name="remove", description="Remove an item from the shop")
@app_commands.describe(name="Item name to remove")
@app_commands.checks.has_permissions(administrator=True)
async def shop_remove(interaction: discord.Interaction, name: str):
    items = shop_items.get(str(interaction.guild_id), {})
    if name not in items:
        await interaction.response.send_message("No item with that name.", ephemeral=True)
        return
    del items[name]
    save_json_file(SHOP_FILE, shop_items)
    await interaction.response.send_message(f"Removed **{name}**.", ephemeral=True)


@shop_remove.error
async def shop_remove_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You need Administrator to do that.", ephemeral=True)
    else:
        print(f"/shop remove error: {error}")


client.tree.add_command(shop_group)


# ---------------------------------------------------------------- leveling
@client.tree.command(name="rank", description="Check your (or someone else's) level and XP")
@app_commands.describe(user="Whose rank to check (defaults to you)")
async def rank_cmd(interaction: discord.Interaction, user: Optional[discord.Member] = None):
    target = user or interaction.user
    data = xp_data.get(pkey(interaction.guild_id, target.id), {"xp": 0, "level": 0})
    next_needed = xp_for_level(data["level"] + 1)
    await interaction.response.send_message(
        f"📊 {target.mention} is **level {data['level']}** with **{data['xp']} XP** "
        f"({next_needed - data['xp']} XP to next level)."
    )


@client.tree.command(name="leaderboard", description="Show the top members by coins or XP")
@app_commands.describe(board="Which leaderboard to show")
@app_commands.choices(
    board=[
        app_commands.Choice(name="Coins", value="coins"),
        app_commands.Choice(name="XP", value="xp"),
    ]
)
async def leaderboard_cmd(interaction: discord.Interaction, board: Optional[app_commands.Choice[str]] = None):
    which = board.value if board else "coins"
    prefix = f"{interaction.guild_id}:"

    if which == "coins":
        rows = sorted(
            ((k, v) for k, v in economy_data.items() if k.startswith(prefix)), key=lambda kv: kv[1], reverse=True
        )[:10]
        title = "💰 Coin leaderboard"
        lines = [f"{i+1}. <@{k.split(':',1)[1]}> — {v} coins" for i, (k, v) in enumerate(rows)]
    else:
        rows = sorted(
            ((k, v) for k, v in xp_data.items() if k.startswith(prefix)), key=lambda kv: kv[1]["xp"], reverse=True
        )[:10]
        title = "📊 XP leaderboard"
        lines = [f"{i+1}. <@{k.split(':',1)[1]}> — level {v['level']} ({v['xp']} XP)" for i, (k, v) in enumerate(rows)]

    if not lines:
        await interaction.response.send_message("No one's on the board yet.", ephemeral=True)
        return
    await interaction.response.send_message(f"**{title}**\n" + "\n".join(lines))


async def award_xp_on_message(message: discord.Message):
    """Separate listener (not @client.event) so it doesn't clobber the main on_message handler."""
    if message.author.bot or not message.guild or not message.content:
        return
    key = pkey(message.guild.id, message.author.id)
    last = xp_cooldown.get(key, 0)
    if time.time() - last < XP_COOLDOWN_SECONDS:
        return
    xp_cooldown[key] = time.time()

    data = xp_data.setdefault(key, {"xp": 0, "level": 0})
    data["xp"] += random.randint(10, 20)
    leveled_up = False
    while data["xp"] >= xp_for_level(data["level"] + 1):
        data["level"] += 1
        leveled_up = True
    save_json_file(XP_FILE, xp_data)

    if leveled_up:
        try:
            await message.channel.send(f"🎉 {message.author.mention} leveled up to **level {data['level']}**!")
        except discord.HTTPException:
            pass


# (hooked in near the bottom of this file, chained onto the existing on_message handler)


# ---------------------------------------------------------------- guess the number
active_guess_games: dict[int, dict] = {}  # channel_id -> {"number", "max", "starter_id"}


@client.tree.command(name="guessnumber", description="Start a guess-the-number game in this channel")
@app_commands.describe(max_number="Upper bound for the number (default 100)")
async def guessnumber(interaction: discord.Interaction, max_number: app_commands.Range[int, 10, 1000000] = 100):
    if interaction.channel_id in active_guess_games:
        await interaction.response.send_message("There's already a game running in this channel.", ephemeral=True)
        return
    active_guess_games[interaction.channel_id] = {
        "number": random.randint(1, max_number),
        "max": max_number,
        "starter_id": interaction.user.id,
    }
    await interaction.response.send_message(
        f"🔢 I'm thinking of a number between 1 and {max_number}. Type your guess in chat!"
    )


async def guess_number_listener(message: discord.Message):
    game = active_guess_games.get(message.channel.id)
    if not game or message.author.bot:
        return
    if not message.content.strip().lstrip("-").isdigit():
        return
    guess = int(message.content.strip())
    if guess == game["number"]:
        reward = max(10, game["max"] // 10)
        add_balance(message.guild.id, message.author.id, reward)
        del active_guess_games[message.channel.id]
        try:
            await message.channel.send(f"🎉 {message.author.mention} got it — the number was **{game['number']}**! +{reward} coins.")
        except discord.HTTPException:
            pass
    elif guess < game["number"]:
        try:
            await message.add_reaction("⬆️")
        except discord.HTTPException:
            pass
    else:
        try:
            await message.add_reaction("⬇️")
        except discord.HTTPException:
            pass


# (hooked in near the bottom of this file, chained onto the existing on_message handler)


# ---------------------------------------------------------------- hangman
HANGMAN_WORDS = [
    "python", "discord", "keyboard", "internet", "pizza", "guitar", "rocket", "forest",
    "shadow", "diamond", "elephant", "battery", "dolphin", "volcano", "castle",
]
HANGMAN_STAGES = [
    "```\n  +---+\n      |\n      |\n      |\n      |\n=========```",
    "```\n  +---+\n  O   |\n      |\n      |\n      |\n=========```",
    "```\n  +---+\n  O   |\n  |   |\n      |\n      |\n=========```",
    "```\n  +---+\n  O   |\n /|   |\n      |\n      |\n=========```",
    "```\n  +---+\n  O   |\n /|\\  |\n      |\n      |\n=========```",
    "```\n  +---+\n  O   |\n /|\\  |\n /    |\n      |\n=========```",
    "```\n  +---+\n  O   |\n /|\\  |\n / \\  |\n      |\n=========```",
]
active_hangman_games: dict[int, dict] = {}  # channel_id -> {"word", "guessed": set, "wrong": int}


def hangman_display(game: dict) -> str:
    word_display = " ".join(c if c in game["guessed"] else "_" for c in game["word"])
    wrong_letters = ", ".join(sorted(c for c in game["guessed"] if c not in game["word"]))
    return f"{HANGMAN_STAGES[game['wrong']]}\n**{word_display}**\nWrong guesses: {wrong_letters or 'none'}"


@client.tree.command(name="hangman", description="Start a game of hangman in this channel")
async def hangman_start(interaction: discord.Interaction):
    if interaction.channel_id in active_hangman_games:
        await interaction.response.send_message("There's already a hangman game running here.", ephemeral=True)
        return
    word = random.choice(HANGMAN_WORDS)
    active_hangman_games[interaction.channel_id] = {"word": word, "guessed": set(), "wrong": 0}
    await interaction.response.send_message(
        "🔡 Hangman started! Type single letters (or guess the whole word) in chat.\n"
        + hangman_display(active_hangman_games[interaction.channel_id])
    )


async def hangman_listener(message: discord.Message):
    game = active_hangman_games.get(message.channel.id)
    if not game or message.author.bot:
        return
    guess = message.content.strip().lower()
    if not guess or not guess.isalpha():
        return

    if len(guess) > 1:
        if guess == game["word"]:
            del active_hangman_games[message.channel.id]
            add_balance(message.guild.id, message.author.id, 50)
            try:
                await message.channel.send(f"🎉 {message.author.mention} guessed the word **{game['word']}**! +50 coins.")
            except discord.HTTPException:
                pass
        return  # wrong full-word guesses don't cost a life

    if guess in game["guessed"]:
        return
    game["guessed"].add(guess)

    if guess not in game["word"]:
        game["wrong"] += 1

    solved = all(c in game["guessed"] for c in game["word"])
    failed = game["wrong"] >= len(HANGMAN_STAGES) - 1

    if solved:
        del active_hangman_games[message.channel.id]
        add_balance(message.guild.id, message.author.id, 30)
        await message.channel.send(f"🎉 Solved! The word was **{game['word']}**. +30 coins for {message.author.mention}.")
    elif failed:
        word = game["word"]
        del active_hangman_games[message.channel.id]
        await message.channel.send(f"💀 Out of guesses! The word was **{word}**.")
    else:
        await message.channel.send(hangman_display(game))


# (hooked in near the bottom of this file, chained onto the existing on_message handler)


# ---------------------------------------------------------------- hook into on_message safely
# This bot's client class is a plain discord.Client (not commands.Bot), which has no
# add_listener(). Instead, chain these three onto whatever on_message is already set to
# (the relay/TTS/automod handler from part2.py) so nothing gets replaced or skipped.
_prior_on_message = client.on_message


async def _part3_on_message(message: discord.Message):
    await _prior_on_message(message)
    await award_xp_on_message(message)
    await guess_number_listener(message)
    await hangman_listener(message)


client.on_message = _part3_on_message


# ================================================================== recurring custom message ("autopost")
AUTOPOST_FILE = "autopost.json"
autopost_config: dict = load_json_file(AUTOPOST_FILE, {})  # "guild_id" -> {channel_id, message, interval_minutes,
                                                            #  title, color, banner_url, thumbnail_url, use_embed,
                                                            #  last_sent (iso str or None)}


async def send_autopost(guild: discord.Guild, config: dict) -> None:
    channel = guild.get_channel(config["channel_id"])
    if not channel:
        return
    text = config["message"].replace("{server}", guild.name).replace("{membercount}", str(guild.member_count))

    try:
        if config.get("use_embed", True):
            color = parse_hex_color(config["color"]) if config.get("color") else discord.Color.blurple()
            embed = discord.Embed(title=config.get("title") or None, description=text, color=color or discord.Color.blurple())
            if config.get("banner_url"):
                embed.set_image(url=config["banner_url"])
            if config.get("thumbnail_url"):
                embed.set_thumbnail(url=config["thumbnail_url"])
            await channel.send(embed=embed)
        else:
            await channel.send(text)
    except discord.HTTPException:
        return

    config["last_sent"] = discord.utils.utcnow().isoformat()
    save_json_file(AUTOPOST_FILE, autopost_config)


async def autopost_loop():
    while True:
        await asyncio.sleep(60)
        now = discord.utils.utcnow()
        for guild_id_str, config in list(autopost_config.items()):
            try:
                guild = client.get_guild(int(guild_id_str))
            except ValueError:
                continue
            if not guild:
                continue
            last_sent = config.get("last_sent")
            due = True
            if last_sent:
                elapsed_minutes = (now - datetime.datetime.fromisoformat(last_sent)).total_seconds() / 60
                due = elapsed_minutes >= config["interval_minutes"]
            if due:
                await send_autopost(guild, config)


autopost_group = app_commands.Group(name="autopost", description="A fully customisable recurring message", guild_only=True)


@autopost_group.command(name="set", description="Set up (or update) a recurring custom message")
@app_commands.describe(
    channel="Where to post it",
    message="Use {server} and {membercount} as placeholders",
    interval_minutes="How often to post, in minutes (minimum 5)",
    title="Embed title (ignored if use_embed is off)",
    color="Hex color for the embed, e.g. #57F287",
    banner_url="A wide image shown at the bottom",
    thumbnail_url="A small corner image",
    use_embed="Post as a styled embed instead of plain text (default: yes)",
)
@app_commands.checks.has_permissions(administrator=True)
async def autopost_set(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    message: str,
    interval_minutes: app_commands.Range[int, 5, 525600],
    title: Optional[str] = None,
    color: Optional[str] = None,
    banner_url: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    use_embed: bool = True,
):
    if color and not parse_hex_color(color):
        await interaction.response.send_message("That doesn't look like a valid hex color. Try `#57F287`.", ephemeral=True)
        return
    for label, url in (("banner_url", bann
