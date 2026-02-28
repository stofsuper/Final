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
DATA_FILE = os.environ.get("DATA_FILE", "/data/chikha_data.json")  # Railway volume path

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
            'sharmouta', 'sharmota', 'mtnayak', 'mtniyak',
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

    async def send_chunks(self, lines: list, header: str = "", max_len: int = 200):
        """Send list of lines in chunks fitting Highrise message limit."""
        chunk = header
        for line in lines:
            test = (chunk + "\n" + line) if chunk else line
            if len(test) > max_len:
                await self.highrise.chat(chunk)
                await asyncio.sleep(0.5)
                chunk = line
            else:
                chunk = test
        if chunk:
            await self.highrise.chat(chunk)

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
    # ─────────────────────────────────────────────────────
