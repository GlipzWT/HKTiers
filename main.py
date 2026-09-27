import datetime
import json
import os
import asyncio
import discord
from discord import app_commands
from discord.ext import commands, tasks
from itertools import cycle

# ---------------------------------------------------------------------------
# КОНФИГУРАЦИЯ БОТА
# ---------------------------------------------------------------------------
BOT_TOKEN = "MTU1MzU1Mjk3NDg1OTYwMDAxNQ.GHM7sf.-671qwoyb5oSAzQcsP6z9NfFdLuahs_85E1-qE"

# ID Сервера
GUILD_ID = 1553373948161556560

# ID Каналов
WAITLIST_CHANNEL_ID = 1553557269696872489
TESTER_PANEL_CHANNEL_ID = 1553557327817351301
RESULTS_CHANNEL_ID = 1553546550482051172
CATEGORY_TICKETS_ID = None

# ID Ролей
WAITLIST_ROLE_ID = 1553554370124189766
RESTRICTED_ROLE_ID = 1553554434183667915
TESTER_ROLE_ID = 1553496244578558113

# ПОЛНЫЙ СПИСОК РОЛЕЙ ТИРОВ (Укажите реальные ID ролей для HT3-HT1 при наличии)
TIER_ROLES = {
    "LT5": 1553554581202407575,
    "HT5": 1553554693190320168,
    "LT4": 1553554840200814804,
    "HT4": 1553554915543089172,
    "LT3": 1553555021239554160,
    "HT3": 1553592852351557652,
    "LT2": 1553592922820050976,
    "HT2": 1553592993338892369,
    "LT1": 1553593080102396005,
    "HT1": 1553593157223059567,
}

# Порядок тиров от младшего к старшему
TIER_ORDER = [
    "Low Tier 5",
    "High Tier 5",
    "Low Tier 4",
    "High Tier 4",
    "Low Tier 3",
    "High Tier 3",
    "Low Tier 2",
    "High Tier 2",
    "Low Tier 1",
    "High Tier 1",
]

# Имена тиров по ключам
TIER_NAMES = {
    "LT5": "Low Tier 5",
    "HT5": "High Tier 5",
    "LT4": "Low Tier 4",
    "HT4": "High Tier 4",
    "LT3": "Low Tier 3",
    "HT3": "High Tier 3",
    "LT2": "Low Tier 2",
    "HT2": "High Tier 2",
    "LT1": "Low Tier 1",
    "HT1": "High Tier 1",
}

# Веса тиров для сортировки в лидерборде
TIER_WEIGHTS = {name: idx + 1 for idx, name in enumerate(TIER_ORDER)}

# Список тиров, имеющих доступ к High Tier тикетам
HIGH_TIER_ELIGIBLE = [
    "Low Tier 3",
    "High Tier 3",
    "Low Tier 2",
    "High Tier 2",
    "Low Tier 1",
    "High Tier 1",
]

# Эмодзи галочки для Пинга в ЛС
VERIFIED_EMOJI = "<:592053verified:1553517378544078910>"

DATA_FILE = "bot_data.json"
DATA_LOCK = asyncio.Lock()


# ---------------------------------------------------------------------------
# МЕНЕДЖЕР ДАННЫХ
# ---------------------------------------------------------------------------
def get_default_data():
    return {
        "queue": [],
        "active_testers": [],
        "paused_testers": [],
        "active_ht_tickets": [],
        "is_open": False,
        "last_test_time": "Не проводился",
        "cooldowns": {},
        "user_tiers": {},
        "user_history": {},
        "tester_stats": {},
        "waitlist_msg_id": None,
        "tester_panel_msg_id": None,
    }


async def load_data():
    async with DATA_LOCK:
        if not os.path.exists(DATA_FILE) or os.path.getsize(DATA_FILE) == 0:
            data = get_default_data()
            save_data_no_lock(data)
            return data

        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "active_testers" not in data:
                    data["active_testers"] = []
                if "paused_testers" not in data:
                    data["paused_testers"] = []
                if "active_ht_tickets" not in data:
                    data["active_ht_tickets"] = []
                if "user_history" not in data:
                    data["user_history"] = {}
                if "tester_panel_msg_id" not in data:
                    data["tester_panel_msg_id"] = None
                if "tester_stats" not in data:
                    data["tester_stats"] = {}
                return data
        except (json.JSONDecodeError, Exception):
            data = get_default_data()
            save_data_no_lock(data)
            return data


def save_data_no_lock(data):
    temp_file = f"{DATA_FILE}.tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(temp_file, DATA_FILE)


async def save_data(data):
    async with DATA_LOCK:
        save_data_no_lock(data)


# ---------------------------------------------------------------------------
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ---------------------------------------------------------------------------
async def notify_first_in_queue(guild: discord.Guild, data: dict):
    if not data["queue"]:
        return

    first_user_id = data["queue"][0]
    member = guild.get_member(first_user_id)
    if member:
        try:
            await member.send(f"{VERIFIED_EMOJI} Вы первый в очереди на квалификационный тест, будьте готовы!")
        except Exception:
            pass


def get_adjacent_tier(current_tier: str, direction: int) -> str:
    """direction: +1 - повышение, -1 - демоут"""
    if current_tier not in TIER_ORDER:
        return current_tier
    idx = TIER_ORDER.index(current_tier)
    new_idx = max(0, min(len(TIER_ORDER) - 1, idx + direction))
    return TIER_ORDER[new_idx]


# ---------------------------------------------------------------------------
# ЭМБЕДЫ
# ---------------------------------------------------------------------------
def get_waitlist_embed(data: dict, guild: discord.Guild) -> discord.Embed:
    if data["is_open"]:
        embed = discord.Embed(
            title="🟢 Очередь на тестирование открыта!",
            description="Тестеры онлайн! Нажмите кнопку ниже, чтобы встать в очередь.\n"
                        "Убедитесь, что вы готовы зайти в игру прямо сейчас.\n\n",
            color=discord.Color.green(),
        )

        testers_list = []
        for t_id in data.get("active_testers", []):
            m = guild.get_member(t_id)
            if m:
                status = " ⏸ *(На паузе)*" if t_id in data.get("paused_testers", []) else ""
                testers_list.append(f"{m.mention}{status}")

        testers_str = ", ".join(testers_list) if testers_list else "Никого нет"
        embed.add_field(name="Тестеры онлайн", value=testers_str, inline=False)

        queue_ids = data["queue"]
        if queue_ids:
            q_list = []
            for idx, p_id in enumerate(queue_ids[:20], 1):
                m = guild.get_member(p_id)
                name = m.display_name if m else f"ID: {p_id}"
                q_list.append(f"`{idx}.` {name}")
            queue_str = "\n".join(q_list)
            if len(queue_ids) > 20:
                queue_str += f"\n*...и еще {len(queue_ids) - 20} чел.*"
        else:
            queue_str = "*Очередь пуста*"

        embed.add_field(
            name=f"Квалификационная очередь ({len(queue_ids)})",
            value=queue_str,
            inline=False,
        )
    else:
        embed = discord.Embed(
            title="🔴 Очередь квалификации закрыта",
            description="Сейчас нет активных тестеров онлайн.\n\n",
            color=discord.Color.red(),
        )

    embed.add_field(
        name="Время последнего теста",
        value=f"`{data.get('last_test_time', 'Не проводился')}`",
        inline=False,
    )
    embed.set_footer(text="Fast PVP [HKTiers] • Нажмите кнопки ниже для взаимодействия")
    return embed


def get_tester_panel_embed(data: dict, guild: discord.Guild) -> discord.Embed:
    status_str = "🟢 **Открыта**" if data["is_open"] else "🔴 **Закрыта**"

    active_testers = data.get("active_testers", [])
    paused_testers = data.get("paused_testers", [])

    testers_list = []
    for t_id in active_testers:
        m = guild.get_member(t_id)
        if m:
            status = " ⏸ *(На паузе)*" if t_id in paused_testers else ""
            testers_list.append(f"{m.display_name}{status}")

    testers_str = ", ".join(testers_list) if testers_list else "Нет активных тестеров"

    embed = discord.Embed(
        title="🛠 Панель Управления Тестеров (HKTiers)",
        description=f"Статус квалификационной очереди: {status_str}\n"
                    f"Игроков в квалификации: **{len(data['queue'])}**\n"
                    f"Тестеры на смене: **{testers_str}**",
        color=discord.Color.blue(),
    )
    embed.add_field(
        name="Время последнего теста",
        value=f"`{data.get('last_test_time', 'Не проводился')}`",
        inline=False,
    )
    return embed


async def update_public_waitlist_message(guild: discord.Guild):
    data = await load_data()
    msg_id = data.get("waitlist_msg_id")
    if not msg_id:
        return

    channel = guild.get_channel(WAITLIST_CHANNEL_ID)
    if not channel:
        return

    try:
        msg = await channel.fetch_message(msg_id)
        await msg.edit(embed=get_waitlist_embed(data, guild), view=PublicWaitlistView())
    except discord.NotFound:
        pass


async def update_tester_panel_message(guild: discord.Guild):
    data = await load_data()
    msg_id = data.get("tester_panel_msg_id")
    if not msg_id:
        return

    channel = guild.get_channel(TESTER_PANEL_CHANNEL_ID)
    if not channel:
        return

    try:
        msg = await channel.fetch_message(msg_id)
        await msg.edit(embed=get_tester_panel_embed(data, guild), view=TesterPanelView())
    except discord.NotFound:
        pass


# ---------------------------------------------------------------------------
# ВЬЮШКИ
# ---------------------------------------------------------------------------
class LeaderboardPaginatorView(discord.ui.View):
    def __init__(self, players_data: list, author_id: int):
        super().__init__(timeout=120)
        self.players_data = players_data
        self.author_id = author_id
        self.current_page = 0
        self.per_page = 10
        self.max_pages = max(1, (len(players_data) + self.per_page - 1) // self.per_page)

    def create_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🏆 Официальный Лидерборд HKTiers",
            description="Общий сквозной рейтинг игроков, прошедших тестирование Fast PVP.\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯",
            color=discord.Color.gold(),
        )

        if not self.players_data:
            embed.add_field(
                name="Список пуст",
                value="*На сервере пока нет игроков с полученными тирами.*",
                inline=False
            )
            return embed

        start_idx = self.current_page * self.per_page
        end_idx = start_idx + self.per_page
        page_items = self.players_data[start_idx:end_idx]

        lines = []
        for global_rank, (member, tier_name) in enumerate(page_items, start=start_idx + 1):
            if global_rank == 1:
                rank_icon = "🥇"
            elif global_rank == 2:
                rank_icon = "🥈"
            elif global_rank == 3:
                rank_icon = "🥉"
            else:
                rank_icon = f"`{global_rank}.`"

            lines.append(f"{rank_icon} {member.mention} — `{member.display_name}` • **[{tier_name}]**")

        embed.add_field(
            name=f"Рейтинг игроков ({start_idx + 1}–{min(end_idx, len(self.players_data))} из {len(self.players_data)}):",
            value="\n".join(lines),
            inline=False,
        )

        embed.set_footer(
            text=f"Страница {self.current_page + 1} из {self.max_pages} • Всего игроков: {len(self.players_data)} • HKTiers"
        )
        return embed

    def update_buttons(self):
        self.prev_button.disabled = (self.current_page == 0)
        self.next_button.disabled = (self.current_page >= self.max_pages - 1)

    @discord.ui.button(label="◀ Назад", style=discord.ButtonStyle.blurple, custom_id="lb_prev")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ Только вызвавший команду может листать страницы!",
                                                           ephemeral=True)

        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="Вперёд ▶", style=discord.ButtonStyle.blurple, custom_id="lb_next")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ Только вызвавший команду может листать страницы!",
                                                           ephemeral=True)

        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)


class WaitlistPingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Получать уведомления", style=discord.ButtonStyle.green, custom_id="wl_add_role")
    async def add_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = interaction.guild.get_role(WAITLIST_ROLE_ID)
        if role:
            await interaction.user.add_roles(role)
            await interaction.response.send_message("✅ Вам выдана роль для уведомлений о тестировании!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Роль не найдена.", ephemeral=True)

    @discord.ui.button(label="Убрать роль", style=discord.ButtonStyle.red, custom_id="wl_remove_role")
    async def remove_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = interaction.guild.get_role(WAITLIST_ROLE_ID)
        if role:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message("🗑 Роль уведомлений снята.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Роль не найдена.", ephemeral=True)


class PublicWaitlistView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Встать в очередь (Квалификация)", style=discord.ButtonStyle.blurple,
                       custom_id="wl_join_queue")
    async def join_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = await load_data()
        user = interaction.user
        user_id_str = str(user.id)
        current_tier = data.get("user_tiers", {}).get(user_id_str, "Не установлен")

        if current_tier in HIGH_TIER_ELIGIBLE:
            return await interaction.response.send_message(
                f"⚠️ Ваш текущий тир — **{current_tier}**. Вы перешли на High Tier этап! "
                f"Используйте кнопку **«High Tier тикет»**.",
                ephemeral=True,
            )

        if not data["is_open"]:
            return await interaction.response.send_message("❌ Очередь квалификации сейчас закрыта!", ephemeral=True)

        restricted_role = interaction.guild.get_role(RESTRICTED_ROLE_ID)
        if restricted_role and restricted_role in user.roles:
            return await interaction.response.send_message("⛔ Вам запрещен доступ к тестированию!", ephemeral=True)

        if user_id_str in data["cooldowns"]:
            last_test_ts = data["cooldowns"][user_id_str]
            now_ts = datetime.datetime.now().timestamp()
            days_passed = (now_ts - last_test_ts) / 86400

            if days_passed < 14:
                days_left = int(14 - days_passed)
                return await interaction.response.send_message(
                    f"⏳ У вас активен кулдаун! Следующий квалификационный тест доступен через **{days_left} дн.**",
                    ephemeral=True,
                )

        if user.id in data["queue"]:
            return await interaction.response.send_message("⚠️ Вы уже в очереди!", ephemeral=True)

        data["queue"].append(user.id)
        was_first = (len(data["queue"]) == 1)
        await save_data(data)

        if was_first:
            await notify_first_in_queue(interaction.guild, data)

        await update_public_waitlist_message(interaction.guild)
        await interaction.response.send_message(
            f"✅ Вы встали в квалификационную очередь! Ваш номер: **{len(data['queue'])}**", ephemeral=True)

    @discord.ui.button(label="🔥 High Tier тикет (LT3+)", style=discord.ButtonStyle.primary, custom_id="wl_ht_ticket")
    async def create_ht_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = await load_data()
        user = interaction.user
        user_id_str = str(user.id)
        current_tier = data.get("user_tiers", {}).get(user_id_str, "Не установлен")

        if current_tier not in HIGH_TIER_ELIGIBLE:
            return await interaction.response.send_message(
                f"⛔ High Tier тикеты доступны только игрокам с тиром **LT3** и выше!\n"
                f"Ваш текущий тир: **{current_tier}**.",
                ephemeral=True,
            )

        if user.id in data.get("active_ht_tickets", []):
            return await interaction.response.send_message(
                "⚠️ У вас уже создан активный High Tier тикет! Дождитесь его завершения.",
                ephemeral=True,
            )

        category = interaction.guild.get_channel(CATEGORY_TICKETS_ID) if CATEGORY_TICKETS_ID else None
        tester_role = interaction.guild.get_role(TESTER_ROLE_ID)

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        if tester_role:
            overwrites[tester_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        channel_name = f"hightier-{user.name}"
        ticket_channel = await interaction.guild.create_text_channel(
            name=channel_name, category=category, overwrites=overwrites
        )

        data["active_ht_tickets"].append(user.id)
        await save_data(data)

        embed = discord.Embed(
            title=f"🔥 High Tier тест: {user.display_name}",
            description=f"**Текущий тир игрока:** `{current_tier}`\n\n"
                        f"Тестеры могут выбрать результат боя по кнопкам ниже:",
            color=discord.Color.dark_gold(),
        )
        embed.set_footer(text="Результаты High Tier тестов заносятся в базу без кулдауна.")

        view = HighTierTicketControlView(player_id=user.id)
        tester_mention = tester_role.mention if tester_role else "Тестеры"
        await ticket_channel.send(content=f"{user.mention} {tester_mention}", embed=embed, view=view)

        await interaction.response.send_message(f"✅ High Tier тикет создан: {ticket_channel.mention}", ephemeral=True)

    @discord.ui.button(label="Выйти из очереди", style=discord.ButtonStyle.gray, custom_id="wl_leave_queue")
    async def leave_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = await load_data()
        if interaction.user.id in data["queue"]:
            was_first = (data["queue"][0] == interaction.user.id)
            data["queue"].remove(interaction.user.id)
            await save_data(data)

            if was_first and data["queue"]:
                await notify_first_in_queue(interaction.guild, data)

            await update_public_waitlist_message(interaction.guild)
            await interaction.response.send_message("🚪 Вы вышли из очереди.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ Вас нет в очереди.", ephemeral=True)


class TesterPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Тестировка (Квалификация)", style=discord.ButtonStyle.blurple, custom_id="tp_next_test")
    async def start_test(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = await load_data()
        if not data["queue"]:
            return await interaction.response.send_message("⚠️ Квалификационная очередь пуста!", ephemeral=True)

        player_id = data["queue"].pop(0)
        await save_data(data)

        if data["queue"]:
            await notify_first_in_queue(interaction.guild, data)

        player = interaction.guild.get_member(player_id)
        if not player:
            return await interaction.response.send_message("❌ Игрок не найден на сервере.", ephemeral=True)

        category = interaction.guild.get_channel(CATEGORY_TICKETS_ID) if CATEGORY_TICKETS_ID else None
        tester_role = interaction.guild.get_role(TESTER_ROLE_ID)

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            player: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        if tester_role:
            overwrites[tester_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        channel_name = f"qual-{interaction.user.name}-{player.name}"
        ticket_channel = await interaction.guild.create_text_channel(
            name=channel_name, category=category, overwrites=overwrites
        )

        try:
            await player.send(f"⚔️ Ваш квалификационный тест начинается! Перейдите в канал: {ticket_channel.mention}")
        except Exception:
            pass

        embed = discord.Embed(
            title=f"Тестирование игрока: {player.display_name}",
            description="Выберите полученный тир по кнопкам ниже:",
            color=discord.Color.gold(),
        )
        view = TicketControlView(player_id=player.id, tester_id=interaction.user.id)
        await ticket_channel.send(content=f"{player.mention} {interaction.user.mention}", embed=embed, view=view)

        await update_public_waitlist_message(interaction.guild)
        await update_tester_panel_message(interaction.guild)
        await interaction.response.send_message(f"✅ Тикет создан: {ticket_channel.mention}", ephemeral=True)

    @discord.ui.button(label="Встать на тестировку", style=discord.ButtonStyle.green, custom_id="tp_shift_on")
    async def shift_on(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = await load_data()
        user_id = interaction.user.id

        if user_id not in data["active_testers"]:
            data["active_testers"].append(user_id)

            if user_id in data["paused_testers"]:
                data["paused_testers"].remove(user_id)

            active_ready = [t for t in data["active_testers"] if t not in data["paused_testers"]]

            if len(active_ready) == 1 and not data["is_open"]:
                data["is_open"] = True

                wl_channel = interaction.guild.get_channel(WAITLIST_CHANNEL_ID)
                if wl_channel:
                    role = interaction.guild.get_role(WAITLIST_ROLE_ID)
                    ping_mention = role.mention if role else "@waitlist"
                    ping_msg = await wl_channel.send(content=f"{ping_mention} Очередь открыта!")
                    await ping_msg.delete()

            await save_data(data)
            await update_public_waitlist_message(interaction.guild)
            await update_tester_panel_message(interaction.guild)
            await interaction.response.send_message("✅ Вы встали на тестировку!", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ Вы уже на смене.", ephemeral=True)

    @discord.ui.button(label="⏸ Пауза", style=discord.ButtonStyle.secondary, custom_id="tp_pause")
    async def pause_shift(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = await load_data()
        user_id = interaction.user.id

        if user_id not in data["active_testers"]:
            return await interaction.response.send_message("⚠️ Сначала встаньте на тестировку!", ephemeral=True)

        if user_id in data["paused_testers"]:
            data["paused_testers"].remove(user_id)
            msg_text = "▶️ Вы снялись с паузы!"

            active_ready = [t for t in data["active_testers"] if t not in data["paused_testers"]]
            if len(active_ready) == 1 and not data["is_open"]:
                data["is_open"] = True
                wl_channel = interaction.guild.get_channel(WAITLIST_CHANNEL_ID)
                if wl_channel:
                    role = interaction.guild.get_role(WAITLIST_ROLE_ID)
                    ping_mention = role.mention if role else "@waitlist"
                    ping_msg = await wl_channel.send(content=f"{ping_mention} Очередь открыта!")
                    await ping_msg.delete()
        else:
            data["paused_testers"].append(user_id)
            msg_text = "⏸ Вы ушли на паузу!"

            active_ready = [t for t in data["active_testers"] if t not in data["paused_testers"]]
            if len(active_ready) == 0:
                data["is_open"] = False
                data["queue"] = []

        await save_data(data)
        await update_public_waitlist_message(interaction.guild)
        await update_tester_panel_message(interaction.guild)
        await interaction.response.send_message(msg_text, ephemeral=True)

    @discord.ui.button(label="Выйти с тестировки", style=discord.ButtonStyle.danger, custom_id="tp_shift_off")
    async def shift_off(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = await load_data()
        user_id = interaction.user.id

        if user_id in data["active_testers"]:
            data["active_testers"].remove(user_id)
            if user_id in data["paused_testers"]:
                data["paused_testers"].remove(user_id)

            active_ready = [t for t in data["active_testers"] if t not in data["paused_testers"]]
            if len(active_ready) == 0:
                data["is_open"] = False
                data["queue"] = []

            await save_data(data)
            await update_public_waitlist_message(interaction.guild)
            await update_tester_panel_message(interaction.guild)
            await interaction.response.send_message("🚪 Вы вышли с тестировки.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ Вы не были на смене.", ephemeral=True)


# ---------------------------------------------------------------------------
# КОНТРОЛЛЕР HIGH TIER ТИКЕТА (БЕЗ ПУБЛИКАЦИИ И БЕЗ КУЛДАУНА)
# ---------------------------------------------------------------------------
class HighTierTicketControlView(discord.ui.View):
    def __init__(self, player_id: int):
        super().__init__(timeout=None)
        self.player_id = player_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        tester_role = interaction.guild.get_role(TESTER_ROLE_ID)
        if tester_role not in interaction.user.roles:
            await interaction.response.send_message(
                "⛔ Только тестеры могут использовать эти кнопки!",
                ephemeral=True
            )
            return False
        return True

    async def apply_ht_change(self, interaction: discord.Interaction, direction: int, action_name: str):
        data = await load_data()
        player = interaction.guild.get_member(self.player_id)

        if not player:
            return await interaction.response.send_message("❌ Игрок не найден на сервере.", ephemeral=True)

        user_id_str = str(self.player_id)
        old_tier = data["user_tiers"].get(user_id_str, "Low Tier 3")

        if direction == 0:
            new_tier = old_tier
        else:
            new_tier = get_adjacent_tier(old_tier, direction)

        now_str = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")

        # Обновление данных
        data["user_tiers"][user_id_str] = new_tier
        data["last_test_time"] = now_str

        # Поиск ключа тира по имени для выдачи роли
        new_tier_key = next((k for k, v in TIER_NAMES.items() if v == new_tier), None)

        if new_tier_key and new_tier_key in TIER_ROLES:
            for t_key, r_id in TIER_ROLES.items():
                if r_id:
                    r = interaction.guild.get_role(r_id)
                    if r and r in player.roles:
                        await player.remove_roles(r)

            target_role_id = TIER_ROLES[new_tier_key]
            if target_role_id:
                new_role = interaction.guild.get_role(target_role_id)
                if new_role:
                    await player.add_roles(new_role)

        # Сохранение истории
        if user_id_str not in data["user_history"]:
            data["user_history"][user_id_str] = []

        data["user_history"][user_id_str].append({
            "from": old_tier,
            "to": new_tier,
            "date": now_str,
        })

        # Освобождение от списка активных High Tier тикетов
        if self.player_id in data.get("active_ht_tickets", []):
            data["active_ht_tickets"].remove(self.player_id)

        tester_str_id = str(interaction.user.id)
        data["tester_stats"][tester_str_id] = data["tester_stats"].get(tester_str_id, 0) + 1

        await save_data(data)

        await interaction.response.send_message(
            f"✅ Решение применимо: **{action_name}** (`{old_tier}` ➔ `{new_tier}`).\nТикет удалится через 5 секунд."
        )
        await discord.utils.sleep_until(datetime.datetime.now() + datetime.timedelta(seconds=5))
        await interaction.channel.delete()

    @discord.ui.button(label="🔻 Демоут", style=discord.ButtonStyle.danger)
    async def demote(self, interaction: discord.Interaction, b: discord.ui.Button):
        await self.apply_ht_change(interaction, direction=-1, action_name="Демоут")

    @discord.ui.button(label="⏸ Холд", style=discord.ButtonStyle.secondary)
    async def hold(self, interaction: discord.Interaction, b: discord.ui.Button):
        await self.apply_ht_change(interaction, direction=0, action_name="Холд (Удержание)")

    @discord.ui.button(label="🔺 Повышение", style=discord.ButtonStyle.success)
    async def promote(self, interaction: discord.Interaction, b: discord.ui.Button):
        await self.apply_ht_change(interaction, direction=1, action_name="Повышение")


# ---------------------------------------------------------------------------
# КОНТРОЛЛЕР ОБЫЧНОГО КВАЛИФИКАЦИОННОГО ТИКЕТА
# ---------------------------------------------------------------------------
class TicketControlView(discord.ui.View):
    def __init__(self, player_id: int, tester_id: int):
        super().__init__(timeout=None)
        self.player_id = player_id
        self.tester_id = tester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        tester_role = interaction.guild.get_role(TESTER_ROLE_ID)
        if tester_role not in interaction.user.roles:
            await interaction.response.send_message(
                "⛔ Только тестеры могут использовать эти кнопки!",
                ephemeral=True
            )
            return False
        return True

    async def process_tier(self, interaction: discord.Interaction, tier_key: str):
        data = await load_data()
        player = interaction.guild.get_member(self.player_id)
        tester = interaction.guild.get_member(self.tester_id)

        if not player:
            return await interaction.response.send_message("❌ Игрок не найден на сервере.", ephemeral=True)

        user_id_str = str(self.player_id)
        old_tier = data["user_tiers"].get(user_id_str, "Не установлен")
        new_tier_name = TIER_NAMES[tier_key]

        # Выдача / снятие ролей
        for t_key, r_id in TIER_ROLES.items():
            if r_id:
                r = interaction.guild.get_role(r_id)
                if r and r in player.roles:
                    await player.remove_roles(r)

        target_role_id = TIER_ROLES.get(tier_key)
        if target_role_id:
            new_role = interaction.guild.get_role(target_role_id)
            if new_role:
                await player.add_roles(new_role)

        now_dt = datetime.datetime.now()
        now_str = now_dt.strftime("%d.%m.%Y %H:%M")

        data["user_tiers"][user_id_str] = new_tier_name
        data["cooldowns"][user_id_str] = now_dt.timestamp()
        data["last_test_time"] = now_str

        if user_id_str not in data["user_history"]:
            data["user_history"][user_id_str] = []

        data["user_history"][user_id_str].append({
            "from": old_tier,
            "to": new_tier_name,
            "date": now_str,
        })

        tester_str_id = str(self.tester_id)
        data["tester_stats"][tester_str_id] = data["tester_stats"].get(tester_str_id, 0) + 1

        await save_data(data)

        # ОПРЕДЕЛЕНИЕ СТАТУСА ТЕСТА И КРАСИВЫЙ ЭМБЕД В #RESULTS
        results_channel = interaction.guild.get_channel(RESULTS_CHANNEL_ID)
        if results_channel:
            old_weight = TIER_WEIGHTS.get(old_tier, 0)
            new_weight = TIER_WEIGHTS.get(new_tier_name, 0)

            if old_tier == "Не установлен":
                status_title = "🗡️ Первый тир получен"
                embed_color = discord.Color.gold()
            elif new_weight > old_weight:
                status_title = "🔺 Повышение"
                embed_color = discord.Color.green()
            elif new_weight < old_weight:
                status_title = "🔻 Понижение"
                embed_color = discord.Color.red()
            else:
                status_title = "⏸ Тир не изменён"
                embed_color = discord.Color.blue()
                badge_text = ""

            res_embed = discord.Embed(
                title=f"⚔️ Результат тестирования Fast PVP",
                description=f"**{status_title}**\n{badge_text}\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯",
                color=embed_color,
            )
            res_embed.add_field(name="👤 Игрок:", value=player.mention, inline=True)
            res_embed.add_field(name="🛡 Тестер:", value=tester.mention if tester else f"<@{self.tester_id}>",
                                inline=True)
            res_embed.add_field(name=" \u200b", value=" \u200b", inline=True)  # Разделитель

            res_embed.add_field(name="📊 Предыдущий тир:", value=f"`{old_tier}`", inline=True)
            res_embed.add_field(name="🏆 Итоговый тир:", value=f"**[{new_tier_name}]**", inline=True)
            res_embed.add_field(name=" \u200b", value=" \u200b", inline=True)

            res_embed.set_thumbnail(url=player.display_avatar.url)
            res_embed.set_footer(text=f"HKTiers • {now_str}")

            await results_channel.send(content=player.mention, embed=res_embed)

        await update_public_waitlist_message(interaction.guild)
        await update_tester_panel_message(interaction.guild)

        await interaction.response.send_message("✅ Результат сохранен! Тикет удалится через 5 секунд.")
        await discord.utils.sleep_until(datetime.datetime.now() + datetime.timedelta(seconds=5))
        await interaction.channel.delete()

    @discord.ui.button(label="LT5", style=discord.ButtonStyle.secondary)
    async def lt5(self, interaction: discord.Interaction, b: discord.ui.Button):
        await self.process_tier(interaction, "LT5")

    @discord.ui.button(label="HT5", style=discord.ButtonStyle.secondary)
    async def ht5(self, interaction: discord.Interaction, b: discord.ui.Button):
        await self.process_tier(interaction, "HT5")

    @discord.ui.button(label="LT4", style=discord.ButtonStyle.secondary)
    async def lt4(self, interaction: discord.Interaction, b: discord.ui.Button):
        await self.process_tier(interaction, "LT4")

    @discord.ui.button(label="HT4", style=discord.ButtonStyle.secondary)
    async def ht4(self, interaction: discord.Interaction, b: discord.ui.Button):
        await self.process_tier(interaction, "HT4")

    @discord.ui.button(label="LT3", style=discord.ButtonStyle.secondary)
    async def lt3(self, interaction: discord.Interaction, b: discord.ui.Button):
        await self.process_tier(interaction, "LT3")

    @discord.ui.button(label="Закрыть (Кулдаун 14 дней)", style=discord.ButtonStyle.danger)
    async def close_cd(self, interaction: discord.Interaction, b: discord.ui.Button):
        data = await load_data()
        data["cooldowns"][str(self.player_id)] = datetime.datetime.now().timestamp()
        await save_data(data)

        await interaction.response.send_message("🔒 Тикет закрыт без результата. Назначен кулдаун 14 дней.")
        await discord.utils.sleep_until(datetime.datetime.now() + datetime.timedelta(seconds=3))
        await interaction.channel.delete()

    @discord.ui.button(label="Закрыть без кулдауна", style=discord.ButtonStyle.gray)
    async def close_no_cd(self, interaction: discord.Interaction, b: discord.ui.Button):
        await interaction.response.send_message("🔒 Тикет закрыт без результата и без кулдауна.")
        await discord.utils.sleep_until(datetime.datetime.now() + datetime.timedelta(seconds=3))
        await interaction.channel.delete()


# ---------------------------------------------------------------------------
# ИНИЦИАЛИЗАЦИЯ И СЛЭШ-КОМАНДЫ
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@tasks.loop(seconds=5)
async def auto_refresh_panels():
    guild = bot.get_guild(GUILD_ID)
    if guild:
        await update_tester_panel_message(guild)
        await update_public_waitlist_message(guild)

# --- РОТАЦИЯ СТАТУСОВ (КАЖДЫЕ 15 СЕКУНД) ---
status_cycle = cycle([1, 2, 3, 4, 5])

@tasks.loop(seconds=15)
async def change_status():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return

    data = await load_data()
    step = next(status_cycle)

    if step == 1:
        # 1. Если тестеры в сети — "Жду вас в очереди!", иначе — "Сплю"
        active_testers = data.get("active_testers", [])
        paused_testers = data.get("paused_testers", [])
        ready_testers = [t for t in active_testers if t not in paused_testers]

        if ready_testers and data.get("is_open", False):
            status_text = "Жду вас в очереди!"
        else:
            status_text = "Сплю"

    elif step == 2:

        status_text = "powered by Алиса ai"

    elif step == 3:

        status_text = "Catweed39 my beloved"

    elif step == 4:

        total_tests = sum(data.get("tester_stats", {}).values())
        status_text = f"Протестил вас уже {total_tests} раз!"

    elif step == 5:

        status_text = "Мяу"

    await bot.change_presence(activity=discord.CustomActivity(name=status_text))

@bot.event
async def on_ready():
    bot.add_view(PublicWaitlistView())
    bot.add_view(TesterPanelView())
    bot.add_view(WaitlistPingView())

    guild = discord.Object(id=GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)

    if not change_status.is_running():
        change_status.start()

    if not auto_refresh_panels.is_running():
        auto_refresh_panels.start()

    print(f"✅ HKTiers бот успешно запущен под именем {bot.user}")


# --- СЛЭШ-КОМАНДЫ ---

@bot.tree.command(name="profile", description="Просмотреть профиль игрока, тир и историю прогресса")
@app_commands.describe(member="Игрок, чей профиль вы хотите посмотреть (по умолчанию вы)")
async def cmd_profile(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    data = await load_data()

    user_id_str = str(target.id)
    current_tier = data.get("user_tiers", {}).get(user_id_str, "Не установлен")

    # Статус кулдауна
    cooldown_status = "🟢 Свободен (нет кулдауна)"
    if current_tier in HIGH_TIER_ELIGIBLE:
        cooldown_status = "🔥 High Tier этап (Кулдаун отсутствует)"
    elif user_id_str in data.get("cooldowns", {}):
        last_test_ts = data["cooldowns"][user_id_str]
        now_ts = datetime.datetime.now().timestamp()
        days_passed = (now_ts - last_test_ts) / 86400

        if days_passed < 14:
            end_date = datetime.datetime.fromtimestamp(last_test_ts) + datetime.timedelta(days=14)
            cooldown_status = f"⏳ Активен (до {end_date.strftime('%d.%m.%Y %H:%M')})"

    # Формирование истории прогресса
    user_history = data.get("user_history", {}).get(user_id_str, [])
    if user_history:
        history_lines = []
        for entry in user_history[-5:]:  # Показываем последние 5 записей
            from_tier = entry["from"]
            to_tier = entry["to"]
            date_str = entry["date"]
            if from_tier == "Не установлен":
                history_lines.append(f"• Получен **{to_tier}** `({date_str})`")
            else:
                history_lines.append(f"• **{from_tier}** ➔ **{to_tier}** `({date_str})`")
        history_str = "\n".join(history_lines)
    else:
        history_str = "*История пока пуста*"

    embed = discord.Embed(
        title=f"Профиль игрока: {target.display_name}",
        color=discord.Color.blue(),
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="Пользователь", value=target.mention, inline=False)
    embed.add_field(name="Текущий тир", value=f"**{current_tier}**", inline=False)
    embed.add_field(name="Статус кулдауна", value=cooldown_status, inline=False)
    embed.add_field(name="📜 История прогресса", value=history_str, inline=False)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="leaderboard", description="Единая таблица лидеров с пагинацией")
async def cmd_leaderboard(interaction: discord.Interaction):
    data = await load_data()
    user_tiers = data.get("user_tiers", {})

    sorted_players = []

    for uid_str, tier_name in user_tiers.items():
        member = interaction.guild.get_member(int(uid_str))
        if member:
            weight = TIER_WEIGHTS.get(tier_name, 0)
            sorted_players.append((member, tier_name, weight))

    sorted_players.sort(key=lambda x: (x[2], x[0].display_name.lower()), reverse=True)
    final_data = [(m, t) for m, t, w in sorted_players]

    view = LeaderboardPaginatorView(players_data=final_data, author_id=interaction.user.id)
    view.update_buttons()

    await interaction.response.send_message(embed=view.create_embed(), view=view)
    view.message = await interaction.original_response()


@bot.tree.command(name="tester_stats", description="[АДМИН] Просмотр статистики проверок тестеров")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_tester_stats(interaction: discord.Interaction):
    data = await load_data()
    stats = data.get("tester_stats", {})

    if not stats:
        return await interaction.response.send_message("📊 Статистика тестеров пока пуста.", ephemeral=True)

    sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)

    lines = []
    for idx, (tester_id_str, count) in enumerate(sorted_stats, 1):
        m = interaction.guild.get_member(int(tester_id_str))
        name = m.mention if m else f"ID: {tester_id_str}"
        lines.append(f"`{idx}.` {name} — **{count}** проведённых тестов")

    embed = discord.Embed(
        title="📊 Статистика работы Тестеров",
        description="\n".join(lines),
        color=discord.Color.purple(),
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="reset_cooldown", description="[АДМИН] Сбросить 14-дневный кулдаун игроку")
@app_commands.describe(member="Игрок, которому нужно сбросить кулдаун")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_reset_cooldown(interaction: discord.Interaction, member: discord.Member):
    data = await load_data()
    user_id_str = str(member.id)

    if user_id_str in data.get("cooldowns", {}):
        del data["cooldowns"][user_id_str]
        await save_data(data)
        await interaction.response.send_message(f"✅ Кулдаун для {member.mention} успешно сброшен!", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ У игрока {member.mention} нет активного кулдауна.", ephemeral=True)


@bot.tree.command(name="waitlist", description="[АДМИН] Отправить сообщение очереди HKTiers")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_waitlist(interaction: discord.Interaction):
    data = await load_data()
    embed = get_waitlist_embed(data, interaction.guild)
    msg = await interaction.channel.send(embed=embed, view=PublicWaitlistView())

    data["waitlist_msg_id"] = msg.id
    await save_data(data)

    await interaction.response.send_message("Сообщение HKTiers Waitlist отправлено!", ephemeral=True)


@bot.tree.command(name="testerpanel", description="[АДМИН] Отправить панель тестеров HKTiers")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_testerpanel(interaction: discord.Interaction):
    data = await load_data()
    embed = get_tester_panel_embed(data, interaction.guild)
    msg = await interaction.channel.send(embed=embed, view=TesterPanelView())

    data["tester_panel_msg_id"] = msg.id
    await save_data(data)

    await interaction.response.send_message("Панель тестеров отправлена!", ephemeral=True)


@bot.tree.command(name="waitlist_ping", description="[АДМИН] Сообщение для выдачи/снятия роли пинга")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_waitlist_ping(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🔔 HKTiers • Уведомления об открытии очереди",
        description="Хотите получать пинги, когда тестеры открывают очередь?\n\n"
                    "Нажмите **«Получать уведомления»**, чтобы подписаться, или **«Убрать роль»**, чтобы отписаться.",
        color=discord.Color.gold(),
    )
    await interaction.channel.send(embed=embed, view=WaitlistPingView())
    await interaction.response.send_message("Сообщение создано!", ephemeral=True)


bot.run(BOT_TOKEN)