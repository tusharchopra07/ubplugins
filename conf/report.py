import asyncio

from pyrogram import filters
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.errors import UserNotParticipant
from pyrogram.types import Chat, User
from ub_core.utils.helpers import get_name

from app import BOT, Config, CustomDB, extra_config, Message, bot

FED_DB = CustomDB("FED_LIST")

# Only allow commands from the bot owner
OWNER_FILTER = filters.user(Config.OWNER_ID)

# Regex Filters
FBAN_REGEX = filters.regex(
    r"(New FedBan|"
    r"starting a federation ban|"
    r"Starting a federation ban|"
    r"start a federation ban|"
    r"FedBan Reason update|"
    r"FedBan reason updated|"
    r"Would you like to update this reason)"
)

@bot.on_message(OWNER_FILTER & filters.command("report", prefixes="/"))
async def report_user(bot: BOT, message: Message):
    """
    Triggered on `/report`.
    Extracts user and reason, performs a federated ban across all federations silently.
    """
    extracted_info = await get_user_reason(message=message)

    if not extracted_info:
        return  # No valid user or reason found

    user_id, user_mention, reason = extracted_info

    # Prevent banning bot owner or privileged users
    if user_id in [Config.OWNER_ID, *Config.SUPERUSERS, *Config.SUDO_USERS]:
        return

    proof_str = ""
    if message.replied:
        try:
            proof = await message.replied.forward(extra_config.FBAN_LOG_CHANNEL)
            proof_str = f"\n { {proof.link} }"
        except Exception:
            pass

    reason = f"{reason}{proof_str}"

    # Prepare fban command
    fban_cmd = f"/fban <a href='tg://user?id={user_id}'>{user_id}</a> {reason}"

    await perform_fed_task(
        user_id=user_id,
        user_mention=user_mention,
        command=fban_cmd,
        task_filter=FBAN_REGEX,
        task_type="Fban",
        reason=reason,
        message=message,
    )


async def get_user_reason(message: Message) -> tuple[int, str, str] | None:
    """
    Extract user and reason from the message.
    """
    user, reason = await message.extract_user_n_reason()
    if isinstance(user, str):
        return
    if not isinstance(user, User):
        user_id = user
        user_mention = f"<a href='tg://user?id={user_id}'>{user_id}</a>"
    else:
        user_id = user.id
        user_mention = user.mention
    return user_id, user_mention, reason


async def perform_fed_task(
    user_id: int,
    user_mention: str,
    command: str,
    task_filter: filters.Filter,
    task_type: str,
    reason: str,
    message: Message,
):
    """
    Execute the federated task (e.g., fban) across all connected federations.
    Suppress task messages in the initiating chat.
    """
    total = 0
    failed = []

    async for fed in FED_DB.find():
        chat_id = int(fed["_id"])
        total += 1

        try:
            cmd = await bot.send_message(
                chat_id=chat_id, text=command, disable_web_page_preview=True
            )
            response = await cmd.get_response(filters=task_filter, timeout=8)
            if not response:
                failed.append(fed["name"])
            elif "Would you like to update this reason" in response.text:
                await response.click("Update reason")
        except Exception as e:
            await bot.log_text(
                text=f"Error banning in fed {fed['name']} [{chat_id}]\nError: {e}",
                type=task_type.upper(),
            )
            failed.append(fed["name"])
            continue

        await asyncio.sleep(1)

    if total == 0:
        return  # No federations connected

    # Prepare log for the FBAN log channel
    log_str = (
        f"❯❯❯ <b>{task_type}ned</b> {user_mention}"
        f"\n<b>ID</b>: {user_id}"
        f"\n<b>Reason</b>: {reason}"
        f"\n<b>Status</b>: {task_type}ned in <b>{total - len(failed)}</b> feds."
    )
    if failed:
        log_str += f"\n<b>Failed</b>: {len(failed)}/{total}\n• " + "\n• ".join(failed)
    if not message.is_from_owner:
        log_str += f"\n\n<b>By</b>: {get_name(message.from_user)}"

    await bot.send_message(
        chat_id=extra_config.FBAN_LOG_CHANNEL,
        text=log_str,
        disable_web_page_preview=True,
    )
    await handle_sudo_fban(command=command)


async def handle_sudo_fban(command: str):
    """
    Handles forwarding fban commands to a sudo federation if configured.
    """
    if not (extra_config.FBAN_SUDO_ID and extra_config.FBAN_SUDO_TRIGGER):
        return
    sudo_cmd = command.replace("/", extra_config.FBAN_SUDO_TRIGGER, 1)
    await bot.send_message(
        chat_id=extra_config.FBAN_SUDO_ID, text=sudo_cmd, disable_web_page_preview=True
    )
