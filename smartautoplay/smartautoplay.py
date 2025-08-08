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
                'vc': None, 'queue': [], 'current': None,
                'paused': False, 'last_active': self.bot.loop.time()
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
        desc = "\n".join(
            f"{i+1}. [{e['title']}]({e.get('url') or 'https://youtu.be/'+e['id']})"
            for i, e in enumerate(entries)
        )
        embed = discord.Embed(title="Search Results", description=desc, color=discord.Color.blurple())
        msg = await ctx.send(embed=embed)
        emojis = ['1️⃣','2️⃣','3️⃣','4️⃣','5️⃣','6️⃣']
        for emj in emojis:
            await msg.add_reaction(emj)
        def check(r, u): return u==ctx.author and r.message.id==msg.id and str(r.emoji) in emojis
        try:
            r,_ = await self.bot.wait_for('reaction_add', check=check, timeout=30)
            idx = emojis.index(str(r.emoji))
            sel = entries[idx]
            url = sel.get('url') or f"https://youtu.be/{sel['id']}"
            info = await self._get_info(url)
            track = Track(url, info.get('title'), info.get('duration',0), ctx.author.id)
            if vc.is_playing():
                player['queue'].append(track)
                await ctx.send(f"Queued: [{track.title}]({track.url})")
            else:
                await self._play(ctx.guild, track)
                await ctx.send(f"Now playing: [{track.title}]({track.url})")
        except asyncio.TimeoutError:
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
        info = await self._get_info(url)
        if not info:
            return await ctx.send("Could not fetch video info.")
        entry = {'url': url, 'title': info['title'], 'duration': info.get('duration',0)}
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

    @playlist.command()
    async def play(self, ctx, name: str):
        pls = await self.config.guild(ctx.guild).playlists()
        if name not in pls:
            return await ctx.send("No such playlist.")
        pl = pls[name]
        if not pl:
            return await ctx.send("Playlist is empty.")
        player = self.get_player(ctx.guild)
        for t in pl:
            player['queue'].append(Track(t['url'], t['title'], t['duration']))
        await ctx.send(f"Enqueued {len(pl)} tracks from `{name}`.")

    @playlist.command()
    async def remove(self, ctx, name: str, idx: int):
        pls = await self.config.guild(ctx.guild).playlists()
        if name not in pls:
            return await ctx.send("No such playlist.")
        try:
            rem = pls[name].pop(idx-1)
        except:
            return await ctx.send("Invalid index.")
        await self.config.guild(ctx.guild).playlists.set(pls)
        await ctx.send(f"Removed from `{name}`: {rem['title']}")

    @playlist.command()
    async def clear(self, ctx, name: str):
        pls = await self.config.guild(ctx.guild).playlists()
        if name not in pls:
            return await ctx.send("No such playlist.")
        pls[name] = []
        await self.config.guild(ctx.guild).playlists.set(pls)
        await ctx.send(f"Cleared playlist `{name}`.")

    @playlist.command()
    async def rename(self, ctx, old: str, new: str):
        pls = await self.config.guild(ctx.guild).playlists()
        if old not in pls:
            return await ctx.send("No such playlist.")
        if new in pls:
            return await ctx.send("New name already exists.")
        pls[new] = pls.pop(old)
        await self.config.guild(ctx.guild).playlists.set(pls)
        await ctx.send(f"Renamed `{old}` to `{new}`.")

    @commands.command()
    async def audioguide(self, ctx):
        guide = (
            "**SmartAudio Bot Guide**\n"
            "!play <url|keywords> — Play or search YouTube\n"
            "!pause/resume/stop — Playback control\n"
            "!loop — Repeat current track\n"
            "!repeatall — Repeat entire queue\n"
            "!shuffle — Shuffle queue\n"
            "!savequeue/loadqueue — Persist queue\n"
            "!queue — Interactive queue pages\n"
            "!playlist create/add/show/play/remove/clear/rename — Manage playlists\n"
            "Reactions: ⬅️➡️ page, 🗑️ remove, 1️⃣–7️⃣ add to playlists 1–7\n"
        )
        await ctx.send(box(guide, lang="ini"))

async def setup(bot):
    await bot.add_cog(SmartAudio(bot))
