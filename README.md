# Sarge-Cogs

Welcome to my collection of cogs for [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot).

## Available Cogs

| Cog | Description |
| --- | --- |
| **SCDroid** | A Star Citizen utility cog. Provides various tools and information lookups for Star Citizen. |
| **BotRelay** | Relays messages between channels using the bot account. Supports mirroring messages across different channels and servers. Based on [MsgMover](https://github.com/coffeebank/coffee-cogs/tree/master/msgmover). |

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
- `SCDroid` requires `beautifulsoup4`, `aiohttp`, `discord.py`, and `discord-ext-tasks`.
- `BotRelay` requires `discord.py>=2.0.0` and `manage_guild` / `manage_messages` permissions depending on your setup.

## Support
If you encounter any issues or have suggestions, please open an issue on the GitHub repository.
