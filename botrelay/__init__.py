from .botrelay import BotRelay

async def setup(bot):
    await bot.add_cog(BotRelay(bot))
