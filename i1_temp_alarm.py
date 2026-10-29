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

import json
import os
import time

import ha_states
import irisone_bus
import notification_policy as policy


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
            - urgent (bool): REQUIRED (T-72d, owner IQ-23). Urgent bands reach
              every recipient; non-urgent bands are dropped for anyone away.
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

        # Policy D2. Two halves were missing here, and both mattered:
        #
        #   Quiet hours -- there were none. A cold-store band re-firing on its
        #   6-hour cooldown would wake the house at 03:00 to repeat something it
        #   had already said at 21:00.
        #
        #   Persistence -- `last_message_timestamp` lived on the limit dict, in
        #   memory. Every AppDaemon restart reset every cooldown and re-alerted
        #   every active band. This app restarts often; that is the "redundant
        #   restart-time re-alerts" D2 names by name.
        #
        # A first occurrence is always sent, whatever the hour. Quiet hours
        # suppress nagging, not news.
        self.quiet_hours = self.args.get("quiet_hours", True)
        self.quiet_start = self.args.get("quiet_start", policy.DEFAULT_QUIET_START)
        self.quiet_end = self.args.get("quiet_end", policy.DEFAULT_QUIET_END)
        self.state_file = self.args.get(
            "state_file", f"/conf/temp_alarm_{self.name}.json"
        )
        self.sent_state = self._load_state()
        # (band key, recipient) -> presence `since` of the last logged drop (O3).
        self._drop_logged: Dict[tuple, Any] = {}

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

            required_keys = ["lt", "gt", "message", "msg_cooldown", "urgent"]
            for key in required_keys:
                if key not in limit:
                    raise ValueError(f"Limit {i} missing required key '{key}'")

            if not isinstance(limit["msg_cooldown"], (int, float)) or limit["msg_cooldown"] < 0:
                raise ValueError(f"Limit {i} has invalid msg_cooldown value")

            # IQ-12/IQ-23: every band states its urgency; no default, so a band
            # nobody classified stops the app instead of guessing.
            if not isinstance(limit["urgent"], bool):
                raise ValueError(f"Limit {i} 'urgent' must be true or false, "
                                 f"got {limit['urgent']!r}")

        # A-71.5: an older shared module winning AppDaemon's import path must
        # stop the app here, not raise at the first alert.
        if not hasattr(policy, "should_notify") or not hasattr(irisone_bus, "presence_for_target"):
            raise RuntimeError(f"stale shared module on the import path: "
                               f"{policy.__file__}, {irisone_bus.__file__}")

        self.log("Configuration validation completed successfully", level="DEBUG")

    def _initialize_limits(self) -> None:
        """Initialize the limits with timestamp tracking."""
        self.log("Initializing temperature limits", level="DEBUG")

        for i, limit in enumerate(self.limits):
            # No per-limit timestamp any more. It lived here, in memory, and
            # every restart reset it -- so every active band re-alerted on boot.
            # Send-times now live in the persisted policy state keyed by band.
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

    @staticmethod
    def _limit_key(index, limit):
        """Stable identity for a band: its bounds, not its position."""
        return f"limit:{limit['gt']}..{limit['lt']}"

    def _now_hour(self):
        """Local hour, for the quiet-hours window.

        get_now() is AppDaemon's clock: Home Assistant's configured timezone,
        correct across the fold (S8-05, T-07). Durations in this app come from
        time.time() epoch seconds and were never affected.
        """
        return self.get_now().hour

    def _load_state(self):
        """Read persisted send-times. Missing or corrupt starts empty."""
        try:
            with open(self.state_file, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return {}
            return {k: v for k, v in data.items() if isinstance(v, (int, float))}
        except FileNotFoundError:
            return {}
        except (ValueError, OSError) as e:
            self.log(f"Cooldown state unreadable, starting fresh: {e}", level="WARNING")
            return {}

    def _save_state(self):
        """Persist atomically. A failure must not stop the alert going out."""
        tmp = f"{self.state_file}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.sent_state, fh)
            os.replace(tmp, self.state_file)
        except OSError as e:
            self.log(
                f"Could not persist cooldown state: {e} -- alerts will repeat "
                f"after the next restart", level="WARNING")

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

            if ha_states.not_reporting(temperature_state):
                # S7-07: was `== "unavailable"` alone, so a sensor reporting
                # "unknown" sailed past this guard into float() -- a live gap
                # the shared predicate closes.
                self.log(
                    f"Temperature sensor is not reporting ({temperature_state}), "
                    f"skipping check", level="WARNING")
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
            band_key, band_urgent, old_state = None, True, {}

            for i, limit in enumerate(self.limits):
                self.log(f"Checking limit {i}: {limit['gt']}°C <= {temperature_value}°C < {limit['lt']}°C",
                        level="DEBUG")

                if limit['gt'] <= temperature_value < limit['lt']:
                    self.log(f"Temperature {temperature_value}°C matches limit {i}", level="INFO")

                    # At most one band is ever active -- the loop breaks here --
                    # so the active set is 0 or 1 key and policy.apply's single
                    # repeat_after is exactly this band's msg_cooldown.
                    #
                    # Keying on the band's bounds rather than its index means an
                    # edited threshold is a different condition and starts fresh,
                    # which is right: a band from 0..1 is not the band from 0..2.
                    # apply() also drops keys that are no longer active, so a
                    # temperature that leaves a band and returns is news again.
                    key = self._limit_key(i, limit)
                    old_state = dict(self.sent_state)
                    to_send, held, self.sent_state = policy.apply(
                        {key}, time.time(), self._now_hour(), self.sent_state,
                        quiet_start=self.quiet_start, quiet_end=self.quiet_end,
                        repeat_after=limit['msg_cooldown'],
                    )
                    self._save_state()

                    if to_send:
                        message_to_send = f"{limit['message']} ({temperature_value:.1f}°C)"
                        band_key, band_urgent = key, limit["urgent"]
                        self.log(
                            f"Preparing to send message: '{message_to_send}' "
                            f"({to_send[0][1]})", level="INFO")
                    else:
                        self.log(f"Limit {i} held: {held[0][1]}", level="DEBUG")

                    break
                else:
                    self.log(f"Temperature {temperature_value}°C does not match limit {i}", level="DEBUG")

            # Send notification if message is ready
            if message_to_send:
                if self._send_notifications(message_to_send, band_key, band_urgent) == 0:
                    # apply() marked the band sent before anyone was gated. Nobody
                    # was reached, so the repeat interval must not start (IQ-13):
                    # if the band still holds when someone comes home, it is news.
                    self.sent_state = policy.uncommit(self.sent_state, old_state, band_key)
                    self._save_state()
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

    def _send_notifications(self, message: str, band_key: str, urgent: bool) -> int:
        """
        Send to every recipient, minus non-urgent drops for anyone away.

        Args:
            message: The message to send
            band_key: The band's policy key, for drop logging and the gate counters
            urgent: The band's configured urgency (owner, IQ-23)

        Returns:
            How many recipients were reached. 0 tells the caller to uncommit.
        """
        reached = 0
        try:
            self.log(f"Sending notification to {len(self.recipients)} recipients", level="INFO")
            domain = self.get_state(irisone_bus.DOMAIN)
            now_epoch = time.time()

            for recipient in self.recipients:
                try:
                    in_home, since = irisone_bus.presence_for_target(domain, recipient, now_epoch)
                    if urgent:
                        send, reason = policy.should_notify(policy.URGENT, in_home)
                    else:
                        send, reason = policy.should_notify(policy.NON_URGENT, in_home)
                    self._report_gate(band_key, recipient, urgent, send, reason)
                    if not send:
                        if policy.drop_log_due(band_key, recipient, since, self._drop_logged):
                            self.log(f"[presence] dropped {self.name}/{band_key} to {recipient}: {reason}")
                        continue

                    service_name = f"notify/{recipient}"
                    title = f"{self.alert_name} Temperature Alert"

                    self.log(f"Sending to {recipient}: '{message}'", level="INFO")

                    self.call_service(
                        service_name,
                        title=title,
                        message=message,
                        data=self._notification_data()
                    )

                    self.log(f"Successfully sent notification to {recipient} ({reason})", level="INFO")
                    reached += 1

                except Exception as e:
                    self.log(f"Failed to send notification to {recipient}: {str(e)}", level="ERROR")
                    self.log(f"Traceback: {traceback.format_exc()}", level="ERROR")

            self.log("Notification sending completed", level="DEBUG")

        except Exception as e:
            self.log(f"Error in notification sending: {str(e)}", level="ERROR")
            self.log(f"Traceback: {traceback.format_exc()}", level="ERROR")
        return reached

    def _report_gate(self, key: str, target: str, urgent: bool, send: bool, reason: str) -> None:
        """Count the decision in irisone.notify_gate_stats (IQ-28). Never blocks a send."""
        try:
            urgency = policy.URGENT if urgent else policy.NON_URGENT
            self.fire_event(irisone_bus.GATE_EVENT, **irisone_bus.gate_event(
                self.name, key, target, urgency, send, reason))
        except Exception as e:  # the counter is evidence, not a dependency
            self.log(f"[presence] could not report gate decision: {e}", level="WARNING")

