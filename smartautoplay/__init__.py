from .smartautoplay import SmartAutoplay

async def setup(bot):
    await bot.add_cog(SmartAutoplay(bot))
