from __future__ import annotations

import asyncio
import time
from pathlib import Path

import discord

from common import (
    active_status_message,
    allow_key,
    create_redis,
    expired_status_message,
    grant_key,
    grant_set_key,
    load_settings,
    normalize_ip,
)


settings = load_settings()


class IPGrantBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        intents.members = True
        super().__init__(intents=intents)
        self.redis = create_redis(settings)
        self._expiry_task: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        self._expiry_task = asyncio.create_task(self.expiry_worker())

    async def close(self) -> None:
        if self._expiry_task is not None:
            self._expiry_task.cancel()
            try:
                await self._expiry_task
            except asyncio.CancelledError:
                pass
        await self.redis.aclose()
        await super().close()

    async def on_ready(self) -> None:
        print(f"discord login ok: {self.user}", flush=True)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.guild is None or message.guild.id != settings.discord_guild_id:
            return
        if message.channel.id != settings.discord_channel_id:
            return

        member = message.author if isinstance(message.author, discord.Member) else None
        if member is None or not any(role.id == settings.discord_role_id for role in member.roles):
            return

        ip_text = normalize_ip(message.content.strip())
        if not ip_text:
            return

        try:
            await message.delete()
        except discord.HTTPException:
            pass

        await self.grant_ip(ip_text, member, message.channel)

    async def grant_ip(
        self,
        ip_text: str,
        member: discord.Member,
        channel: discord.abc.MessageableChannel,
    ) -> None:
        expires_at = int(time.time()) + settings.grant_ttl_seconds
        existing = await self.redis.hgetall(grant_key(ip_text))

        await self.redis.set(allow_key(ip_text), "1", ex=settings.grant_ttl_seconds)

        status_message = None
        if existing.get("status_message_id"):
            status_message = await self.fetch_status_message(
                int(existing.get("status_channel_id", settings.discord_channel_id)),
                int(existing["status_message_id"]),
            )

        content = active_status_message(ip_text, member.mention, str(member), expires_at)
        if status_message is None:
            status_message = await channel.send(content)
        else:
            await status_message.edit(content=content)

        await self.redis.hset(
            grant_key(ip_text),
            mapping={
                "ip": ip_text,
                "requester_id": str(member.id),
                "requester_mention": member.mention,
                "requester_name": str(member),
                "status_channel_id": str(status_message.channel.id),
                "status_message_id": str(status_message.id),
                "expires_at": str(expires_at),
            },
        )
        await self.redis.expire(grant_key(ip_text), settings.grant_record_ttl_seconds)
        await self.redis.sadd(grant_set_key(), ip_text)

    async def fetch_status_message(
        self,
        channel_id: int,
        message_id: int,
    ) -> discord.Message | None:
        channel = self.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(channel_id)
            except discord.HTTPException:
                return None
        if not isinstance(channel, discord.TextChannel):
            return None
        try:
            return await channel.fetch_message(message_id)
        except discord.HTTPException:
            return None

    async def expire_due_grants(self) -> None:
        now = int(time.time())
        for ip_text in await self.redis.smembers(grant_set_key()):
            metadata = await self.redis.hgetall(grant_key(ip_text))
            if not metadata:
                await self.redis.srem(grant_set_key(), ip_text)
                continue

            try:
                expires_at = int(metadata.get("expires_at", "0"))
            except ValueError:
                expires_at = 0

            if now < expires_at:
                continue

            await self.redis.delete(allow_key(ip_text))

            requester_mention = metadata.get("requester_mention", "unknown")
            requester_name = metadata.get("requester_name", "unknown")
            status_message = None
            if metadata.get("status_message_id") and metadata.get("status_channel_id"):
                try:
                    status_message = await self.fetch_status_message(
                        int(metadata["status_channel_id"]),
                        int(metadata["status_message_id"]),
                    )
                except ValueError:
                    status_message = None

            if status_message is not None:
                try:
                    await status_message.edit(
                        content=expired_status_message(
                            ip_text,
                            requester_mention,
                            requester_name,
                            expires_at,
                        )
                    )
                except discord.HTTPException:
                    pass

            await self.redis.srem(grant_set_key(), ip_text)
            await self.redis.delete(grant_key(ip_text))

    async def expiry_worker(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self.expire_due_grants()
            except Exception as exc:
                print(f"expiry worker error: {exc}", flush=True)
            await asyncio.sleep(5)


def read_token() -> str:
    return Path(settings.discord_token_file).read_text(encoding="utf-8").strip()


def main() -> None:
    bot = IPGrantBot()
    bot.run(read_token(), log_handler=None)


if __name__ == "__main__":
    main()
