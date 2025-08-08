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
    """Smart Audio – YouTube autoplay, search, playlists, and reaction controls."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=123456789)
        self.config.register_guild(
            queue=[], autoplay=True, repeat=False, repeat_one=False,
            shuffle=False, volume=0.5, playlists={}
        )
        self.players = {}
        # start idle disconnect loop
        self._idle_task = self.bot.loop.create_task(self._idle_loop())

    def cog_unload(self):
        try:
            self._idle_task.cancel()
        except Exception:
            pass

    def get_player(self, guild):
        player = self.players.get(guild.id)
        if not player:
            player = {
                'vc': None,
                'queue': [],
                'current': None,
                'paused': False,
                'last_active': self.bot.loop.time()
            }
            self.players[guild.id] = player
        return player

    async def _idle_loop(self):
        """Background task: disconnect when alone for >2 minutes."""
        await self.bot.wait_until_red_ready()
        while True:
            for guild in self.bot.guilds:
                vc = guild.voice_client
                if vc and vc.is_connected() and len(vc.channel.members) <= 1:
                    player = self.get_player(guild)
                    idle = self.bot.loop.time() - player['last_active']
                    if idle > 120:
                        await vc.disconnect()
                        log.info(f"Disconnected from {guild.name} due to inactivity.")
            await asyncio.sleep(30)

    async def _get_info(self, url):
        ydl_opts = {'format': 'bestaudio/best', 'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                return ydl.extract_info(url, download=False)
            except Exception as e:
                log.warning(f"yt-dlp error: {e}")
                return None

    async def _search(self, query, limit=6):
        opts = {'quiet': True, 'extract_flat': True, 'skip_download': True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
                return info.get('entries', [])
            except Exception as e:
                log.warning(f"search error: {e}")
                return []

    async def _play(self, guild, track):
        player = self.get_player(guild)
        vc = guild.voice_client
        if not vc:
            return
        source = discord.FFmpegPCMAudio(track.url)
        vol = await self.config.guild(guild).volume()
        vc.source = discord.PCMVolumeTransformer(source, volume=vol)
        vc.play(vc.source, after=lambda e: self.bot.loop.create_task(self._after(guild)))
        player['current'] = track
        player['last_active'] = self.bot.loop.time()

    async def _after(self, guild):
        player = self.get_player(guild)
        queue = player['queue']
        rep = await self.config.guild(guild).repeat()
        one = await self.config.guild(guild).repeat_one()
        if one and player['current']:
            await self._play(guild, player['current'])
            return
        if rep and player['current']:
            queue.append(player['current'])
        if queue:
            nextt = queue.pop(0)
            await self._play(guild, nextt)
        else:
            player['current'] = None

    @commands.command()
    async def play(self, ctx, *, query):
        """Play a URL or search YouTube for keywords and select."""
        vc = ctx.guild.voice_client or (await ctx.author.voice.channel.connect() if ctx.author.voice else None)
        if not vc:
            return await ctx.send("Join a voice channel first.")
        player = self.get_player(ctx.guild)
        if query.startswith('http'):
            info = await self._get_info(query)
            if not info:
                return await ctx.send("Could not load video.")
            track = Track(query, info.get('title'), info.get('duration', 0), ctx.author.id)
            if vc.is_playing():
                player['queue'].append(track)
                await ctx.send(f"Queued: [{track.title}]({track.url})")
            else:
                await self._play(ctx.guild, track)
                await ctx.send(f"Now playing: [{track.title}]({track.url})")
            return
        entries = await self._search(query)
                if not entries:
            return await ctx.send("No results found.")

        # Build a newline-joined list of results
        desc = "
".join(
            f"{i+1}. [{e['title']}]({e.get('url') or 'https://youtu.be/'+e['id']})"  
            for i, e in enumerate(entries)
        )
        embed = discord.Embed(
            title="Search Results",
            description=desc,
            color=discord.Color.blurple()
        )
        msg = await ctx.send(embed=embed)
        emojis = ['1️⃣','2️⃣','3️⃣','4️⃣','5️⃣','6️⃣']
        for emj in emojis:
            await msg.add_reaction(emj)

        def check(r, u):
            return u == ctx.author and r.message.id == msg.id and str(r.emoji) in emojis

        try:
            r, _ = await self.bot.wait_for('reaction_add', check=check, timeout=30)
            idx = emojis.index(str(r.emoji))
            sel = entries[idx]
            url = sel.get('url') or f"https://youtu.be/{sel['id']}"
            info = await self._get_info(url)
            track = Track(url, info.get('title'), info.get('duration', 0), ctx.author.id)
            if vc.is_playing():
                player['queue'].append(track)
                await ctx.send(f"Queued: [{track.title}]({track.url})")
            else:
                await self._play(ctx.guild, track)
                await ctx.send(f"Now playing: [{track.title}]({track.url})")
        except asyncio.TimeoutError:
            return await ctx.send("Selection timed out.")
            return await ctx.send("Selection timed out.")

    @commands.command()
    async def pause(self, ctx):
        vc = ctx.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await ctx.send("Paused.")

    @commands.command()
    async def resume(self, ctx):
        vc = ctx.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await ctx.send("Resumed.")

    @commands.command()
    async def stop(self, ctx):
        vc = ctx.guild.voice_client
        if vc:
            vc.stop()
            await ctx.send("Stopped.")

    @commands.command()
    async def volume(self, ctx, level: float):
        level = max(0.0, min(1.0, level))
        await self.config.guild(ctx.guild).volume.set(level)
        vc = ctx.guild.voice_client
        if vc and vc.source:
            vc.source.volume = level
        await ctx.send(f"Volume set to {int(level*100)}%.")

    @commands.command()
    async def loop(self, ctx):
        cur = await self.config.guild(ctx.guild).repeat_one()
        await self.config.guild(ctx.guild).repeat_one.set(not cur)
        await ctx.send(f"Loop current: {'on' if not cur else 'off'}")

    @commands.command()
    async def repeatall(self, ctx):
        cur = await self.config.guild(ctx.guild).repeat()
        await self.config.guild(ctx.guild).repeat.set(not cur)
        await ctx.send(f"Repeat all: {'on' if not cur else 'off'}")

    @commands.command()
    async def shuffle(self, ctx):
        player = self.get_player(ctx.guild)
        random.shuffle(player['queue'])
        await ctx.send("Queue shuffled.")

    @commands.command()
    async def savequeue(self, ctx):
        player = self.get_player(ctx.guild)
        data = [vars(t) for t in player['queue']]
        await self.config.guild(ctx.guild).queue.set(data)
        await ctx.send("Queue saved.")

    @commands.command()
    async def loadqueue(self, ctx):
        raw = await self.config.guild(ctx.guild).queue()
