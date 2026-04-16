import discord
import aiohttp
import json
import logging
import os
import xml.etree.ElementTree as ET
import time
import asyncio
import re
from bs4 import BeautifulSoup
from redbot.core import commands, Config
from discord.ext import tasks

class FleetPaginationView(discord.ui.View):
    def __init__(self, pages, author, ctx=None, timeout=60):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.author = author
        self.ctx = ctx
        self.current_page = 0
        
        self.children[0].disabled = True
        self.children[1].disabled = len(pages) <= 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("Only the command sender can control this menu.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.primary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = max(0, self.current_page - 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = min(len(self.pages) - 1, self.current_page + 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    def update_buttons(self):
        self.children[0].disabled = (self.current_page == 0)
        self.children[1].disabled = (self.current_page == len(self.pages) - 1)

    async def on_timeout(self):
        try:
            if hasattr(self, 'message') and self.message:
                if hasattr(self, 'ctx') and self.ctx:
                    try:
                        await self.ctx.message.delete()
                    except Exception:
                        pass
                await self.message.delete()
        except:
            pass

class WikiSelectView(discord.ui.View):
    """Dropdown menu view for selecting a Wiki page result."""
    def __init__(self, results, author, ctx=None, timeout=60):
        super().__init__(timeout=timeout)
        self.results = results
        self.author = author
        self.ctx = ctx
        self.selected_title = None
        
        options = []
        for res in results[:25]:
            title = res.get('title')
            label = title[:100]
            value = title[:100]
            
            desc = res.get('snippet', "").replace('<span class="searchmatch">', '').replace('</span>', '')
            if len(desc) > 90:
                desc = desc[:90] + "..."
                
            options.append(discord.SelectOption(label=label, value=value, description=desc if desc else None))
            
        self.add_item(WikiSelectCallback(options))

    async def on_timeout(self):
        try:
            if hasattr(self, 'message') and self.message:
                if hasattr(self, 'ctx') and self.ctx:
                    try:
                        await self.ctx.message.delete()
                    except Exception:
                        pass
                await self.message.delete()
        except:
            pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("Only the command sender can select a result.", ephemeral=True)
            return False
        return True

class WikiSelectCallback(discord.ui.Select):
    def __init__(self, options):
        super().__init__(placeholder="Select a page...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_title = self.values[0]
        self.view.stop()
        await interaction.response.defer()

class CommoditySelectView(discord.ui.View):
    """Selection view for Trade command."""
    def __init__(self, options, author, ctx=None, timeout=60):
        super().__init__(timeout=timeout)
        self.author = author
        self.ctx = ctx
        self.selected_value = None
        self.add_item(CommoditySelectCallback(options))

    async def on_timeout(self):
        try:
            if hasattr(self, 'message') and self.message:
                if hasattr(self, 'ctx') and self.ctx:
                    try:
                        await self.ctx.message.delete()
                    except Exception:
                        pass
                await self.message.delete()
        except:
            pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("Only the command sender can select a commodity.", ephemeral=True)
            return False
        return True

class CommoditySelectCallback(discord.ui.Select):
    def __init__(self, options):
        super().__init__(placeholder="Select a commodity...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_value = self.values[0]
        self.view.stop()
        await interaction.response.defer()

class ShipSelectView(discord.ui.View):
    """Dropdown menu view for selecting a ship from search results."""
    def __init__(self, ships, author, ctx=None, timeout=60):
        super().__init__(timeout=timeout)
        self.ships = ships
        self.author = author
        self.ctx = ctx
        self.selected_ship = None
        
        options = []
        for ship in ships[:25]:
            label = f"{ship.get('name')} ({ship.get('manufacturer', {}).get('code', 'UNK')})"
            slug = ship.get('slug')
            value = slug if slug else ship.get('name')
            options.append(discord.SelectOption(label=label, value=value))
            
        self.add_item(ShipSelectCallback(options))

    async def on_timeout(self):
        try:
            if hasattr(self, 'message') and self.message:
                if hasattr(self, 'ctx') and self.ctx:
                    try:
                        await self.ctx.message.delete()
                    except Exception:
                        pass
                await self.message.delete()
        except:
            pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("Only the command sender can select a ship.", ephemeral=True)
            return False
        return True

class ShipSelectCallback(discord.ui.Select):
    def __init__(self, options):
        super().__init__(placeholder="Select a ship...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_ship = self.values[0]
        self.view.stop()
        await interaction.response.defer()

class SCDroid(commands.Cog):
    """Advanced Star Citizen integration for API telemetry and fleet management."""

    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
        self.config = Config.get_conf(self, identifier=892374982734)
        
        default_global = {
            "sc_api_key": None
        }
        self.config.register_global(**default_global)
        
        default_user = {
            "fleet": []
        }
        self.config.register_user(**default_user)
        
        self.item_cache = []
        self.item_cache_time = 0
        self.craft_cache = []
        self.craft_cache_time = 0
        self.cache_duration = 86400
        self.ship_cache = []
        self.ship_cache_path = os.path.join(os.path.dirname(__file__), "ship_cache.json")
        self.bot.loop.create_task(self.load_ship_cache())

    async def load_ship_cache(self):
        """Load ship cache from disk if available, else fetch from FleetYards."""
        try:
            if os.path.exists(self.ship_cache_path):
                with open(self.ship_cache_path, "r", encoding="utf-8") as f:
                    self.ship_cache = json.load(f)
            else:
                await self.update_ship_cache()
        except Exception as e:
            self.ship_cache = []
            print(f"Error loading ship cache: {e}")

    async def update_ship_cache(self):
        """Fetch ship data from FleetYards, populate self.ship_cache, and save to disk."""
        url_base = "https://api.fleetyards.net/v1/models?page="
        try:
            all_ships = []
            page = 1
            
            async with aiohttp.ClientSession() as session:
                while True:
                    url = f"{url_base}{page}"
                    async with session.get(url, headers={'User-Agent': 'Mozilla/5.0'}) as response:
                        if response.status != 200:
                            print(f"Error reading FleetYards API page {page}: Status {response.status}")
                            break
                            
                        data = await response.json()
                        
                        items = data if isinstance(data, list) else data.get("items", [])
                        
                        if not items or len(items) == 0:
                            break
                            
                        all_ships.extend(items)
                        page += 1
                        
                        await asyncio.sleep(0.5)

            if all_ships:
                self.ship_cache = all_ships
                with open(self.ship_cache_path, "w", encoding="utf-8") as f:
                    json.dump(self.ship_cache, f)
            else:
                print("No ships found during FleetYards update.")

        except Exception as e:
            self.ship_cache = []
            print(f"Error updating ship cache: {e}")

    @commands.Cog.listener()
    async def on_assistant_cog_add(self, cog):
        schema_trade = {
            "name": "sc_get_trade_info",
            "description": "Check the best buy and sell locations for a given Star Citizen commodity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "commodity": {
                        "type": "string",
                        "description": "The name of the commodity to check prices for (e.g., 'Laranite', 'Agricium')."
                    }
                },
                "required": ["commodity"]
            }
        }
        await cog.register_function(self.qualified_name, schema_trade)
        
        schema_status = {
            "name": "sc_get_server_status",
            "description": "Check the current status of the Star Citizen Persistent Universe components and services.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
        await cog.register_function(self.qualified_name, schema_status)

        schema_news = {
            "name": "sc_get_news",
            "description": "Get the latest news post from the RSI Comm-Link.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
        await cog.register_function(self.qualified_name, schema_news)

        schema_wiki = {
            "name": "sc_search_wiki",
            "description": "Search the Star Citizen Tools Wiki for lore or context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The info to search for on the Star Citizen wiki (e.g., 'stanton system')."
                    }
                },
                "required": ["query"]
            }
        }
        await cog.register_function(self.qualified_name, schema_wiki)

        schema_cstone = {
            "name": "sc_get_item_prices",
            "description": "Locate an item and find out where to buy it and how much it costs in the Star Citizen verse.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {
                        "type": "string",
                        "description": "The name of the item to search for (e.g., 'FS-9', 'Arrow I Missile')."
                    }
                },
                "required": ["item_name"]
            }
        }
        await cog.register_function(self.qualified_name, schema_cstone)

        schema_ship = {
            "name": "sc_get_ship_stats",
            "description": "Get the statistics for a specific Star Citizen ship.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ship_name": {
                        "type": "string",
                        "description": "The name of the ship to look up (e.g., 'Avenger Titan')."
                    }
                },
                "required": ["ship_name"]
            }
        }
        await cog.register_function(self.qualified_name, schema_ship)

        schema_user = {
            "name": "sc_get_user_profile",
            "description": "Look up a Star Citizen player's public profile by their RSI handle.",
            "parameters": {
                "type": "object",
                "properties": {
                    "handle": {
                        "type": "string",
                        "description": "The RSI handle (username) of the player to look up (e.g., 'SomePlayer123')."
                    }
                },
                "required": ["handle"]
            }
        }
        await cog.register_function(self.qualified_name, schema_user)

        schema_org = {
            "name": "sc_get_org_profile",
            "description": "Look up a Star Citizen organization's profile by its SID symbol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "The organization SID/symbol to look up (e.g., 'TEST')."
                    }
                },
                "required": ["symbol"]
            }
        }
        await cog.register_function(self.qualified_name, schema_org)

        schema_craft = {
            "name": "sc_get_craft_blueprint",
            "description": "Look up crafting blueprint requirements and materials for an item in Star Citizen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {
                        "type": "string",
                        "description": "The name of the item to look up a crafting blueprint for (e.g., 'FS-9', 'Gallium')."
                    }
                },
                "required": ["item_name"]
            }
        }
        await cog.register_function(self.qualified_name, schema_craft)

        schema_mine = {
            "name": "sc_get_mining_info",
            "description": "Look up mining locations and data for a minable element or mineral in Star Citizen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "element": {
                        "type": "string",
                        "description": "The name of the minable element to look up (e.g., 'Quantainium', 'Bexalite')."
                    }
                },
                "required": ["element"]
            }
        }
        await cog.register_function(self.qualified_name, schema_mine)

        schema_compare = {
            "name": "sc_compare_ships",
            "description": "Compare two Star Citizen ships side-by-side by their stats.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ship1": {
                        "type": "string",
                        "description": "The name of the first ship to compare (e.g., 'Avenger Titan')."
                    },
                    "ship2": {
                        "type": "string",
                        "description": "The name of the second ship to compare (e.g., 'Cutlass Black')."
                    }
                },
                "required": ["ship1", "ship2"]
            }
        }
        await cog.register_function(self.qualified_name, schema_compare)

    async def sc_get_trade_info(self, *args, **kwargs) -> str:
        """Looks up commodity trade information."""
        commodity = kwargs.get("commodity", "")
        if not commodity:
            return "Error: Commodity name not provided."
        
        api_base = "https://api.uexcorp.space/2.0"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{api_base}/commodities") as response:
                    if response.status != 200:
                        return f"Could not contact UEXCorp API (HTTP {response.status})."
                    
                    data = await response.json()
                    all_commodities = data.get("data", [])
                    
                    query = commodity.lower()
                    matches = []
                    for c in all_commodities:
                        if query in c.get("name", "").lower() or query == c.get("code", "").lower():
                            matches.append(c)
                            
                    if not matches:
                        return f"No commodity found matching '{commodity}'."
                        
                    matches.sort(key=lambda x: (x.get("name", "").lower() != query, len(x.get("name", ""))))
                    selected_commodity = matches[0]
                    c_name = selected_commodity.get("name")
                    
                async with session.get(f"{api_base}/commodities_prices", params={"commodity_name": c_name}) as price_resp:
                    if price_resp.status != 200:
                         return f"Found commodity '{c_name}', but could not fetch price data."
                    
                    price_data = await price_resp.json()
                    terminals = price_data.get("data", [])
                    
                    if not terminals:
                        return f"No active trading terminals currently report dealing with '{c_name}'."
                        
                    buys = [t for t in terminals if t.get("price_buy", 0) > 0]
                    sells = [t for t in terminals if t.get("price_sell", 0) > 0]
                    
                    buys.sort(key=lambda x: x["price_buy"])
                    sells.sort(key=lambda x: x["price_sell"], reverse=True)
                    
                    result_lines = [f"Market Data for {c_name} (Avg Price: {selected_commodity.get('price_buy', 0)} aUEC):"]
                    
                    result_lines.append("\nTop 3 Lowest Buy Locations (Where you BUY):")
                    if not buys:
                        result_lines.append("- No active buy locations")
                    for b in buys[:3]:
                        # Handle the case where the API dict structure differs from expected
                        terminal = b.get('terminal', {})
                        loc = terminal.get('name', 'Unknown')
                        if loc == 'Unknown' and isinstance(terminal, str): # API might return terminal as a string
                             loc = terminal
                        elif loc == 'Unknown':
                             # Try getting it from the parent object if terminal dict is missing/empty
                             loc = b.get('terminal_name', b.get('location_name', 'Unknown'))
                        price = b.get('price_buy', 0)
                        result_lines.append(f"- {loc}: {price} aUEC")
                        
                    result_lines.append("\nTop 3 Highest Sell Locations (Where you SELL):")
                    if not sells:
                        result_lines.append("- No active sell locations")
                    for s in sells[:3]:
                        terminal = s.get('terminal', {})
                        loc = terminal.get('name', 'Unknown')
                        if loc == 'Unknown' and isinstance(terminal, str):
                             loc = terminal
                        elif loc == 'Unknown':
                             loc = s.get('terminal_name', s.get('location_name', 'Unknown'))
                        price = s.get('price_sell', 0)
                        result_lines.append(f"- {loc}: {price} aUEC")
                        
                    return "\n".join(result_lines)
            except Exception as e:
                return f"Error while trying to fetch trade data: {e}"

    async def sc_get_server_status(self, *args, **kwargs) -> str:
        """Checks the live SC server status."""
        url = "https://status.robertsspaceindustries.com/"
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        return f"Could not retrieve status from RSI (HTTP {response.status})."
                    
                    html_content = await response.text()
                    
                    status_text = "Unknown"
                    if 'data-status="operational"' in html_content:
                        status_text = "Operational"
                    elif 'data-status="maintenance"' in html_content:
                        status_text = "Maintenance (Updates in progress)"
                    elif 'data-status="degraded"' in html_content:
                        status_text = "Degraded Performance (Experiencing issues)"
                    elif 'data-status="major"' in html_content:
                        status_text = "Major Outage (Services mostly offline)"
                        
                    result = f"Current RSI / Star Citizen Global Server Status: {status_text}\n"
                    
                    match = re.search(r'<div class="issue__header ">\s*<h3>\s*(.*?)\s*</h3>', html_content, re.DOTALL)
                    if match:
                        incident = match.group(1).strip()
                        result += f"\nRecent Incident:\n{incident}"
                        
                    return result
        except Exception as e:
            return f"Error fetching server status: {e}"

    async def sc_get_news(self, *args, **kwargs) -> str:
        """Fetches the latest Comm-Link news."""
        feed_url = "https://leonick.se/feeds/rsi/atom"
        import xml.etree.ElementTree as ET
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(feed_url) as response:
                    if response.status != 200:
                        return "Could not fetch RSI news feed."
                    
                    xml_data = await response.text()
                    root = ET.fromstring(xml_data)
                    ns = {'atom': 'http://www.w3.org/2005/Atom'}
                    
                    latest_entry = root.find('atom:entry', ns)
                    if latest_entry is None:
                        return "No news found."
                        
                    title = latest_entry.find('atom:title', ns).text
                    link = latest_entry.find('atom:link', ns).attrib['href']
                    updated = latest_entry.find('atom:updated', ns).text
                    
                    return f"**Latest RSI Comm-Link News**\nTitle: {title}\nPublished: {updated}\nLink: {link}"
        except Exception as e:
            return f"Error fetching news: {e}"

    async def sc_search_wiki(self, *args, **kwargs) -> str:
        """Looks up info on the Star Citizen Wiki."""
        query = kwargs.get("query", "")
        if not query:
            return "Error: Query not provided."

        url = "https://starcitizen.tools/api.php"
        search_params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json"
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=search_params) as response:
                    if response.status != 200:
                        return "Could not contact the Star Citizen Wiki."
                    
                    data = await response.json()
                    if "query" not in data or "search" not in data["query"] or not data["query"]["search"]:
                        return f"No wiki results found for '{query}'."
                    
                    results = data["query"]["search"]
                    top_result = results[0]
                    title = top_result["title"]
                    
                summary_params = {
                    "action": "query",
                    "prop": "extracts",
                    "exintro": "1",
                    "explaintext": "1",
                    "titles": title,
                    "format": "json"
                }
                
                async with session.get(url, params=summary_params) as summary_resp:
                    if summary_resp.status == 200:
                        sum_data = await summary_resp.json()
                        pages = sum_data.get("query", {}).get("pages", {})
                        if pages:
                            page_id = list(pages.keys())[0]
                            extract = pages[page_id].get("extract", "No summary available.")
                            return f"**Wiki Page: {title}**\n\n{extract}"
            return "Error retrieving wiki page summary."
        except Exception as e:
            return f"Error searching wiki: {e}"

    async def sc_get_item_prices(self, *args, **kwargs) -> str:
        """Looks up item prices and their locations."""
        item_name = kwargs.get("item_name", "")
        if not item_name: return "Error: Item name not provided."
        
        import time
        current_time = time.time()
        if not self.item_cache or (current_time - self.item_cache_time > self.cache_duration):
            url = "https://finder.cstone.space/GetSearch"
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            self.item_cache = await response.json(content_type=None)
                            self.item_cache_time = current_time
            except Exception as e:
                return f"Error connecting to CStone to check items: {e}"

        query = item_name.lower()
        matches = []
        for item in self.item_cache:
            if item.get('Sold') == 0: continue
            if query in item.get('name', '').lower():
                matches.append(item)
                
        matches.sort(key=lambda x: len(x['name']))
        if not matches:
            return f"No items found matching '{item_name}' that are currently sold in game."
            
        selected_item = matches[0]
        item_id = selected_item['id']
        actual_name = selected_item['name']
        
        url = f"https://finder.cstone.space/Search/{item_id}"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                         return f"Could not connect to {url}"
                    html = await resp.text()

            soup = BeautifulSoup(html, 'html.parser')
            
            pricetab = soup.find("div", class_="pricetab")
            loc_list = []
            if pricetab:
                table = pricetab.find("table")
                if table:
                    tbody = table.find("tbody")
                    if tbody:
                        for row in tbody.find_all("tr"):
                            cols = row.find_all("td")
                            if len(cols) >= 3:
                                loc_name = cols[0].text.strip()
                                price = cols[1].text.strip()
                                verified = cols[2].text.strip()
                                loc_list.append(f"- {loc_name}: {price} (Verified: {verified})")
            
            if not loc_list:
                return f"**Item found: {actual_name}**\nNo buy/sell listings currently available."
            result = f"**Item found: {actual_name}**\n\nBuy Locations:\n" + "\n".join(loc_list[:10])
            if len(loc_list) > 10:
                result += f"\n\n*(Showing 10 of {len(loc_list)} locations. See more at {url})*"
            return result
        except Exception as e:
             return f"Error fetching item details: {e}"

    async def sc_get_ship_stats(self, *args, **kwargs) -> str:
        """Looks up ship statistics."""
        ship_name = kwargs.get("ship_name", "")
        if not ship_name: return "Error: Ship name not provided."
        
        if not hasattr(self, 'ship_cache') or not self.ship_cache:
            return "Ship cache is local and not yet loaded. I need the ship_cache to answer this."

        params = ship_name.lower().split()
        matches = []
        for ship in self.ship_cache:
            name = (ship.get("name") or "").lower()
            manufacturer = (ship.get("manufacturer", {}).get("name") or "").lower()
            if all(word in name for word in params) or all(word in manufacturer for word in params) or ship_name.lower() == name:
                matches.append(ship)
                
        if not matches:
             return f"No ships found matching '{ship_name}'."
             
        matches.sort(key=lambda x: (x.get("name", "").lower() != ship_name.lower(), len(x.get("name", ""))))
        selected_ship = matches[0]
        
        name = selected_ship.get('name', 'Unknown')
        manuf = selected_ship.get("manufacturer", {}).get("name", "Unknown")
        focus = selected_ship.get("focus", "N/A")
        status = selected_ship.get("productionStatus", "Unknown").title()
        
        stats = []
        if selected_ship.get("pledgePrice"): stats.append(f"Pledge Price: ${selected_ship['pledgePrice']}")
        if selected_ship.get("price"): stats.append(f"In-Game Price: {selected_ship['price']} aUEC")
        if selected_ship.get("maxCrew"): stats.append(f"Max Crew: {selected_ship['maxCrew']}")
        if selected_ship.get("cargo"): stats.append(f"Cargo: {selected_ship['cargo']} SCU")
        if selected_ship.get("scmSpeed"): stats.append(f"SCM Speed: {selected_ship['scmSpeed']} m/s")
        if selected_ship.get("afterburnerSpeed"): stats.append(f"Max Speed: {selected_ship['afterburnerSpeed']} m/s")
        
        return f"**Ship Data: {name}**\nManufacturer: {manuf}\nFocus: {focus}\nStatus: {status}\n\nStats:\n" + "\n".join(stats)

    async def sc_get_user_profile(self, *args, **kwargs) -> str:
        """Looks up a Star Citizen player profile by RSI handle."""
        handle = kwargs.get("handle", "")
        if not handle:
            return "Error: Player handle not provided."

        api_key = await self.config.sc_api_key()
        if not api_key:
            return "Error: The SC API key has not been configured."

        url = f"https://api.starcitizen-api.com/{api_key}/v1/auto/user/{handle}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return f"Could not reach SC API (HTTP {response.status})."
                    data = await response.json()
                    if data.get("success") != 1:
                        return f"Player '{handle}' not found."
                    profile = data["data"]["profile"]
                    org = data["data"].get("organization", {})
                    result = (
                        f"**{profile.get('display', handle)}** (@{profile.get('handle', handle)})\n"
                        f"Enlisted: {profile.get('enlisted', 'N/A')[:10]}\n"
                    )
                    if org:
                        result += f"Organization: {org.get('name')} [{org.get('sid')}]"
                    return result
        except Exception as e:
            return f"Error fetching player profile: {e}"

    async def sc_get_org_profile(self, *args, **kwargs) -> str:
        """Looks up a Star Citizen organization profile by SID."""
        symbol = kwargs.get("symbol", "")
        if not symbol:
            return "Error: Organization symbol not provided."

        api_key = await self.config.sc_api_key()
        if not api_key:
            return "Error: The SC API key has not been configured."

        url = f"https://api.starcitizen-api.com/{api_key}/v1/auto/organization/{symbol}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return f"Could not reach SC API (HTTP {response.status})."
                    data = await response.json()
                    if data.get("success") != 1:
                        return f"Organization '{symbol}' not found."
                    org = data["data"]
                    headline = org.get("headline", "")
                    headline_text = str(headline).strip() if not isinstance(headline, dict) else headline.get("plaintext", "").strip()
                    focus = [org.get("primaryActivity"), org.get("secondaryActivity")]
                    focus = [f for f in focus if f]
                    return (
                        f"**{org.get('name')} [{org.get('sid')}]**\n"
                        f"Archetype: {org.get('archetype', 'N/A')} | Members: {org.get('members', 'N/A')} | Language: {org.get('lang', 'N/A')}\n"
                        + (f"Focus: {', '.join(focus)}\n" if focus else "")
                        + (f"Description: {headline_text}" if headline_text else "")
                    )
        except Exception as e:
            return f"Error fetching org profile: {e}"

    async def sc_get_craft_blueprint(self, *args, **kwargs) -> str:
        """Looks up crafting blueprint info from SCCrafter."""
        item_name = kwargs.get("item_name", "")
        if not item_name:
            return "Error: Item name not provided."

        import time as _time
        current_time = _time.time()
        if not self.craft_cache or (current_time - self.craft_cache_time > self.cache_duration):
            url = "https://sccrafter.com/Blueprints.json"
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            self.craft_cache = data.get('blueprints', [])
                            self.craft_cache_time = current_time
                        else:
                            return f"Failed to fetch blueprints (HTTP {resp.status})."
            except Exception as e:
                return f"Error reaching SCCrafter API: {e}"

        query = item_name.lower()
        matches = [bp for bp in self.craft_cache if query in bp.get("blueprintName", "").lower() or query in bp.get("internalName", "").lower()]
        if not matches:
            return f"No crafting blueprint found for '{item_name}'."

        matches.sort(key=lambda x: len(x.get("blueprintName", "")))
        bp = matches[0]
        name = bp.get("blueprintName", "Unknown")
        cat = bp.get("categoryName", "N/A")
        ct = bp.get("craftTime", {})
        time_str = f"{ct.get('days',0)}d {ct.get('hours',0)}h {ct.get('minutes',0)}m {ct.get('seconds',0)}s"

        slots = bp.get("slots", [])
        req_lines = []
        for slot in slots:
            count = slot.get("requiredCount", 1)
            for opt in slot.get("options", []):
                if opt.get("type") == "resource":
                    res = opt.get("resourceName", "Unknown Resource")
                    scu = opt.get("standardCargoUnits", 0) * count
                    req_lines.append(f"- {count}x {res} ({scu:.2f} SCU)")
                elif opt.get("type") == "item":
                    res = opt.get("entityName", "Unknown Item")
                    req_lines.append(f"- {count}x {res}")

        result = f"**Crafting Blueprint: {name}**\nCategory: {cat} | Base Time: {time_str}\n"
        if req_lines:
            result += "\nMaterials Needed:\n" + "\n".join(req_lines)
        else:
            result += "\nNo known materials required."

        if len(matches) > 1:
            result += f"\n\n*(Found {len(matches)} matching blueprints. Showing closest match.)*"
        return result

    async def sc_get_mining_info(self, *args, **kwargs) -> str:
        """Looks up mining element data from SCMDB."""
        element = kwargs.get("element", "")
        if not element:
            return "Error: Element name not provided."

        import time as _time
        current_time = _time.time()
        if not getattr(self, "mine_cache", None) or (current_time - getattr(self, "mine_cache_time", 0) > self.cache_duration):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get("https://scmdb.net/data/game-versions.json") as resp:
                        if resp.status != 200:
                            return "Failed to fetch SCMDB version index."
                        v_data = await resp.json()
                        vers = v_data[0]['version']
                    async with session.get(f"https://scmdb.net/data/mining_data-{vers}.json") as resp:
                        if resp.status != 200:
                            return "Failed to fetch SCMDB mining data."
                        self.mine_cache = await resp.json()
                        self.mine_cache_time = current_time
            except Exception as e:
                return f"Error reaching SCMDB: {e}"

        data = self.mine_cache
        elements = data.get("mineableElements", {})
        query = element.lower()
        matches = [(k, v) for k, v in elements.items() if query in v.get("name", "").lower()]
        if not matches:
            return f"No minable element found matching '{element}'."

        matches.sort(key=lambda x: len(x[1].get("name", "")))
        selected_guid, elem = matches[0]
        name = elem.get("name", "Unknown")
        rarity = elem.get("rarity", "Unknown").title()
        instability = elem.get("instability", 0.0)
        resistance = elem.get("resistance", 0.0)

        comps_info = {}
        for ck, cv in data.get("compositions", {}).items():
            part = next((p for p in cv.get("parts", []) if p.get("elementGuid") == selected_guid), None)
            if part:
                comps_info[ck] = {"q": int(part.get("qualityScale", 0) * 1000), "min": part.get("minPercent", 0), "max": part.get("maxPercent", 0)}

        locs = []
        for loc in data.get("locations", []):
            best_q = 0
            best_min = best_max = 0
            valid = False
            for g in loc.get("groups", []):
                for dep in g.get("deposits", []):
                    cid = dep.get("compositionGuid")
                    if cid in comps_info and comps_info[cid]["q"] > best_q:
                        best_q = comps_info[cid]["q"]
                        best_min = comps_info[cid]["min"]
                        best_max = comps_info[cid]["max"]
                        valid = True
            if valid and best_q >= 500:
                locs.append(f"- {loc.get('system','?')} / {loc.get('locationName','?')} (Q:{best_q}, {best_min:.1f}%-{best_max:.1f}%)")

        locs.sort()
        result = (
            f"**Mining: {name}**\n"
            f"Rarity: {rarity} | Instability: {instability:.2f} | Resistance: {resistance:.2f}\n\n"
        )
        if locs:
            result += "Top Locations (Quality ≥ 500):\n" + "\n".join(locs[:10])
            if len(locs) > 10:
                result += f"\n*(+ {len(locs)-10} more locations)*"
        else:
            result += "No known high-quality locations found."
        return result

    async def sc_compare_ships(self, *args, **kwargs) -> str:
        """Compares two ships side by side using cached ship data."""
        ship1_name = kwargs.get("ship1", "")
        ship2_name = kwargs.get("ship2", "")
        if not ship1_name or not ship2_name:
            return "Error: Two ship names are required."

        if not self.ship_cache:
            return "Ship cache is not yet loaded."

        def find_ship(query):
            params = query.lower().split()
            matches = [s for s in self.ship_cache if all(w in (s.get("name") or "").lower() for w in params)]
            if not matches:
                return None
            matches.sort(key=lambda x: (x.get("name", "").lower() != query.lower(), len(x.get("name", ""))))
            return matches[0]

        s1 = find_ship(ship1_name)
        s2 = find_ship(ship2_name)

        if not s1:
            return f"Could not find a ship matching '{ship1_name}'."
        if not s2:
            return f"Could not find a ship matching '{ship2_name}'."

        def stat(ship, key, suffix=""):
            val = ship.get(key)
            return f"{val}{suffix}" if val is not None else "N/A"

        lines = [
            f"**{s1.get('name')} vs {s2.get('name')}**",
            f"{'Stat':<20} {'Ship 1':<20} {'Ship 2'}",
            f"{'Manufacturer':<20} {(s1.get('manufacturer',{}).get('name','?')):<20} {s2.get('manufacturer',{}).get('name','?')}",
            f"{'Pledge Price':<20} ${s1.get('pledgePrice') or 'N/A':<19} ${s2.get('pledgePrice') or 'N/A'}",
            f"{'In-Game Price':<20} {stat(s1,'price',' aUEC'):<20} {stat(s2,'price',' aUEC')}",
            f"{'Max Crew':<20} {stat(s1,'maxCrew'):<20} {stat(s2,'maxCrew')}",
            f"{'Cargo':<20} {stat(s1,'cargo',' SCU'):<20} {stat(s2,'cargo',' SCU')}",
            f"{'SCM Speed':<20} {stat(s1,'scmSpeed',' m/s'):<20} {stat(s2,'scmSpeed',' m/s')}",
            f"{'Max Speed':<20} {stat(s1,'afterburnerSpeed',' m/s'):<20} {stat(s2,'afterburnerSpeed',' m/s')}",
            f"{'Status':<20} {s1.get('productionStatus','?').title():<20} {s2.get('productionStatus','?').title()}",
        ]
        return "\n".join(lines)

    def cog_unload(self):
        self.bot.loop.create_task(self.session.close())

    @commands.group(name="sc", invoke_without_command=True)
    async def sc_base(self, ctx):
        """Primary command group for all Star Citizen queries."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @sc_base.command(name="setkey")
    @commands.is_owner()
    async def sc_setkey(self, ctx, key: str):
        """Set your starcitizen-api.com API key (Bot Owner Only)."""
        await self.config.sc_api_key.set(key)
        await ctx.send("Star Citizen API key has been successfully configured.")

    @sc_base.command(name="updatecache")
    @commands.is_owner()
    async def sc_updatecache(self, ctx):
        """Force refresh the local ship cache from FleetYards (Bot Owner Only)."""
        msg = await ctx.send("Fetching new, updated ship data from FleetYards (this may take 1-2 minutes)....")
        async with ctx.typing():
            await self.update_ship_cache()
            await msg.edit(content=f"Ship cache successfully updated! Loaded {len(self.ship_cache)} ships.")

    @sc_base.command(name="user")
    async def sc_user(self, ctx, handle: str):
        """Retrieve a Star Citizen user profile."""
        api_key = await self.config.sc_api_key()
        if not api_key:
            return await ctx.send(f"The API key has not been set by the bot owner yet. Use `{ctx.clean_prefix}sc setkey`.")
            
        url = f"https://api.starcitizen-api.com/{api_key}/v1/auto/user/{handle}"
        
        async with ctx.typing():
            try:
                async with self.session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("success") == 1:
                            profile = data["data"]["profile"]
                            org = data["data"].get("organization", {})
                            
                            embed = discord.Embed(
                                title=profile.get("display", handle),
                                url=profile.get("page", {}).get("url", ""),
                                color=discord.Color.blue()
                            )
                            embed.set_thumbnail(url=profile.get("image", ""))
                            embed.add_field(name="Handle", value=profile.get("handle", "N/A"))
                            embed.add_field(name="Enlisted", value=profile.get("enlisted", "N/A")[:10])
                            
                            if org:
                                embed.add_field(name="Organization", value=f"{org.get('name')} ({org.get('sid')})", inline=False)
                            
                            await ctx.send(embed=embed)
                        else:
                            await ctx.send("User not found or API returned an error.")
                    else:
                        await ctx.send(f"Upstream API Error: HTTP {response.status}")
            except Exception as e:
                await ctx.send(f"Failed to reach the Star Citizen API: {e}")

    @sc_base.command(name="importfleet")
    async def sc_importfleet(self, ctx):
        """Import your personal fleet from a FleetYards or Hangar XPLORer JSON file."""
        if not ctx.message.attachments:
            return await ctx.send("Please attach your exported JSON file to the command message.")
            
        attachment = ctx.message.attachments[0]
        
        if not attachment.filename.lower().endswith('.json'):
            return await ctx.send("The attached file must be a .json file.")
            
        try:
            file_bytes = await attachment.read()
            fleet_data = json.loads(file_bytes)
            
            if isinstance(fleet_data, list):
                await self.config.user(ctx.author).fleet.set(fleet_data)
                
                count = len(fleet_data)
                manufacturers = set(s.get("manufacturerCode", "Unknown") for s in fleet_data if isinstance(s, dict))
                
                msg = await ctx.send(f"Successfully imported {count} ships from {len(manufacturers)} manufacturers into your personal database!")
                await msg.delete(delay=10)
                try:
                    await ctx.message.delete(delay=10)
                except:
                    pass
            else:
                msg = await ctx.send("Invalid JSON format. Expected a list structure.")
                await msg.delete(delay=10)
                try:
                    await ctx.message.delete(delay=10)
                except:
                    pass
        except json.JSONDecodeError:
            msg = await ctx.send("Failed to parse the JSON file. Ensure the file is not corrupted.")
            await msg.delete(delay=10)
            try:
                await ctx.message.delete(delay=10)
            except:
                pass

    @sc_base.group(name="myfleet", invoke_without_command=True)
    async def sc_myfleet(self, ctx):
        """View a summary of your imported fleet, including manufacturer stats."""
        fleet = await self.config.user(ctx.author).fleet()
        if not fleet:
            return await ctx.send(f"Your hangar is empty! Use `{ctx.clean_prefix}sc importfleet` to upload your JSON file.")
        
        total_ships = len(fleet)
        
        manufacturers = {}
        for ship in fleet:
            man = ship.get("manufacturerName", "Unknown")
            manufacturers[man] = manufacturers.get(man, 0) + 1
            
        sorted_man = sorted(manufacturers.items(), key=lambda x: x[1], reverse=True)
        
        embed = discord.Embed(title=f"{ctx.author.display_name}'s Fleet Summary", color=discord.Color.blue())
        
        embed.description = (
            f"**Total:**\n{total_ships} ships\n\n"
            f"**Manufacturer Focus:**\n" + 
            "\n".join([f"{man}: {count} ships" for man, count in sorted_man[:3]])
        )
        
        embed.set_footer(text=f"Use `{ctx.clean_prefix}sc myfleet list` to see individual ships.")
        msg = await ctx.send(embed=embed)
        await msg.delete(delay=60)
        try:
            await ctx.message.delete(delay=60)
        except:
            pass

    @sc_myfleet.command(name="list")
    async def sc_myfleet_list(self, ctx):
        """List all individual ships in your fleet with pagination."""
        fleet = await self.config.user(ctx.author).fleet()
        if not fleet:
            return await ctx.send(f"Your hangar is empty! Use `{ctx.clean_prefix}sc importfleet` to upload your JSON file.")
            
        sorted_fleet = sorted(fleet, key=lambda x: x.get("name", ""))
        
        pages = []
        chunk_size = 15
        chunks = [sorted_fleet[i:i + chunk_size] for i in range(0, len(sorted_fleet), chunk_size)]
        
        for i, chunk in enumerate(chunks):
            display_lines = []
            for ship in chunk:
                name = ship.get("name") or ship.get("type") or "Unknown Ship"
                custom_name = ship.get("shipName")
                
                if custom_name:
                    display_lines.append(f"**{custom_name}** ({name})")
                else:
                    display_lines.append(name)
            
            embed = discord.Embed(title=f"{ctx.author.display_name}'s Hangar", color=discord.Color.green())
            embed.description = "\n".join(display_lines)
            embed.set_footer(text=f"Page {i+1} of {len(chunks)} | Total ships: {len(sorted_fleet)}")
            pages.append(embed)

        if len(pages) > 0:
            view = FleetPaginationView(pages, ctx.author, ctx=ctx, timeout=60)
            message = await ctx.send(embed=pages[0], view=view)
            view.message = message
        else:
             await ctx.send("Your fleet is currently empty. Use `[p]fleet add` to add ships!")
    
    @sc_base.command(name="find")
    async def sc_find(self, ctx, *, query: str):
        """Search for a ship in your personal fleet."""
        fleet = await self.config.user(ctx.author).fleet()
        if not fleet:
            return await ctx.send(f"Your hangar is empty! Use `{ctx.clean_prefix}sc importfleet` to upload your JSON file.")
            
        query = query.lower()
        matches = []
        for ship in fleet:
            name = (ship.get("name") or "").lower()
            custom_name = (ship.get("shipName") or "").lower()
            manufacturer = (ship.get("manufacturerName") or "").lower()
            
            if query in name or query in custom_name or query in manufacturer:
                matches.append(ship)
        
        if not matches:
            return await ctx.send(f"No ships found matching '{query}'.")
            
        embed = discord.Embed(title=f"Fleet Search: {query}", color=discord.Color.blue())
        
        for ship in matches[:10]:
            name = ship.get("name", "Unknown")
            custom_name = ship.get("shipName")
            manufacturer = ship.get("manufacturerCode", "Unknown")
            slug = ship.get("slug")
            
            display_title = f"{name} - '{custom_name}'" if custom_name else name
            
            details = f"**Manufacturer:** {manufacturer}"
            if slug:
                details += f"\n[View on FleetYards](https://fleetyards.net/ships/{slug})"
            
            embed.add_field(name=display_title, value=details, inline=False)
            
        if len(matches) > 10:
            embed.set_footer(text=f"Showing top 10 of {len(matches)} matches.")
            
        await ctx.send(embed=embed)

    @sc_base.command(name="ship")
    async def sc_ship(self, ctx, *, ship_name: str):
        """Search for a ship (locally cached) and display its statistics."""
        if not self.ship_cache:
            await ctx.send("Ship cache is still building... please wait a moment.")
            await self.update_ship_cache()
            
        params = ship_name.lower().split()
        matches = []
        
        for ship in self.ship_cache:
            name = (ship.get("name") or "").lower()
            manufacturer = (ship.get("manufacturer", {}).get("name") or "").lower()
            code = (ship.get("manufacturer", {}).get("code") or "").lower()
            
            if all(word in name for word in params) or all(word in manufacturer for word in params) or ship_name.lower() == name:
                matches.append(ship)
        
        if not matches:
            return await ctx.send(f"No ships found matching '{ship_name}'.")

        matches.sort(key=lambda x: (x.get("name", "").lower() != ship_name.lower(), len(x.get("name", ""))))
        
        selected_ship = None
        
        if len(matches) > 1:
            view = ShipSelectView(matches, ctx.author)
            msg = await ctx.send("Multiple ships found. Please select one:", view=view)
            
            if await view.wait():
                await ctx.send("Selection timed out.")
                return
            
            selected_slug = view.selected_ship
            selected_ship = next((s for s in self.ship_cache if s.get("slug") == selected_slug or s.get("name") == selected_slug), None)
            try:
                await msg.delete()
            except:
                pass
        else:
            selected_ship = matches[0]

        if not selected_ship:
             await ctx.send("Error retrieving ship details.")
             return

        embed = discord.Embed(
            title=f"{selected_ship.get('name', 'Unknown')} ({selected_ship.get('manufacturer', {}).get('code', 'UNK')})",
            url=f"https://fleetyards.net/ships/{selected_ship.get('slug')}",
            color=discord.Color.dark_red()
        )
        
        def valid_url(url_val):
            return url_val and isinstance(url_val, str) and url_val.startswith("http")

        media = selected_ship.get("media", {})
        
        def extract_url(media_val):
            if not media_val:
                return None
            if isinstance(media_val, dict):
                val = media_val.get("url") or media_val.get("largeUrl")
            else:
                val = str(media_val)
                
            if val and isinstance(val, str) and val.endswith('/'):
                val = val[:-1]
                
            return val

        # Prefer storeImage -> fleetchartImage -> angledView -> sideView -> frontView -> base image
        image_url = extract_url(media.get("storeImage"))
        if not valid_url(image_url):
            image_url = extract_url(media.get("fleetchartImage"))
        if not valid_url(image_url):
            image_url = extract_url(media.get("angledView"))
        if not valid_url(image_url):
            image_url = extract_url(media.get("sideView"))
        if not valid_url(image_url):
            image_url = extract_url(media.get("frontView"))
        if not valid_url(image_url):
            image_url = extract_url(selected_ship.get("storeImage"))
        if not valid_url(image_url):
            image_url = extract_url(selected_ship.get("image"))
            
        if valid_url(image_url):
            embed.set_image(url=image_url)

        manufacturer = selected_ship.get("manufacturer", {}).get("name", "Unknown")
        embed.add_field(name="Manufacturer", value=manufacturer, inline=True)
        embed.add_field(name="Focus", value=selected_ship.get("focus", "N/A"), inline=True)
        embed.add_field(name="Class", value=selected_ship.get("classification", "N/A").title(), inline=True)
        
        stats = []
        
        # Helper to get nested safely
        pledge = selected_ship.get("pledgePrice")
        ingame = selected_ship.get("price")
        if pledge:
            try:
                stats.append(f"Pledge Price: ${float(pledge):,.0f}")
            except:
                stats.append(f"Pledge Price: ${pledge}")
        if ingame:
            try:
                stats.append(f"In-Game Price: {float(ingame):,.0f} aUEC")
            except:
                stats.append(f"In-Game Price: {ingame} aUEC")
                
        crew = selected_ship.get("crew", {})
        if crew and crew.get("max"):
            stats.append(f"Max Crew: {crew['max']}")
        elif selected_ship.get("maxCrew"):
            stats.append(f"Max Crew: {selected_ship['maxCrew']}")
            
        metrics = selected_ship.get("metrics", {})
        if metrics and metrics.get("cargo"):
            stats.append(f"Cargo: {metrics['cargo']} SCU")
        elif selected_ship.get("cargo"):
            stats.append(f"Cargo: {selected_ship['cargo']} SCU")
            
        speeds = selected_ship.get("speeds", {})
        if speeds and speeds.get("scmSpeed"):
            stats.append(f"SCM Speed: {speeds['scmSpeed']} m/s")
        elif selected_ship.get("scmSpeed"):
            stats.append(f"SCM Speed: {selected_ship['scmSpeed']} m/s")
            
        if speeds and speeds.get("scmSpeedBoosted"):
            stats.append(f"Max Speed: {speeds['scmSpeedBoosted']} m/s")
        elif speeds and speeds.get("afterburnerSpeed"):
            stats.append(f"Max Speed: {speeds['afterburnerSpeed']} m/s")
        elif selected_ship.get("afterburnerSpeed"):
            stats.append(f"Max Speed: {selected_ship['afterburnerSpeed']} m/s")

        embed.add_field(name="Specifications", value="\n".join(stats) or "No stats available", inline=False)
        embed.add_field(name="Status", value=selected_ship.get("productionStatus", "Unknown").title(), inline=True)
        
        await ctx.send(embed=embed)

    @sc_base.command(name="org")
    async def sc_org(self, ctx, symbol: str):
        """Retrieve a Star Citizen Organization profile."""
        api_key = await self.config.sc_api_key()
        if not api_key:
            return await ctx.send("The API key has not been set by the bot owner yet. Use `[p]sc setkey`.")
            
        url = f"https://api.starcitizen-api.com/{api_key}/v1/auto/organization/{symbol}"
        
        async with ctx.typing():
            try:
                async with self.session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("success") == 1:
                            org = data["data"]
                            
                            headline = org.get("headline", "")
                            headline_text = str(headline).strip() if not isinstance(headline, dict) else headline.get("plaintext", "").strip()
                            description_val = headline_text if headline_text else None
                            
                            embed = discord.Embed(
                                title=f"{org.get('name')} [{org.get('sid')}]",
                                url=org.get("url", ""),
                                description=description_val,
                                color=discord.Color.blurple()
                            )
                            
                            if org.get("logo"):
                                embed.set_thumbnail(url=org["logo"])
                            

                            if org.get("banner"):
                                embed.set_image(url=org["banner"])
                                
                            embed.add_field(name="Archetype", value=org.get("archetype", "N/A"), inline=True)
                            embed.add_field(name="Members", value=str(org.get("members", "N/A")), inline=True)
                            embed.add_field(name="Primary Language", value=org.get("lang", "N/A"), inline=True)
                            
                            focus = [org.get("primaryActivity"), org.get("secondaryActivity")]
                            focus = [f for f in focus if f]
                            if focus:
                                embed.add_field(name="Focus", value=", ".join(focus), inline=False)
                                
                            await ctx.send(embed=embed)
                        else:
                            await ctx.send("Organization not found or API returned an error.")
                    else:
                        await ctx.send(f"Upstream API Error: HTTP {response.status}")
            except Exception as e:
                await ctx.send(f"Failed to reach the Star Citizen API: {e}")

    @sc_base.command(name="addship")
    async def sc_addship(self, ctx, *, ship_name: str):
        """Add a ship to your personal fleet by searching FleetYards."""
        if not self.ship_cache:
            await ctx.send("Ship cache is still building... please wait a moment.")
            await self.update_ship_cache()
            
        params = ship_name.lower().split()
        matches = []
        
        for ship in self.ship_cache:
            name = (ship.get("name") or "").lower()
            if all(word in name for word in params) or ship_name.lower() == name:
                matches.append(ship)
        
        if not matches:
            return await ctx.send(f"No ships found matching '{ship_name}'.")

        matches.sort(key=lambda x: (x.get("name", "").lower() != ship_name.lower(), len(x.get("name", ""))))
        
        selected_ship = None
        
        if len(matches) > 1:
            view = ShipSelectView(matches, ctx.author, ctx=ctx)
            msg = await ctx.send("Multiple ships found. Please select one:", view=view)
            view.message = msg
            
            if await view.wait():
                msg2 = await ctx.send("Selection timed out.")
                await msg2.delete(delay=60)
                
            selected_slug = view.selected_ship
            selected_ship = next((s for s in self.ship_cache if s.get("slug") == selected_slug or s.get("name") == selected_slug), None)
            try:
                await msg.delete()
            except:
                pass
        else:
            selected_ship = matches[0]

        if not selected_ship:
             return await ctx.send("Cancelled.")
        
        new_ship = {
            "name": selected_ship.get("name"),
            "manufacturerName": selected_ship.get("manufacturer", {}).get("name", "Unknown"),
            "manufacturerCode": selected_ship.get("manufacturer", {}).get("code", "UNK"),
            "slug": selected_ship.get("slug"),
            "shipName": None
        }
        
        fleet = await self.config.user(ctx.author).fleet()
        if fleet is None:
            fleet = []
        
        fleet.append(new_ship)
        
        await self.config.user(ctx.author).fleet.set(fleet)
        await ctx.send(f"Added **{new_ship['name']}** to your fleet.")

    @sc_base.command(name="removeship")
    async def sc_removeship(self, ctx, *, ship_name: str):
        """Remove a ship from your personal fleet."""
        fleet = await self.config.user(ctx.author).fleet()
        if not fleet:
            return await ctx.send("Your hangar is empty.")
            
        found = False
        new_fleet = []
        ship_name_lower = ship_name.lower()
        
        for ship in fleet:
            if not found:
                name = (ship.get("name") or "").lower()
                custom = (ship.get("shipName") or "").lower()
                
                if ship_name_lower == name or ship_name_lower == custom or ship_name_lower in name:
                    found = True
                    continue # Remove this one
            
            new_fleet.append(ship)
            
        if found:
            await self.config.user(ctx.author).fleet.set(new_fleet)
            await ctx.send(f"Removed **{ship_name}** from your fleet.")
        else:
            await ctx.send(f"Could not find a ship named '{ship_name}' in your fleet.")


    @sc_base.command(name="craft")
    async def sc_craft(self, ctx, *, item_name: str):
        """Search for crafting blueprints via SCCrafter.
        
        Example: [p]sc craft FS-9
        """
        async with ctx.typing():
            current_time = __import__('time').time()
            if not self.craft_cache or (current_time - self.craft_cache_time > self.cache_duration):
                url = "https://sccrafter.com/Blueprints.json"
                try:
                    async with self.session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            self.craft_cache = data.get('blueprints', [])
                            self.craft_cache_time = current_time
                        else:
                            return await ctx.send(f"Failed to fetch blueprints (HTTP {resp.status}).")
                except Exception as e:
                    return await ctx.send(f"Error reaching SCCrafter API: {e}")
            
            blueprints = self.craft_cache
            query = item_name.lower()
            matches = []
            
            for bp in blueprints:
                name = bp.get("blueprintName", "").lower()
                int_name = bp.get("internalName", "").lower()
                if query in name or query in int_name:
                    matches.append(bp)
            
            if not matches:
                return await ctx.send(f"No crafting blueprint found for '{item_name}'.")
                
            # Filter matches by exactish match if many
            matches.sort(key=lambda x: len(x.get("blueprintName", "")))
            selected_bp = matches[0]
            
            if len(matches) > 1:
                options = []
                import discord
                for m in matches[:25]:
                    label = m.get('blueprintName', 'Unknown')
                    desc = f"Category: {m.get('categoryName', 'Unknown')}"
                    val = m.get('internalName', str(len(options)))
                    options.append(discord.SelectOption(label=label[:100], value=val, description=desc[:100]))
                
                class BpSelect(discord.ui.Select):
                    def __init__(self, bp_options):
                        super().__init__(placeholder="Multiple blueprints found matters... select one", options=bp_options)
                    async def callback(self, interaction: discord.Interaction):
                        self.view.selected_val = self.values[0]
                        self.view.stop()
                        
                class BpView(discord.ui.View):
                    def __init__(self, ctx, bp_options):
                        super().__init__(timeout=60)
                        self.ctx = ctx
                        self.selected_val = None
                        self.add_item(BpSelect(bp_options))
                    async def interaction_check(self, interaction: discord.Interaction) -> bool:
                        if interaction.user != self.ctx.author:
                            await interaction.response.send_message("Only the command author can select.", ephemeral=True)
                            return False
                        return True
                        
                view = BpView(ctx, options)
                prompt = discord.Embed(
                    title=f"Multiple blueprints found for '{item_name}'",
                    description="Please select the exact item below:",
                    color=discord.Color.gold()
                )
                msg = await ctx.send(embed=prompt, view=view)
                
                if await view.wait():
                    try: await msg.delete()
                    except: pass
                    return
                else:
                    val = view.selected_val
                    selected_bp = next((m for m in matches if m.get("internalName", "") == val or m.get("blueprintName", "") == val), matches[0])
                    try: await msg.delete()
                    except: pass
            
            name = selected_bp.get("blueprintName", "Unknown Blueprint")
            cat = selected_bp.get("categoryName", "N/A")
            craft_time = selected_bp.get("craftTime", {})
            time_str = f"{craft_time.get('days', 0)}d {craft_time.get('hours', 0)}h {craft_time.get('minutes', 0)}m {craft_time.get('seconds', 0)}s"
            is_reward = selected_bp.get("isReward", False)
            
            embed = __import__('discord').Embed(
                title=f"Crafting: {name}",
                color=__import__('discord').Color.green(),
                url="https://sccrafter.com/"
            )
            embed.set_author(name="SCCrafter", url="https://sccrafter.com/", icon_url="https://sccrafter.com/CrafterFavicon.png")
            embed.add_field(name="Category", value=cat, inline=True)
            embed.add_field(name="Base Time", value=time_str, inline=True)
            
            if is_reward:
                missions = selected_bp.get("rewardMissions", [])
                if missions:
                    m_list = [m.get("mission", "Unknown") for m in missions[:3]]
                    val = "\n".join(f"- {m}" for m in m_list)
                    if len(missions) > 3: val += f"\n*(+ {len(missions)-3} more)*"
                    embed.add_field(name="Source (Mission Reward)", value=val, inline=False)
            
            slots = selected_bp.get("slots", [])
            req_str = ""
            for slot in slots:
                count = slot.get("requiredCount", 1)
                for opt in slot.get("options", []):
                    if opt.get("type", "") == "resource":
                        res = opt.get("resourceName", "Unknown Resource")
                        scu = opt.get("standardCargoUnits", 0) * count
                        req_str += f"- **{count}x** {res} ({scu:.2f} SCU)\n"
                    elif opt.get("type", "") == "item":
                        res = opt.get("entityName", "Unknown Item")
                        req_str += f"- **{count}x** {res}\n"
            
            if req_str:
                embed.add_field(name="Materials Needed", value=req_str, inline=False)
            else:
                embed.add_field(name="Materials Needed", value="No known materials.", inline=False)
                
            embed.set_footer(text="Powered by sccrafter.com")
            
            await ctx.send(embed=embed)


    @sc_base.command(name="mine")
    async def sc_mine(self, ctx, *, item_name: str):
        """Search mining data and locations via SCMDB.
        
        Example: [p]sc mine quantainium
        """
        async with ctx.typing():
            current_time = __import__('time').time()
            if not getattr(self, "mine_cache", None) or (current_time - getattr(self, "mine_cache_time", 0) > self.cache_duration):
                try:
                    # 1. Fetch latest version string
                    vers_url = "https://scmdb.net/data/game-versions.json"
                    async with self.session.get(vers_url) as resp:
                        if resp.status == 200:
                            v_data = await resp.json()
                            vers = v_data[0]['version']
                        else:
                            return await ctx.send(f"Failed to fetch SCMDB version index (HTTP {resp.status}).")
                    
                    # 2. Fetch the matched json
                    mine_url = f"https://scmdb.net/data/mining_data-{vers}.json"
                    async with self.session.get(mine_url) as resp:
                        if resp.status == 200:
                            self.mine_cache = await resp.json()
                            self.mine_cache_time = current_time
                        else:
                            return await ctx.send(f"Failed to fetch SCMDB mining DB (HTTP {resp.status}).")
                except Exception as e:
                    return await ctx.send(f"Error reaching SCMDB API: {e}")
            
            data = getattr(self, "mine_cache", {})
            elements = data.get("mineableElements", {})
            query = item_name.lower()
            matches = []
            
            for k, v in elements.items():
                name = v.get("name", "").lower()
                if query in name:
                    matches.append((k, v))
            
            if not matches:
                return await ctx.send(f"No minable element found matching '{item_name}'.")

            # fuzzy resolve
            matches.sort(key=lambda x: len(x[1].get("name", "")))
            selected_guid, selected_elem = matches[0]
            
            if len(matches) > 1:
                options = []
                import discord
                for m_id, m_elem in matches[:25]:
                    label = m_elem.get('name', 'Unknown')
                    desc = f"Rarity: {m_elem.get('rarity', 'Unknown').title()}"
                    options.append(discord.SelectOption(label=label[:100], value=m_id, description=desc[:100]))
                
                class MineSelect(discord.ui.Select):
                    def __init__(self, m_opts):
                        super().__init__(placeholder="Multiple materials found... select one", options=m_opts)
                    async def callback(self, interaction: discord.Interaction):
                        self.view.selected_val = self.values[0]
                        self.view.stop()
                        
                class MineView(discord.ui.View):
                    def __init__(self, ctx, m_opts):
                        super().__init__(timeout=60)
                        self.ctx = ctx
                        self.selected_val = None
                        self.add_item(MineSelect(m_opts))
                    async def interaction_check(self, interaction: discord.Interaction) -> bool:
                        if interaction.user != self.ctx.author:
                            await interaction.response.send_message("Only the command author can select.", ephemeral=True)
                            return False
                        return True
                        
                view = MineView(ctx, options)
                prompt = discord.Embed(
                    title=f"Multiple elements found for '{item_name}'",
                    description="Please select the exact material below:",
                    color=discord.Color.gold()
                )
                msg = await ctx.send(embed=prompt, view=view)
                
                if await view.wait():
                    try: await msg.delete()
                    except: pass
                    return
                else:
                    selected_guid = view.selected_val
                    selected_elem = elements.get(selected_guid, matches[0][1])
                    try: await msg.delete()
                    except: pass

            name = selected_elem.get("name", "Unknown Element")
            rarity = selected_elem.get("rarity", "Unknown").title()
            instability = selected_elem.get("instability", 0.0)
            resistance = selected_elem.get("resistance", 0.0)
            cluster = selected_elem.get("clusterFactor", 0.0)
            opt_window = selected_elem.get("optimalWindowMidpoint", 0.0)
            sig = selected_elem.get("scanSignature", 0)
            
            # reverse compositions -> locations
            # 1. Map composition guids to their highest specific element quality and quantity
            comps_info = {}
            for ck, cv in data.get("compositions", {}).items():
                match_part = next((p for p in cv.get("parts", []) if p.get("elementGuid") == selected_guid), None)
                if match_part:
                    q = int(match_part.get("qualityScale", 0) * 1000)
                    min_q = match_part.get("minPercent", 0)
                    max_q = match_part.get("maxPercent", 0)
                    comps_info[ck] = {"q": q, "min": min_q, "max": max_q}

            # 2. Map locations with best quality
            # We want to keep sites with QUALITY >= 500
            locs_mapped = []
            for loc in data.get("locations", []):
                best_loc_q = 0
                best_loc_min = 0
                best_loc_max = 0
                has_valid_dep = False
                
                for g in loc.get("groups", []):
                    for dep in g.get("deposits", []):
                        cid = dep.get("compositionGuid")
                        if cid in comps_info:
                            cinfo = comps_info[cid]
                            if cinfo["q"] > best_loc_q:
                                best_loc_q = cinfo["q"]
                                best_loc_min = cinfo["min"]
                                best_loc_max = cinfo["max"]
                            has_valid_dep = True
                
                if has_valid_dep and best_loc_q >= 500:
                    sys_name = loc.get("system", "Unknown")
                    loc_name = loc.get("locationName", "Unknown")
                    sys_loc = f"{sys_name} / {loc_name}"
                    locs_mapped.append({
                        "sys": sys_name,
                        "loc": sys_loc,
                        "q": best_loc_q,
                        "min": best_loc_min,
                        "max": best_loc_max
                    })

            # Sort primarily by Quality (descending), then Max Quantity (descending)
            locs_mapped.sort(key=lambda x: (x["q"], x["max"]), reverse=True)

            pages = []
            chunk_size = 10
            
            if not locs_mapped:
                chunks = [[]]
            else:
                chunks = [locs_mapped[i:i + chunk_size] for i in range(0, len(locs_mapped), chunk_size)]
                
            for i, chunk in enumerate(chunks):
                embed = __import__('discord').Embed(
                    title=f"Mining: {name}",
                    color=__import__('discord').Color.orange(),
                    url="https://scmdb.net/?page=mine"
                )
                embed.set_author(name="SCMDB", url="https://scmdb.net/", icon_url="https://scmdb.net/favicon.svg")
                
                embed.add_field(name="Rarity", value=rarity, inline=True)
                embed.add_field(name="Instability", value=f"{instability:,.2f}", inline=True)
                embed.add_field(name="Resistance", value=f"{resistance:,.2f}", inline=True)
                embed.add_field(name="Opt Window", value=f"{opt_window:,.2f}", inline=True)
                embed.add_field(name="Cluster Factor", value=f"{cluster:,.2f}", inline=True)
                embed.add_field(name="Base Signature", value=f"{sig:,}", inline=True)
                
                if chunk:
                    loc_strings = []
                    for mapping in chunk:
                        loc_strings.append(f"**{mapping['loc']}** (Q: {mapping['q']}, Qty: {mapping['min']:.2f}%-{mapping['max']:.2f}%)")
                    
                    final_str = "\n".join(loc_strings)
                    embed.add_field(name=f"Top Locations ({i*chunk_size+1}-{i*chunk_size+len(chunk)} of {len(locs_mapped)})", value=final_str[:1024], inline=False)
                else:
                    embed.add_field(name="Known Locations", value="No locations found with Quality >= 500.", inline=False)

                embed.set_footer(text=f"Page {i+1} of {len(chunks)} | Data sourced from SCMDB.net")
                pages.append(embed)
            
            if len(pages) > 1:
                view = FleetPaginationView(pages, ctx.author, timeout=60)
                message = await ctx.send(embed=pages[0], view=view)
            else:
                await ctx.send(embed=pages[0])

    @sc_base.command(name="status")
    async def sc_status(self, ctx):
        """Check the current status of the Persistent Universe by scraping the RSI Status Page."""
        url = "https://status.robertsspaceindustries.com/"
        
        async with ctx.typing():
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                async with self.session.get(url, headers=headers) as response:
                    if response.status != 200:
                        return await ctx.send(f"Could not retrieve status from RSI (HTTP {response.status}).")
                    
                    html_content = await response.text()
                    
                    status_text = "Unknown"
                    color = discord.Color.greyple()
                    
                    if 'data-status="operational"' in html_content:
                        status_text = "Operational"
                        color = discord.Color.green()
                    elif 'data-status="maintenance"' in html_content:
                        status_text = "Maintenance"
                        color = discord.Color.orange()
                    elif 'data-status="degraded"' in html_content:
                        status_text = "Degraded Performance"
                        color = discord.Color.gold()
                    elif 'data-status="major"' in html_content:
                        status_text = "Major Outage"
                        color = discord.Color.red()
                        
                    embed = discord.Embed(
                        title="RSI Platform Status", 
                        url=url, 
                        color=color,
                        description=f"**Current Global Status:** {status_text}"
                    )
                    
                    match = re.search(r'<div class="issue__header ">\s*<h3>\s*(.*?)\s*</h3>', html_content, re.DOTALL)
                    if match:
                        latest_incident = match.group(1).strip()
                        embed.add_field(name="Latest Incident", value=latest_incident, inline=False)
                        
                    await ctx.send(embed=embed)

            except Exception as e:
                await ctx.send(f"Failed to reach RSI Status Page: {e}")

    @sc_base.command(name="news")
    async def sc_news(self, ctx):
        """Manually fetch the latest RSI Comm-Link post."""
        feed_url = "https://leonick.se/feeds/rsi/atom"
        
        async with ctx.typing():
            try:
                async with self.session.get(feed_url) as response:
                    if response.status != 200:
                        return await ctx.send("Could not fetch RSI news feed.")
                    
                    xml_data = await response.text()
                    root = ET.fromstring(xml_data)
                    ns = {'atom': 'http://www.w3.org/2005/Atom'}
                    
                    latest_entry = root.find('atom:entry', ns)
                    if latest_entry is None:
                        return await ctx.send("No news found.")
                        
                    title = latest_entry.find('atom:title', ns).text
                    link = latest_entry.find('atom:link', ns).attrib['href']
                    updated = latest_entry.find('atom:updated', ns).text
                    
                    embed = discord.Embed(
                        title="Latest RSI Comm-Link",
                        description=f"**[{title}]({link})**",
                        color=discord.Color.gold()
                    )
                    embed.set_footer(text=f"Published: {updated}")
                    
                    await ctx.send(embed=embed)
            except Exception as e:
                await ctx.send(f"Error fetching news: {e}")

    @sc_base.command(name="reloadships")
    @commands.is_owner()
    async def sc_reloadships(self, ctx):
        """Force a manual refresh of the ship database from FleetYards."""
        await ctx.send("Manually refreshing ship database...")
        await self.update_ship_cache()
        await ctx.send(f"Done. Cache now contains {len(self.ship_cache)} ships.")

    @sc_base.command(name="compare")
    async def sc_compare(self, ctx, *, query: str):
        """Compare two ships side-by-side. Usage: `[p]sc compare <ship1> vs <ship2>`"""
        if " vs " not in query.lower():
             return await ctx.send(f"Please separate ship names with ' vs '. Example: `{ctx.clean_prefix}sc compare titan vs cutlass`")
        
        ship1_query, ship2_query = query.split(" vs " if " vs " in query else " VS ", 1)
        
        async def get_ship(query):
            params = query.lower().split()
            matches = []
            for ship in self.ship_cache:
                name = (ship.get("name") or "").lower()
                manufacturer = (ship.get("manufacturer", {}).get("name") or "").lower()
                
                if all(word in name for word in params) or \
                   all(word in manufacturer for word in params) or \
                   query.lower() == name:
                    matches.append(ship)
            
            if not matches:
                await ctx.send(f"No ships found matching '{query}'.")
                return None
                
            matches.sort(key=lambda x: (x.get("name", "").lower() != query.lower(), len(x.get("name", ""))))
            
            if len(matches) > 1:
                view = ShipSelectView(matches, ctx.author)
                msg = await ctx.send(f"Multiple ships found for '**{query}**'. Please select one:", view=view)
                
                if await view.wait():
                    await ctx.send("Selection timed out.")
                    return None
                
                selected_slug = view.selected_ship
                selected_ship = next((s for s in self.ship_cache if s.get("slug") == selected_slug or s.get("name") == selected_slug), None)
                try:
                    await msg.delete()
                except:
                    pass
                return selected_ship
            else:
                return matches[0]

        ship1 = await get_ship(ship1_query.strip())
        if not ship1: return
        
        ship2 = await get_ship(ship2_query.strip())
        if not ship2: return
            
        embed = discord.Embed(
            title=f"Compare: {ship1['name']} vs {ship2['name']}",
            color=discord.Color.magenta()
        )
        
        def get_ship_field(ship, field):
            if field == "pledgePrice":
                return ship.get("pledgePrice")
            elif field == "ingamePrice":
                return ship.get("price")
            elif field == "scmSpeed":
                speeds = ship.get("speeds") or {}
                return speeds.get("scmSpeed") or ship.get("scmSpeed")
            elif field == "maxCrew":
                crew = ship.get("crew") or {}
                return crew.get("max") or ship.get("maxCrew")
            elif field == "cargo":
                metrics = ship.get("metrics") or {}
                return metrics.get("cargo") or ship.get("cargo")
            elif field == "length":
                metrics = ship.get("metrics") or {}
                return metrics.get("length") or ship.get("length")
            elif field == "mass":
                metrics = ship.get("metrics") or {}
                return metrics.get("mass") or ship.get("mass")
            return ship.get(field)

        def compare_val(field, label, suffix="", prefix="", reverse=False):
            v1 = get_ship_field(ship1, field)
            v2 = get_ship_field(ship2, field)
            
            val1_str = "N/A"
            val2_str = "N/A"

            n1 = None
            n2 = None
            
            if v1 is not None:
                try:
                    n1 = float(str(v1).replace('$', '').replace(',', ''))
                    if n1.is_integer():
                         val1_str = f"{int(n1):,}"
                    else:
                         val1_str = f"{n1:,.2f}"
                except:
                    val1_str = str(v1)

            if v2 is not None:
                try:
                    n2 = float(str(v2).replace('$', '').replace(',', ''))
                     # Format number nicely
                    if n2.is_integer():
                         val2_str = f"{int(n2):,}"
                    else:
                         val2_str = f"{n2:,.2f}"
                except:
                     val2_str = str(v2)

            if n1 is not None and n2 is not None:
                if n1 != n2:
                    v1_better = False
                    if reverse:
                         if n1 < n2: v1_better = True
                    else:
                         if n1 > n2: v1_better = True
                    
                    if v1_better:
                        val1_str = f"**{val1_str}** 🔼"
                    else:
                        val2_str = f"**{val2_str}** 🔼"

            p1 = prefix if val1_str != "N/A" else ""
            p2 = prefix if val2_str != "N/A" else ""
            embed.add_field(name=f"{label} (1)", value=f"{p1}{val1_str}{suffix}", inline=True)
            embed.add_field(name=f"{label} (2)", value=f"{p2}{val2_str}{suffix}", inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)

        embed.add_field(name="Ship 1", value=ship1['name'], inline=True)
        embed.add_field(name="Ship 2", value=ship2['name'], inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        compare_val("pledgePrice", "Pledge Price", prefix="$", reverse=True)
        compare_val("ingamePrice", "In-Game Price", suffix=" aUEC", reverse=True)
        compare_val("scmSpeed", "SCM Speed", " m/s")
        compare_val("maxCrew", "Max Crew", reverse=True)
        compare_val("cargo", "Cargo", " SCU")
        compare_val("length", "Length", " m", reverse=True)
        compare_val("mass", "Mass", " kg", reverse=True) 
        
        await ctx.send(embed=embed)

    @sc_base.command(name="galactapedia", aliases=["lore", "wiki"])
    async def sc_galactapedia(self, ctx, *, query: str):
        """Search the Star Citizen Tools Wiki (Lore & Info)."""
        url = "https://starcitizen.tools/api.php"
        search_params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json"
        }
        
        async with ctx.typing():
            try:
                # 1. Search for titles
                async with self.session.get(url, params=search_params) as response:
                    if response.status != 200:
                        return await ctx.send("Could not contact the Star Citizen Wiki.")
                    
                    data = await response.json()
                    
                    if "query" not in data or "search" not in data["query"] or not data["query"]["search"]:
                        return await ctx.send(f"No results found for '{query}'.")
                    
                    results = data["query"]["search"]
                    
                    results.sort(key=lambda x: (
                        0 if x["title"].lower().startswith(query.lower()) else
                        1 if query.lower() in x["title"].lower() else 
                        2, 
                        len(x["title"])
                    ))
                    
                    top_result = results[0]
                    title = top_result["title"]
                    
                    is_exact_match = title.lower() == query.lower()
                    if not is_exact_match and len(results) > 1:
                        view = WikiSelectView(results[:10], ctx.author)
                        
                        prompt_bed = discord.Embed(
                            title=f"Multiple results found for '{query}'",
                            description=f"Top match: **{title}**.\nSelect a specific page below, or I will show the top result in 15 seconds.",
                            color=discord.Color.gold()
                        )
                        msg = await ctx.send(embed=prompt_bed, view=view)
                        
                        if await view.wait():
                            try:
                                await msg.delete()
                            except:
                                pass
                        else:
                            title = view.selected_title
                            try:
                                await msg.delete()
                            except:
                                pass

                    summary_params = {
                        "action": "query",
                        "prop": "extracts|pageimages",
                        "exintro": "1",
                        "explaintext": "1",
                        "titles": title,
                        "pithumbsize": 600,
                        "format": "json"
                    }
                    
                    async with self.session.get(url, params=summary_params) as summary_resp:
                        if summary_resp.status == 200:
                            summary_data = await summary_resp.json()
                            pages = summary_data["query"]["pages"]
                            page_id = list(pages.keys())[0]
                            page_info = pages[page_id]
                            
                            extract = page_info.get("extract", "No summary available.")
                            if len(extract) > 1000:
                                extract = extract[:997] + "..."
                                
                            image_url = page_info.get("thumbnail", {}).get("source")
                            
                            wiki_url = f"https://starcitizen.tools/{title.replace(' ', '_')}"
                            official_search = f"https://robertsspaceindustries.com/galactapedia?query={query.replace(' ', '+')}"
                            
                            embed = discord.Embed(
                                title=title,
                                url=wiki_url,
                                description=extract,
                                color=discord.Color.dark_teal()
                            )
                            
                            if image_url:
                                embed.set_image(url=image_url)
                            
                            embed.add_field(
                                name="Read More", 
                                value=f"• [Star Citizen Wiki]({wiki_url})\n• [RSI Galactapedia Search]({official_search})", 
                                inline=False
                            )
                            embed.set_footer(text="Data source: starcitizen.tools")
                            
                            await ctx.send(embed=embed)
                        else:
                            await ctx.send(f"Found result **{title}**, but could not fetch details.")
                            
            except Exception as e:
                self.logger.error(f"Wiki search error: {e}")
                await ctx.send(f"An error occurred while searching: {e}")

    @sc_base.command(name="trade")
    async def sc_trade(self, ctx, *, commodity: str):
        """Check the best buy/sell locations for a commodity (User Reported)."""
        api_base = "https://api.uexcorp.space/2.0"
        
        async with ctx.typing():
            try:
                async with self.session.get(f"{api_base}/commodities") as response:
                    if response.status != 200:
                        return await ctx.send(f"Could not contact UEXCorp API (HTTP {response.status}).")
                    
                    data = await response.json()
                    all_commodities = data.get("data", [])
                    
                    matches = []
                    query = commodity.lower()
                    for c in all_commodities:
                        c_name = c.get("name", "").lower()
                        c_code = c.get("code", "").lower()
                        if query in c_name or query == c_code:
                            matches.append(c)
                            
                    if not matches:
                         return await ctx.send(f"No commodity found matching '{commodity}'.")
                         
                    matches.sort(key=lambda x: (x.get("name", "").lower() != query, len(x.get("name", ""))))
                    selected_commodity = matches[0]
                    
                    if len(matches) > 1:
                        options = []
                        for m in matches[:25]:
                            label = f"{m.get('name')} ({m.get('code')})"
                            val = m.get('name')
                            desc = f"Type: {m.get('kind', 'Unknown')}"
                            options.append(discord.SelectOption(label=label, value=val, description=desc))
                            
                        view = CommoditySelectView(options, ctx.author)
                        
                        prompt = discord.Embed(
                            title=f"Multiple commodities found for '{commodity}'",
                            description=f"Top match: **{matches[0].get('name')}**.\nSelect one below.",
                            color=discord.Color.gold()
                        )
                        msg = await ctx.send(embed=prompt, view=view)
                        
                        if await view.wait():
                            try: await msg.delete() 
                            except: pass
                        else:
                            sel_name = view.selected_value
                            selected_commodity = next((m for m in matches if m.get("name") == sel_name), matches[0])
                            try: await msg.delete()
                            except: pass

                    c_name = selected_commodity.get("name")
                    c_kind = selected_commodity.get("kind", "Resource")
                    c_slug = selected_commodity.get("slug")
                    
                    async with self.session.get(f"{api_base}/commodities_prices", params={"commodity_name": c_name}) as price_resp:
                        if price_resp.status != 200:
                             return await ctx.send(f"Could not retrieve pricing data for **{c_name}**.")
                        
                        price_data = await price_resp.json()
                        terminals = price_data.get("data", [])
                        
                        if not terminals:
                            return await ctx.send(f"No current market data available for **{c_name}**.")
                            
                        buys = [t for t in terminals if t.get("price_buy") > 0]
                        sells = [t for t in terminals if t.get("price_sell") > 0]
                        
                        buys.sort(key=lambda x: x["price_buy"])
                        sells.sort(key=lambda x: x["price_sell"], reverse=True)
                        
                        embed = discord.Embed(title=f"Market Data: {c_name}", color=discord.Color.gold())
                        embed.set_thumbnail(url=f"https://uexcorp.space/img/commodities/{c_slug}.jpg")
                        embed.add_field(name="Type", value=c_kind, inline=True)
                        embed.add_field(name="Avg Price", value=f"{selected_commodity.get('price_buy', 0):,.2f} aUEC", inline=True)
                        
                        buy_str = ""
                        if buys:
                            for t in buys[:5]:
                                loc_name = t.get("terminal_name") or t.get("city_name") or t.get("outpost_name") or "Unknown Loc"
                                sys_name = t.get("star_system_name", "Stanton")
                                price = t.get("price_buy")
                                stock = t.get("scu_sell_stock")
                                buy_str += f"**{price:,.2f}** - {loc_name} ({sys_name}) [{stock} SCU]\n"
                        else:
                            buy_str = "No buy locations listed."
                            
                        embed.add_field(name="📉 Best Places to BUY (Lowest Price)", value=buy_str, inline=False)
                        
                        sell_str = ""
                        if sells:
                            for t in sells[:5]:
                                loc_name = t.get("terminal_name") or t.get("city_name") or t.get("outpost_name") or "Unknown Loc"
                                sys_name = t.get("star_system_name", "Stanton")
                                price = t.get("price_sell")
                                demand = t.get("scu_buy_max", 0)
                                sell_str += f"**{price:,.2f}** - {loc_name} ({sys_name})\n"
                        else:
                            sell_str = "No sell locations listed."
                            
                        embed.add_field(name="📈 Best Places to SELL (Highest Price)", value=sell_str, inline=False)
                        
                        embed.set_footer(text="Data provided by UEXCorp.space | Prices are user-reported and may vary.")
                        await ctx.send(embed=embed)
                        
            except Exception as e:
                self.logger.error(f"Trade command error: {e}")
                await ctx.send(f"An error occurred looking up trade info: {e}")

    @sc_base.command(name="item", aliases=["cstone"])
    async def sc_item(self, ctx, *, item_name: str):
        """Find where to buy an item in the Verse (powered by CStone).
        
        Example: [p]sc item Arrow I Missile
        """
        async with ctx.typing():
            # 1. Fetch the big list of items from CStone's search endpoint
            # Check if cache is missing or expired
            current_time = time.time()
            if not self.item_cache or (current_time - self.item_cache_time > self.cache_duration):
                url = "https://finder.cstone.space/GetSearch"
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                self.item_cache = await resp.json(content_type=None)
                                self.item_cache_time = current_time
                except Exception as e:
                    return await ctx.send(f"Error connecting to CStone to update index: {e}")

            # Use cached data
            search_data = self.item_cache

            # 2. Filter locally based on input
            query = item_name.lower()
            matches = []
            
            for item in search_data:
                if item.get('Sold') == 0:
                    continue
                    
                if query in item['name'].lower():
                    matches.append(item)
            
            matches.sort(key=lambda x: len(x['name']))

            if not matches:
                return await ctx.send(f"No item found matching '{item_name}' that is currently sold in game.")

            # 3. Handle results
            if len(matches) == 1:
                await self.process_cstone_item(ctx, matches[0]['id'], matches[0]['name'])
            else:
                view = FuzzySelectView(ctx, matches[:25], None, self.process_cstone_item)
                msg = await ctx.send(f"Found multiple items for '{item_name}'. Please select one:", view=view)

    async def process_cstone_item(self, ctx, item_id, item_name):
        """Scrapes the detail page for a specific item ID."""
        url = f"https://finder.cstone.space/Search/{item_id}"
        
        try:
            async with ctx.typing():
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            return await ctx.send(f"Failed to load details for {item_name}.")
                        html = await resp.text()

                soup = BeautifulSoup(html, 'html.parser')
                
                # Extract Description
                description = "No description available."
                desc_label = soup.find(string=lambda t: t and "DESCRIPTION" in t)
                if desc_label:
                    parent_div = desc_label.find_parent('div')
                    if parent_div:
                        desc_div = parent_div.find_next_sibling('div')
                        if desc_div:
                           description = desc_div.get_text(strip=True)

                # Extract Image
                image_url = None
                img_tag = soup.find('img', id='img')
                if img_tag and img_tag.get('src'):
                     image_url = img_tag.get('src')
                
                if not image_url:
                    image_url = f"https://cstone.space/uifimages/{item_id}.png"

                # Extract Locations Table
                locations_text = ""
                
                pricetab = soup.find("div", class_="pricetab")
                if pricetab:
                     table = pricetab.find("table")
                     if table:
                         tbody = table.find("tbody")
                         if tbody:
                             rows = tbody.find_all("tr")
                             loc_list = []
                             for row in rows:
                                 cols = row.find_all("td")
                                 if len(cols) >= 2:
                                     loc_name = cols[0].get_text(strip=True)
                                     raw_price = cols[1].get_text(strip=True)
                                     
                                     import re
                                     numeric_str = re.sub(r'[^\d.]', '', raw_price)
                                     formatted_price = raw_price
                                     if numeric_str:
                                         try:
                                             num = float(numeric_str)
                                             formatted_price = f"{num:,.0f} aUEC"
                                         except ValueError:
                                             pass
                                     loc_list.append(f"**{loc_name}**\nPrice: {formatted_price}")
                             
                             if loc_list:
                                 pass # We'll handle building embeds with pagination

                # Create Embed
                embeds = []
                
                if not loc_list:
                    embed = discord.Embed(
                        title=item_name,
                        description=description if len(description) < 4000 else description[:4000] + "...",
                        color=discord.Color.blue(),
                        url=url
                    )
                    if image_url:
                        embed.set_thumbnail(url=image_url)
                    embed.add_field(name="Locations & Prices", value="No pricing or location data found locally.", inline=False)
                    embed.set_footer(text=f"Data from cstone.space | Item ID: {item_id[:8]}")
                    embeds.append(embed)
                else:
                    chunk_size = 5
                    chunks = [loc_list[i:i + chunk_size] for i in range(0, len(loc_list), chunk_size)]
                    
                    for idx, chunk in enumerate(chunks):
                        embed = discord.Embed(
                            title=item_name,
                            description=description if len(description) < 4000 else description[:4000] + "...",
                            color=discord.Color.blue(),
                            url=url
                        )
                        if image_url:
                            embed.set_thumbnail(url=image_url)
                        
                        locations_val = "\n\n".join(chunk)
                        embed.add_field(name="Locations & Prices", value=locations_val, inline=False)
                        embed.set_footer(text=f"Data from cstone.space | Page {idx+1}/{len(chunks)} | Item ID: {item_id[:8]}")
                        embeds.append(embed)

                if len(embeds) == 1:
                    await ctx.send(embed=embeds[0])
                else:
                    class PaginationView(discord.ui.View):
                        def __init__(self, items, ctx=None):
                            super().__init__(timeout=60)
                            self.items = items
                            self.ctx = ctx
                            self.current_page = 0
                            self._update_buttons()

                        async def on_timeout(self):
                            try:
                                if hasattr(self, 'message') and self.message:
                                    if hasattr(self, 'ctx') and self.ctx:
                                        try:
                                            await self.ctx.message.delete()
                                        except Exception:
                                            pass
                                    await self.message.delete()
                            except:
                                pass

                        def _update_buttons(self):
                            self.children[0].disabled = (self.current_page == 0)
                            self.children[1].disabled = (self.current_page == len(self.items) - 1)

                        @discord.ui.button(label='◀', style=discord.ButtonStyle.blurple)
                        async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                            self.current_page -= 1
                            self._update_buttons()
                            await interaction.response.edit_message(embed=self.items[self.current_page], view=self)

                        @discord.ui.button(label='▶', style=discord.ButtonStyle.blurple)

                        async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                            self.current_page += 1
                            self._update_buttons()
                            await interaction.response.edit_message(embed=self.items[self.current_page], view=self)
                    
                    view = PaginationView(embeds)
                    msg = await ctx.send(embed=embeds[0], view=view)

        except Exception as e:
            import traceback
            print(f"Error scraping {item_name}: {e}")
            traceback.print_exc()
            await ctx.send(f"An error occurred while fetching item details for **{item_name}**.")
class FuzzySelectView(discord.ui.View):
    def __init__(self, ctx, options, search_func, callback_func):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.options_data = options
        self.search_func = search_func
        self.callback_func = callback_func

        # Create dropdown
        select = discord.ui.Select(
            placeholder="Select a matching item...",
            min_values=1,
            max_values=1,
 options=[
                discord.SelectOption(
                   
                    label=opt['name'][:100], 
                    value=opt['id'],
                    description=f"{opt.get('Sold', '?')} locations"[:100] if isinstance(opt.get('Sold'), str) else None
                ) for opt in options[:25]
            ]
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def on_timeout(self):
        try:
            if hasattr(self, 'message') and self.message:
                if hasattr(self, 'ctx') and self.ctx:
                    try:
                        await self.ctx.message.delete()
                    except Exception:
                        pass
                await self.message.delete()
        except:
            pass

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This isn't your search!", ephemeral=True)
            return

        selected_id = interaction.data['values'][0]
        # Find the full option object to get the name
        selected_option = next(opt for opt in self.options_data if opt['id'] == selected_id)
        selected_name = selected_option['name']
        
       
        
        # Defer and run the actual logic
        await interaction.response.defer()
        # Clean up view
        await interaction.message.delete()
        
        # Trigger the callback
        await self.callback_func(self.ctx, selected_id, selected_name)
