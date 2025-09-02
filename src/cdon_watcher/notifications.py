"""Notification services for CDON Watcher."""

import aiohttp

from .config import CONFIG


class NotificationService:
    """Handles Discord notifications and console output."""

    async def send_notifications(self, alerts: list[dict]) -> None:
        """Send Discord notifications for price alerts."""
        if not alerts:
            return

        # Console output (always enabled)
        self._print_console_alerts(alerts)

        # Discord webhook
        if CONFIG["discord_webhook"]:
            await self.send_discord_notification(alerts)

    def _print_console_alerts(self, alerts: list[dict]) -> None:
        """Print alerts to console."""
        print("\n" + "=" * 50)
        print("🎉 PRICE ALERTS!")
        print("=" * 50)
        for alert in alerts:
            if alert["alert_type"] == "price_drop":
                print(f"📉 {alert['title']}")
                print(f"   Price dropped: €{alert['old_price']} → €{alert['new_price']}")
            elif alert["alert_type"] == "target_reached":
                print(f"🎯 {alert['title']}")
                print(f"   Target price reached: €{alert['new_price']}")
            print(f"   View: {alert['url']}\n")

    async def send_discord_notification(self, alerts: list[dict]) -> None:
        """Send Discord webhook notification."""
        try:
            for alert in alerts:
                embed = {
                    "title": alert["title"],
                    "description": f"Price: €{alert['old_price']} → €{alert['new_price']}",
                    "url": alert["url"],
                    "color": 0x00FF00 if alert["alert_type"] == "price_drop" else 0x0099FF,
                }

                async with aiohttp.ClientSession() as session:
                    await session.post(CONFIG["discord_webhook"], json={"embeds": [embed]})

            print("✅ Discord notifications sent")
        except Exception as e:
            print(f"❌ Failed to send Discord notification: {e}")
