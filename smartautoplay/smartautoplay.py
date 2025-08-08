import discord
import yt_dlp
import asyncio
import logging
import random
from datetime import timedelta
from redbot.core import commands, Config
from redbot.core.utils.chat_formatting import humanize_timedelta, box

log = logging.getLogger("red.smartaudio")

class Track:
    def __init__(self, url, title, duration, added_by=None):
        self.url = url
        self.title = title
        self.duration = duration
        self.added_by = added_by

class SmartAudio(commands.Cog):
    """Smart Audio – Delegates to Redbot's Audio cog for playback, with search, playlists, and autoplay."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=123456789)
        self.config.register_guild(
            queue=[], autoplay=True, repeat=False, repeat_one=False,
            shuffle=False, volume=0.5, playlists={}
        )
        self.audio_cog = None
        self.bot.loop.create_task(self._set_audio_cog())

    async def _set_audio_cog(self):
        await self.bot.wait_until_red_ready()
        self.audio_cog = self.bot.get_cog('Audio')
        if not self.audio_cog:
            log.error('Audio cog not found; SmartAudio will not function.')

    # Blocking helpers for search and info
    def _search_blocking(self, query, limit=6):
        opts = {'quiet': True, 'extract_flat': True, 'skip_download': True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
                return info.get('entries', [])
            except Exception as e:
                log.error(f"yt-dlp error searching: {e}")
                return []

    def _get_info_blocking(self, url):
        ydl_opts = {'format': 'bestaudio/best', 'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                return ydl.extract_info(url, download=False)
            except Exception as e:
                log.error(f"yt-dlp error fetching info: {e}")
                return None

            log.error('Audio cog not found; SmartAudio will not function.')

    @commands.command(name="saplay", aliases=["splay"])
    async def saplay(self, ctx, *, query):
        """SmartAudio play command (avoids core Audio play conflict)."""
        # Ensure core Audio cog is loaded
        if not self.audio_cog:
            # Try to fetch again in case it loaded later
            self.audio_cog = self.bot.get_cog('Audio') or self.bot.get_cog('audio')
        if not self.audio_cog:
            return await ctx.send("⚠️ Core Audio cog not loaded. Use `[p]load audio` first.")("⚠️ Core Audio cog not loaded. Use `[p]load audio` first.")
        # determine URL or search
        if query.startswith('http'):
            url = query
        else:
            entries = await asyncio.to_thread(self._search_blocking, query, 6)
            if not entries:
                return await ctx.send("🔍 No results found.")
            desc = "\n".join(
                f"{i+1}. [{e['title']}]({e.get('url') or 'https://youtu.be/'+e['id']})"
                for i, e in enumerate(entries)
            )
            embed = discord.Embed(title="Search Results", description=desc)
            msg = await ctx.send(embed=embed)
            emojis = ['1️⃣','2️⃣','3️⃣','4️⃣','5️⃣','6️⃣']
            for em in emojis: await msg.add_reaction(em)
            def check(r,u): return u==ctx.author and r.message.id==msg.id and str(r.emoji) in emojis
            try:
                r,_ = await self.bot.wait_for('reaction_add', check=check, timeout=30)
                url = entries[emojis.index(str(r.emoji))].get('url') or f"https://youtu.be/{entries[emojis.index(str(r.emoji))]['id']}"
            except asyncio.TimeoutError:
                return await ctx.send("⏲️ Selection timed out.")
        player = self.audio_cog._get_player(ctx.guild)
        await player.queue_url(url, guild=ctx.guild)
        await ctx.send(f"✅ Queued: <{url}>")

    @commands.command(name="sapause")
    async def sapause(self, ctx):
        """SmartAudio pause playback via core Audio cog."""
        if self.audio_cog:
            player = self.audio_cog._get_player(ctx.guild)
            await player.pause()
            await ctx.send("⏸️ Paused.")

    @commands.command(name="saresume")
    async def saresume(self, ctx):
        """SmartAudio resume playback via core Audio cog."""
        if self.audio_cog:
            player = self.audio_cog._get_player(ctx.guild)
            await player.resume()
            await ctx.send("▶️ Resumed.")

    @commands.command(name="sastop")
    async def sastop(self, ctx):
        """SmartAudio stop playback via core Audio cog."""
        if self.audio_cog:
            player = self.audio_cog._get_player(ctx.guild)
            await player.stop()
            await ctx.send("⏹️ Stopped.")

    @commands.command(name="savolume")
    async def savolume(self, ctx, level: float):
        """SmartAudio set volume via core Audio cog."""
        level = max(0.0, min(1.0, level))
        await self.config.guild(ctx.guild).volume.set(level)
        await ctx.send(f"🔈 Volume set to {int(level*100)}%.")

    @commands.command(name="sal!oop", aliases=["saloop"])
    async def saloop(self, ctx):
        """SmartAudio toggle repeat one song."""
        cur = await self.config.guild(ctx.guild).repeat_one()
        await self.config.guild(ctx.guild).repeat_one.set(not cur)
        await ctx.send(f"🔂 Repeat one: {'on' if not cur else 'off'}")

    @commands.command(name="sarepeatall")
    async def sarepeatall(self, ctx):
        """SmartAudio toggle repeat all queue."""
        cur = await self.config.guild(ctx.guild).repeat()
        await self.config.guild(ctx.guild).repeat.set(not cur)
        await ctx.send(f"🔁 Repeat all: {'on' if not cur else 'off'}")

    @commands.command(name="sashuffle")
    async def sashuffle(self, ctx):
        """SmartAudio shuffle queue."""
        player = self.audio_cog._get_player(ctx.guild)
        queue = player.queue
        random.shuffle(queue)
        await ctx.send("🔀 Queue shuffled.")

    @commands.group(name="saplaylist", invoke_without_command=True)
    async def saplaylist(self, ctx):
        """SmartAudio playlist management."""
        await ctx.send_help('saplaylist')

    @saplaylist.command(name="create")
    async def saplaylist_create(self, ctx, name: str):
        pls = await self.config.guild(ctx.guild).playlists()
        if name in pls:
            return await ctx.send("❌ Playlist exists.")
        pls[name] = []
        await self.config.guild(ctx.guild).playlists.set(pls)
        await ctx.send(f"✅ Created `{name}`.")

    @saplaylist.command(name="add")
    async def saplaylist_add(self, ctx, name: str, url: str):
        pls = await self.config.guild(ctx.guild).playlists()
        if name not in pls:
            return await ctx.send("❌ No such playlist.")
        info = await asyncio.to_thread(self._get_info_blocking, url)
        if not info:
            return await ctx.send("⚠️ Could not fetch video info.")
        pls[name].append({'url':url,'title':info['title'],'duration':info.get('duration',0)})
        await self.config.guild(ctx.guild).playlists.set(pls)
        await ctx.send(f"✅ Added to `{name}`: {info['title']}")

    @saplaylist.command(name="show")
    async def saplaylist_show(self, ctx, name: str):
        pls = await self.config.guild(ctx.guild).playlists()
        if name not in pls:
            return await ctx.send("❌ No such playlist.")
        pl = pls[name]
        if not pl:
            return await ctx.send("(empty)")
        lines = [f"{i+1}. [{t['title']}]({t['url']}) ({humanize_timedelta(timedelta(seconds=t['duration']))})" for i,t in enumerate(pl)]
        await ctx.send(box("\n".join(lines)))

async def setup(bot):
    await bot.add_cog(SmartAudio(bot))
