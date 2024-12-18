import asyncio

from pyrogram import filters
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import Chat, User
from ub_core.utils.helpers import get_name

from app import BOT, Config, CustomDB, Message, bot, extra_config

FED_DB = CustomDB("FED_LIST")

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

UNFBAN_REGEX = BASIC_FILTER & filters.regex(r"(New un-FedBan|I'll give|Un-FedBan)")

# Specify the group ID where forwarded messages will be sent for automatic banning
FBAN_GROUP_ID = -1002299458034  # Replace with your actual group ID

@bot.on_message(filters.chat(FBAN_GROUP_ID) & filters.forwarded)
async def auto_fban(bot: BOT, message: Message):
    if message.forward_from:
        user_id = message.forward_from.id
        user_mention = message.forward_from.mention
        reason = f"Automated Fed-Ban Proof: /n"
        await perform_fban(bot, message, user_id, user_mention, reason)

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

    response = await confirmation.wait_for_response(filters=filters.regex(r"^[yn]$"), timeout=30)

    if not response or response.text.lower() == 'n':
        await progress.edit("FBan cancelled.")
        return

    await perform_fban(bot, message, user_id, user_mention, reason, progress)

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

@bot.add_cmd(cmd="addf")
async def add_fed(bot: BOT, message: Message):
    """
    CMD: ADDF
    INFO: Add a Fed Chat to DB.
    USAGE:
        .addf | .addf NAME
    """
    data = dict(name=message.input or message.chat.title, type=str(message.chat.type))
    await FED_DB.add_data({"_id": message.chat.id, **data})
    text = f"#FBANS\n<b>{data['name']}</b>: <code>{message.chat.id}</code> added to FED LIST."
    await message.reply(text=text, del_in=5, block=True)
    await bot.log_text(text=text, type="info")

@bot.add_cmd(cmd="delf")
async def remove_fed(bot: BOT, message: Message):
    """
    CMD: DELF
    INFO: Delete a Fed from DB.
    FLAGS: -all to delete all feds.
    USAGE:
        .delf | .delf id | .delf -all
    """
    if "-all" in message.flags:
        await FED_DB.drop()
        await message.reply("FED LIST cleared.")
        return
    chat: int | str | Chat = message.input or message.chat
    name = ""
    if isinstance(chat, Chat):
        name = f"Chat: {chat.title}\n"
        chat = chat.id
    elif chat.lstrip("-").isdigit():
        chat = int(chat)
    deleted: int = await FED_DB.delete_data(id=chat)
    if deleted:
        text = f"#FBANS\n<b>{name}</b><code>{chat}</code> removed from FED LIST."
        await message.reply(text=text, del_in=8)
        await bot.log_text(text=text, type="info")
    else:
        await message.reply(text=f"<b>{name or chat}</b> not in FED LIST.", del_in=8)

@bot.add_cmd(cmd="listf")
async def fed_list(bot: BOT, message: Message):
    """
    CMD: LISTF
    INFO: View Connected Feds.
    FLAGS: -id to list Fed Chat IDs.
    USAGE: .listf | .listf -id
    """
    output: str = ""
    total = 0
    async for fed in FED_DB.find():
        output += f'<b>• {fed["name"]}</b>\n'
        if "-id" in message.flags:
            output += f'  <code>{fed["_id"]}</code>\n'
        total += 1
    if not total:
        await message.reply("You don't have any Feds Connected.")
        return
    output: str = f"List of <b>{total}</b> Connected Feds:\n\n{output}"
    await message.reply(output, del_in=30, block=True)

@bot.add_cmd(cmd="unfban")
async def un_fban(bot: BOT, message: Message):
    progress: Message = await message.reply("❯")
    extracted_info = await get_user_reason(message=message, progress=progress)

    if not extracted_info:
        return

    user_id, user_mention, reason = extracted_info
    unfban_cmd: str = f"/unfban <a href='tg://user?id={user_id}'>{user_id}</a> {reason}"

    await perform_fed_task(
        user_id=user_id,
        user_mention=user_mention,
        command=unfban_cmd,
        task_filter=UNFBAN_REGEX,
        task_type="Un-FBan",
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
        cmd: Message = await bot.send_message(
            chat_id=chat_id, text=command, disable_web_page_preview=True
        )
        response: Message | None = await cmd.get_response(
            filters=task_filter, timeout=8
        )
        if not response:
            failed.append(fed["name"])
        elif "Would you like to update this reason" in response.text:
            await response.click("Update reason")
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
        disable_web_page_preview=True,
    )
    await progress.edit(
        text=resp_str, del_in=5, block=True, disable_web_page_preview=True
    )
    await handle_sudo_fban(command=command)

async def handle_sudo_fban(command: str):
    if not (extra_config.FBAN_SUDO_ID and extra_config.FBAN_SUDO_TRIGGER):
        return
    sudo_cmd = command.replace("/", extra_config.FBAN_SUDO_TRIGGER, 1)
    await bot.send_message(
        chat_id=extra_config.FBAN_SUDO_ID, text=sudo_cmd, disable_web_page_preview=True
    )

