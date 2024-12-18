import asyncio
from typing import Optional, Set

from pyrogram import filters
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import Chat, User, Message as PyroMessage, MessageOriginUser, MessageOriginChannel
from ub_core.utils.helpers import get_name

from app import BOT, Config, CustomDB, Message, bot, extra_config

FED_DB = CustomDB("FED_LIST")
FBAN_APPROVERS = CustomDB("FBAN_APPROVERS")

BASIC_FILTER = filters.user([609517172, 2059887769]) & ~filters.service

FBAN_REGEX = BASIC_FILTER & filters.regex(
    r"(New FedBan|"
    r"starting a federation ban|"
    r"Starting a federation ban|"
    r"start a federation ban|"
    r"FedBan Reason update|"
    r"FedBan reason updated|"
    r"Would you like to update this reason)"
)

# Specify the group ID where forwarded messages will be sent for automatic banning
FBAN_GROUP_ID = -1002299458034  # Replace with your actual group ID

async def wait_for_response(bot: BOT, chat_id: int, user_id: int, timeout: int = 30) -> Optional[str]:
    start_time = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start_time < timeout:
        try:
            async for message in bot.get_chat_history(chat_id, limit=1):
                if message.from_user and message.from_user.id == user_id and message.text and message.text.lower() in ['y', 'n']:
                    return message.text.lower()
        except Exception as e:
            print(f"Error in wait_for_response: {e}")
        await asyncio.sleep(1)
    return None

async def is_fban_approver(user_id: int) -> bool:
    return await FBAN_APPROVERS.find_one({"_id": user_id}) is not None

@bot.on_message(filters.chat(FBAN_GROUP_ID) & filters.forwarded)
async def auto_fban(bot: BOT, message: Message):
    if not message.from_user:
        return

    if isinstance(message.forward_origin, MessageOriginChannel):
        return  # Ignore messages forwarded from channels

    if isinstance(message.forward_origin, MessageOriginUser):
        user_id = message.forward_origin.sender_user.id
        user_mention = message.forward_origin.sender_user.mention
    else:
        await message.reply("Unable to determine the user to ban.")
        return

    reason = f"Auto-FBan: Forwarded message in {message.chat.title}"
    
    # Ask for confirmation
    confirmation = await message.reply(
        f"Are you sure you want to FBan {user_mention}?\n"
        f"Reason: {reason}\n\n"
        f"Reply with 'y' to confirm or 'n' to cancel."
    )

    response = await wait_for_response(bot, message.chat.id, message.from_user.id)

    if response == 'y':
        await perform_fban(bot, message, user_id, user_mention, reason)
    else:
        await message.reply("FBan cancelled.")

@bot.add_cmd(cmd="ffbanp")
async def manual_fban(bot: BOT, message: Message):
    progress: Message = await message.reply("Processing...")
    extracted_info = await get_user_reason(message=message, progress=progress)
    if not extracted_info:
        return

    user_id, user_mention, reason = extracted_info

    if user_id in [Config.OWNER_ID, *Config.SUPERUSERS, *Config.SUDO_USERS]:
        await progress.edit("Cannot FBan Owner/Sudo users.")
        return

    confirmation = await message.reply(
        f"Are you sure you want to FBan {user_mention}?\n"
        f"Reason: {reason}\n\n"
        f"Reply with 'y' to confirm or 'n' to cancel."
    )

    response = await wait_for_response(bot, message.chat.id, message.from_user.id)

    if response == 'y':
        await perform_fban(bot, message, user_id, user_mention, reason, progress)
    else:
        await progress.edit("FBan cancelled.")

@bot.add_cmd(cmd="fapprove")
async def add_fban_approver(bot: BOT, message: Message):
    if not message.from_user or message.from_user.id != Config.OWNER_ID:
        return

    user, _ = await message.extract_user_n_reason()
    if not user:
        await message.reply("Please specify a user to add as an FBan approver.")
        return

    await FBAN_APPROVERS.add_data({"_id": user.id, "name": user.first_name})
    await message.reply(f"{user.mention} has been added as an FBan approver.")

@bot.add_cmd(cmd="fremove")
async def remove_fban_approver(bot: BOT, message: Message):
    if not message.from_user or message.from_user.id != Config.OWNER_ID:
        return

    user, _ = await message.extract_user_n_reason()
    if not user:
        await message.reply("Please specify a user to remove from FBan approvers.")
        return

    result = await FBAN_APPROVERS.delete_data(id=user.id)
    if result:
        await message.reply(f"{user.mention} has been removed from FBan approvers.")
    else:
        await message.reply(f"{user.mention} is not an FBan approver.")

async def perform_fban(bot: BOT, message: Message, user_id: int, user_mention: str, reason: str, progress: Message = None):
    if progress:
        await progress.edit("Processing FBan...")
    else:
        progress = await message.reply("Processing FBan...")

    proof = await message.forward(extra_config.FBAN_LOG_CHANNEL)
    proof_str = f"\n{proof.link}"
    reason = f"{reason}{proof_str}"

    fban_cmd: str = f"/fban <a href='tg://user?id={user_id}'>{user_id}</a> {reason}"

    await perform_fed_task(
        user_id=user_id,
        user_mention=user_mention,
        command=fban_cmd,
        task_filter=FBAN_REGEX,
        task_type="FBan",
        reason=reason,
        progress=progress,
        message=message,
    )

async def get_user_reason(
    message: Message, progress: Message
) -> tuple[int, str, str] | None:
    user, reason = await message.extract_user_n_reason()
    if isinstance(user, str):
        await progress.edit(user)
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
    progress: Message,
    message: Message,
):
    await progress.edit("❯❯")
    total: int = 0
    failed: list[str] = []
    async for fed in FED_DB.find():
        chat_id = int(fed["_id"])
        total += 1
        try:
            cmd: Message = await bot.send_message(
                chat_id=chat_id, text=command, link_preview_options={"is_disabled": True}
            )
            response: Message | None = await cmd.get_response(
                filters=task_filter, timeout=8
            )
            if not response:
                failed.append(fed["name"])
            elif "Would you like to update this reason" in response.text:
                await response.click("Update reason")
        except asyncio.TimeoutError:
            failed.append(fed["name"])
        except Exception as e:
            failed.append(f"{fed['name']} ({str(e)})")
        await asyncio.sleep(1)
    if not total:
        await progress.edit("You Don't have any feds connected!")
        return
    resp_str = (
        f"❯❯❯ <b>{task_type}ned</b> {user_mention}"
        f"\n<b>ID</b>: {user_id}"
        f"\n<b>Reason</b>: {reason}"
        f"\n<b>Initiated in</b>: {message.chat.title or 'PM'}"
    )
    if failed:
        resp_str += f"\n<b>Failed</b> in: {len(failed)}/{total}\n• " + "\n• ".join(
            failed
        )
    else:
        resp_str += f"\n<b>Status</b>: {task_type}ned in <b>{total}</b> feds."
    if not message.is_from_owner:
        resp_str += f"\n\n<b>By</b>: {get_name(message.from_user)}"
    await bot.send_message(
        chat_id=extra_config.FBAN_LOG_CHANNEL,
        text=resp_str,
        link_preview_options={"is_disabled": True},
    )
    await progress.edit(
        text=resp_str, del_in=5, block=True, link_preview_options={"is_disabled": True}
    )
    await handle_sudo_fban(command=command)

async def handle_sudo_fban(command: str):
    if not (extra_config.FBAN_SUDO_ID and extra_config.FBAN_SUDO_TRIGGER):
        return
    sudo_cmd = command.replace("/", extra_config.FBAN_SUDO_TRIGGER, 1)
    await bot.send_message(
        chat_id=extra_config.FBAN_SUDO_ID, text=sudo_cmd, link_preview_options={"is_disabled": True}
    )

