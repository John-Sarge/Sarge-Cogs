# Sarge-Cogs

Welcome to my collection of cogs for [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot).

## Available Cogs

| Cog | Description |
| --- | --- |
| **SCDroid** | A Star Citizen utility cog. Provides various tools and information lookups for Star Citizen. |
| **BotRelay** | Relays messages between channels using the bot account. Supports mirroring messages across different channels and servers. Based on [MsgMover](https://github.com/coffeebank/coffee-cogs/tree/master/msgmover). |

### SCDroid Features & Data Sources
`SCDroid` relies on several community and official APIs to function.
* **Ship Lookup & Comparison (`[p]sc ship`, `[p]sc compare`)**: Data provided by the [FleetYards API](https://fleetyards.net/).
* **Commodity Trading (`[p]sc trade`)**: Commodity pricing and locations provided by the [UEXCorp API](https://uexcorp.space/).
* **Item Lookup (`[p]sc item`, `[p]sc cstone`)**: In-game item prices and vendor locations provided by [Cornerstone (CStone)](https://cstone.space/).
* **Wiki Search (`[p]sc galactapedia`, `[p]sc wiki`, `[p]sc lore`)**: Lore and game info driven by the [Star Citizen Tools Wiki API](https://starcitizen.tools/).
* **User & Org Profiles (`[p]sc user`, `[p]sc org`)**: Fetched via the [starcitizen-api.com](https://starcitizen-api.com/). *(Requires Bot Owner to set an API key).*
* **News & Status (`[p]sc news`, `[p]sc status`)**: Directly fetched from RSI's Comm-Link RSS feed and the [RSI Status Page](https://status.robertsspaceindustries.com/).
* **Fleet Management (`[p]sc importfleet`, `[p]sc myfleet`, `[p]sc addship`, `[p]sc removeship`)**: Personal Discord-based hangar tracking. Supports importing JSON files from FleetYards or Hangar XPLORer.
* **Vrt-Assistant Integration**: SCDroid natively integrates with [Assistant from Vertyco](https://github.com/vertyco/vrt-cogs/tree/main/assistant). This exposes several custom AI functions to your bot (e.g. `sc_get_trade_info`, `sc_get_item_prices`, `sc_search_wiki`, `sc_get_ship_stats`, etc.), allowing natural language AI conversations about the Star Citizen universe.

## Installation

To add this repository to your Redbot and install these cogs, run the following commands in your Discord server where your bot is present:

1. Add the repository:
   ```text
   [p]repo add sarge-cogs https://github.com/John-Sarge/Sarge-Cogs
   ```
   *(Assuming your bot's prefix is `[p]`)*

2. Install the desired cog:
   ```text
   [p]cog install sarge-cogs scdroid
   [p]cog install sarge-cogs botrelay
   ```

3. Load the cog:
   ```text
   [p]load scdroid
   [p]load botrelay
   ```

## Requirements
- **Red-DiscordBot V3**
- `SCDroid` requires `beautifulsoup4`, `aiohttp`, and `discord.py`.
- `BotRelay` requires `discord.py>=2.0.0` and `manage_guild` / `manage_messages` permissions depending on your setup.

## Support
If you encounter any issues or have suggestions, please open an issue on the GitHub repository.
