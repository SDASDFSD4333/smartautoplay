import discord
import yt_dlp
import asyncio
import logging
import random
from datetime import timedelta
from redbot.core import commands, Config
from redbot.core.utils.chat_formatting import humanize_timedelta, box

# Ensure Opus is loaded
if not discord.opus.is_loaded():
    discord.opus.load_opus('libopus.so.0')

log = logging.getLogger("red.smartaudio")

class Track:
    def __init__(self, url, title, duration, added_by=None):
        self.url = url
        self.title = title
        self.duration = duration
        self.added_by = added_by

class SmartAudio(commands.Cog):
    """SmartAudio – autonomous playback with search, queue, playlists, and autoplay."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=123456789)
        self.config.register_guild(
            autoplay=True, repeat=False, repeat_one=False, shuffle=False, volume=0.5, playlists={}, queue=[]
        )
        self.players = {}
        self.idle_task = self.bot.loop.create_task(self._idle_loop())

    def cog_unload(self):
        self.idle_task.cancel()

    def get_player(self, guild):
        player = self.players.get(guild.id)
        if not player:
            player = {'vc': None, 'queue': [], 'current': None, 'last_active': self.bot.loop.time()}
            self.players[guild.id] = player
        return player

    async def _idle_loop(self):
        await self.bot.wait_until_red_ready()
        while True:
            for guild in self.bot.guilds:
                vc = guild.voice_client
                if vc and vc.is_connected() and len(vc.channel.members) <= 1:
                    player = self.get_player(guild)
                    if self.bot.loop.time() - player['last_active'] > 300:
                        await vc.disconnect()
                        log.info(f"Disconnected from {guild.name} due to inactivity.")
            await asyncio.sleep(60)

    def _search_blocking(self, query, limit=6):
        opts = {'quiet': True, 'extract_flat': True, 'skip_download': True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            return info.get('entries', []) or []

    def _get_info_blocking(self, url):
        opts = {'format': 'bestaudio/best', 'quiet': True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    @commands.command()
    async def play(self, ctx, *, query):
        """Play a URL or search YouTube for keywords and select."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("You need to be in a voice channel.")
        channel = ctx.author.voice.channel
        vc = ctx.guild.voice_client
        if not vc:
            try:
                vc = await channel.connect()
            except discord.errors.ConnectionClosed as e:
                log.error(f"Voice handshake failed: {e}")
                return await ctx.send(
                    "🔌 Voice handshake failed (4006). "
                    "Ensure PyNaCl, libopus, and network access to Discord voice servers are correct."
                )
        player = self.get_player(ctx.guild)
        if query.startswith('http'):
            info = await asyncio.to_thread(self._get_info_blocking, query)
            track = Track(query, info.get('title'), info.get('duration', 0), ctx.author.id)
        else:
            entries = await asyncio.to_thread(self._search_blocking, query)
            if not entries:
                return await ctx.send("No results found.")
            desc = "\n".join(
                f"{i+1}. [{e['title']}]({e.get('url') or 'https://youtu.be/'+e['id']})"
                for i,e in enumerate(entries)
            )
            embed = discord.Embed(title="Search Results", description=desc)
            msg = await ctx.send(embed=embed)
            emojis = ['1️⃣','2️⃣','3️⃣','4️⃣','5️⃣','6️⃣']
            for em in emojis: await msg.add_reaction(em)
            def check(r,u): return u==ctx.author and r.message.id==msg.id and str(r.emoji) in emojis
            try:
                r,_ = await self.bot.wait_for('reaction_add', check=check, timeout=30)
                sel = entries[emojis.index(str(r.emoji))]
                url = sel.get('url') or f"https://youtu.be/{sel['id']}"
                info = await asyncio.to_thread(self._get_info_blocking, url)
                track = Track(url, info.get('title'), info.get('duration', 0), ctx.author.id)
            except asyncio.TimeoutError:
                return await ctx.send("Selection timed out.")
        if vc.is_playing():
            player['queue'].append(track)
            return await ctx.send(f"Queued: [{track.title}]({track.url})")
        source = discord.FFmpegPCMAudio(track.url)
        vc.source = discord.PCMVolumeTransformer(source, volume=await self.config.guild(ctx.guild).volume())
        vc.play(vc.source, after=lambda e: asyncio.create_task(self._after(ctx.guild)))
        player['current'] = track
        player['last_active'] = self.bot.loop.time()
        await ctx.send(f"Now playing: [{track.title}]({track.url})")

    async def _after(self, guild):
        player = self.get_player(guild)
        queue = player['queue']
        rep = await self.config.guild(guild).repeat()
        one = await self.config.guild(guild).repeat_one()
        if one and player['current']:
            return await self._play(guild, player['current'])
        if rep and player['current']:
            queue.append(player['current'])
        if queue:
            nxt = queue.pop(0)
            await self._play(guild, nxt)
        else:
            player['current'] = None

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
    async def audioguide(self, ctx):
        guide = (
            "**SmartAudio Guide**\n"
            "!play <url|keywords> — search & queue via YouTube\n"
            "!pause/resume/stop — playback control\n"
            "!loop/repeatall — repeat settings\n"
            "!shuffle — shuffle queue\n"
            """Queue commands: "Get queue and reaction controls sel..."""
        )
        await ctx.send(box(guide, lang="ini"))

async def setup(bot):
    await bot.add_cog(SmartAudio(bot))
