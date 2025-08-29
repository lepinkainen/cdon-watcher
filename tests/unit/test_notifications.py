"""Unit tests for notification services."""

from io import StringIO
from unittest.mock import patch

import pytest

from src.cdon_watcher.notifications import NotificationService


class TestNotificationFormatting:
    """Test notification formatting functions that don't require external services."""

    @pytest.fixture
    def notification_service(self) -> NotificationService:
        """Create NotificationService instance for testing."""
        return NotificationService()

    def test_print_console_alerts_empty_list(
        self, notification_service: NotificationService
    ) -> None:
        """Test console alert printing with empty alert list."""
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            notification_service._print_console_alerts([])
            output = mock_stdout.getvalue()
            # Function always prints header, even for empty list
            assert "PRICE ALERTS!" in output, "Should print header even for empty list"
            # But should not print any specific alert content
            assert "📉" not in output, "Should not print price drop emoji"
            assert "🎯" not in output, "Should not print target reached emoji"

    def test_print_console_alerts_price_drop(
        self, notification_service: NotificationService
    ) -> None:
        """Test console alert printing for price drop alerts."""
        alerts = [
            {
                "alert_type": "price_drop",
                "title": "The Matrix Blu-ray",
                "old_price": 29.99,
                "new_price": 19.99,
                "url": "https://cdon.fi/tuote/matrix-abc123/",
            }
        ]

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            notification_service._print_console_alerts(alerts)
            output = mock_stdout.getvalue()

            # Check that output contains expected elements
            assert "PRICE ALERTS!" in output
            assert "📉 The Matrix Blu-ray" in output
            assert "Price dropped: €29.99 → €19.99" in output
            assert "https://cdon.fi/tuote/matrix-abc123/" in output

    def test_print_console_alerts_target_reached(
        self, notification_service: NotificationService
    ) -> None:
        """Test console alert printing for target price reached alerts."""
        alerts = [
            {
                "alert_type": "target_reached",
                "title": "Blade Runner 2049 4K",
                "old_price": 35.00,
                "new_price": 25.00,
                "url": "https://cdon.fi/tuote/blade-runner-def456/",
            }
        ]

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            notification_service._print_console_alerts(alerts)
            output = mock_stdout.getvalue()

            # Check that output contains expected elements
            assert "🎯 Blade Runner 2049 4K" in output
            assert "Target price reached: €25.0" in output
            assert "https://cdon.fi/tuote/blade-runner-def456/" in output

    def test_print_console_alerts_multiple_alerts(
        self, notification_service: NotificationService
    ) -> None:
        """Test console alert printing with multiple alerts."""
        alerts = [
            {
                "alert_type": "price_drop",
                "title": "Movie A",
                "old_price": 20.00,
                "new_price": 15.00,
                "url": "https://cdon.fi/tuote/movie-a/",
            },
            {
                "alert_type": "target_reached",
                "title": "Movie B",
                "old_price": 30.00,
                "new_price": 25.00,
                "url": "https://cdon.fi/tuote/movie-b/",
            },
        ]

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            notification_service._print_console_alerts(alerts)
            output = mock_stdout.getvalue()

            # Check that both alerts are present
            assert "📉 Movie A" in output
            assert "🎯 Movie B" in output
            assert "€20.0 → €15.0" in output
            assert "€25.0" in output
            assert output.count("View:") == 2, "Should have two 'View:' entries"

    def test_print_console_alerts_unknown_alert_type(
        self, notification_service: NotificationService
    ) -> None:
        """Test console alert printing with unknown alert type."""
        alerts = [
            {
                "alert_type": "unknown_type",
                "title": "Test Movie",
                "old_price": 20.00,
                "new_price": 15.00,
                "url": "https://cdon.fi/tuote/test/",
            }
        ]

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            notification_service._print_console_alerts(alerts)
            output = mock_stdout.getvalue()

            # Should still print basic info but without specific emoji/message
            assert "PRICE ALERTS!" in output
            assert "https://cdon.fi/tuote/test/" in output  # URL always printed
            # Should not contain price drop or target reached messages
            assert "Price dropped:" not in output
            assert "Target price reached:" not in output
            # For unknown alert types, title is not printed with emoji prefix
            assert "📉" not in output
            assert "🎯" not in output

    def test_print_console_alerts_formatting(
        self, notification_service: NotificationService
    ) -> None:
        """Test console alert formatting details."""
        alerts = [
            {
                "alert_type": "price_drop",
                "title": "Test Movie",
                "old_price": 29.99,
                "new_price": 19.99,
                "url": "https://cdon.fi/tuote/test/",
            }
        ]

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            notification_service._print_console_alerts(alerts)
            output = mock_stdout.getvalue()

            # Check formatting elements
            assert "=" * 50 in output, "Should have header separator"
            assert output.count("🎉") >= 1, "Should have celebration emoji"
            assert "View:" in output, "Should have View label"

    @pytest.mark.parametrize(
        "old_price,new_price,expected_old,expected_new",
        [
            (29.99, 19.99, "€29.99", "€19.99"),
            (15.0, 12.5, "€15.0", "€12.5"),
            (100, 75, "€100", "€75"),
            (0.99, 0.50, "€0.99", "€0.5"),
        ],
    )
    def test_price_formatting_in_alerts(
        self,
        notification_service: NotificationService,
        old_price: float,
        new_price: float,
        expected_old: str,
        expected_new: str,
    ) -> None:
        """Test price formatting in alert messages."""
        alerts = [
            {
                "alert_type": "price_drop",
                "title": "Test Movie",
                "old_price": old_price,
                "new_price": new_price,
                "url": "https://cdon.fi/tuote/test/",
            }
        ]

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            notification_service._print_console_alerts(alerts)
            output = mock_stdout.getvalue()

            assert f"{expected_old} → {expected_new}" in output, (
                f"Should format prices as {expected_old} → {expected_new}"
            )

    def test_unicode_handling_in_alerts(self, notification_service: NotificationService) -> None:
        """Test handling of unicode characters in alert messages."""
        alerts = [
            {
                "alert_type": "price_drop",
                "title": "Amélie - Blu-ray édition spéciale",
                "old_price": 25.50,
                "new_price": 18.99,
                "url": "https://cdon.fi/tuote/amélie-special/",
            }
        ]

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            notification_service._print_console_alerts(alerts)
            output = mock_stdout.getvalue()

            # Should handle unicode characters properly
            assert "Amélie - Blu-ray édition spéciale" in output
            assert "€25.5 → €18.99" in output

    def test_long_title_handling(self, notification_service: NotificationService) -> None:
        """Test handling of very long movie titles."""
        long_title = "This Is A Very Long Movie Title That Contains Many Words And Characters To Test Display Formatting"
        alerts = [
            {
                "alert_type": "target_reached",
                "title": long_title,
                "old_price": 30.00,
                "new_price": 20.00,
                "url": "https://cdon.fi/tuote/long-title/",
            }
        ]

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            notification_service._print_console_alerts(alerts)
            output = mock_stdout.getvalue()

            # Should include the full title without truncation
            assert long_title in output
            assert "Target price reached: €20.0" in output
