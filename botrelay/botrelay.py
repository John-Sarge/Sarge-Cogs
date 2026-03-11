import discord
import typing 
from redbot.core import Config, commands
from redbot.core.utils.chat_formatting import pagify
import logging
import io

logger = logging.getLogger("red.scdroid.botrelay")

class BotRelay(commands.Cog):
    """
    Relays messages between channels using the bot account.
    Based on MsgMover from coffeebank (https://github.com/coffeebank/coffee-cogs/tree/master/msgmover).
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=94857263541, force_registration=True)

        default_global = {
            "relays": {}  
            # "source_channel_id": [dest_id_1, dest_id_2]
        }
        self.config.register_global(**default_global)

    @commands.group(name="botrelay", aliases=["br"])
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def botrelay(self, ctx):
        """Manage message relays."""
        pass

    @botrelay.command(name="add")
    async def botrelay_add(self, ctx, destination: typing.Union[discord.TextChannel, discord.Thread, int]):
        """
        Relay messages from THIS channel to another.
        """
        dest_chan = None
        dest_id = None

        if isinstance(destination, int):
            dest_id = destination
            dest_chan = self.bot.get_channel(dest_id)
        else:
            dest_id = destination.id
            dest_chan = destination

        # Cross-server Check: If channel not in this guild, we need to ensure bot can see it
        if not dest_chan:
             return await ctx.send(f"I cannot interfere with channel `{dest_id}`. Check that I am in the server/channel and have permissions.")

        if ctx.channel.id == dest_id:
            return await ctx.send("Source and destination cannot be the same channel.")
        
        async with self.config.relays() as relays:
            src_id = str(ctx.channel.id) # Key must be string
            if src_id not in relays:
                relays[src_id] = []
            
            if dest_id in relays[src_id]:
                return await ctx.send(f"Messages are already being relayed to {dest_chan.mention}.")
            
            relays[src_id].append(dest_id)
        
        await ctx.send(f"✅ Messages from {ctx.channel.mention} will now be relayed to {dest_chan.mention}.")

    @botrelay.command(name="remove")
    async def botrelay_remove(self, ctx, destination: typing.Union[discord.TextChannel, discord.Thread, int]):
        """
        Stop relaying messages from THIS channel to another.
        """
        dest_id = None
        if isinstance(destination, int):
            dest_id = destination
        else:
            dest_id = destination.id

        source = ctx.channel
        
        async with self.config.relays() as relays:
            src_id = str(source.id)
            if src_id not in relays or dest_id not in relays[src_id]:
                return await ctx.send("That relay configuration does not exist.")
            
            relays[src_id].remove(dest_id)
            if not relays[src_id]:
                del relays[src_id]

        dest_mention = f"<#{dest_id}>"
        # Try to resolve mention nicely if we can
        chan = self.bot.get_channel(dest_id)
        if chan:
            dest_mention = chan.mention

        await ctx.send(f"❌ Relay to {dest_mention} has been removed.")

    @botrelay.command(name="list")
    async def botrelay_list(self, ctx):
        """
        List all active relays in this server.
        """
        relays = await self.config.relays()
        if not relays:
            return await ctx.send("No relays configured.")

        msg = "**Active Relays:**\n"
        for src_id, dest_ids in relays.items():
            source_channel = ctx.guild.get_channel(int(src_id))
            
            # Since relays are global, we only want to list relays originating from THIS guild
            if not source_channel:
                 continue

            source_name = source_channel.mention if source_channel else f"<#{src_id}> (Deleted)"
            
            dest_list = []
            for dest_id in dest_ids:
                # Use bot.get_channel to find channels outside this guild if necessary
                dest_channel = self.bot.get_channel(dest_id)
                if dest_channel:
                    dest_list.append(dest_channel.mention)
                else:
                    dest_list.append(f"<#{dest_id}> (Deleted)")
            
            msg += f"{source_name} ➡️ {', '.join(dest_list)}\n"

        if msg == "**Active Relays:**\n":
             return await ctx.send("No relays configured for this server.")

        for page in pagify(msg):
            await ctx.send(page)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        The main relay listener.
        """
        if not message.guild:
            return

        relays = await self.config.relays()
        src_id = str(message.channel.id)
        
        if src_id not in relays:
            return

        dest_ids = relays[src_id]
        if not dest_ids:
            return

        final_content = message.content or ""
        
        # Handle reply
        if message.reference and isinstance(message.reference.resolved, discord.Message):
            ref_msg = message.reference.resolved
            # Truncate reply snippet
            ref_snippet = ref_msg.content or (ref_msg.embeds and "[Embed]") or "[Attachment]" or "[Unknown]"
            if len(ref_snippet) > 50:
                ref_snippet = ref_snippet[:50] + "..."
            
            # Add reply block quote
            reply_header = f"> *Replying to {ref_msg.author.display_name}: {ref_snippet}*"
            final_content = f"{reply_header}\n{final_content}"
        
        # Embeds
        embeds_to_send = [e for e in message.embeds if e.type in ('rich', 'image', 'video', 'article')]

        # Attachments
        files_data = [] # List of (filename, BytesIO)
        # Download attachments
        for att in message.attachments:
            if att.size > 8388608: # 8MB generic limit
                final_content += f"\n[Attachment too large: {att.url}]"
                continue
            
            try:
                data = await att.read()
                files_data.append((att.filename, io.BytesIO(data)))
            except Exception as e:
                logger.error(f"Failed to download: {e}")
                final_content += f"\n[Failed to download: {att.url}]"

        for dest_id in dest_ids:
            dest_channel = self.bot.get_channel(dest_id)
            if not dest_channel:
                continue
            
            # Permissions check
            try:
                if not dest_channel.permissions_for(dest_channel.guild.me).send_messages:
                     continue
            except AttributeError:
                 continue

            # File Management for this specific send
            files_to_send = []
            for fname, fbio in files_data:
                # We copy the buffer because discord.File closes it
                new_bio = io.BytesIO(fbio.getvalue())
                files_to_send.append(discord.File(fp=new_bio, filename=fname))

            try:
                pages = list(pagify(final_content))
                if not pages:
                    # Message has no content (only embeds/attachments)
                    await dest_channel.send(
                        embeds=embeds_to_send,
                        files=files_to_send,
                        allowed_mentions=discord.AllowedMentions.none() 
                    )
                else:
                    for i, page in enumerate(pages):
                        # Only send embeds and files on the last page
                        current_embeds = embeds_to_send if i == len(pages) - 1 else []
                        current_files = files_to_send if i == len(pages) - 1 else []
                        
                        await dest_channel.send(
                            content=page,
                            embeds=current_embeds,
                            files=current_files,
                            allowed_mentions=discord.AllowedMentions.none() 
                        )
            except Exception as e:
                logger.error(f"Failed to relay to {dest_channel.id}: {e}")
        
        # Cleanup original memory
        for _, fbio in files_data:
            fbio.close()

