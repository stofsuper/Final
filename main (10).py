import asyncio
import random
import re
import time
import json
import os
import sys
from datetime import datetime, timedelta
from highrise import BaseBot, Position, AnchorPosition
from highrise.models import SessionMetadata, User, CurrencyItem, Item
from emotes import EMOTE_DICT

# ── CONTEST DEADLINE ─────────────────────────────────────────────────
# Contest ends 2.5 days from 2026-02-26 (deadline: 2026-02-28 ~21:46 UTC)
CONTEST_DEADLINE = 1772315197  # Unix timestamp

def get_contest_countdown() -> str:
    """Returns formatted countdown string, or None if contest is over."""
    remaining = CONTEST_DEADLINE - time.time()
    if remaining <= 0:
        return None
    days    = int(remaining // 86400)
    hours   = int((remaining % 86400) // 3600)
    minutes = int((remaining % 3600) // 60)
    seconds = int(remaining % 60)
    parts = []
    if days:    parts.append(f"{days}j")
    if hours:   parts.append(f"{hours}h")
    if minutes: parts.append(f"{minutes}m")
    if not days: parts.append(f"{seconds}s")
    return " ".join(parts)


# ─────────────────────────────────────────────────────────────────────
#  PERSISTENCE HELPERS
#  All data saved to bot_data.json — reloaded on every restart
# ─────────────────────────────────────────────────────────────────────
DATA_FILE = "chikha_data.json"  # ChikhatraX own file — separate from Sikiriti

def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Persistence] Could not load {DATA_FILE}: {e}")
    return {}

def save_data(data: dict):
    try:
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, DATA_FILE)
    except Exception as e:
        print(f"[Persistence] Could not save {DATA_FILE}: {e}")


class MyBot(BaseBot):
    def __init__(self):
        super().__init__()

        # ── OWNER ────────────────────────────────────────────────────
        self.is_connected = False  # Track WebSocket connection state
        self.owner_username = "Highrisemaroc"
        self.second_owner_username = "st0f"  # Second owner with same permissions

        # ── MODERATORS ───────────────────────────────────────────────
        self.moderators = set()  # Mods have permanent VIP access

        # ── FOLLOW ───────────────────────────────────────────────────
        self.following_user = None
        self.following_username = None

        # ── MISC ─────────────────────────────────────────────────────
        self.custom_greetings = {}
        self.awaiting_greeting = []
        self.looping_users = {}
        self.user_cooldowns = {}
        self.cooldown_seconds = 2
        self.points_cooldowns = {}       # Separate cooldown just for earning points
        self.points_cooldown_seconds = 60  # 1 point max per 60 seconds from chat
        self.reaction_cooldowns = {}     # Cooldown for reaction points — 60s per user
        self.reaction_cooldown_seconds = 60
        self.emote_cooldowns = {}        # Cooldown for emote points — 60s per user
        self.emote_cooldown_seconds = 60
        self.join_points_given = set()   # Users who already got join bonus (first time only)

        # ── FLOOR MANAGEMENT ─────────────────────────────────────────
        self.vip_floor = None
        self.dance_floor = None
        self.users_dancing_on_floor = {}  # Track users auto-dancing on floor
        self.vip_warned = set()             # Track users already warned about VIP floor
        self.dance_floor_emote = None     # Current shared emote — random, changes every beat
        self.dance_beat_start = 0.0       # Timestamp of last beat — new joiners wait for next beat

        # Floor setup wizard state (two-point system)
        self.floor_setup = {
            'vip':   {'step': 0, 'point1': None},
            'dance': {'step': 0, 'point1': None},
        }

        # ── VIP ACCESS SYSTEM (tiered) ───────────────────────────────
        self.vip_permanent = set()  # Permanent VIP (500g)
        self.vip_timed = {}  # {username: expiry_timestamp}
        self.tip_totals = {}  # {username: cumulative gold tipped to bot}

        # ── TIPPING ──────────────────────────────────────────────────
        self.auto_tip_enabled = {}
        self.auto_tip_amount = {}
        self.auto_tip_interval = {}
        self.auto_tip_tasks = {}  # Stores actual asyncio Task so we can hard-cancel it

        # ── TIME TRACKING ────────────────────────────────────────────
        self.user_join_times = {}

        # ── DAWYA WORD GAME ──────────────────────────────────────────
        self.dawya_active = False          # Is the word currently "live"?
        self.dawya_claimed = False         # Has someone claimed it already this round?
        self.dawya_winner_this_round = None  # Username of this round's winner
        self.dawya_current_word = None     # The word for the current round
        self.dawya_words = [
            'dawya', 'zwina', 'mzyan', 'labas',
            'bghit', 'chkun', 'walo', 'bzaf',
            'safi', 'mrhba', '3ziza',
        ]



        # ── AUTO-RESPONSES (Moroccan Darija) ────────────────────────
        self.auto_responses = {
            'salam': ['<#ff8c00>Salam ! 👋', '<#9b59b6>Wa3likom salam! 😊', '<#00cfff>Salam, labas 3lik? ✨', '<#ff69b4>Salam! Mrhba bik! 💙'],
            'hello': ['<#f1c40f>Salam khoya! 👋', '<#00e676>Mrhba bik! 😊', '<#bf00ff>Ahlan wa sahlan! ✨'],
            'bonjour': ['<#ff4500>Salam! 👋', '<#f1c40f>Sbah lkhir! ☀️', '<#ff69b4>Mrhba bik! 😊'],
            'labas': ['<#00e676>Labas, hamdollah! 💫', '<#9b59b6>Bikhir, wenta labas? 😊', '<#ff8c00>Kolchi bikhir! ✨', '<#00cfff>Hamdollah, labas 3lik? 💙'],
            'cv': ['<#f1c40f>Bikhir hamdollah! 😊', '<#ff69b4>Labas, wenta cv? ✨', '<#bf00ff>Kolchi mezyan! 💫'],
            'kifash': ['<#00cfff>Mezyan, hamdollah! 💫', '<#ff8c00>Bikhir, wenta labas? 😊'],
            'wach': ['<#9b59b6>Labas, kolchi mezyan! 😊', '<#f1c40f>Bikhir hamdollah! ✨'],
            'bye': ['<#ff8c00>Bslama 👋', '<#00cfff>Alla ysahel 3lik! 💙', '<#9b59b6>Sir bslama! ✨', '<#ff69b4>T3awd terja3! 💫'],
            'besslama': ['<#f1c40f>Bslama! 👋', '<#bf00ff>Alla ysahel 3lik! 💙', '<#ff4500>Sir bslama ✨'],
            'au revoir': ['<#00e676>Bslama! 👋', '<#ff8c00>Alla ysahel! 💙', '<#9b59b6>T3awd terja3! ✨'],
            'merci': ['<#ff69b4>Bla jmil khoya! 😊', '<#00cfff>Ma3lich, ra7a! 💙', '<#f1c40f>Bla jmil! ✨'],
            'shukran': ['<#bf00ff>Bla jmil! 😊', '<#ff8c00>Ma3lich khoya! 💙', '<#00e676>3la rahatk! ✨'],
            'svp': ['<#ff69b4>N3am? Ana hna! 😊', '<#9b59b6>Gol liya! 👂', '<#f1c40f>Wach bghiti? ✨'],
            'afak': ['<#00cfff>N3am khoya? 😊', '<#ff4500>Gol liya! 👂', '<#bf00ff>Ana hna bach n3awnek! ✨'],
            'bot': ['<#f1c40f>N3am? Ana hna! 🤖', '<#ff8c00>Bot f khidmatk! ⚡', '<#9b59b6>Gol liya ash bghiti? 😊'],
            'mezyan': ['<#00e676>Mezyan bzaf! 😊', '<#ff69b4>Ah mezyan hamdollah! ✨', '<#bf00ff>Kolchi mezyan! 💫'],
            'mzn': ['<#ff8c00>Mezyan bzaf! 😊', '<#00cfff>Hamdollah! ✨'],
            'zwina': ['<#ff69b4>Nta zwina! 😊', '<#9b59b6>Nti zwin/a bzaf! ✨', '<#f1c40f>Kolchi zwina 3andkom! 💫'],
        }

        # ── COMPLIMENTS (Moroccan Darija) ───────────────────────────
        # ── PRESET OUTFITS (owner only — fill item IDs after running !myoutfit) ──
        # Each outfit is a list of {"type": "...", "id": "...", "amount": "1"} dicts.
        # Run !myoutfit in game to see your bot's current item IDs, then paste them here.
        self.outfits = {
            1:  [],  # !outfit1
            2:  [],  # !outfit2
            3:  [],  # !outfit3
            4:  [],  # !outfit4
            5:  [],  # !outfit5
            6:  [],  # !outfit6
            7:  [],  # !outfit7
            8:  [],  # !outfit8
            9:  [],  # !outfit9
            10: [],  # !outfit10
            11: [],  # !outfit11
            12: [],  # !outfit12
            13: [],  # !outfit13
            14: [],  # !outfit14
            15: [],  # !outfit15
            16: [],  # !outfit16
            17: [],  # !outfit17
            18: [],  # !outfit18
            19: [],  # !outfit19
            20: [],  # !outfit20
        }

        # ── BAD WORDS FILTER (Moroccan + International) ─────────────
        self.bad_words = [
            '97ba', '9ahba', 'qahba', 'kahba',
            'zaml', 'zamal', 'zamel', 'zeml', 'z4ml', 'z4mal',
            'fuck', 'bitch', 'whore', 'slut',
            'sex', 'l7wa', '7wa', 'lhwa', 'lhwa', '3ahira', 'fahisha',
            'porn', 'porno', 'xxnx', 'xnxx', 'pornhub',
            'nhwik', 'n7wik', 'hawi', '7awi',
            'kol khara', 'kolkhara', 'khara',
            'wld l97ba', 'wld l9ahba', 'bok', 'omok',
            'dick', 'pussy', 'cock', 'penis', 'vagina',
            'shit', 'asshole',
            'nik', 'nayek', 'maniak',
            'sharmouta', 'sharmota', 'mtnayak', 'zbi','tarma','zb','9lawi','mlawi','tiz','krk','fkark','zabi','zebi','zok','mtniyak',
        ]

        # ── TRUTH OR DARE (Moroccan Darija) ─────────────────────────
        self.truths = [
            "Chno hiya l7aja li bghiti tbdlha f rasek? 🤔",
            "Mn hiya l crush dyalek l'awwel f7ayatek? 💘",
            "Chno hiya l7aja li bghiti dir walakin khassek t5af? 😅",
            "Ash hiya l7aja li khssak thshm menha? 🙈",
            "Wach dar 3lik wahd chi 7aja 3jebtek bzzaf? Gol lina! 😂",
            "Chno hiya l'mousa f7ayatek daba hadi? 😬",
            "Men hiya l'insana li bagha/bagha t3ish m3aha 3omrek kollu? 💙",
            "Ash hiya l'amaniya li bagha t7a9e9ha had l'3am? 🌟",
            "Wach 3lik chi sir li ma3rfu 7ta wa7ed? Gol lina! 🤫",
            "Ash hiya l7aja li k5alik tebki bla sabab? 😢",
            "Chno hiya l'hobby li khassak tbd'a walakin 3ib 3lik? 🎭",
            "Mn hiya l'insana li bagha t3tazal menha f7ayatek? 👋",
        ]
        # ── LOAD JOKES, RIDDLES, DARES FROM JSON FILES ───────────────
        def _load_json(filename, key):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    return [item[key] for item in json.load(f)]
            except Exception as e:
                print(f"[JSON] Could not load {filename}: {e}")
                return []

        loaded_dares   = _load_json("tahadi.json",   "dare")
        loaded_jokes   = _load_json("nokat.json",    "joke")
        loaded_riddles = _load_json("swalouat.json", "riddle")
        loaded_answers = _load_json("swalouat.json", "answer")

        # Fall back to built-in dares if JSON missing
        self.dares = loaded_dares if loaded_dares else [
            "Kteb 'Ana bot w khdam bzaf!' f chat! 🤖",
            "Dir 3 emotes m5talefin f saf wa7ed! 💃",
            "3tik l'okhrin 3 compliments daba f chat! 💙",
            "Kteb message bdarija kollu b 7rouf kbar (CAPS)! 📢",
        ]
        self.jokes          = loaded_jokes    # 200 jokes from nokat.json
        self.riddles        = loaded_riddles  # 100 riddles from swalouat.json
        self.riddle_answers = loaded_answers

        # Active riddle state: {user_id: {"answer": str, "username": str}}
        self.active_riddles: dict = {}

        self.emote_dict = EMOTE_DICT
        self.emote_keys = list(self.emote_dict.keys())

        # ── LOAD PERSISTENT DATA ─────────────────────────────────────
        saved = load_data()
        self.moderators       = set(saved.get("moderators", []))
        self.vip_permanent    = set(saved.get("vip_permanent", []))
        self.vip_timed        = saved.get("vip_timed", {})
        self.tip_totals       = saved.get("tip_totals", {})
        self.user_total_time  = saved.get("user_total_time", {})
        self.user_sessions    = saved.get("user_sessions", {})
        # tip_bank removed — bot tips directly from wallet
        self.user_stats       = saved.get("user_stats", {})
        self.user_ratings     = saved.get("user_ratings", {})
        self.custom_greetings = saved.get("custom_greetings", {})
        self.vip_floor        = saved.get("vip_floor", None)
        self.dance_floor      = saved.get("dance_floor", None)
        self.bot_last_position = saved.get("bot_last_position", None)
        print("[Persistence] Data loaded from disk")

    # ─────────────────────────────────────────────────────────────────
    #  PERSISTENCE
    # ─────────────────────────────────────────────────────────────────
    def _persist(self):
        save_data({
            "moderators":       list(self.moderators),
            "vip_permanent":    list(self.vip_permanent),
            "vip_timed":        self.vip_timed,
            "tip_totals":       self.tip_totals,
            "user_total_time":  self.user_total_time,
            "user_sessions":    self.user_sessions,
            "user_stats":       self.user_stats,
            "user_ratings":     self.user_ratings,
            "custom_greetings": self.custom_greetings,
            "vip_floor":        self.vip_floor,
            "dance_floor":      self.dance_floor,
            "bot_last_position": self.bot_last_position,
        })

    async def auto_save_loop(self):
        tick = 0
        while True:
            await asyncio.sleep(60)
            try:
                if not self.is_connected:
                    continue
                tick += 1
                await self.update_all_user_times()
                self.clean_expired_vip()

                # Every 5 minutes — award 5 points to every user currently in the room
                if tick % 5 == 0 and self.user_join_times:
                    try:
                        room_users = await self.safe_get_room_users()
                        for u, _ in room_users:
                            if u.id in self.user_join_times and u.id != self.highrise.my_id:
                                self.add_rating_points(u.username, 5)
                                print(f"[Points] +5 time points → {u.username}")
                    except Exception as e:
                        print(f"[Points] Error awarding time points: {e}")

                self._persist()
                print("[Persistence] Auto-saved")
            except Exception as e:
                print(f"[Persistence] Auto-save error: {e}")

    async def position_saver_loop(self):
        """Save bot position every 5 minutes — not aggressively, avoids respawn loop."""
        while True:
            await asyncio.sleep(300)  # Every 5 minutes only
            try:
                if not self.is_connected:
                    continue
                if not self.following_user:
                    room_users = await self.safe_get_room_users()
                    bot_pos = next((p for u, p in room_users if u.id == self.highrise.my_id), None)
                    if bot_pos and hasattr(bot_pos, 'x'):
                        self.bot_last_position = {
                            'x': bot_pos.x,
                            'y': bot_pos.y,
                            'z': bot_pos.z,
                            'facing': bot_pos.facing
                        }
                        print(f"[Position] Saved ({bot_pos.x}, {bot_pos.y}, {bot_pos.z})")
            except Exception as e:
                print(f"[Position] Error saving position: {e}")

    # ─────────────────────────────────────────────────────────────────
    #  OWNER/MOD CHECK
    # ─────────────────────────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────────────
    #  GOLD BAR HELPER
    # ─────────────────────────────────────────────────────────────────
    def to_gold_bar(self, amount: int) -> str | None:
        """Convert integer amount to Highrise gold bar string.
        Only exact supported values work: 1,5,10,50,100,500,1000,5000,10000"""
        mapping = {
            1: "gold_bar_1",
            5: "gold_bar_5",
            10: "gold_bar_10",
            50: "gold_bar_50",
            100: "gold_bar_100",
            500: "gold_bar_500",
            1000: "gold_bar_1k",
            5000: "gold_bar_5000",
            10000: "gold_bar_10k",
        }
        return mapping.get(amount, None)

    async def get_wallet_gold(self) -> int:
        """Return the bot's current gold balance from its wallet. Returns 0 on failure."""
        try:
            wallet = (await self.highrise.get_wallet()).content
            for item in wallet:
                if isinstance(item, CurrencyItem) and item.type == "gold":
                    return item.amount
        except Exception as e:
            print(f"[Wallet] Could not fetch wallet: {e}")
        return 0

    def is_owner(self, user: User) -> bool:
        return (user.username.lower() == self.owner_username.lower() or
                user.username.lower() == self.second_owner_username.lower())

    def is_mod(self, user: User) -> bool:
        return user.username in self.moderators

    def is_owner_or_mod(self, user: User) -> bool:
        return self.is_owner(user) or self.is_mod(user)

    # ─────────────────────────────────────────────────────────────────
    #  COLOR GRADIENTS (Per-character coloring for public chat!)
    # ─────────────────────────────────────────────────────────────────
    def gradient_text(self, text: str, gradient_type: str = "rainbow") -> str:
        """Apply color gradient to text character by character - PUBLIC CHAT FORMAT"""
        gradients = {
            "rainbow": ["ff0000", "ff7f00", "ffff00", "00ff00", "0000ff", "4b0082", "9400d3"],
            "fire": ["ff0e3c", "ff2a4e", "ff2e51", "ff526f", "ff6347", "ff7f50"],
            "ocean": ["00affe", "00c0fe", "3ccffe", "72d7f8", "80ddfb", "a5e4f9"],
            "pink": ["ff1493", "ff69b4", "ff00ff", "ba55d3", "9370db", "dda0dd"],
            "green": ["00ff7f", "00ff00", "00dd00", "00bb00", "009900", "007700"],
            "purple": ["9400d3", "8a2be2", "9370db", "ba55d3", "dda0dd", "ee82ee"],
            "sunset": ["ff6b35", "ff8c42", "ffaa5c", "ffd97d", "fff5ba", "fffacd"],
            "cyan": ["00ffff", "00e5e5", "00cccc", "00b2b2", "009999", "008080"],
            "gold": ["ffd700", "ffed4e", "ffff00", "ffed4e", "ffd700", "ffcc00"],
        }
        
        colors = gradients.get(gradient_type, gradients["rainbow"])
        result = ""
        color_index = 0
        
        for char in text:
            # Apply color to all characters except spaces and some punctuation
            if char != " ":
                result += f"<#{colors[color_index % len(colors)]}>{char}"
                color_index += 1
            else:
                result += " "
        
        return result
    
    def random_gradient(self) -> str:
        """Get random gradient type"""
        return random.choice(["rainbow", "fire", "ocean", "pink", "green", "purple", "sunset", "cyan", "gold"])
    
    def style_greeting(self, text: str) -> str:
        """Style greeting with gradient"""
        gradient = self.random_gradient()
        return self.gradient_text(text, gradient)
    
    def style_message(self, text: str) -> str:
        """Style message with gradient"""
        gradient = self.random_gradient()
        return self.gradient_text(text, gradient)

    # ─────────────────────────────────────────────────────────────────
    #  VIP ACCESS SYSTEM
    # ─────────────────────────────────────────────────────────────────
    def has_vip_access(self, username: str) -> bool:
        """Check if user has VIP access (mod, permanent, or active timed)"""
        # Owner and mods always have access
        if username.lower() in (self.owner_username.lower(), self.second_owner_username.lower()) or username in self.moderators:
            return True
        # Permanent VIP
        if username in self.vip_permanent:
            return True
        # Timed VIP (check if not expired)
        if username in self.vip_timed:
            if time.time() < self.vip_timed[username]:
                return True
            else:
                # Expired, remove
                del self.vip_timed[username]
                return False
        return False

    def clean_expired_vip(self):
        """Remove expired VIP access"""
        current_time = time.time()
        expired = [user for user, expiry in self.vip_timed.items() if current_time >= expiry]
        for user in expired:
            del self.vip_timed[user]
        if expired:
            print(f"[VIP] Cleaned {len(expired)} expired VIP access")

    def get_vip_status_text(self, username: str) -> str:
        """Get VIP status description"""
        if username.lower() in (self.owner_username.lower(), self.second_owner_username.lower()):
            return "👑 Owner (Permanent VIP)"
        if username in self.moderators:
            return "🛡️ Moderator (Permanent VIP)"
        if username in self.vip_permanent:
            return "💎 Permanent VIP (500g)"
        if username in self.vip_timed:
            expiry = self.vip_timed[username]
            remaining = expiry - time.time()
            if remaining > 0:
                days = int(remaining / 86400)
                hours = int((remaining % 86400) / 3600)
                if days > 0:
                    return f"⏰ VIP Access: {days}d {hours}h remaining"
                else:
                    return f"⏰ VIP Access: {hours}h remaining"
        return "❌ No VIP Access"

    # ─────────────────────────────────────────────────────────────────
    #  STARTUP
    # ─────────────────────────────────────────────────────────────────
    async def _restore_position(self, pos: dict):
        """Walk to spawn position once on startup — no retry loop to avoid respawn spam."""
        await asyncio.sleep(4)  # Let room fully load first
        try:
            x, y, z = pos['x'], pos['y'], pos['z']
            facing = pos.get('facing', 'FrontRight')
            await self.highrise.walk_to(Position(x, y, z, facing))
            print(f"[Position] Moved to ({x}, {y}, {z}, {facing})")
        except Exception as e:
            print(f"[Position] Could not restore position: {e}")

    async def safe_get_room_users(self):
        """Safely call get_room_users — returns empty list if disconnected or API fails."""
        if not self.is_connected:
            return []
        try:
            result = await asyncio.wait_for(self.highrise.get_room_users(), timeout=8.0)
            if not hasattr(result, "content"):
                err_msg = str(result).lower()
                if "not in room" in err_msg:
                    # Bot lost room membership — flag as disconnected to stop hammering API
                    self.is_connected = False
                    print("[API] Not in room — suppressing API calls until reconnect")
                else:
                    print(f"[API] get_room_users returned error: {result}")
                return []
            return result.content
        except asyncio.TimeoutError:
            print("[API] get_room_users timed out")
            return []
        except Exception as e:
            err = str(e).lower()
            if "closing transport" in err or "not connected" in err or "not in room" in err:
                self.is_connected = False
                print("[API] Connection lost — suppressing further API calls until reconnect")
            else:
                print(f"[API] get_room_users error: {e}")
            return []

    async def keep_alive(self):
        """Pings the room every 60 seconds — 10s caused rate-limit disconnects."""
        while True:
            await asyncio.sleep(60)
            try:
                if not self.is_connected:
                    await asyncio.sleep(5)
                    continue
                result = await asyncio.wait_for(self.highrise.get_room_users(), timeout=8.0)
                if hasattr(result, "content"):
                    print("[KeepAlive] Ping OK")
                else:
                    err_msg = str(result).lower()
                    if "not in room" in err_msg:
                        self.is_connected = False
                        print("[KeepAlive] Not in room — waiting for reconnect")
                    else:
                        print(f"[KeepAlive] Unexpected response: {result}")
            except asyncio.TimeoutError:
                print("[KeepAlive] Ping timed out")
            except Exception as e:
                err = str(e).lower()
                if "closing transport" in err or "not connected" in err or "not in room" in err:
                    self.is_connected = False
                    print("[KeepAlive] Connection closed — waiting for reconnect")
                else:
                    print(f"[KeepAlive] Error: {e}")

    async def on_start(self, session_metadata: SessionMetadata):
        self.is_connected = True
        print("Bot fully loaded!")
        await self.highrise.chat("<#ff2200> Talit ala wladi o jit andi<#ff3300>16 bnt o dri 8 f lhbs o lb9i khadamin ala rasshom  🌟")
        
        # Restore bot position
        target_pos = None
        if self.bot_last_position:
            target_pos = {
                'x': float(self.bot_last_position['x']),
                'y': round(float(self.bot_last_position['y']), 1),
                'z': float(self.bot_last_position['z']),
                'facing': str(self.bot_last_position.get('facing', 'FrontRight'))
            }
        else:
            target_pos = {'x': 11.5, 'y': 11.75, 'z': 0.5, 'facing': 'FrontRight'}

        asyncio.create_task(self._restore_position(target_pos))

        # Only start background tasks once — they stay alive across reconnects
        # via the is_connected flag. Creating them again causes duplicates.
        if not hasattr(self, '_tasks_started'):
            self._tasks_started = True
            asyncio.create_task(self.bot_brain())
            asyncio.create_task(self.periodic_announcements())
            asyncio.create_task(self.floor_monitor())
            asyncio.create_task(self.dance_beat_loop())
            asyncio.create_task(self.auto_save_loop())
            asyncio.create_task(self.position_saver_loop())
            asyncio.create_task(self.keep_alive())
            asyncio.create_task(self.dawya_game_loop())
            print("[Tasks] Background tasks started")
        else:
            print("[Tasks] Reconnected — reusing existing background tasks")

    # ─────────────────────────────────────────────────────────────────
    #  FLOOR MONITOR (Dance floor auto-dance, VIP floor restricted)
    # ─────────────────────────────────────────────────────────────────
    async def floor_monitor(self):
        await asyncio.sleep(5)
        while True:
            try:
                await asyncio.sleep(5)
                if not self.is_connected:
                    continue
                if not self.vip_floor and not self.dance_floor:
                    continue
                room_users = await self.safe_get_room_users()
                for user, position in room_users:
                    if user.id == self.highrise.my_id:
                        continue
                    # Skip seated/anchored users — AnchorPosition has no x/y/z
                    if not hasattr(position, 'x'):
                        continue

                    # VIP floor check — warn once per entry, not every 2s
                    if self.vip_floor and self.is_on_floor(position, self.vip_floor):
                        if not self.has_vip_access(user.username):
                            if user.id not in self.vip_warned:
                                self.vip_warned.add(user.id)
                                await self.highrise.chat(
                                    f"🚫 @{user.username}, VIP floor requires VIP access!\n"
                                    f"💎 30g = 1 day | 100g = 7 days | 500g = Permanent"
                                )
                    else:
                        self.vip_warned.discard(user.id)
                    
                    # Dance floor — register user so beat loop picks them up
                    if self.dance_floor and self.is_on_floor(position, self.dance_floor):
                        if user.id not in self.users_dancing_on_floor:
                            self.users_dancing_on_floor[user.id] = True
                            # Greet + let the central beat loop handle the emote
                            asyncio.create_task(self.auto_dance_on_floor(user.id, user.username))
                    else:
                        # User left dance floor, stop dancing
                        if user.id in self.users_dancing_on_floor:
                            self.users_dancing_on_floor[user.id] = False
                            await asyncio.sleep(0.3)
                            if user.id in self.users_dancing_on_floor:
                                del self.users_dancing_on_floor[user.id]
                            
            except Exception as e:
                print(f"Error in floor monitor: {e}")

    async def auto_dance_on_floor(self, user_id, username):
        """
        Called when a user steps onto the dance floor.
        Marks them as 'pending' (False) so the beat loop skips them until the
        next beat boundary — then flips them to True so they join in perfect sync.
        """
        try:
            # Mark as pending — beat loop only fires emotes for True entries
            self.users_dancing_on_floor[user_id] = False

            # Calculate exact wait until the next beat boundary
            if self.dance_floor_emote and self.dance_floor_emote in self.emote_dict:
                duration = float(self.emote_dict[self.dance_floor_emote][1])
                elapsed = time.time() - self.dance_beat_start
                # Use modulo so this works correctly even if multiple beats have passed
                wait = max(0.0, duration - (elapsed % max(duration, 0.001)))
                if wait > 0.1:
                    await asyncio.sleep(wait)

            # Activate — included in the very next beat tick
            self.users_dancing_on_floor[user_id] = True

        except Exception as e:
            print(f"Error in auto_dance_on_floor: {e}")
            # Activate anyway so user is not permanently stuck as pending
            self.users_dancing_on_floor[user_id] = True

    async def dance_beat_loop(self):
        """
        ONE central beat loop — picks a NEW random emote every beat and
        fires it to ALL floor dancers at exactly the same instant.
        FIX: refreshes room cache every 5 beats instead of every beat.
        """
        all_emotes = self.emote_keys[:]
        _cached_room_ids: set = set()
        _beat_count: int = 0

        while True:
            try:
                if not self.is_connected:
                    await asyncio.sleep(2)
                    continue
                if self.dance_floor and self.users_dancing_on_floor:
                    emote_name = random.choice(all_emotes)
                    emote_data = self.emote_dict[emote_name]
                    emote_id   = emote_data[0]
                    duration   = float(emote_data[1])

                    self.dance_beat_start = time.time()
                    self.dance_floor_emote = emote_name

                    # FIX: refresh room cache every 5 beats only (80% fewer API calls)
                    _beat_count += 1
                    if _beat_count >= 5 or not _cached_room_ids:
                        try:
                            room_users = await self.safe_get_room_users()
                            _cached_room_ids = {u.id for u, _ in room_users}
                            _beat_count = 0
                        except Exception:
                            _cached_room_ids = set(self.users_dancing_on_floor.keys())

                    stale = []
                    tasks = []
                    task_uids = []
                    for uid, active in list(self.users_dancing_on_floor.items()):
                        if not active:
                            continue
                        if uid not in _cached_room_ids:
                            stale.append(uid)
                            continue
                        tasks.append(self.highrise.send_emote(emote_id, uid))
                        task_uids.append(uid)

                    if tasks:
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                        for uid, result in zip(task_uids, results):
                            if isinstance(result, Exception):
                                print(f"[Beat] emote error for {uid}: {result}")
                                stale.append(uid)

                    for uid in stale:
                        self.users_dancing_on_floor.pop(uid, None)

                    await asyncio.sleep(max(duration, 2.0))
                else:
                    await asyncio.sleep(1.0)

            except asyncio.CancelledError:
                print("[Beat] dance_beat_loop cancelled cleanly")
                return
            except Exception as e:
                print(f"[Beat] dance_beat_loop error: {e}")
                await asyncio.sleep(2.0)

    def is_on_floor(self, user_pos, floor_coords: dict) -> bool:
        """Check if user is on a floor area. Safely handles AnchorPosition (seated users)."""
        try:
            x = user_pos.x
            y = user_pos.y
            z = user_pos.z
        except AttributeError:
            # AnchorPosition (user is seated/anchored) — no x/y/z, skip them
            return False
        x_match = abs(x - floor_coords['x']) <= floor_coords.get('rx', 2)
        y_match = abs(y - floor_coords['y']) <= floor_coords.get('ry', 0.6)
        z_match = abs(z - floor_coords['z']) <= floor_coords.get('rz', 2)
        return x_match and y_match and z_match

    # ─────────────────────────────────────────────────────────────────
    #  FOLLOW LOOP (Fixed to match facing direction)
    # ─────────────────────────────────────────────────────────────────
    async def follow_loop(self):
        while self.following_user:
            try:
                await asyncio.sleep(2)  # FIX: was 0.5s = 120 API calls/min
                if not self.following_user:
                    break
                room_users = await self.safe_get_room_users()
                target_pos = next((p for u, p in room_users if u.id == self.following_user), None)
                if target_pos is None:
                    self.following_user = None
                    self.following_username = None
                    break
                # Match the facing direction of the user being followed
                await self.highrise.walk_to(Position(
                    target_pos.x + 1.0, 
                    target_pos.y, 
                    target_pos.z, 
                    target_pos.facing  # KEY FIX: use target's facing direction
                ))
            except Exception as e:
                print(f"Error in follow_loop: {e}")
                await asyncio.sleep(2)

    # ─────────────────────────────────────────────────────────────────
    #  AUTO-TIP LOOP
    # ─────────────────────────────────────────────────────────────────
    async def auto_tip_loop(self, username: str):
        """Auto-tips a random user every interval — uses bot wallet directly."""
        try:
            while self.auto_tip_enabled.get(username, False):
                interval = self.auto_tip_interval.get(username, 60)
                # Sleep in small chunks so stop is near-instant
                for _ in range(interval * 2):
                    if not self.auto_tip_enabled.get(username, False):
                        return
                    await asyncio.sleep(0.5)
                if not self.auto_tip_enabled.get(username, False):
                    return
                amount = self.auto_tip_amount.get(username, 1)
                try:
                    room_users = await self.safe_get_room_users()
                    eligible = [u for u, _ in room_users
                                if u.id != self.highrise.my_id and u.username != username]
                    if eligible:
                        recipient = random.choice(eligible)
                        gold = self.to_gold_bar(amount)
                        if not gold:
                            await self.highrise.chat(f"❌ Auto-tip amount {amount}g not supported!")
                            self.auto_tip_enabled[username] = False
                            return
                        # Check wallet balance before tipping
                        balance = await self.get_wallet_gold()
                        if balance < amount:
                            await self.highrise.chat("❌ Bot wallet is empty! Auto-tip stopped. 💸")
                            self.auto_tip_enabled[username] = False
                            return
                        await self.highrise.tip_user(recipient.id, gold)
                        await self.highrise.chat(f"💰 Auto-tip: @{recipient.username} +{amount}g! 🎉")
                except Exception as e:
                    print(f"Error in auto_tip_loop: {e}")
                    await self.highrise.chat(f"❌ Auto-tip error: {e}")
        except asyncio.CancelledError:
            pass  # Task was hard-cancelled — clean exit
        finally:
            self.auto_tip_enabled.pop(username, None)
            self.auto_tip_tasks.pop(username, None)

    # ─────────────────────────────────────────────────────────────────
    #  LEADERBOARD
    # ─────────────────────────────────────────────────────────────────
    EXCLUDED_BOTS = {"sikiriti_3lal"}  # Bots/owners to exclude from leaderboards

    def _is_excluded_from_lb(self, username: str) -> bool:
        """Exclude bots and both owners from leaderboards"""
        return (username.lower() in self.EXCLUDED_BOTS or
                username.lower() == self.owner_username.lower() or
                username.lower() == self.second_owner_username.lower())

    # Colors per rank position for leaderboard rows
    LB_COLORS = {
        1: "f1c40f",   # 🥇 Gold
        2: "c0c0c0",   # 🥈 Silver
        3: "ff8c00",   # 🥉 Bronze/Orange
        4: "ff69b4",   # Pink
        5: "bf00ff",   # Purple
        6: "00cfff",   # Cyan
        7: "00e676",   # Green
        8: "ff4500",   # Red-orange
        9: "aaaaaa",   # Grey
        10: "ffffff",  # White
    }

    def get_leaderboard_text(self) -> list:
        """Return top-10 leaderboard split into message chunks, excluding bots"""
        filtered = {u: p for u, p in self.user_ratings.items()
                    if not self._is_excluded_from_lb(u)}
        if not filtered:
            return ["📊 Leaderboard is empty!"]
        sorted_users = sorted(filtered.items(), key=lambda x: x[1], reverse=True)[:10]
        msgs = []
        # Part 1: ranks 1-5
        lines1 = ["<#f1c40f>🏆 TOP 10 (1/2)"]
        for i, (uname, pts) in enumerate(sorted_users[:5], 1):
            color = self.LB_COLORS.get(i, "ffffff")
            name = uname[:12]
            lines1.append(f"<#{color}>{self.get_rank_emoji(i)} {name} {pts}p {self.get_rank_name(pts)}")
        msgs.append("\n".join(lines1))
        if len(sorted_users) > 5:
            lines2 = ["<#00cfff>🏆 TOP 10 (2/2)"]
            for i, (uname, pts) in enumerate(sorted_users[5:], 6):
                color = self.LB_COLORS.get(i, "ffffff")
                name = uname[:12]
                lines2.append(f"<#{color}>{self.get_rank_emoji(i)} {name} {pts}p {self.get_rank_name(pts)}")
            msgs.append("\n".join(lines2))
        return msgs

    def get_tips_leaderboard_text(self) -> list:
        """Return top-10 tippers split into message chunks, excluding bots"""
        tippers = {u: s.get('tips_given', 0) for u, s in self.user_stats.items()
                   if s.get('tips_given', 0) > 0 and not self._is_excluded_from_lb(u)}
        if not tippers:
            return ["💰 No tips recorded yet!"]
        sorted_users = sorted(tippers.items(), key=lambda x: x[1], reverse=True)[:10]
        msgs = []
        lines1 = ["<#ff8c00>💰 Top Tippers — Part 1/2 💰"]
        for i, (uname, count) in enumerate(sorted_users[:5], 1):
            color = self.LB_COLORS.get(i, "ffffff")
            lines1.append(f"<#{color}>{self.get_rank_emoji(i)} {uname} — {count} tips")
        msgs.append("\n".join(lines1))
        if len(sorted_users) > 5:
            lines2 = ["<#ff69b4>💰 Top Tippers — Part 2/2 💰"]
            for i, (uname, count) in enumerate(sorted_users[5:], 6):
                color = self.LB_COLORS.get(i, "ffffff")
                lines2.append(f"<#{color}>{self.get_rank_emoji(i)} {uname} — {count} tips")
            msgs.append("\n".join(lines2))
        return msgs

    # ─────────────────────────────────────────────────────────────────
    #  HELPERS
    # ─────────────────────────────────────────────────────────────────
    def get_rank_emoji(self, position: int) -> str:
        return {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟"}.get(position, "•")

    def get_rank_name(self, rating: int) -> str:
        if rating >= 10000: return "Lv:🔥"
        elif rating >= 8000: return "Lv:💎"
        elif rating >= 2500: return "Lv:👑"
        elif rating >= 1000: return "Lv:⭐"
        elif rating >= 150: return "Lv:🥈"
        elif rating >= 50:  return "Lv:🥉"
        else:               return "Lv:🌱"

    def format_time(self, seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"

    async def update_all_user_times(self):
        try:
            current_time = time.time()
            # FIX: one API call total — not one per tracked user
            room_users = await self.safe_get_room_users()
            room_map = {u.id: u for u, _ in room_users}
            for user_id, join_time in list(self.user_join_times.items()):
                user = room_map.get(user_id)
                if user:
                    session_time = current_time - join_time
                    self.user_total_time[user.username] = \
                        self.user_total_time.get(user.username, 0) + session_time
                    self.user_join_times[user_id] = current_time
        except Exception as e:
            print(f"Error updating user times: {e}")

    def add_rating_points(self, username: str, points: int):
        self.user_ratings[username] = self.user_ratings.get(username, 0) + points

    def update_stats(self, username: str, stat_type: str):
        if username not in self.user_stats:
            self.user_stats[username] = {'messages': 0, 'emotes': 0, 'tips_given': 0}
        self.user_stats[username][stat_type] = self.user_stats[username].get(stat_type, 0) + 1
        if stat_type == 'messages':
            # Only award points if enough time has passed — prevents spam farming
            now = time.time()
            last_points = self.points_cooldowns.get(username, 0)
            if now - last_points >= self.points_cooldown_seconds:
                self.add_rating_points(username, 1)
                self.points_cooldowns[username] = now
        elif stat_type == 'emotes':
            # Only award points if enough time has passed — prevents spam farming
            now = time.time()
            last_emote = self.emote_cooldowns.get(username, 0)
            if now - last_emote >= self.emote_cooldown_seconds:
                self.add_rating_points(username, 2)
                self.emote_cooldowns[username] = now

    async def check_cooldown(self, user: User) -> bool:
        now = time.time()
        last_time = self.user_cooldowns.get(user.id, 0)
        if now - last_time < self.cooldown_seconds:
            return False
        self.user_cooldowns[user.id] = now
        return True

    async def periodic_announcements(self):
        """Auto-post help tips and announcements"""
        tips = [
            "💡 Kteb !help bach tchof les commandes!",
            "⭐ Tip 30g+ bach tkhtar VIP greeting dyalk!",
            "👑 VIP: 30g (nhar), 100g (semana), 500g (dima)!",
            "🕺 Dance floor maftou7 l kol nas - dkhal w rqass!",
            "🌟 Tip lbot bach tkhtar greeting dyalk!",
            "🎲 Jrb !truth, !dare, !roll, !flip!",
        ]
        
        help_tips = [
            "📖 Type !help for commands!",
            "🎭 Type !help2 for emotes!",
            "📊 Type !help3 for stats!",
            "🎲 !roll|!flip|!truth|!dare|!joke|!riddle",
            "⭐ Check !ranks for rank system!",
            "👑 Tip 30g to get VIP access!",
        ]
        
        # FIX: Sikiriti fires at T+30, T+330... ChikhatraX waits 150s first
        # so it fires at T+450, T+750... — they never collide
        await asyncio.sleep(150)
        counter = 0
        while True:
            await asyncio.sleep(300)
            try:
                if not self.is_connected:
                    continue
                counter += 1
                if counter % 2 == 0:
                    tip = random.choice(help_tips)
                    await self.highrise.chat(tip)
                else:
                    announcement = random.choice(tips)
                    await self.highrise.chat(announcement)
            except Exception as e:
                print(f"Error in announcements: {e}")
                await asyncio.sleep(30)

    async def bot_brain(self):
        """Chikha dances using dance emotes from EMOTE_DICT.
        Starts with a 7s offset so it never fires at the same time as Sikiriti.
        on_emote already ignores both bots so no conflict loop."""
        # Offset start so Chikha and Sikiriti never send emotes simultaneously
        await asyncio.sleep(7)
        while True:
            try:
                if not self.is_connected:
                    await asyncio.sleep(5)
                    continue
                if not self.following_user:
                    # Filter only dance emotes from the loaded EMOTE_DICT
                    dance_keys = [k for k in self.emote_keys
                                  if any(tag in self.emote_dict[k][0].lower()
                                         for tag in ('dance', 'idle-dance', 'idle_dance'))]
                    if dance_keys:
                        key = random.choice(dance_keys)
                        emote_id = self.emote_dict[key][0]
                        duration = float(self.emote_dict[key][1])
                        await self.highrise.send_emote(emote_id)
                        # Wait for emote to finish before picking the next one
                        await asyncio.sleep(max(duration - 0.5, 2.0))
                    else:
                        await asyncio.sleep(10)
                else:
                    await asyncio.sleep(2)
            except Exception as e:
                err = str(e).lower()
                if "not in room" in err or "user not" in err:
                    await asyncio.sleep(10)
                elif "closing transport" in err or "not connected" in err:
                    self.is_connected = False
                    print("[bot_brain] Connection lost — pausing")
                    await asyncio.sleep(10)
                else:
                    print(f"Error in bot_brain: {e}")
                    await asyncio.sleep(5)

    # ─────────────────────────────────────────────────────────────────
    #  EVENTS
    # ─────────────────────────────────────────────────────────────────
    async def on_user_join(self, user: User, position: Position):
        try:
            if user.username.lower() == "sikiriti_3lal":
                return  # No greeting or tracking for Sikiriti
            self.user_join_times[user.id] = time.time()
            self.user_sessions[user.username] = self.user_sessions.get(user.username, 0) + 1
            rating = self.user_ratings.get(user.username, 0)
            rank_name = self.get_rank_name(rating)
            vip_badge = " 👑 [VIP]" if self.has_vip_access(user.username) else ""

            if user.username in self.custom_greetings:
                await self.highrise.chat(
                    f"⭐ [VIP] {user.username}{vip_badge} ({rank_name}): {self.custom_greetings[user.username]}"
                )
            else:
                # Moroccan Darija greetings — one solid color per message
                greetings = [
                    f"✨ <#ff8c00>Mrhba bik @{user.username}{vip_badge}! [{rank_name}] ✨",
                    f"🌟 <#9b59b6>Salam @{user.username}{vip_badge}! Labas 3lik? [{rank_name}]",
                    f"🎉 <#f1c40f>Ahlan wa sahlan @{user.username}{vip_badge}! [{rank_name}] 🎊",
                    f"🏠 <#ffffff>@{user.username}{vip_badge} dkhal l dar! [{rank_name}] 💫",
                    f"💖 <#ff69b4>Hanya @{user.username}{vip_badge}! Farhana bik! [{rank_name}]",
                    f"👋 <#aaaaaa>Salam @{user.username}{vip_badge}! Chno akhbar? [{rank_name}]",
                    f"⭐ <#ff4500>@{user.username}{vip_badge} dkhalti f wakt mezyan! [{rank_name}]",
                    f"🙏 <#00cfff>@{user.username}{vip_badge} wassal! Hamdollah 3la salama! [{rank_name}]",
                    f"😊 <#00e676>Shkoun hada? @{user.username}{vip_badge} Mrhba bik! [{rank_name}]",
                    f"🎊 <#ff1493>Safi @{user.username}{vip_badge} ja! Kolchi wla mezyan! [{rank_name}]",
                    f"💙 <#c0c0c0>@{user.username}{vip_badge} f dar! Allah ykhlik lina! [{rank_name}]",
                    f"🏡 <#bf00ff>Tfadal @{user.username}{vip_badge}! Dar dyalk! [{rank_name}]",
                    f"🔥 <#ff2d2d>@{user.username}{vip_badge} wassal! Mrhba bik! [{rank_name}]",
                    f"💎 <#00e5ff>@{user.username}{vip_badge} ja! Kolchi mezyan daba! [{rank_name}]",
                ]
                await self.highrise.chat(random.choice(greetings))

            for _ in range(2):
                await self.highrise.react("heart", user.id)
                await asyncio.sleep(0.4)

            # First-time visitor tip
            if user.username not in self.user_stats:
                self.user_stats[user.username] = {'messages': 0, 'emotes': 0, 'tips_given': 0}
                # Tip first-time visitors 1g only if wallet has enough
                try:
                    balance = await self.get_wallet_gold()
                    if balance >= 1:
                        gold = self.to_gold_bar(1)
                        if gold:
                            await self.highrise.tip_user(user.id, gold)
                            await self.highrise.chat(f"1 🎁   @{user.username}! ✨")
                    else:
                        print(f"[Wallet] Skipping welcome tip for {user.username} — wallet empty.")
                except Exception as e:
                    print(f"Could not tip first-time user {user.username}: {e}")

            # +5 join bonus — first time only, not every rejoin
            if user.username not in self.join_points_given:
                self.join_points_given.add(user.username)
                self.add_rating_points(user.username, 5)
            self._persist()

        except Exception as e:
            print(f"Error in on_user_join: {e}")

    async def on_user_leave(self, user: User):
        try:
            if user.id in self.user_join_times:
                session_time = time.time() - self.user_join_times[user.id]
                self.user_total_time[user.username] = \
                    self.user_total_time.get(user.username, 0) + session_time
                del self.user_join_times[user.id]
                self.add_rating_points(user.username, int(session_time / 60))

            goodbyes = [
                f"👋 <#ff8c00>Bslama @{user.username}! T3awd terja3! 💙",
                f"✨ <#9b59b6>Sir bslama @{user.username}! Alla ysahel 3lik! 💫",
                f"💙 <#f1c40f>@{user.username} msha! Nchofok 3la khir! 🌟",
                f"🌙 <#ff69b4>Bslama @{user.username}! Ma tghib bzaf! ✨",
                f"🙏 <#00cfff>@{user.username} thla! 💫",
                f"🌟 <#00e676>T3awd ji @{user.username}! Bslama! 👋",
                f"💎 <#ff4500>@{user.username} msha! Allah ysahel 3lih! ✨",
                f"🔥 <#bf00ff>Bslama @{user.username}! Nchofok 3la khir! 💫",
            ]
            await self.highrise.chat(random.choice(goodbyes))

            self.vip_warned.discard(user.id)

            if self.following_user == user.id:
                self.following_user = None
                self.following_username = None

            if user.id in self.looping_users:
                self.looping_users[user.id] = False
                await asyncio.sleep(0.3)
                if user.id in self.looping_users:
                    del self.looping_users[user.id]

            # Stop dancing if leaving
            if user.id in self.users_dancing_on_floor:
                self.users_dancing_on_floor[user.id] = False
                await asyncio.sleep(0.3)
                if user.id in self.users_dancing_on_floor:
                    del self.users_dancing_on_floor[user.id]

            self._persist()

        except Exception as e:
            print(f"Error in on_user_leave: {e}")

    async def on_tip(self, sender: User, receiver: User, tip: CurrencyItem):
        try:
            if receiver.id == self.highrise.my_id:
                self.update_stats(sender.username, 'tips_given')
                self.add_rating_points(sender.username, tip.amount)
                await self.highrise.send_emote("emote-lust")

                # VIP ACCESS TIERED SYSTEM — cumulative tips so split tips still count
                prev_total = self.tip_totals.get(sender.username, 0)
                new_total = prev_total + tip.amount
                self.tip_totals[sender.username] = new_total

                vip_message = ""
                newly_got_vip = False  # Track if they just unlocked VIP this tip

                if sender.username in self.vip_permanent:
                    if new_total >= 30:
                        vip_message = "💎 Nta deja VIP permanent!"
                elif new_total >= 500:
                    self.vip_permanent.add(sender.username)
                    self.vip_timed.pop(sender.username, None)
                    vip_message = "🎉 VIP DIMA! RAK VIP PERMANENT! 🎉"
                    newly_got_vip = True
                elif new_total >= 100:
                    expiry = time.time() + (7 * 24 * 3600)
                    self.vip_timed[sender.username] = expiry
                    vip_message = f"👑 7 AYAM VIP ACCESS! (Total: {new_total}g) 👑"
                    newly_got_vip = prev_total < 100
                elif new_total >= 30:
                    expiry = time.time() + (24 * 3600)
                    self.vip_timed[sender.username] = expiry
                    vip_message = f"✨ 1 DAY VIP ACCESS! (Total: {new_total}g) ✨"
                    newly_got_vip = prev_total < 30
                elif new_total < 30:
                    remaining = 30 - new_total
                    vip_message = f"💡 Tip {remaining}g more for 1-day VIP + custom greeting! (Total: {new_total}g)"

                if tip.amount >= 100:
                    mega = self.gradient_text("MEGA TIP", "fire")
                    await self.highrise.chat(
                        f"🔥 {mega}! @{sender.username} 3ta {tip.amount}g!\n"
                        f"{vip_message}"
                    )
                elif tip.amount >= 50:
                    wow = self.gradient_text("WOW", "cyan")
                    await self.highrise.chat(
                        f"💎 {wow}! @{sender.username} 3ta {tip.amount}g!\n"
                        f"{vip_message if vip_message else ''}"
                    )
                else:
                    await self.highrise.chat(
                        f"🎉 @{sender.username} 3ta {tip.amount}g! Shukran! 💙"
                        + (f"\n{vip_message}" if vip_message else "")
                    )

                # Greeting offer — show on first VIP unlock OR any tip from existing VIP
                is_vip_now = self.has_vip_access(sender.username)
                if newly_got_vip:
                    await self.highrise.chat(
                        f"🎁 @{sender.username}, rak VIP! Kteb !setgreeting [greeting dyalk] "
                        f"bach twli t7yyed bik kol mara tdkhol! 👑"
                    )
                    if sender.username not in self.awaiting_greeting:
                        self.awaiting_greeting.append(sender.username)
                elif is_vip_now:
                    # Already VIP and tipped again — remind them they can update their greeting
                    current = self.custom_greetings.get(sender.username)
                    if current:
                        await self.highrise.chat(
                            f"💙 @{sender.username} shukran 3la tip! "
                            f"Greeting dyalek daba: \"{current}\" — "
                            f"Baghi tbdla? Kteb !setgreeting [greeting jdid] 🔄"
                        )
                    else:
                        await self.highrise.chat(
                            f"💙 @{sender.username} shukran 3la tip! "
                            f"Ma3ndakch greeting — kteb !setgreeting [greeting dyalk] bach t7yed bik! 👑"
                        )
                    if sender.username not in self.awaiting_greeting:
                        self.awaiting_greeting.append(sender.username)
            else:
                self.update_stats(sender.username, 'tips_given')
                self.add_rating_points(sender.username, tip.amount // 2)
                await self.highrise.chat(f"💝 @{sender.username} tipped @{receiver.username} {tip.amount}g!")

            self._persist()
        except Exception as e:
            print(f"Error in on_tip: {e}")

    async def on_reaction(self, user: User, receiver: User, reaction: str):
        try:
            if user.username.lower() == "sikiriti_3lal":
                return  # Ignore Sikiriti reactions
            if receiver.id == self.highrise.my_id:
                reactions_responses = {
                    'heart':  ['Nbghik nta! 💙', 'Baraka fik khoya!', 'Nta zwina! 💕'],
                    'thumbs': ['Nta mezyan!', 'Tbarkllah 3lik!', 'Top! 🔥'],
                    'clap':   ['Bravo !', 'Mezyan!', 'Tbarkallah! 💫'],
                    'wave':   ['Salam ', 'Labas?', 'Fin a sat! 😊'],
                }
                response = reactions_responses.get(reaction, ['Baraka fik! 😊', 'Mezyan! ✨'])
                await self.highrise.chat(f"@{user.username} {random.choice(response)}")
                # Cooldown — max +3 pts per 60 seconds from reactions
                now = time.time()
                last = self.reaction_cooldowns.get(user.username, 0)
                if now - last >= self.reaction_cooldown_seconds:
                    self.add_rating_points(user.username, 3)
                    self.reaction_cooldowns[user.username] = now
        except Exception as e:
            print(f"Error in on_reaction: {e}")

    async def on_emote(self, user: User, emote_id: str, receiver: User | None):
        try:
            # Ignore emotes from both bots — prevents animation restart loop
            if user.username.lower() in ("sikiriti_3lal", "_chikhatrax_"):
                return
            # Ignore if emote has no receiver (bot self-emotes broadcast to room)
            # Only track and react to real human users doing emotes
            self.update_stats(user.username, 'emotes')
            if 'dance' in emote_id.lower():
                await self.highrise.react("fire", user.id)
        except Exception as e:
            print(f"Error in on_emote: {e}")

    async def on_user_move(self, user: User, pos: Position):
        """Follow owner in real-time whenever they move."""
        if self.following_user == user.id:
            try:
                # Use target's facing direction for proper following
                await self.highrise.walk_to(Position(pos.x + 1.0, pos.y, pos.z, pos.facing))
            except Exception as e:
                print(f"Error following on move: {e}")

    # ───────────����─────────────────────────────────────────────────────
    #  WHISPER HANDLER — Owner commands via private whisper
    # ─────────────────────────────────────────────────────────────────
    async def on_whisper(self, user: User, message: str):
        """Owner/mod whisper commands — fully private, invisible to room."""
        try:
            if not self.is_owner(user):
                # Non-owners get a polite private reply
                await self.highrise.send_whisper(user.id, "🤫 Whisper commands are for owners only!")
                return
            await self._handle_owner_command(user, message, whisper=True)
        except Exception as e:
            print(f"Error in on_whisper: {e}")

    async def _w(self, user: User, text: str, whisper: bool):
        """Send response as whisper or public chat depending on context."""
        if whisper:
            await self.highrise.send_whisper(user.id, text)
        else:
            await self.highrise.chat(text)

    async def _handle_owner_command(self, user: User, message: str, whisper: bool = False) -> bool:
        """
        Handle all owner-only commands.
        Returns True if a command was matched (so on_chat can return early).
        When whisper=True, all responses go to send_whisper instead of chat.
        """
        msg = message.strip()
        low = msg.lower()

        if low == '!dawya':
            if self.dawya_active:
                await self._w(user, "⚠️ Challenge deja active!", whisper)
            else:
                self.dawya_active = True
                self.dawya_claimed = False
                self.dawya_winner_this_round = None
                self.dawya_current_word = random.choice(self.dawya_words)
                announce = self.gradient_text("⚡ WORD CHALLENGE! ⚡", "fire")
                await self.highrise.chat(
                    f"{announce}\n"
                    f"🏃 Awwel wa7ed ykteb '{self.dawya_current_word}' f chat "
                    f"ywl +5 nqat f leaderboard! 🏆"
                )
                async def _expire():
                    await asyncio.sleep(20)
                    if self.dawya_active and not self.dawya_claimed:
                        self.dawya_active = False
                        self.dawya_current_word = None
                        await self.highrise.chat(f"⏰ Waqt sala! Ma7ad kteb '{self.dawya_current_word or ''}' 😅")
                asyncio.create_task(_expire())
            return True

        # ── MODERATOR MANAGEMENT ─────────────────────────────
        if low.startswith('!addmod '):
            target = msg[8:].strip().lstrip('@')
            self.moderators.add(target)
            self._persist()
            await self._w(user, f"🛡️ @{target} added as moderator!", whisper)
            return True

        if low.startswith('!removemod '):
            target = msg[11:].strip().lstrip('@')
            self.moderators.discard(target)
            self._persist()
            await self._w(user, f"✅ @{target} removed from moderators.", whisper)
            return True

        if low == '!modlist':
            if self.moderators:
                await self._w(user, f"🛡️ Moderators:\n{', '.join(sorted(self.moderators))}", whisper)
            else:
                await self._w(user, "🛡️ No moderators set.", whisper)
            return True

        # ── FOLLOW / STOP ────────────────────────────────────
        if low in ('follow', '!follow'):
            self.following_user = user.id
            self.following_username = user.username
            asyncio.create_task(self.follow_loop())
            await self._w(user, f"🚶 Now following @{user.username}!", whisper)
            return True

        if low in ('stop', '!stop', '!unfollow'):
            self.following_user = None
            self.following_username = None
            if user.id in self.looping_users:
                self.looping_users[user.id] = False
                await asyncio.sleep(0.3)
                if user.id in self.looping_users:
                    del self.looping_users[user.id]
            await self._w(user, "🛑 Stopped.", whisper)
            return True

        # ── VIP FLOOR SETUP ──────────────────────────────────
        if low in ('!setvipfloor', '!setvip'):
            self.floor_setup['vip'] = {'step': 1, 'point1': None}
            await self._w(user,
                "👑 VIP Floor Setup — Step 1/2\n"
                "Walk to the FIRST corner of the VIP area\n"
                "then type: !vippoint", whisper)
            return True

        if low == '!vippoint':
            setup = self.floor_setup['vip']
            room_users = await self.safe_get_room_users()
            my_pos = next((p for u, p in room_users
                           if u.username.lower() == self.owner_username.lower()), None)
            if my_pos is None:
                await self._w(user, "❌ Can't find your position. Try again.", whisper)
                return True
            if setup['step'] == 1:
                setup['point1'] = {'x': my_pos.x, 'y': my_pos.y, 'z': my_pos.z}
                setup['step'] = 2
                await self._w(user,
                    f"✅ Point 1 saved: ({my_pos.x:.1f}, {my_pos.y:.1f}, {my_pos.z:.1f})\n"
                    "Step 2/2: Walk to the OPPOSITE corner\n"
                    "then type: !vippoint", whisper)
            elif setup['step'] == 2:
                p1 = setup['point1']
                self.vip_floor = {
                    'x':  (p1['x'] + my_pos.x) / 2,
                    'y':  (p1['y'] + my_pos.y) / 2,
                    'z':  (p1['z'] + my_pos.z) / 2,
                    'rx': abs(p1['x'] - my_pos.x) / 2 + 0.5,
                    'ry': max(abs(p1['y'] - my_pos.y) / 2, 0.6),
                    'rz': abs(p1['z'] - my_pos.z) / 2 + 0.5,
                }
                setup['step'] = 0
                self._persist()
                await self._w(user,
                    f"✅ VIP Floor set!\n"
                    f"Center: ({self.vip_floor['x']:.1f}, {self.vip_floor['y']:.1f}, {self.vip_floor['z']:.1f})\n"
                    "👑 VIP members only!", whisper)
            else:
                await self._w(user, "⚠️ Start with !setvipfloor first.", whisper)
            return True

        # ── DANCE FLOOR SETUP ────────────────────────────────
        if low in ('!setdancefloor', '!setdance'):
            self.floor_setup['dance'] = {'step': 1, 'point1': None}
            await self._w(user,
                "🕺 Dance Floor Setup — Step 1/2\n"
                "Walk to the FIRST corner of the dance area\n"
                "then type: !dancepoint", whisper)
            return True

        if low == '!dancepoint':
            setup = self.floor_setup['dance']
            room_users = await self.safe_get_room_users()
            my_pos = next((p for u, p in room_users
                           if u.username.lower() == self.owner_username.lower()), None)
            if my_pos is None:
                await self._w(user, "❌ Can't find your position. Try again.", whisper)
                return True
            if setup['step'] == 1:
                setup['point1'] = {'x': my_pos.x, 'y': my_pos.y, 'z': my_pos.z}
                setup['step'] = 2
                await self._w(user,
                    f"✅ Point 1 saved: ({my_pos.x:.1f}, {my_pos.y:.1f}, {my_pos.z:.1f})\n"
                    "Step 2/2: Walk to the OPPOSITE corner\n"
                    "then type: !dancepoint", whisper)
            elif setup['step'] == 2:
                p1 = setup['point1']
                self.dance_floor = {
                    'x':  (p1['x'] + my_pos.x) / 2,
                    'y':  (p1['y'] + my_pos.y) / 2,
                    'z':  (p1['z'] + my_pos.z) / 2,
                    'rx': abs(p1['x'] - my_pos.x) / 2 + 0.5,
                    'ry': max(abs(p1['y'] - my_pos.y) / 2, 0.6),
                    'rz': abs(p1['z'] - my_pos.z) / 2 + 0.5,
                }
                setup['step'] = 0
                self._persist()
                await self._w(user,
                    f"✅ Dance Floor set!\n"
                    f"Center: ({self.dance_floor['x']:.1f}, {self.dance_floor['y']:.1f}, {self.dance_floor['z']:.1f})\n"
                    "🕺 Everyone can dance here!", whisper)
            else:
                await self._w(user, "⚠️ Start with !setdancefloor first.", whisper)
            return True

        # ── FLOOR CLEAR ──────────────────────────────────────
        if low == '!clearvip':
            self.vip_floor = None
            self._persist()
            await self._w(user, "🗑️ VIP floor cleared!", whisper)
            return True

        if low == '!cleardance':
            self.dance_floor = None
            self.dance_floor_emote = None
            self._persist()
            await self._w(user, "🗑️ Dance floor cleared!", whisper)
            return True

        # ── FLOOR STATUS ─────────────────────────────────────
        if low == '!floorstatus':
            vip_s = (f"({self.vip_floor['x']:.1f}, {self.vip_floor['y']:.1f}, {self.vip_floor['z']:.1f})"
                     if self.vip_floor else "Not set")
            dan_s = (f"({self.dance_floor['x']:.1f}, {self.dance_floor['y']:.1f}, {self.dance_floor['z']:.1f})"
                     if self.dance_floor else "Not set")
            await self._w(user,
                f"🗺️ Floor Status:\n"
                f"👑 VIP Floor: {vip_s}\n"
                f"🕺 Dance Floor: {dan_s}", whisper)
            return True

        # ── ANNOUNCE ─────────────────────────────────────────
        if low.startswith('!announce '):
            await self.highrise.chat(f"📢 ANNOUNCEMENT: {msg[10:].strip()}")
            if whisper:
                await self._w(user, "✅ Announcement sent!", whisper)
            return True

        # ── OWNER HELP ───────────────────────────────────────
        if low == '!ownercmds':
            await self._w(user,
                "👑 OWNER COMMANDS (whisper these!):\n"
                "follow / stop — follow/unfollow\n"
                "!addmod @u / !removemod @u\n"
                "!modlist\n"
                "!setvipfloor → !vippoint ×2\n"
                "!setdancefloor → !dancepoint ×2\n"
                "!clearvip / !cleardance\n"
                "!floorstatus\n"
                "!clearlb / !resetstats\n"
                "!setpos / !announce [msg]\n"
                "!hearts", whisper)
            return True

        # ── OUTFIT COMMANDS (owner only) ─────────────────────
        if low == '!myoutfit':
            try:
                resp = await self.highrise.get_outfit()
                items = resp.outfit if hasattr(resp, 'outfit') else []
                if not items:
                    await self._w(user, "❌ Could not get bot outfit!", whisper)
                    return True
                lines = ["👗 Bot current outfit item IDs:"]
                for item in items:
                    lines.append(f"  type={item.type} id={item.id}")
                # Split into chunks of 10 lines
                chunk = []
                for line in lines:
                    chunk.append(line)
                    if len(chunk) == 10:
                        await self._w(user, "\n".join(chunk), whisper)
                        chunk = []
                if chunk:
                    await self._w(user, "\n".join(chunk), whisper)
            except Exception as e:
                await self._w(user, f"❌ Error: {e}", whisper)
            return True

        # !outfit1 through !outfit20
        import re as _re
        outfit_match = _re.fullmatch(r'!outfit(\d+)', low)
        if outfit_match:
            num = int(outfit_match.group(1))
            if num < 1 or num > 20:
                await self._w(user, "❌ Use !outfit1 to !outfit20", whisper)
                return True
            items = self.outfits.get(num, [])
            if not items:
                await self._w(user, f"❌ Outfit {num} is empty! Run !myoutfit to get item IDs and fill self.outfits[{num}] in main.py", whisper)
                return True
            try:
                from highrise.models import Item
                outfit_items = [Item(type=i["type"], id=i["id"], amount=i.get("amount","1")) for i in items]
                await self.highrise.set_outfit(outfit_items)
                await self._w(user, f"✅ Outfit {num} applied! 👗", whisper)
            except Exception as e:
                await self._w(user, f"❌ Could not apply outfit {num}: {e}", whisper)
                print(f"[Outfit] Error applying outfit {num}: {e}")
            return True

        # ── SET POSITION ─────────────────────────────────────
        if low == '!setpos':
            try:
                room_users = await self.safe_get_room_users()
                bot_pos = next((p for u, p in room_users if u.id == self.highrise.my_id), None)
                if bot_pos:
                    self.bot_last_position = {
                        'x': bot_pos.x, 'y': bot_pos.y,
                        'z': bot_pos.z, 'facing': bot_pos.facing
                    }
                    self._persist()
                    await self._w(user,
                        f"✅ Bot position saved!\n"
                        f"({bot_pos.x:.1f}, {bot_pos.y:.1f}, {bot_pos.z:.1f})\n"
                        "Bot will spawn here after reconnect!", whisper)
                else:
                    await self._w(user, "❌ Could not find bot position!", whisper)
            except Exception as e:
                print(f"Error setting position: {e}")
                await self._w(user, "❌ Error saving position!", whisper)
            return True

        # ── CLEAR LEADERBOARD ────────────────────────────────
        if low == '!clearlb':
            self.user_ratings = {}
            self._persist()
            await self._w(user, "🗑️ Leaderboard cleared!", whisper)
            return True

        # ── RESET ALL STATS ──────────────────────────────────
        if low == '!resetstats':
            self.user_stats = {}
            self.user_ratings = {}
            self.tip_totals = {}
            self.user_total_time = {}
            self._persist()
            await self._w(user, "⚠️ ALL user stats reset!", whisper)
            return True

        # ── HEARTS ───────────────────────────────────────────
        if low == '!hearts':
            room_users = await self.safe_get_room_users()
            targets = [u for u, _ in room_users if u.id != self.highrise.my_id]
            if not targets:
                await self._w(user, "❌ No users in room!", whisper)
                return True
            await self.highrise.chat(f"💙 Sending blue hearts to everyone! ({len(targets)} users)")
            for target in targets:
                try:
                    await self.highrise.react("heart", target.id)
                    await asyncio.sleep(0.3)
                except Exception as e:
                    print(f"[Hearts] Failed for {target.username}: {e}")
            return True

        return False  # No owner command matched

    # ─────────────────────────────────────────────────────────────────
    #  MAIN CHAT HANDLER
    # ─────────────────────────────────────────────────────────────────
    async def on_chat(self, user: User, message: str):
        try:
            if user.username.lower() == "sikiriti_3lal":
                return  # Ignore Sikiriti completely
            msg = message.strip()
            low = msg.lower()
            self.update_stats(user.username, 'messages')

            # ── BAD LANGUAGE FILTER ───────────────────────────────────
            # Skip check for owner and mods
            if not self.is_owner_or_mod(user):
                # Check both original and a stripped version (removes spaces/dots between letters)
                low_stripped = re.sub(r'[\s\.\-_*]+', '', low)  # e.g. "z a m a l" → "zamal"
                found_bad = None
                for bad_word in self.bad_words:
                    if bad_word in low or bad_word in low_stripped:
                        found_bad = bad_word
                        break
                if found_bad:
                    print(f"[MODERATION] Bad word detected from {user.username}: '{found_bad}' in: '{msg}'")
                    try:
                        await self.highrise.chat(f"🚫 @{user.username} m3a salama! Ma kan3tiw liya bad language hna! ⚠️")
                    except Exception as e:
                        print(f"[MODERATION] Could not send kick message: {e}")
                    try:
                        await self.highrise.moderate_room(user.id, "kick", 0)
                        print(f"[MODERATION] Kicked {user.username} successfully.")
                    except Exception as e:
                        print(f"[MODERATION] Kick failed for {user.username}: {e}")
                        try:
                            await self.highrise.chat(f"⚠️ @{user.username} Badlanguage hna! ⚠️ kick 1 📌")
                        except Exception as e2:
                            print(f"[MODERATION] Warning chat also failed: {e2}")
                    return

            # ── Riddle answer check ──────────────────────────────────
            if not low.startswith('!') and user.id in self.active_riddles:
                state = self.active_riddles[user.id]
                correct_key = state["answer"].lower()
                # Accept if user's message contains the key word of the answer
                import re as _re
                key_words = _re.sub(r'[^\w\s]', '', correct_key).split()
                user_msg_clean = _re.sub(r'[^\w\s]', '', low)
                if any(kw in user_msg_clean for kw in key_words if len(kw) > 2):
                    del self.active_riddles[user.id]
                    await self.highrise.chat(
                        f"✅ SA7! @{user.username} jaweb sa7!\n"
                        f"{state['answer']}\n"
                        f"🏅 +10 nqat!"
                    )
                    self.add_rating_points(user.username, 10)
                    return

            # ── WORD CHALLENGE — check before auto-responses ────────
            if self.dawya_active and not self.dawya_claimed and self.dawya_current_word and low.strip() == self.dawya_current_word:
                self.dawya_claimed = True
                self.dawya_active = False
                self.dawya_winner_this_round = user.username
                self.add_rating_points(user.username, 5)
                self._persist()
                winner_text = self.gradient_text(f"🏆 {user.username} WIN!", "gold")

                # 1 in 5 chance to also send 5g — skip silently if bot wallet is empty
                gold_bonus = False
                if random.randint(1, 5) == 1:
                    try:
                        balance = await self.get_wallet_gold()
                        if balance >= 5:
                            await self.highrise.tip_user(user.id, self.to_gold_bar(5))
                            gold_bonus = True
                    except Exception as e:
                        print(f"[WordGame] Gold bonus failed: {e}")

                if gold_bonus:
                    await self.highrise.chat(
                        f"{winner_text}\n"
                        f"✅ @{user.username} kteb '{self.dawya_current_word}' l'awwel! +5 nqat + 5g 🎉💰\n"
                        f"📊 Total dyalek: {self.user_ratings.get(user.username, 0)} nqat"
                    )
                else:
                    await self.highrise.chat(
                        f"{winner_text}\n"
                        f"✅ @{user.username} kteb '{self.dawya_current_word}' l'awwel! +5 nqat! 🎉\n"
                        f"📊 Total dyalek: {self.user_ratings.get(user.username, 0)} nqat"
                    )
                self.dawya_current_word = None
                return

            # ── Auto-responses — only fire if not a command ──────────
            if not low.startswith('!'):
                for trigger, responses in self.auto_responses.items():
                    if trigger in low:
                        response = random.choice(responses)
                        await self.highrise.chat(f"@{user.username} {response}")
                        return

            # ── Custom greeting setter ────────────────────────────────
            # Method 1: !setgreeting [text] — any VIP user can use this anytime
            if low.startswith('!setgreeting '):
                greeting_text = msg[13:].strip()
                if not self.has_vip_access(user.username):
                    await self.highrise.chat(f"❌ @{user.username} khssek tkoun VIP bach tdir greeting dyalk! 💎")
                    return
                if not greeting_text:
                    await self.highrise.chat(f"❌ @{user.username} kteb: !setgreeting [message dyalk] 📝")
                    return
                if len(greeting_text) > 200:
                    await self.highrise.chat(f"❌ @{user.username} message twil bzaf! Max 200 characters.")
                    return
                self.custom_greetings[user.username] = greeting_text
                if user.username in self.awaiting_greeting:
                    self.awaiting_greeting.remove(user.username)
                self._persist()
                success_msg = f"✅ {self.gradient_text(f'VIP Greeting t7fad l @{user.username}!', 'green')} 🌟"
                await self.highrise.chat(success_msg)
                return

            # Method 2: !set [text] — only for users in awaiting_greeting list (after tipping)
            if user.username in self.awaiting_greeting and low.startswith('!set '):
                greeting_text = msg[5:].strip()
                if not greeting_text:
                    error_msg = f"❌ {self.gradient_text('Khssek tkteb message! Dir !set [Message dyalk]', 'fire')}"
                    await self.highrise.chat(error_msg)
                    return
                if len(greeting_text) > 200:
                    error_msg = f"❌ {self.gradient_text('Message twil bzaf! Max 200 characters.', 'fire')}"
                    await self.highrise.chat(error_msg)
                    return
                self.custom_greetings[user.username] = greeting_text
                self.awaiting_greeting.remove(user.username)
                self._persist()
                success_msg = f"✅ {self.gradient_text(f'VIP Greeting t7fad l @{user.username}!', 'green')} 🌟"
                await self.highrise.chat(success_msg)
                return

            # ═══════════════════════════════════════════════════════════
            #  OWNER-ONLY COMMANDS (also available via whisper — see on_whisper)
            # ═══════════════════════════════════════════════════════════
            if self.is_owner(user):
                matched = await self._handle_owner_command(user, message, whisper=False)
                if matched:
                    return

            # ═══════════════════════════════════════════════════════════
            #  PUBLIC COMMANDS
            # ═══════════════════════════════════════════════════════════

            # FIX: owners/mods bypass cooldown — their commands always work
            if not self.is_owner_or_mod(user):
                if not await self.check_cooldown(user):
                    return

            # ── HELP ─────────────────────────────────────────────────
            if low == '!help':
                await self.highrise.chat(
                    "🤖 COMMANDS 1/3\n"
                    "!tip @u 5g|!tipall 5g\n"
                    "!autotip 5g 60s|!stopautotip\n"
                    "👑 30g=1d|100g=7d|500g=dima\n"
                    "!vipstatus | !help2 for more"
                )
                return

            if low == '!help2':
                await self.highrise.chat(
                    "🤖 BOT COMMANDS (2/3)\n"
                    "🎭 EMOTES:\n"
                    f"1-{len(self.emote_keys)} - Do emote\n"
                    "loop N - Loop emote\n"
                    "stop - Stop loop\n\n"
                    "🗺️ FLOORS:\n"
                    "!vipfloor - TP to VIP\n"
                    "!dancefloor - TP to dance\n\n"
                    "Type !help3 for more"
                )
                return

            if low in ('!help3', '!commands'):
                await self.highrise.chat(
                    "🤖 COMMANDS 3/3\n"
                    "!stats|!rank|!ranks|!lb\n"
                    "!tiplb|!time|!tt @u\n"
                    "!joke|!riddle(!skip)|!dare\n"
                    "!truth|!roll|!flip"
                )
                return

            # ── VIP STATUS ───────────────────────────────────────────
            if low == '!vipstatus':
                status = self.get_vip_status_text(user.username)
                await self.highrise.chat(f"👑 VIP Status for @{user.username}:\n{status}")
                return



            # ── WALLET BALANCE ────────────────────────────────────
            if low in ('!wallet', '!balance', '!gold', '!flous'):
                balance = await self.get_wallet_gold()
                if self.is_owner(user):
                    await self.highrise.chat(f"💰 Bot wallet: {balance}g")
                else:
                    await self.highrise.chat(f"@{user.username} 💰 Bot wallet: {balance}g")
                return

            # ── TIP @USER ────────────────────────────────────────────
            # Fix: use exact match prefix '!tip @' to avoid clashing with !tipall
            if low.startswith('!tip ') and not low.startswith('!tipall'):
                if not self.is_owner(user):
                    await self.highrise.chat("❌ Only the owner can use !tip!")
                    return
                parts = msg.split()
                if len(parts) >= 3:
                    try:
                        target_username = parts[1].lstrip('@')
                        # Accept both "5" and "5g"
                        amount = int(parts[2].replace('g', '').replace('G', ''))
                        if amount <= 0:
                            await self.highrise.chat("❌ Amount must be positive!")
                            return
                        # Find target in room
                        room_users = await self.safe_get_room_users()
                        target_user = next((u for u, _ in room_users
                                            if u.username.lower() == target_username.lower()), None)
                        if not target_user:
                            await self.highrise.chat(f"❌ @{target_username} not found in room!")
                            return
                        gold = self.to_gold_bar(amount)
                        if not gold:
                            await self.highrise.chat(
                                f"❌ {amount}g not supported!\nUse: 1, 5, 10, 50, 100, 500, 1000, 5000, 10000"
                            )
                            return
                        # Check wallet balance before tipping
                        balance = await self.get_wallet_gold()
                        if balance < amount:
                            await self.highrise.chat(f"❌ Bot wallet is empty! Can't tip @{target_username}. 💸")
                            return
                        await self.highrise.chat(f"💸 Tipping @{target_username} {amount}g... ⏳")
                        await self.highrise.tip_user(target_user.id, gold)
                        await self.highrise.chat(f"✅ @{target_username} received {amount}g! 💰")
                    except ValueError:
                        await self.highrise.chat("❌ Invalid amount! Use: !tip @user 5")
                    except Exception as e:
                        await self.highrise.chat(f"❌ Tip failed: {e}")
                        print(f"[Tip] Error: {e}")
                else:
                    await self.highrise.chat("Usage: !tip @username 5")
                return

            # ── TIP ALL ──────────────────────────────────────────────
            if low.startswith('!tipall'):
                if not self.is_owner(user):
                    await self.highrise.chat("❌ Only the owner can use !tipall!")
                    return
                parts = msg.split()
                if len(parts) >= 2:
                    try:
                        amount = int(parts[1].replace('g', '').replace('G', ''))
                        if amount <= 0:
                            await self.highrise.chat("❌ Amount must be positive!")
                            return
                        room_users = await self.safe_get_room_users()
                        eligible = [u for u, _ in room_users
                                    if u.id != self.highrise.my_id and u.username != user.username]
                        if not eligible:
                            await self.highrise.chat("❌ No other users in room!")
                            return
                        total = amount * len(eligible)
                        # Check wallet balance before starting
                        balance = await self.get_wallet_gold()
                        if balance < total:
                            await self.highrise.chat(
                                f"❌ Bot wallet is empty or insufficient! Need {total}g but only have {balance}g. 💸"
                            )
                            return
                        await self.highrise.chat(
                            f"💸 Tipping {len(eligible)} users {amount}g each ({total}g total)... ⏳"
                        )
                        tipped = 0
                        failed = 0
                        for target in eligible:
                            try:
                                gold = self.to_gold_bar(amount)
                                if not gold:
                                    await self.highrise.chat(f"❌ {amount}g not supported! Use: 1,5,10,50,100,500,1000")
                                    return
                                await self.highrise.tip_user(target.id, gold)
                                tipped += 1
                                # Show progress for each user
                                await self.highrise.chat(
                                    f"✅ [{tipped}/{len(eligible)}] @{target.username} +{amount}g 💰"
                                )
                                await asyncio.sleep(0.8)
                            except Exception as e:
                                failed += 1
                                print(f"[TipAll] Failed for {target.username}: {e}")
                                await self.highrise.chat(f"⚠️ Failed to tip @{target.username}")
                        await self.highrise.chat(
                            f"🎉 Done! Tipped {tipped} users {amount}g each!"
                            + (f" ({failed} failed)" if failed else "")
                        )
                    except ValueError:
                        await self.highrise.chat("❌ Invalid amount! Use: !tipall 5")
                    except Exception as e:
                        await self.highrise.chat(f"❌ TipAll failed: {e}")
                        print(f"[TipAll] Error: {e}")
                else:
                    await self.highrise.chat("Usage: !tipall 5")
                return

            # ── AUTO-TIP ─────────────────────────────────────────────
            if low.startswith('!autotip '):
                if not self.is_owner(user):
                    await self.highrise.chat("❌ Only the owner can use !autotip!")
                    return
                parts = msg.split()
                if len(parts) >= 3:
                    try:
                        amount = int(parts[1].replace('g', '').replace('G', ''))
                        interval_raw = parts[2]
                        interval = int(interval_raw.replace('s', '').replace('m', ''))
                        if 'm' in interval_raw:
                            interval *= 60
                        if amount <= 0 or interval <= 0:
                            await self.highrise.chat("❌ Amount and interval must be positive!")
                            return
                        if interval < 30:
                            await self.highrise.chat("❌ Minimum interval is 30 seconds!")
                            return
                        # Cancel any existing task first
                        if user.username in self.auto_tip_tasks:
                            self.auto_tip_tasks[user.username].cancel()
                        self.auto_tip_enabled[user.username] = True
                        self.auto_tip_amount[user.username] = amount
                        self.auto_tip_interval[user.username] = interval
                        task = asyncio.create_task(self.auto_tip_loop(user.username))
                        self.auto_tip_tasks[user.username] = task
                        await self.highrise.chat(
                            f"✅ Auto-tip ON! Bot tips {amount}g every {interval}s to random users!"
                        )
                    except ValueError:
                        await self.highrise.chat("❌ Invalid format! Use: !autotip 5 60s")
                else:
                    await self.highrise.chat("Usage: !autotip 5 60s (or 1m)")
                return

            if low == '!stopautotip':
                if not self.is_owner(user):
                    await self.highrise.chat("❌ Only the owner can use !stopautotip!")
                    return
                if user.username in self.auto_tip_tasks or self.auto_tip_enabled.get(user.username):
                    # Hard cancel the task
                    task = self.auto_tip_tasks.pop(user.username, None)
                    if task and not task.done():
                        task.cancel()
                    # Clear all state
                    self.auto_tip_enabled.pop(user.username, None)
                    self.auto_tip_amount.pop(user.username, None)
                    self.auto_tip_interval.pop(user.username, None)
                    await self.highrise.chat(f"🛑 Auto-tip STOPPED for @{user.username}!")
                else:
                    await self.highrise.chat("❌ No active auto-tip found.")
                return

            if low == '!autostatus':
                if self.auto_tip_enabled.get(user.username):
                    amount = self.auto_tip_amount.get(user.username, 0)
                    interval = self.auto_tip_interval.get(user.username, 0)
                    await self.highrise.chat(
                        f"✅ Auto-tip ACTIVE\n"
                        f"Tipping {amount}g every {interval}s from bot wallet!"
                    )
                else:
                    await self.highrise.chat(f"❌ Auto-tip not active for @{user.username}")
                return

            # ── FLOORS ───────────────────────────────────────────────
            if low in ('!vipfloor', 'vip'):
                if self.has_vip_access(user.username):
                    if self.vip_floor:
                        await self.highrise.teleport(
                            user.id,
                            Position(self.vip_floor['x'], self.vip_floor['y'], self.vip_floor['z'])
                        )
                        await self.highrise.chat(f"👑 @{user.username} → VIP Floor! ✨")
                    else:
                        await self.highrise.chat("VIP floor not set yet!")
                else:
                    await self.highrise.chat(
                        f"@{user.username}, VIP access required!\n"
                        f"💎 30g = 1 day | 100g = 7 days | 500g = Permanent"
                    )
                return

            if low == '!dancefloor':
                if self.dance_floor:
                    await self.highrise.teleport(
                        user.id,
                        Position(self.dance_floor['x'], self.dance_floor['y'], self.dance_floor['z'])
                    )
                    await self.highrise.chat(f"🕺 @{user.username} teleported to dance floor!")
                else:
                    await self.highrise.chat("Dance floor not set yet!")
                return

            # ── LEADERBOARD ──────────────────────────────────────────
            if low in ('!leaderboard', '!top', '!lb'):
                for msg in self.get_leaderboard_text():
                    await self.highrise.chat(msg)
                    await asyncio.sleep(0.5)
                await asyncio.sleep(0.5)
                # Contest countdown
                countdown = get_contest_countdown()
                if countdown:
                    await self.highrise.chat(
                        f"🏆 CONTEST — TOP 3 YRBHO!\n"
                        f"⏳ Remaining: {countdown}\n"
                        f"💡 Earn pts: 💬chat|💃dance|🎁tip 1gold = 1point|⏱️stay!"
                    )
                else:
                    await self.highrise.chat("💡 Earn pts: 💬chat|💃dance|🎁tip bot: 1gold=1point|⏱️stay!")
                return

            if low in ('!tiplb', '!tippers'):
                for msg in self.get_tips_leaderboard_text():
                    await self.highrise.chat(msg)
                    await asyncio.sleep(0.5)
                return

            # ── RANKS & STATS ────────────────────────────────────────
            if low == '!ranks':
                await self.highrise.chat(
                    "⭐ RANK SYSTEM ⭐\n"
                    "🌱 ROOKIE: 0-49 pts\n"
                    "🥉 BRONZE: 50-149 pts\n"
                    "🥈 SILVER: 150-299 pts\n"
                    "⭐ GOLD: 300-499 pts\n"
                    "👑 PLATINUM: 500-749 pts\n"
                    "💎 DIAMOND: 750-999 pts\n"
                    "🔥 LEGEND: 1000+ pts"
                )
                return

            if low.startswith('!rank'):
                parts = msg.split()
                target = parts[1].lstrip('@') if len(parts) > 1 else user.username
                rating = self.user_ratings.get(target, 0)
                vip_status = " 👑 [VIP]" if self.has_vip_access(target) else ""
                await self.highrise.chat(
                    f"🏅 @{target}{vip_status}\n"
                    f"Rating: {rating} pts\nRank: {self.get_rank_name(rating)}"
                )
                return

            if low.startswith('!stats'):
                parts = msg.split()
                target = parts[1].lstrip('@') if len(parts) > 1 else user.username
                if target in self.user_stats:
                    stats = self.user_stats[target]
                    pts = self.user_ratings.get(target, 0)
                    await self.highrise.chat(
                        f"📊 @{target}:\n"
                        f"💬 {stats['messages']} msgs|🎭 {stats['emotes']} emotes\n"
                        f"⏰ {self.format_time(self.user_total_time.get(target, 0))}\n"
                        f"🏅 {self.get_rank_name(pts)} ({pts} pts)"
                    )
                else:
                    await self.highrise.chat(f"No stats for @{target}")
                return

            # ── TIME LEADERBOARD ──────────────────────────────────────
            if low in ('!time', '!timelb'):
                # Include current session time for users still in room
                combined = dict(self.user_total_time)
                now = time.time()
                try:
                    room_users = await self.safe_get_room_users()
                    for u, _ in room_users:
                        if u.id in self.user_join_times:
                            live = now - self.user_join_times[u.id]
                            combined[u.username] = combined.get(u.username, 0) + live
                except Exception:
                    pass
                # Exclude bots/owners
                filtered = {u: t for u, t in combined.items() if not self._is_excluded_from_lb(u) and t > 0}
                if not filtered:
                    await self.highrise.chat("⏰ No time data yet!")
                    return
                sorted_users = sorted(filtered.items(), key=lambda x: x[1], reverse=True)[:10]
                # Time colors per position
                time_colors = {1:"f1c40f", 2:"c0c0c0", 3:"ff8c00", 4:"ff69b4", 5:"bf00ff",
                               6:"00cfff", 7:"00e676", 8:"ff4500", 9:"aaaaaa", 10:"ffffff"}
                # Part 1: ranks 1-5
                lines1 = ["<#f1c40f>⏰ TOP 10 TIME SPENDERS ⏰"]
                for i, (uname, secs) in enumerate(sorted_users[:5], 1):
                    color = time_colors.get(i, "ffffff")
                    lines1.append(f"<#{color}>{self.get_rank_emoji(i)} {uname} — {self.format_time(secs)}")
                await self.highrise.chat("\n".join(lines1))
                # Part 2: ranks 6-10
                if len(sorted_users) > 5:
                    await asyncio.sleep(0.5)
                    lines2 = ["<#00cfff>⏰ TOP TIME — Part 2/2 ⏰"]
                    for i, (uname, secs) in enumerate(sorted_users[5:], 6):
                        color = time_colors.get(i, "ffffff")
                        lines2.append(f"<#{color}>{self.get_rank_emoji(i)} {uname} — {self.format_time(secs)}")
                    await self.highrise.chat("\n".join(lines2))
                return

            # ── PLAYER TIME (!tt @user or !tt for self) ───────────────
            if low.startswith('!tt'):
                parts = msg.split()
                target = parts[1].lstrip('@') if len(parts) > 1 else user.username
                total = self.user_total_time.get(target, 0)
                # Add live session if still in room
                now = time.time()
                try:
                    room_users = await self.safe_get_room_users()
                    for u, _ in room_users:
                        if u.username.lower() == target.lower() and u.id in self.user_join_times:
                            total += now - self.user_join_times[u.id]
                            break
                except Exception:
                    pass
                if total == 0:
                    await self.highrise.chat(f"<#aaaaaa>⏰ No time recorded for @{target} yet!")
                else:
                    await self.highrise.chat(f"<#00cfff>⏰ @{target} spent {self.format_time(total)} in the room! 🏠")
                return



            # ── SOCIAL ───────────────────────────────────────────────

            if low == '!truth':
                await self.highrise.chat(f"🤔 TRUTH l @{user.username}: {random.choice(self.truths)}")
                return

            if low == '!dare':
                dare = random.choice(self.dares)
                await self.highrise.chat(f"😈 DARE l @{user.username}:\n{dare}")
                return

            if low == '!joke':
                if not self.jokes:
                    await self.highrise.chat("😅 Jokes not loaded — add nokat.json!")
                    return
                joke = random.choice(self.jokes)
                await self.highrise.chat(joke)
                return

            if low == '!riddle':
                if not self.riddles:
                    await self.highrise.chat("😅 Riddles not loaded — add swalouat.json!")
                    return
                # Only one active riddle per user at a time
                if user.id in self.active_riddles:
                    await self.highrise.chat(f"@{user.username} — 3endek riddle mazal! Jaweb wla kteb !skip!")
                    return
                idx = random.randrange(len(self.riddles))
                riddle  = self.riddles[idx]
                answer  = self.riddle_answers[idx]
                await self.highrise.chat(f"{riddle}\n⏳ 3endek 25 sec!")
                # Store active riddle state
                self.active_riddles[user.id] = {"answer": answer, "username": user.username}
                # Auto-reveal after 25 seconds
                async def _reveal(uid=user.id, ans=answer, uname=user.username):
                    await asyncio.sleep(25)
                    if uid in self.active_riddles:
                        del self.active_riddles[uid]
                        try:
                            await self.highrise.chat(f"⏰ Waqt sala @{uname}!\n{ans}")
                        except Exception:
                            pass
                asyncio.create_task(_reveal())
                return

            if low == '!skip':
                if user.id in self.active_riddles:
                    ans = self.active_riddles.pop(user.id)["answer"]
                    await self.highrise.chat(f"⏭️ @{user.username} skipped!\n{ans}")
                else:
                    await self.highrise.chat(f"@{user.username} — ma 3endeksh riddle daba!")
                return

            if low == '!roll':
                await self.highrise.chat(f"🎲 @{user.username} rolled {random.randint(1, 6)}!")
                return

            if low == '!flip':
                await self.highrise.chat(f"🪙 @{user.username}: {random.choice(['Heads', 'Tails'])}!")
                return

            # ── STOP (non-owner stops their own emote loop) ───────────
            if low == 'stop' and not self.is_owner(user):
                if user.id in self.looping_users:
                    self.looping_users[user.id] = False
                    await asyncio.sleep(0.3)
                    if user.id in self.looping_users:
                        del self.looping_users[user.id]
                await self.highrise.chat(f"🛑 @{user.username} stopped.")
                return

            # ── RANDOM EMOTE ──────────────────────────────────────────
            if low == 'random':
                if user.id in self.looping_users:
                    await self.highrise.chat(f"⚠️ @{user.username} rak deja f loop! Kteb '0' bach twaqaf 🛑")
                    return
                self.looping_users[user.id] = True
                await self.highrise.chat(f"🎲 @{user.username} random emotes loop! Kteb '0' bach twaqaf 🛑")
                asyncio.create_task(self.loop_random_emote(user.id))
                return

            # ── STOP WITH 0 ───────────────────────────────────────────
            if low == '0':
                if user.id in self.looping_users:
                    self.looping_users[user.id] = False
                    await asyncio.sleep(0.3)
                    if user.id in self.looping_users:
                        del self.looping_users[user.id]
                    await self.highrise.chat(f"🛑 @{user.username} stopped random loop!")
                return

            # ── EMOTE NUMBERS ─────────────────────────────────────────
            loop_match   = re.fullmatch(r"loop\s+(\d+)", low)
            number_match = re.fullmatch(r"(\d+)", low)

            if loop_match or number_match:
                is_loop = bool(loop_match)
                index = int(loop_match.group(1) if loop_match else number_match.group(1)) - 1

                if 0 <= index < len(self.emote_keys):
                    emote_name = self.emote_keys[index]
                    emote_data = self.emote_dict[emote_name]
                    emote_id   = emote_data[0]
                    duration   = float(emote_data[1])

                    if is_loop:
                        if user.id in self.looping_users:
                            # Already looping — just tell them to stop first, do nothing
                            await self.highrise.chat(
                                f"⚠️ @{user.username} rak deja f loop! Kteb 'stop' awwel, men b3d kteb loop jdid 🛑"
                            )
                            return
                        # No active loop — start fresh
                        self.looping_users[user.id] = True
                        await self.highrise.chat(f"🔄 @{user.username} looping #{index + 1}")
                        asyncio.create_task(self.loop_emote(user.id, emote_id, duration))
                    else:
                        await self.highrise.send_emote(emote_id, user.id)
                else:
                    await self.highrise.chat(f"❌ Invalid. Choose 1-{len(self.emote_keys)}")
                return


            # ── INFO & DATA COMMANDS ──────────────────────────────────

            # !info [username] — anyone sees own info, owner can check others
            if low == "!info" or low.startswith("!info "):
                parts = msg.split()
                target = parts[1] if len(parts) >= 2 and self.is_owner(user) else user.username
                pts = self.user_ratings.get(target, 0)
                perm = "💎Yes" if target in self.vip_permanent else "No"
                timed_str = "No"
                if target in self.vip_timed:
                    rem = self.vip_timed[target] - time.time()
                    if rem > 0:
                        timed_str = f"{int(rem//86400)}d{int((rem%86400)//3600)}h"
                is_mod = "Yes" if target in self.moderators else "No"
                greeting = self.custom_greetings.get(target, "None")[:35]
                await self.highrise.chat(f"👤{target} ⭐{pts}pts 💎{perm} ⏰{timed_str} 🛡️{is_mod}")
                await asyncio.sleep(0.4)
                await self.highrise.chat(f"💬 {greeting}")
                return

            # !infow [username] — same but whispered
            if low == "!infow" or low.startswith("!infow "):
                parts = msg.split()
                target = parts[1] if len(parts) >= 2 and self.is_owner(user) else user.username
                pts = self.user_ratings.get(target, 0)
                perm = "💎Yes" if target in self.vip_permanent else "No"
                timed_str = "No"
                if target in self.vip_timed:
                    rem = self.vip_timed[target] - time.time()
                    if rem > 0:
                        timed_str = f"{int(rem//86400)}d{int((rem%86400)//3600)}h"
                is_mod = "Yes" if target in self.moderators else "No"
                greeting = self.custom_greetings.get(target, "None")[:35]
                await self.highrise.send_whisper(user.id, f"👤{target} ⭐{pts}pts 💎{perm} ⏰{timed_str} 🛡️{is_mod}")
                await asyncio.sleep(0.3)
                await self.highrise.send_whisper(user.id, f"💬 {greeting}")
                return

            # ── OWNER ONLY COMMANDS ───────────────────────────────────
            if self.is_owner(user):

                # !data — overview
                if low == "!data":
                    await self.highrise.chat(f"📊 VIP💎{len(self.vip_permanent)} Timed⏰{len(self.vip_timed)} Pts⭐{len(self.user_ratings)} Greet💬{len(self.custom_greetings)} Mods🛡️{len(self.moderators)}")
                    await asyncio.sleep(0.4)
                    await self.highrise.chat("!viplist !timedvip !pointslist !greetlist")
                    return

                # !viplist — permanent VIPs
                if low == "!viplist":
                    if self.vip_permanent:
                        vips = list(self.vip_permanent)
                        chunks = [vips[i:i+5] for i in range(0, len(vips), 5)]
                        for chunk in chunks:
                            await self.highrise.chat("💎 " + " | ".join(chunk))
                            await asyncio.sleep(0.4)
                    else:
                        await self.highrise.chat("💎 No permanent VIPs.")
                    return

                # !timedvip — timed VIPs with time left
                if low == "!timedvip":
                    if self.vip_timed:
                        now = time.time()
                        lines = []
                        for u, exp in self.vip_timed.items():
                            rem = exp - now
                            lines.append(f"{u}:{int(rem//86400)}d{int((rem%86400)//3600)}h" if rem > 0 else f"{u}:expired")
                        chunks = [lines[i:i+4] for i in range(0, len(lines), 4)]
                        for chunk in chunks:
                            await self.highrise.chat("⏰ " + " | ".join(chunk))
                            await asyncio.sleep(0.4)
                    else:
                        await self.highrise.chat("⏰ No timed VIPs.")
                    return

                # !pointslist — top 15
                if low == "!pointslist":
                    sorted_pts = sorted(self.user_ratings.items(), key=lambda x: x[1], reverse=True)[:15]
                    lines = [f"{i+1}.{u}:{p}" for i, (u, p) in enumerate(sorted_pts)]
                    chunks = [lines[i:i+5] for i in range(0, len(lines), 5)]
                    for chunk in chunks:
                        await self.highrise.chat("⭐ " + " | ".join(chunk))
                        await asyncio.sleep(0.4)
                    return

                # !greetlist — all greetings
                if low == "!greetlist":
                    if self.custom_greetings:
                        lines = [f"{u}: {g[:20]}" for u, g in list(self.custom_greetings.items())[:12]]
                        chunks = [lines[i:i+3] for i in range(0, len(lines), 3)]
                        for chunk in chunks:
                            await self.highrise.chat("💬 " + " | ".join(chunk))
                            await asyncio.sleep(0.4)
                    else:
                        await self.highrise.chat("💬 No greetings.")
                    return

                # !addvip username hours
                if low.startswith("!addvip "):
                    parts = msg.split()
                    if len(parts) >= 3:
                        try:
                            target, hours = parts[1], float(parts[2])
                            self.vip_timed[target] = time.time() + hours * 3600
                            self._persist()
                            await self.highrise.chat(f"✅ @{target} VIP {int(hours//24)}d{int(hours%24)}h!")
                        except:
                            await self.highrise.chat("❌ !addvip username hours")
                    else:
                        await self.highrise.chat("❌ !addvip username hours")
                    return

                # !removevip username
                if low.startswith("!removevip "):
                    target = msg.split()[1] if len(msg.split()) >= 2 else None
                    if target:
                        removed = False
                        if target in self.vip_timed:
                            del self.vip_timed[target]; removed = True
                        if target in self.vip_permanent:
                            self.vip_permanent.discard(target); removed = True
                        if removed:
                            self._persist()
                            await self.highrise.chat(f"✅ VIP removed: @{target}")
                        else:
                            await self.highrise.chat(f"❌ @{target} has no VIP")
                    return

                # !addpermvip username
                if low.startswith("!addpermvip "):
                    parts = msg.split()
                    if len(parts) >= 2:
                        self.vip_permanent.add(parts[1])
                        self._persist()
                        await self.highrise.chat(f"💎 @{parts[1]} Permanent VIP!")
                    return

                # !addpoints username amount
                if low.startswith("!addpoints "):
                    parts = msg.split()
                    if len(parts) >= 3:
                        try:
                            target, amount = parts[1], int(parts[2])
                            self.user_ratings[target] = self.user_ratings.get(target, 0) + amount
                            self._persist()
                            await self.highrise.chat(f"✅ +{amount}pts @{target} → {self.user_ratings[target]}")
                        except:
                            await self.highrise.chat("❌ !addpoints username amount")
                    else:
                        await self.highrise.chat("❌ !addpoints username amount")
                    return

                # !removepoints username amount
                if low.startswith("!removepoints "):
                    parts = msg.split()
                    if len(parts) >= 3:
                        try:
                            target, amount = parts[1], int(parts[2])
                            self.user_ratings[target] = max(0, self.user_ratings.get(target, 0) - amount)
                            self._persist()
                            await self.highrise.chat(f"✅ -{amount}pts @{target} → {self.user_ratings[target]}")
                        except:
                            await self.highrise.chat("❌ !removepoints username amount")
                    else:
                        await self.highrise.chat("❌ !removepoints username amount")
                    return

                # !setpoints username amount
                if low.startswith("!setpoints "):
                    parts = msg.split()
                    if len(parts) >= 3:
                        try:
                            target, amount = parts[1], int(parts[2])
                            self.user_ratings[target] = amount
                            self._persist()
                            await self.highrise.chat(f"✅ @{target} points = {amount}")
                        except:
                            await self.highrise.chat("❌ !setpoints username amount")
                    return

                # !addgreeting username text
                if low.startswith("!addgreeting "):
                    parts = msg.split(None, 2)
                    if len(parts) >= 3:
                        self.custom_greetings[parts[1]] = parts[2]
                        self._persist()
                        await self.highrise.chat(f"✅ Greeting set: @{parts[1]}")
                    else:
                        await self.highrise.chat("❌ !addgreeting username text")
                    return

                # !removegreeting username
                if low.startswith("!removegreeting "):
                    parts = msg.split()
                    if len(parts) >= 2:
                        target = parts[1]
                        if target in self.custom_greetings:
                            del self.custom_greetings[target]
                            self._persist()
                            await self.highrise.chat(f"✅ Greeting removed: @{target}")
                        else:
                            await self.highrise.chat(f"❌ No greeting for @{target}")
                    return

                # !addmod username
                if low.startswith("!addmod "):
                    parts = msg.split()
                    if len(parts) >= 2:
                        self.moderators.add(parts[1])
                        self._persist()
                        await self.highrise.chat(f"🛡️ @{parts[1]} is now a mod!")
                    return

                # !removemod username
                if low.startswith("!removemod "):
                    parts = msg.split()
                    if len(parts) >= 2:
                        target = parts[1]
                        if target in self.moderators:
                            self.moderators.discard(target)
                            self._persist()
                            await self.highrise.chat(f"✅ Mod removed: @{target}")
                        else:
                            await self.highrise.chat(f"❌ @{target} is not a mod")
                    return

        except Exception as e:
            print(f"Error in on_chat: {e}")

    # ─────────────────────────────────────────────────────────────────
    #  EMOTE LOOP
    # ─────────────────────────────────────────────────────────────────
    # Emotes that have a visible stand-up/reset at the end — re-trigger aggressively early
    FLOOR_EMOTES = {
        "idle-floorsleeping",   # Cozy Nap
        "idle-floorsleeping2",  # Relaxing
        "idle_layingdown",      # Attentive
        "sit-relaxed",          # Relaxed
        "idle-loop-sitfloor",   # Sit
        "idle-toilet",          # Toilet
        "idle_zombie",          # Zombie
        "idle-nervous",         # Nervous
        "idle_singing",         # Singing
        "idle-loop-sad",        # Bummed
        "idle-loop-happy",      # Chillin'
        "idle-loop-annoyed",    # Annoyed
        "idle-loop-aerobics",   # Aerobics
        "idle-loop-tired",      # Sleepy
        "idle-loop-tapdance",   # Tap Loop
        "idle-dance-casual",    # Casual Dance
        "idle-guitar",          # Air Guitar
        "idle-uwu",             # UwU
        "idle-dance-tiktok4",   # TikTok Dance 4
        "idle-wild",            # Scritchy
    }

    # ─────────────────────────────────────────────────────────────────
    #  DAWYA WORD GAME
    # ─────────────────────────────────────────────────────────────────
    async def dawya_game_loop(self):
        """Every 1-8 minutes, challenge the room to type a random Moroccan word first."""
        await asyncio.sleep(60)  # Initial delay — let the room settle
        while True:
            try:
                # Wait a random interval between rounds (1–8 minutes)
                wait = random.randint(60, 480)
                await asyncio.sleep(wait)
                if not self.is_connected:
                    continue

                # Pick a random word
                word = random.choice(self.dawya_words)
                self.dawya_current_word = word
                self.dawya_active = True
                self.dawya_claimed = False
                self.dawya_winner_this_round = None

                announce = self.gradient_text("⚡ WORD CHALLENGE! ⚡", "fire")
                await self.highrise.chat(
                    f"{announce}\n"
                    f"🏃 Awwel wa7ed ykteb '{word}' f chat "
                    f"ywl +5 nqat f leaderboard! 🏆"
                )

                # Give players 20 seconds to respond
                await asyncio.sleep(20)

                # Time's up — if nobody claimed it
                if self.dawya_active and not self.dawya_claimed:
                    self.dawya_active = False
                    self.dawya_current_word = None
                    await self.highrise.chat(f"⏰ Waqt sala! Ma7ad kteb '{word}'... 😅")

            except Exception as e:
                print(f"[WordGame] Error: {e}")
                await asyncio.sleep(30)

    async def on_disconnect(self) -> None:
        """Called when the WebSocket drops — wait and let the SDK reconnect naturally."""
        self.is_connected = False
        print("[DISCONNECT] Bot disconnected — waiting for SDK to reconnect...")

    async def loop_emote(self, user_id, emote_id, duration):
        try:
            while self.looping_users.get(user_id, False):
                if not self.is_connected:
                    await asyncio.sleep(2)
                    continue
                await self.highrise.send_emote(emote_id, user_id)
                # Floor/idle emotes have a visible stand-up at the end —
                # re-trigger 2.5s early to cut off the reset animation.
                # Regular emotes just need a small 0.4s overlap.
                if emote_id in self.FLOOR_EMOTES:
                    sleep_time = max(duration - 2.5, 0.8)
                else:
                    sleep_time = max(duration - 0.4, 0.8)
                await asyncio.sleep(sleep_time)
        except Exception as e:
            print(f"Error in loop_emote: {e}")
        finally:
            if user_id in self.looping_users:
                del self.looping_users[user_id]

    async def loop_random_emote(self, user_id):
        """Keep playing random emotes for a user until they type '0'."""
        try:
            while self.looping_users.get(user_id, False):
                if not self.is_connected:
                    await asyncio.sleep(2)
                    continue
                emote_name = random.choice(self.emote_keys)
                emote_data = self.emote_dict[emote_name]
                emote_id   = emote_data[0]
                duration   = float(emote_data[1])
                try:
                    await self.highrise.send_emote(emote_id, user_id)
                except Exception:
                    # User doesn't own this emote — skip it silently
                    continue
                if emote_id in self.FLOOR_EMOTES:
                    sleep_time = max(duration - 2.5, 0.8)
                else:
                    sleep_time = max(duration - 0.4, 0.8)
                await asyncio.sleep(sleep_time)
        except Exception as e:
            print(f"Error in loop_random_emote: {e}")
        finally:
            if user_id in self.looping_users:
                del self.looping_users[user_id]