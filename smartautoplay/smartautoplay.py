import asyncio
import yt_dlp
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import bold

class SmartAutoplay(commands.Cog):
    """Smart Autoplay – Plays related tracks like YouTube's Mix"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=987654321)
        self.audio_cog = None
        self.looping = {}

    async def red_get_data_for_user(self, *, user_id):
        return {}

    @commands.Cog.listener()
    async def on_red_ready(self):
        self.audio_cog = self.bot.get_cog("Audio")
        if not self.audio_cog:
            print("Audio cog not found!")

    @commands.Cog.listener()
    async def on_track_end(self, guild, track, track_error=None):
        """Trigger when a track ends and autoplay is enabled."""
        if not await self.config.guild(guild).autoplay_enabled():
            return

        title = track.title
        related_url = await self._get_related_track(title)
        if related_url:
            vc = self.audio_cog._get_player(guild)
            await vc.queue_url(related_url, guild=guild)
        else:
            await guild.system_channel.send("Couldn't find a related track!")

    @commands.group()
    async def smartplay(self, ctx):
        """Toggle autoplay settings."""
        pass

    @smartplay.command()
    async def on(self, ctx):
        await self.config.guild(ctx.guild).autoplay_enabled.set(True)
        await ctx.send("Autoplay enabled.")

    @smartplay.command()
    async def off(self, ctx):
        await self.config.guild(ctx.guild).autoplay_enabled.set(False)
        await ctx.send("Autoplay disabled.")

    async def _get_related_track(self, query):
        """Use yt-dlp to grab a related video"""
        ydl_opts = {
            "quiet": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
            "default_search": "ytsearch10",
            "forcejson": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(query, download=False)
                if "entries" in info:
                    for entry in info["entries"]:
                        return entry["url"]
            except Exception as e:
                print(f"[Autoplay Error] {e}")
                return None
