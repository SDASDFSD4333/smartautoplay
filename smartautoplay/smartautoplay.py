import discord
import yt_dlp
import asyncio
import logging
import random
from datetime import timedelta
from redbot.core import commands, Config
from redbot.core.tasks import loop
from redbot.core.utils.chat_formatting import humanize_timedelta

log = logging.getLogger("red.smartaudio")

class Track:
    def __init__(self, url, title, duration, added_by=None):
        self.url = url
        self.title = title
        self.duration = duration
        self.added_by = added_by

class SmartAudio(commands.Cog):
    """Smart Audio – YouTube autoplay, search, playlists, and reaction controls."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=123456789)
        self.config.register_guild(
            queue=[],
            autoplay=True,
            repeat=False,
            repeat_one=False,
            shuffle=False,
            volume=0.5,
            playlists={}
        )
        self.players = {}
        self.idle_check.start()

    def cog_unload(self):
        self.idle_check.cancel()

    def get_player(self, guild):
        if guild.id not in self.players:
            self.players[guild.id] = {
                "vc": None,
                "queue": [],
                "current": None,
                "paused": False,
                "loop": False,
                "last_active": asyncio.get_event_loop().time()
            }
        return self.players[guild.id]

    @loop(seconds=30)
    async def idle_check(self):
        for guild in self.bot.guilds:
            vc = guild.voice_client
            if not vc or not vc.is_connected():
                continue
            if len(vc.channel.members) <= 1:
                player = self.get_player(guild)
                idle_time = asyncio.get_event_loop().time() - player.get("last_active", 0)
                if idle_time > 120:
                    await vc.disconnect()
                    log.info(f"Disconnected from {guild.name} due to inactivity.")

    async def _get_info(self, url):
        ydl_opts = {"format": "bestaudio/best", "quiet": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                return info
            except Exception as e:
                log.warning(f"yt-dlp failed: {e}")
                return None

    def _format_track(self, i, track):
        dur = humanize_timedelta(timedelta(seconds=track.duration))
        return f"{i+1}. [{track.title}]({track.url}) ({dur})"

    @commands.command()
    async def queue(self, ctx):
        player = self.get_player(ctx.guild)
        queue = player["queue"]
        current = player["current"]
        if not current and not queue:
            return await ctx.send("Nothing is currently playing.")

        page = 0
        per_page = 10

        def get_page_embed():
            start = page * per_page
            end = start + per_page
            tracks = queue[start:end]
            desc = ""
            if current:
                dur = humanize_timedelta(timedelta(seconds=current.duration))
                desc += f"**🎶 Now Playing:** [{current.title}]({current.url}) ({dur})\n\n"
            if tracks:
                desc += "**Up Next:**\n" + "\n".join(self._format_track(i + start, t) for i, t in enumerate(tracks))
            else:
                desc += "*(no tracks on this page)*"
            return discord.Embed(title="Playback Queue", description=desc)

        msg = await ctx.send(embed=get_page_embed())
        await msg.add_reaction("⬅️")
        await msg.add_reaction("➡️")
        await msg.add_reaction("🗑️")

        def check(reaction, user):
            return user == ctx.author and reaction.message.id == msg.id and str(reaction.emoji) in ["⬅️", "➡️", "🗑️"]

        while True:
            try:
                reaction, _ = await self.bot.wait_for("reaction_add", check=check, timeout=60)
                emoji = str(reaction.emoji)
                if emoji == "⬅️" and page > 0:
                    page -= 1
                elif emoji == "➡️" and (page + 1) * per_page < len(queue):
                    page += 1
                elif emoji == "🗑️":
                    index_to_remove = page * per_page
                    if queue:
                        removed = queue.pop(index_to_remove)
                        await ctx.send(f"Removed: `{removed.title}` from the queue.")
                await msg.edit(embed=get_page_embed())
                await msg.remove_reaction(emoji, ctx.author)
            except asyncio.TimeoutError:
                break

    @commands.command()
    async def audioguide(self, ctx):
        legend = (
            "**SmartAudio Bot Guide**\n"
            "🎵 `!play <url|keywords>` — Play music or search YouTube\n"
            "⏸️ `!pause`, ▶️ `!resume`, ⏹️ `!stop` — Playback control\n"
            "🔁 `!loop` — Repeat current song\n"
            "🔂 `!repeatall` — Repeat full queue\n"
            "🔀 `!shuffle` — Shuffle queue\n"
            "📥 `!savequeue`, `!loadqueue` — Persist queue\n"
            "📄 `!queue` — Show now playing + queue (interactive)\n"
            "📂 `!playlist <subcommand>` — Manage playlists\n"
            "🔢 1️⃣–7️⃣ — Add current song to Playlist 1–7\n"
            "⬅️➡️ — Scroll queue or playlist\n"
            "🗑️ — Remove top track on page\n"
        )
        await ctx.send(legend)
