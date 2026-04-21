"""Tests for application configuration defaults."""

from app.config import Settings


class TestSettingsDefaults:
    """Tests for default setting values."""

    def test_default_servicebus_connection_string(self):
        """Default Service Bus connection string should be empty."""
        s = Settings(
            _env_file=None,
            azure_servicebus_connection_string="",
        )
        assert s.azure_servicebus_connection_string == ""

    def test_default_queue_name(self):
        """Default queue name should be 'order-events'."""
        s = Settings(_env_file=None)
        assert s.azure_servicebus_queue_name == "order-events"

    def test_default_log_level(self):
        """Default log level should be 'INFO'."""
        s = Settings(_env_file=None)
        assert s.log_level == "INFO"

    def test_default_environment(self):
        """Default environment should be 'development'."""
        s = Settings(_env_file=None)
        assert s.environment == "development"

    def test_default_service_name(self):
        """Default service name should be 'eventflow-payment-service'."""
        s = Settings(_env_file=None)
        assert s.service_name == "eventflow-payment-service"

    def test_default_service_version(self):
        """Default service version should be '1.0.0'."""
        s = Settings(_env_file=None)
        assert s.service_version == "1.0.0"

    def test_default_order_service_url(self):
        """Default order service URL should be empty."""
        s = Settings(_env_file=None)
        assert s.order_service_url == ""

    def test_default_appinsights_connection_string(self):
        """Default Application Insights connection string should be empty."""
        s = Settings(_env_file=None)
        assert s.applicationinsights_connection_string == ""
