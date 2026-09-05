"""
Temperature Alarm App for AppDaemon.

This module provides a temperature monitoring and alerting system for Home Assistant
via AppDaemon. It monitors temperature sensors and sends notifications when
temperature values fall within configured ranges.

Author: the_louie
License: BSD 2-Clause
"""

from datetime import datetime
from typing import Any, Dict
import traceback

import appdaemon.plugins.hass.hassapi as hass


class TempAlarm(hass.Hass):
    """
    Temperature Alarm App for AppDaemon.

    Monitors temperature sensors and sends notifications when temperature values
    fall within configured ranges. Supports multiple temperature thresholds with
    configurable cooldown periods to prevent notification spam.

    Configuration:
        sensor (str): Entity ID of the temperature sensor to monitor
        recipients (list[str]): List of notification service names
        name (str): Display name for the alarm system
        limits (list[dict]): List of temperature limit configurations
            - lt (float): Upper temperature limit (less than)
            - gt (float): Lower temperature limit (greater than or equal)
            - message (str): Notification message for this range
            - msg_cooldown (int): Cooldown period in seconds
    """

    def initialize(self) -> None:
        """
        Initialize the temperature alarm system.

        Sets up configuration, validates parameters, and starts monitoring
        the specified temperature sensor.

        Raises:
            ValueError: If required configuration is missing or invalid
        """
        try:
            self.log("Initializing TempAlarm application", level="INFO")

            # Load and validate configuration
            self._load_configuration()
            self._validate_configuration()

            # Initialize internal state
            self._initialize_limits()

            # Start monitoring
            self.listen_state(self._state_change_callback, self.sensor)

            # Check initial state
            initial_state = self.get_state(self.sensor)
            self.log(f"Initial sensor state: {initial_state}", level="DEBUG")
            self._check_temperature_state(initial_state)

            self.log(
                f"TempAlarm '{self.alert_name}' initialized successfully. "
                f"Monitoring sensor: {self.sensor}, "
                f"Recipients: {self.recipients}",
                level="INFO"
            )

        except Exception as e:
            self.log(
                f"Failed to initialize TempAlarm: {str(e)}",
                level="ERROR"
            )
            self.log(f"Traceback: {traceback.format_exc()}", level="ERROR")
            raise

    def _load_configuration(self) -> None:
        """
        Load configuration parameters from AppDaemon args.

        Raises:
            ValueError: If required configuration is missing
        """
        self.log("Loading configuration parameters", level="DEBUG")

        self.sensor = self.args.get("sensor")
        self.recipients = self.args.get("recipients")
        # Display name. AppDaemon injects the app's YAML key into args["name"]
        # and overwrites whatever the config author wrote there, so a config
        # saying `name: "Vind"` is silently discarded. Verified live 2026-09-05
        # against the admin API: args["name"] reads 'WindAlarm', 'RainAlarm',
        # 'TemperatureAlarm', 'TempAlarmLghEntre' -- the app keys, every time,
        # with the configured value gone entirely rather than kept elsewhere.
        #
        # So the display name has to come from a key AppDaemon does not reserve.
        # Falling back to args["name"] preserves exactly the previous behaviour
        # for a config that has not been updated: the app key. (T-53)
        self.alert_name = (
            self.args.get("alert_name")
            or self.args.get("name")
            or self.__class__.__name__
        )
        self.limits = self.args.get("limits")

        # Android companion-app delivery settings. The default HA notification channel
        # can be disabled on the phone, which silently discards every notification sent
        # to it - HA reports success and nothing arrives. Sending on a dedicated channel
        # keeps these alerts independent of that setting and lets them be muted on
        # their own without affecting other apps. See backlog T-52.
        self.notification_channel = self.args.get("notification_channel", "temperature_alerts")
        self.notification_priority = self.args.get("notification_priority", "high")

        self.log(f"Configuration loaded - Sensor: {self.sensor}, "
                f"Name: {self.alert_name}, Limits count: {len(self.limits)}",
                level="DEBUG")

    def _validate_configuration(self) -> None:
        """
        Validate that all required configuration parameters are present and valid.

        Raises:
            ValueError: If configuration is invalid
        """
        self.log("Validating configuration", level="DEBUG")

        if not self.sensor:
            raise ValueError("Required configuration 'sensor' is missing")

        if not self.recipients:
            raise ValueError("Required configuration 'recipients' is missing")

        # No check on alert_name. It cannot be missing: AppDaemon always injects
        # the app's YAML key into args["name"], so the resolver above always
        # returns something. The check that used to sit here read
        # `if not self.alert_name: raise` and had never been reachable in the
        # app's life -- a validation that cannot fire is not protection, it is
        # a claim of protection. Refusing to start over a cosmetic display name
        # would also be the wrong trade: the alert matters, its title does not.

        if not self.limits or not isinstance(self.limits, list):
            raise ValueError("Required configuration 'limits' is missing or not a list")

        # Ensure recipients is a list
        if not isinstance(self.recipients, list):
            self.recipients = [self.recipients]

        # Validate limits structure
        for i, limit in enumerate(self.limits):
            if not isinstance(limit, dict):
                raise ValueError(f"Limit {i} is not a dictionary")

            required_keys = ["lt", "gt", "message", "msg_cooldown"]
            for key in required_keys:
                if key not in limit:
                    raise ValueError(f"Limit {i} missing required key '{key}'")

            if not isinstance(limit["msg_cooldown"], (int, float)) or limit["msg_cooldown"] < 0:
                raise ValueError(f"Limit {i} has invalid msg_cooldown value")

        self.log("Configuration validation completed successfully", level="DEBUG")

    def _initialize_limits(self) -> None:
        """Initialize the limits with timestamp tracking."""
        self.log("Initializing temperature limits", level="DEBUG")

        for i, limit in enumerate(self.limits):
            # Initialize last message timestamp to epoch start
            limit["last_message_timestamp"] = datetime(1970, 1, 1)
            self.log(f"Initialized limit {i}: {limit['gt']}°C <= temp < {limit['lt']}°C "
                    f"-> '{limit['message']}' (cooldown: {limit['msg_cooldown']}s)",
                    level="DEBUG")

    def _state_change_callback(self, entity: str, attribute: str,
                             old: str, new: str, kwargs: Dict[str, Any]) -> None:
        """
        Callback for sensor state changes.

        Args:
            entity: The entity that changed
            attribute: The attribute that changed
            old: Previous state value
            new: New state value
            kwargs: Additional callback arguments
        """
        try:
            if new != old and new is not None:
                self.log(f"Temperature sensor state changed: {old} -> {new}", level="DEBUG")
                self._check_temperature_state(new)
            else:
                self.log(f"Ignoring state change: {old} -> {new}", level="DEBUG")

        except Exception as e:
            self.log(f"Error in state change callback: {str(e)}", level="ERROR")
            self.log(f"Traceback: {traceback.format_exc()}", level="ERROR")

    def _check_temperature_state(self, temperature_state: str) -> None:
        """
        Check temperature state against configured limits and send notifications.

        Args:
            temperature_state: The current temperature state as a string
        """
        try:
            # Handle invalid states
            if temperature_state is None:
                self.log("Temperature state is None, skipping check", level="WARNING")
                return

            if temperature_state == "unavailable":
                self.log("Temperature sensor is unavailable, skipping check", level="WARNING")
                return

            # Convert to float and validate
            try:
                temperature_value = float(temperature_state)
            except (ValueError, TypeError) as e:
                self.log(f"Invalid temperature value '{temperature_state}': {str(e)}", level="ERROR")
                return

            self.log(f"Checking temperature {temperature_value}°C against {len(self.limits)} limits",
                    level="DEBUG")

            # Check each limit
            message_to_send = None
            current_time = datetime.now()  # Single timestamp for consistency

            for i, limit in enumerate(self.limits):
                self.log(f"Checking limit {i}: {limit['gt']}°C <= {temperature_value}°C < {limit['lt']}°C",
                        level="DEBUG")

                if limit['gt'] <= temperature_value < limit['lt']:
                    self.log(f"Temperature {temperature_value}°C matches limit {i}", level="INFO")

                    # Check cooldown
                    time_since_last = current_time - limit['last_message_timestamp']
                    cooldown_remaining = limit['msg_cooldown'] - time_since_last.total_seconds()

                    if cooldown_remaining <= 0:
                        message_to_send = f"{limit['message']} ({temperature_value:.1f}°C)"
                        limit['last_message_timestamp'] = current_time
                        self.log(f"Preparing to send message: '{message_to_send}'", level="INFO")
                    else:
                        self.log(f"Cooldown active for limit {i}. "
                               f"Remaining: {cooldown_remaining:.0f}s / {limit['msg_cooldown']}s",
                               level="DEBUG")

                    break
                else:
                    self.log(f"Temperature {temperature_value}°C does not match limit {i}", level="DEBUG")

            # Send notification if message is ready
            if message_to_send:
                self._send_notifications(message_to_send)
            else:
                self.log("No notification message to send", level="DEBUG")

        except Exception as e:
            self.log(f"Error checking temperature state: {str(e)}", level="ERROR")
            self.log(f"Traceback: {traceback.format_exc()}", level="ERROR")

    def _notification_data(self) -> dict:
        """Build the companion-app data block for a notification.

        Returns the Android delivery hints every notify call in this app must carry:
        a dedicated channel, plus priority/ttl so the message is not deferred by Doze.
        Returns an empty dict if no channel is configured, so the caller can pass it
        unconditionally.
        """
        if not self.notification_channel:
            return {}
        data = {"channel": self.notification_channel}
        if self.notification_priority:
            data["priority"] = self.notification_priority
            data["ttl"] = 0
        return data

    def _send_notifications(self, message: str) -> None:
        """
        Send notifications to all configured recipients.

        Args:
            message: The message to send
        """
        try:
            self.log(f"Sending notification to {len(self.recipients)} recipients", level="INFO")

            for recipient in self.recipients:
                try:
                    service_name = f"notify/{recipient}"
                    title = f"{self.alert_name} Temperature Alert"

                    self.log(f"Sending to {recipient}: '{message}'", level="INFO")

                    self.call_service(
                        service_name,
                        title=title,
                        message=message,
                        data=self._notification_data()
                    )

                    self.log(f"Successfully sent notification to {recipient}", level="INFO")

                except Exception as e:
                    self.log(f"Failed to send notification to {recipient}: {str(e)}", level="ERROR")
                    self.log(f"Traceback: {traceback.format_exc()}", level="ERROR")

            self.log("Notification sending completed", level="DEBUG")

        except Exception as e:
            self.log(f"Error in notification sending: {str(e)}", level="ERROR")
            self.log(f"Traceback: {traceback.format_exc()}", level="ERROR")

