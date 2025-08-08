import discord
import yt_dlp
import asyncio
import logging
from redbot.core import commands, Config
from redbot.core.utils.chat_formatting import box, humanize_timedelta
from datetime import timedelta
import random

log = logging.getLogger("red.smartaudio")

class Track:
    def __init__(self, url, title, duration, added_by=None):
        self.url = url
        self.title = title
        self.duration = duration
        self.added_by = added_by

class SmartAudio(commands.Cog):
    """Smart Audio – Custom autoplay, queue, playlist, and reaction-based audio controls."""

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
            playlists={},
        )
        self.players = {}
        self.page_controls = {}

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        return

    def get_player(self, guild):
        if guild.id not in self.players:
            self.players[guild.id] = {
                "vc": None,
                "current": None,
                "queue": [],
                "message": None,
                "page": 0,
            }
        return self.players[guild.id]

    async def _get_info(self, url):
        ydl_opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "noplaylist": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                return info
            except Exception as e:
                log.warning(f"yt-dlp info fetch failed: {e}")
                return None

    async def _search_youtube(self, query, limit=6):
        opts = {"quiet": True, "extract_flat": True, "skip_download": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
                return info.get("entries", [])
            except Exception as e:
                log.error(f"YouTube search failed: {e}")
                return []

    def _format_track(self, i, track):
        duration = humanize_timedelta(timedelta(seconds=track.duration)) if track.duration else "?"
        return f"{i+1}. [{track.title}]({track.url}) ({duration})"

    @commands.command()
    async def audioguide(self, ctx):
        """Show SmartAudio command & emoji help."""
        guide = (
            "**SmartAudio Commands & Emoji Reactions**\n\n"
            "`!play <keywords or URL>` — Search YouTube or play a link\n"
            "`!queue` — Show queue with ⬅️➡️ pages, 🗑️ to remove, 1️⃣-7️⃣ to save\n"
            "`!playlist` — Manage custom playlists\n"
            "`!nowplaying` — See what's playing + next\n"
            "`!repeatall`, `!loop`, `!volume` — Playback settings\n\n"
            "**Emoji Reactions:**\n"
            "⬅️ ➡️ — Page navigation\n"
            "🗑️ — Remove a track from queue/playlist\n"
            "1️⃣ 2️⃣ 3️⃣ ... — Add to playlist 1, 2, 3...\n"
            "🆘 — Show this guide"
        )
        await ctx.send(box(guide))

    @commands.command()
    async def nowplaying(self, ctx):
        """Show the current and next song."""
        player = self.get_player(ctx.guild)
        current = player["current"]
        queue = player["queue"]
        if not current:
            await ctx.send("Nothing is currently playing.")
            return
        duration = humanize_timedelta(timedelta(seconds=current.duration))
        embed = discord.Embed(title="Now Playing", description=f"[{current.title}]({current.url}) ({duration})")
        if queue:
            next_track = queue[0]
            next_dur = humanize_timedelta(timedelta(seconds=next_track.duration))
            embed.add_field(name="Next Up", value=f"[{next_track.title}]({next_track.url}) ({next_dur})")
        await ctx.send(embed=embed)

    @commands.command()
    async def queue(self, ctx):
        """Show the current queue with pagination."""
        player = self.get_player(ctx.guild)
        page = player["page"] = 0
        await self._send_queue(ctx, page)

    async def _send_queue(self, ctx, page):
        player = self.get_player(ctx.guild)
        queue = player["queue"]
        current = player["current"]
        if not current and not queue:
            await ctx.send("Queue is empty.")
            return

        per_page = 10
        start = page * per_page
        end = start + per_page
        paginated = queue[start:end]

        embed = discord.Embed(title="🎶 Music Queue", color=discord.Color.blurple())
        if current:
            dur = humanize_timedelta(timedelta(seconds=current.duration))
            embed.add_field(name="Now Playing", value=f"[{current.title}]({current.url}) ({dur})", inline=False)
        if paginated:
            lines = [self._format_track(i + start, t) for i, t in enumerate(paginated)]
            embed.add_field(name="Up Next", value="\n".join(lines), inline=False)
        embed.set_footer(text="⬅️ Prev • ➡️ Next • 🗑️ Remove • 1️⃣ Add to Playlist 1, etc.")

        if player["message"]:
            await player["message"].edit(embed=embed)
        else:
            msg = await ctx.send(embed=embed)
            player["message"] = msg
            for emoji in ["⬅️", "➡️", "🗑️", "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣"]:
                await msg.add_reaction(emoji)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot:
            return
        msg = reaction.message
        for guild in self.players:
            player = self.players[guild]
            if player.get("message") and player["message"].id == msg.id:
                await self._handle_queue_reaction(reaction, user, guild)
                break

    async def _handle_queue_reaction(self, reaction, user, guild_id):
        player = self.get_player(self.bot.get_guild(guild_id))
        emoji = str(reaction.emoji)
        if emoji == "⬅️":
            if player["page"] > 0:
                player["page"] -= 1
        elif emoji == "➡️":
            player["page"] += 1
        elif emoji == "🗑️":
            if player["queue"]:
                player["queue"].pop(0)
        elif emoji in ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣"]:
            index = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣"].index(emoji)
            playlists = await self.config.guild(self.bot.get_guild(guild_id)).playlists()
            keys = list(playlists.keys())
            if index < len(keys):
                name = keys[index]
                if player["current"]:
                    entry = {
                        "url": player["current"].url,
                        "title": player["current"].title,
                        "duration": player["current"].duration,
                    }
                    playlists[name].append(entry)
                    await self.config.guild(self.bot.get_guild(guild_id)).playlists.set(playlists)
        await self._send_queue(await self.bot.get_channel(reaction.message.channel.id).fetch_message(reaction.message.id), player["page"])
