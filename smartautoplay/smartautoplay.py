import discord
import os
# Ensure Opus library is loaded for voice encryption
if not discord.opus.is_loaded():
    for lib in ('libopus.so.0', 'libopus.so', 'opus.dll'):
        try:
            discord.opus.load_opus(lib)
            print(f"Loaded Opus library: {lib}")
            break
        except Exception:
            continue
    else:
        print("[SmartAudio Error] Could not load Opus library; install libopus.")
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
    """SmartAudio – autonomous playback with search, playlists, and autoplay."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=123456789)
        self.config.register_guild(
            queue=[], autoplay=True, repeat=False, repeat_one=False,
            shuffle=False, volume=0.5, playlists={}
        )
        self.players = {}
        # Start idle disconnect loop
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
                'vc': None, 'queue': [], 'current': None,
                'paused': False, 'last_active': self.bot.loop.time()
            }
            self.players[guild.id] = player
        return player

    async def _idle_loop(self):
        """Disconnect when alone for >5 minutes."""
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
            try:
                info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
                return info.get('entries', [])
            except Exception as e:
                log.error(f"yt-dlp search error: {e}")
                return []

    def _get_info_blocking(self, url):
        ydl_opts = {'format': 'bestaudio/best', 'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                return ydl.extract_info(url, download=False)
            except Exception as e:
                log.error(f"yt-dlp info error: {e}")
                return None

    @commands.command()
    async def play(self, ctx, *, query):
        """Play a URL or search YouTube for keywords and select."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("You need to be in a voice channel.")
        vc = ctx.guild.voice_client or await ctx.author.voice.channel.connect()
        player = self.get_player(ctx.guild)
        # URL playback
        if query.startswith('http'):
            info = await asyncio.to_thread(self._get_info_blocking, query)
            if not info:
                return await ctx.send("Could not load video.")
            track = Track(query, info.get('title'), info.get('duration',0), ctx.author.id)
        else:
            entries = await asyncio.to_thread(self._search_blocking, query, 6)
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
                track = Track(url, info.get('title'), info.get('duration',0), ctx.author.id)
            except asyncio.TimeoutError:
                return await ctx.send("Selection timed out.")
        # enqueue or play
        if vc.is_playing():
            player['queue'].append(track)
            return await ctx.send(f"Queued: [{track.title}]({track.url})")
        # play immediately
        source = discord.FFmpegPCMAudio(track.url)
        vol = await self.config.guild(ctx.guild).volume()
        vc.source = discord.PCMVolumeTransformer(source, volume=vol)
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
            await self._play(guild, player['current'])
            return
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
    async def savequeue(self, ctx):
        player = self.get_player(ctx.guild)
        data = [vars(t) for t in player['queue']]
        await self.config.guild(ctx.guild).queue.set(data)
        await ctx.send("Queue saved.")

    @commands.command()
    async def loadqueue(self, ctx):
        raw = await self.config.guild(ctx.guild).queue()
        player = self.get_player(ctx.guild)
        player['queue'] = [Track(d['url'], d['title'], d['duration'], d.get('added_by')) for d in raw]
        await ctx.send(f"Loaded {len(player['queue'])} tracks.")

    @commands.group(invoke_without_command=True)
    async def playlist(self, ctx):
        "Manage playlists. Use subcommands."
        await ctx.send_help('playlist')

    @playlist.command()
    async def create(self, ctx, name: str):
        pls = await self.config.guild(ctx.guild).playlists()
        if name in pls:
            return await ctx.send("Playlist already exists.")
        pls[name] = []
        await self.config.guild(ctx.guild).playlists.set(pls)
        await ctx.send(f"Created playlist `{name}`.")

    @playlist.command()
    async def add(self, ctx, name: str, url: str):
        pls = await self.config.guild(ctx.guild).playlists()
        if name not in pls:
            return await ctx.send("No such playlist.")
        info = await asyncio.to_thread(self._get_info_blocking, url)
        if not info:
            return await ctx.send("Could not fetch video info.")
        entry = {'url': url, 'title': info['title'], 'duration': info.get('duration', 0)}
        pls[name].append(entry)
        await self.config.guild(ctx.guild).playlists.set(pls)
        await ctx.send(f"Added to `{name}`: {entry['title']}")

    @playlist.command()
    async def show(self, ctx, name: str):
        pls = await self.config.guild(ctx.guild).playlists()
        if name not in pls:
            return await ctx.send("No such playlist.")
        pl = pls[name]
        if not pl:
            return await ctx.send("Playlist is empty.")
        lines = [
            f"{i+1}. [{t['title']}]({t['url']}) ({humanize_timedelta(timedelta(seconds=t['duration']))})"
            for i, t in enumerate(pl)
        ]
        desc = "\n".join(lines)
        await ctx.send(embed=discord.Embed(title=f"Playlist: {name}", description=desc, color=discord.Color.blurple()))

async def setup(bot):
    await bot.add_cog(SmartAudio(bot))
