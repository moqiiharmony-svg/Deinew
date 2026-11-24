

async def send_join_leave_message(member: discord.Member, config: dict) -> None:
    text = (
        config["message"]
        .replace("{user}", member.mention)
        .replace("{username}", str(member))
        .replace("{server}", member.guild.name)
        .replace("{membercount}", str(member.guild.member_count))
    )
    content = member.mention if (config.get("mention_user") and not config.get("use_embed")) else None

    if config.get("use_embed", True):
        color = parse_hex_color(config["color"]) if config.get("color") else discord.Color.blurple()
        embed = discord.Embed(title=config.get("title") or None, description=text, color=color or discord.Color.blurple())
        if config.get("banner_url"):
            embed.set_image(url=config["banner_url"])
        if config.get("thumbnail_url"):
            embed.set_thumbnail(url=config["thumbnail_url"])
        elif not config.get("banner_url"):
            embed.set_thumbnail(url=member.display_avatar.url)
        send_kwargs = {"embed": embed}
        if config.get("mention_user"):
            send_kwargs["content"] = member.mention
    else:
        send_kwargs = {"content": (f"{member.mention} " if config.get("mention_user") else "") + text}

    try:
        if config.get("dm_instead"):
            await member.send(**send_kwargs)
        else:
            channel = member.guild.get_channel(config["channel_id"])
            if channel:
                await channel.send(**send_kwargs)
    except discord.HTTPException:
        pass


@client.tree.command(name="welcomemsg", description="Set a fully customisable message for when someone joins")
@app_commands.describe(
    channel="Where to post it (ignored if dm_instead is on)",
    message="Use {user}, {username}, {server}, {membercount} as placeholders",
    title="Embed title (ignored if use_embed is off)",
    color="Hex color for the embed, e.g. #57F287",
    banner_url="A wide image shown at the bottom",
    thumbnail_url="A small corner image (defaults to the new member's avatar)",
    use_embed="Post as a styled embed instead of plain text (default: yes)",
    dm_instead="DM the message to the new member instead of posting in a channel",
    mention_user="Ping the member alongside the message",
)
@app_commands.checks.has_permissions(administrator=True)
async def welcomemsg(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    message: str,
    title: Optional[str] = None,
    color: Optional[str] = None,
    banner_url: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    use_embed: bool = True,
    dm_instead: bool = False,
    mention_user: bool = True,
):
    if not await validate_join_leave_inputs(interaction, color, banner_url, thumbnail_url):
        return
    welcome_config[str(interaction.guild_id)] = build_join_leave_config(
        channel, message, title, color, banner_url, thumbnail_url, use_embed, dm_instead, mention_user
    )
    save_json_file(WELCOME_FILE, welcome_config)
    await interaction.response.send_message("Welcome message set.", ephemeral=True)


@welcomemsg.error
async def welcomemsg_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You need Administrator to do that.", ephemeral=True)
    else:
        print(f"/welcomemsg error: {error}")


@client.tree.command(name="leavemsg", description="Set a fully customisable message for when someone leaves")
@app_commands.describe(
    channel="Where to post it",
    message="Use {user}, {username}, {server}, {membercount} as placeholders",
    title="Embed title (ignored if use_embed is off)",
    color="Hex color for the embed, e.g. #ED4245",
    banner_url="A wide image shown at the bottom",
    thumbnail_url="A small corner image",
    use_embed="Post as a styled embed instead of plain text (default: yes)",
)
@app_commands.checks.has_permissions(administrator=True)
async def leavemsg(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    message: str,
    title: Optional[str] = None,
    color: Optional[str] = None,
    banner_url: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    use_embed: bool = True,
):
    if not await validate_join_leave_inputs(interaction, color, banner_url, thumbnail_url):
        return
    # Leave messages can't DM (the member is already gone) or @mention (same reason).
    leavemsg_config[str(interaction.guild_id)] = build_join_leave_config(
        channel, message, title, color, banner_url, thumbnail_url, use_embed, False, False
    )
    save_json_file(LEAVEMSG_FILE, leavemsg_config)
    await interaction.response.send_message("Leave message set.", ephemeral=True)


@leavemsg.error
async def leavemsg_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You need Administrator to do that.", ephemeral=True)
    else:
        print(f"/leavemsg error: {error}")


@client.tree.command(name="rolemessageoff", description="Turn off the role-trigger message")
@app_commands.checks.has_permissions(administrator=True)
async def rolemessageoff(interaction: discord.Interaction):
    had = role_announce_config.pop(interaction.guild_id, None)
    save_role_announce()
    await interaction.response.send_message(
        "Turned off." if had else "It wasn't set up to begin with.", ephemeral=True
    )


@rolemessageoff.error
async def rolemessageoff_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You need Administrator to do that.", ephemeral=True)
    else:
        print(f"/rolemessageoff error: {error}")


@app_commands.command(
    name="verifyrolesetup", description="Choose the role /verifyuser hands out automatically"
)
@app_commands.describe(role="Must be below your own top role")
@app_commands.checks.has_permissions(administrator=True)
async def verifyrolesetup(interaction: discord.Interaction, role: discord.Role):
    if role.position >= interaction.user.top_role.position and interaction.guild.owner_id != interaction.user.id:
        await interaction.response.send_message(
            "You can only pick a role below your own highest role.", ephemeral=True
        )
        return
    if role.position >= interaction.guild.me.top_role.position:
        await interaction.response.send_message(
            "I can't assign that role — it's above my own highest role. Move my role above it first.",
            ephemeral=True,
        )
        return
    if role.is_default() or role.managed:
        await interaction.response.send_message("That role can't be assigned manually.", ephemeral=True)
        return

    verify_role_config[interaction.guild_id] = role.id
    save_verify_role()
    await interaction.response.send_message(
        f"{role.mention} will now be given to anyone `/verifyuser` is run on.", ephemeral=True
    )


@verifyrolesetup.error
async def verifyrolesetup_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You need Administrator to do that.", ephemeral=True)
    else:
        print(f"/verifyrolesetup error: {error}")


@app_commands.command(
    name="verifyuser", description="Look up a submitted TikTok by @mention or raw user ID"
)
@app_commands.describe(
    user="A current member to look up",
    user_id="A raw user ID — use this for someone who's left the server",
)
@app_commands.checks.has_permissions(manage_messages=True)
async def verifyuser(
    interaction: discord.Interaction,
    user: Optional[discord.Member] = None,
    user_id: Optional[str] = None,
):
    if not user and not user_id:
        await interaction.response.send_message("Give me a member or a user ID.", ephemeral=True)
        return

    if user:
        uid = user.id
        label = user.mention
    else:
        try:
            uid = int(user_id.strip())
        except ValueError:
            await interaction.response.send_message("That doesn't look like a valid user ID.", ephemeral=True)
            return
        label = f"<@{uid}>"

    record = verified.get(pkey(interaction.guild_id, uid))
    lines = (
        [f"{label} verified with **{record['tiktok']}**."]
        if record
        else [f"{label} hasn't verified."]
    )

    role_id = verify_role_config.get(interaction.guild_id)
    if role_id:
        role = interaction.guild.get_role(role_id)
        if not role:
            lines.append("(Configured verify role no longer exists — run /verifyrolesetup again.)")
        elif not user:
            lines.append("(Role not assigned — that user isn't currently in the server.)")
        elif role in user.roles:
            pass  # already has it
        else:
            try:
                await user.add_roles(role, reason=f"/verifyuser run by {interaction.user}")
                lines.append(f"Gave them {role.mention}.")
            except discord.Forbidden:
                lines.append("(Couldn't assign the role — check my permissions and role position.)")

    await interaction.response.send_message("\n".join(lines), ephemeral=True)

    log_id = verifyuser_log_channel.get(interaction.guild_id)
    if log_id:
        try:
            log_ch = client.get_channel(log_id) or await client.fetch_channel(log_id)
            embed = discord.Embed(title="/verifyuser used", color=discord.Color.blurple())
            embed.add_field(name="Run by", value=interaction.user.mention, inline=False)
            embed.add_field(name="Target", value=label, inline=False)
            embed.add_field(name="Result", value="\n".join(lines), inline=False)
            embed.timestamp = discord.utils.utcnow()
            await log_ch.send(embed=embed)
        except discord.HTTPException:
            pass


@verifyuser.error
async def verifyuser_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You need Manage Messages to do that.", ephemeral=True)
    else:
        print(f"/verifyuser error: {error}")


@app_commands.command(name="unverify", description="Remove a member's verified status")
@app_commands.describe(user="The member to unverify")
@app_commands.checks.has_permissions(administrator=True)
async def unverify(interaction: discord.Interaction, user: discord.Member):
    had = verified.pop(pkey(interaction.guild_id, user.id), None)
    save_verified()

    if VERIFIED_ROLE_ID:
        role = interaction.guild.get_role(VERIFIED_ROLE_ID)
        if role and role in user.roles:
            try:
                await user.remove_roles(role, reason=f"Unverified by {interaction.user}")
            except discord.Forbidden:
                pass

    msg = f"{user.mention} has been unverified." if had else f"{user.mention} wasn't on record, but I checked for the role too."
    await interaction.response.send_message(msg, ephemeral=True)


@unverify.error
async def unverify_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You need Administrator to do that.", ephemeral=True)
    else:
        print(f"/unverify error: {error}")


# ================================================================== utility commands
@client.tree.command(name="avatar", description="Show a member's avatar")
@app_commands.describe(user="Whose avatar to show (defaults to you)")
async def avatar_cmd(interaction: discord.Interaction, user: Optional[discord.Member] = None):
    member = user or interaction.user
    embed = discord.Embed(title=f"{member.display_name}'s avatar", color=discord.Color.blurple())
    embed.set_image(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@client.tree.command(name="userinfo", description="Show info about a member")
@app_commands.describe(user="Whose info to show (defaults to you)")
async def userinfo(interaction: discord.Interaction, user: Optional[discord.Member] = None):
    member = user or interaction.user
    embed = discord.Embed(title=str(member), color=discord.Color.blurple())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(
        name="Joined server",
        value=discord.utils.format_dt(member.joined_at, "R") if member.joined_at else "Unknown",
    )
    embed.add_field(name="Account created", value=discord.utils.format_dt(member.created_at, "R"))
    roles = [r.mention for r in member.roles if r.name != "@everyone"]
    embed.add_field(name=f"Roles ({len(roles)})", value=", ".join(roles) if roles else "None", inline=False)
    await interaction.response.send_message(embed=embed)


@client.tree.command(name="serverinfo", description="Show info about this server")
async def serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(title=guild.name, color=discord.Color.blurple())
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="Members", value=str(guild.member_count))
    embed.add_field(name="Created", value=discord.utils.format_dt(guild.created_at, "R"))
    embed.add_field(name="Boost level", value=str(guild.premium_tier))
    embed.add_field(name="Boosts", value=str(guild.premium_subscription_count))
    await interaction.response.send_message(embed=embed)


@client.tree.command(name="ping", description="Check the bot's latency")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"Pong! {round(client.latency * 1000)}ms")


@client.tree.command(name="purge", description="Delete a batch of recent messages in this channel")
@app_commands.describe(amount="How many messages to delete (1-100)")
@app_commands.checks.has_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"Deleted {len(deleted)} message(s).", ephemeral=True)


@purge.error
async def purge_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You need Manage Messages to do that.", ephemeral=True)
    else:
        print(f"/purge error: {error}")


class ConfirmPurgeView(discord.ui.View):
    def __init__(self, author_id: int, channel: discord.TextChannel):
        super().__init__(timeout=30)
        self.author_id = author_id
        self.channel = channel

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the person who ran the command can confirm this.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Confirm — delete everything", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Purging — recreating the channel now...", view=self)

        try:
            new_channel = await self.channel.clone(reason=f"/fullpurge by {interaction.user}")
            await new_channel.edit(position=self.channel.position)
            await self.channel.delete(reason=f"/fullpurge by {interaction.user}")
            await new_channel.send(f"✅ Channel purged by {interaction.user.mention}.")
        except discord.Forbidden:
            try:
                await interaction.followup.send(
                    "I don't have permission to manage this channel.", ephemeral=True
                )
            except discord.HTTPException:
                pass
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Cancelled.", view=self)
        self.stop()


@client.tree.command(
    name="fullpurge", description="Delete EVERY message in this channel, including ones older than 14 days"
)
@app_commands.checks.has_permissions(administrator=True)
async def fullpurge(interaction: discord.Interaction):
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message("This only works in a normal text channel.", ephemeral=True)
        return

    view = ConfirmPurgeView(interaction.user.id, channel)
    await interaction.response.send_message(
        "⚠️ This clones this channel and deletes the original — the only way to wipe messages older than "
        "14 days, since Discord won't bulk-delete those directly. The new channel keeps the same name, "
        "permissions, and position, but message history, pins, and the channel's ID are gone for good.\n\n"
        "If this channel is used for `/setstorage`, `/setverify`, `/setlog`, or TTS, you'll need to run "
        "that setup command again afterward, since the channel ID changes.\n\nThis can't be undone. Confirm?",
        view=view,
        ephemeral=True,
    )


@fullpurge.error
async def fullpurge_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You need Administrator to do that.", ephemeral=True)
    else:
        print(f"/fullpurge error: {error}")


@client.tree.command(name="kick", description="Kick a member from the server")
@app_commands.describe(user="Who to kick", reason="Why they're being kicked")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, user: discord.Member, reason: Optional[str] = None):
    if user.top_role >= interaction.user.top_role and interaction.guild.owner_id != interaction.user.id:
        await interaction.response.send_message("You can't kick someone with an equal or higher role.", ephemeral=True)
        return
    try:
        await user.kick(reason=reason or f"Kicked by {interaction.user}")
    except discord.Forbidden:
        await interaction.response.send_message("I don't have permission to kick that member.", ephemeral=True)
        return
    log_mod_action(interaction.guild_id, user.id, "kick", reason, interaction.user)
    await interaction.response.send_message(f"Kicked {user.mention}." + (f" Reason: {reason}" if reason else ""))


@kick.error
async def kick_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You need Kick Members to do that.", ephemeral=True)
    else:
        print(f"/kick error: {error}")


@client.tree.command(name="ban", description="Ban a member from the server")
@app_commands.describe(user="Who to ban", reason="Why they're being banned")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, user: discord.Member, reason: Optional[str] = None):
    if user.top_role >= interaction.user.top_role and interaction.guild.owner_id != interaction.user.id:
        await interaction.response.send_message("You can't ban someone with
