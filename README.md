# Temperature Alarm App for AppDaemon

A robust temperature monitoring and alerting system for Home Assistant via AppDaemon. This application monitors temperature sensors and sends notifications when temperature values fall within configured ranges, with configurable cooldown periods to prevent notification spam.

**Copyright (c) 2025, the_louie**

## Features

- **Multi-threshold monitoring**: Configure multiple temperature ranges with different alert messages
- **Cooldown periods**: Prevent notification spam with configurable cooldown intervals
- **Extensive logging**: Enterprise-grade logging with proper error handling and context
- **Robust error handling**: Comprehensive exception handling with detailed error messages
- **Type safety**: Full type hints for better code maintainability
- **Configuration validation**: Automatic validation of all configuration parameters

## Installation

1. Copy `i1_temp_alarm.py` to your AppDaemon `apps` directory
2. Copy the configuration from `config.yaml.example` to your AppDaemon configuration file
3. Customize the configuration for your specific needs
4. Restart AppDaemon

## Configuration

### Basic Configuration

```yaml
TempAlarmExample:
  module: i1_temp_alarm
  class: TempAlarm
  sensor: "sensor.your_temperature_sensor"
  recipients:
    - mobile_app_your_device
  name: "Your Location Name"
  limits:
    - lt: 5
      gt: 1
      message: "Temperature is normal"
      msg_cooldown: 86400
    - lt: 1
      gt: 0
      message: "Getting cold"
      msg_cooldown: 86400
    - lt: 0
      gt: -4
      message: "Very cold"
      msg_cooldown: 21600
    - lt: -4
      gt: -999
      message: "Too cold!"
      msg_cooldown: 3600
```

### Configuration Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sensor` | string | Yes | Entity ID of the temperature sensor to monitor |
| `recipients` | list[string] | Yes | List of notification service names |
| `name` | string | Yes | Display name for the alarm system |
| `limits` | list[dict] | Yes | List of temperature limit configurations |

### Limit Configuration

Each limit in the `limits` list should contain:

| Parameter | Type | Description |
|-----------|------|-------------|
| `lt` | float | Upper temperature limit (less than) |
| `gt` | float | Lower temperature limit (greater than or equal) |
| `message` | string | Notification message for this range |
| `msg_cooldown` | int | Cooldown period in seconds |

### Temperature Range Logic

The application uses the following logic to determine which limit applies:
- `gt <= temperature < lt`
- Limits are checked in order, and the first matching limit is used
- If no limit matches, no notification is sent

## Usage Examples

### Cold Storage Monitoring

```yaml
ColdStorageAlarm:
  module: i1_temp_alarm
  class: TempAlarm
  sensor: "sensor.cold_storage_temp"
  recipients:
    - mobile_app_pixel_9_pro
    - notify_telegram
  name: "Cold Storage"
  limits:
    - lt: 5
      gt: 1
      message: "Cold storage temperature is normal"
      msg_cooldown: 86400
    - lt: 1
      gt: 0
      message: "Cold storage is getting warm"
      msg_cooldown: 21600
    - lt: 0
      gt: -4
      message: "Cold storage is very warm"
      msg_cooldown: 3600
    - lt: -4
      gt: -999
      message: "Cold storage is too warm!"
      msg_cooldown: 1800
```

### Greenhouse Monitoring

```yaml
GreenhouseAlarm:
  module: i1_temp_alarm
  class: TempAlarm
  sensor: "sensor.greenhouse_temperature"
  recipients:
    - mobile_app_garden_phone
  name: "Greenhouse"
  limits:
    - lt: 15
      gt: 10
      message: "Greenhouse temperature is low"
      msg_cooldown: 3600
    - lt: 10
      gt: 5
      message: "Greenhouse is very cold"
      msg_cooldown: 1800
    - lt: 5
      gt: -999
      message: "Greenhouse is freezing!"
      msg_cooldown: 900
    - lt: 999
      gt: 30
      message: "Greenhouse is too hot"
      msg_cooldown: 1800
```

## Logging

The application provides extensive logging at multiple levels:

- **DEBUG**: Detailed operation information
- **INFO**: General operation status and notifications
- **WARNING**: Non-critical issues (e.g., sensor unavailable)
- **ERROR**: Critical errors with full stack traces

All log messages include context information such as sensor name, temperature values, and operation status.

## Error Handling

The application includes comprehensive error handling:

- **Configuration validation**: All configuration parameters are validated at startup
- **Sensor state handling**: Graceful handling of unavailable or invalid sensor states
- **Notification failures**: Individual notification failures don't stop other notifications
- **Exception logging**: All exceptions are logged with full stack traces

## Development

### Code Style

- Follows PEP 8 style guide (except line length: 120 characters)
- Full type hints throughout
- Comprehensive docstrings
- Extensive error handling and logging

## License

BSD 2-Clause License. See [LICENSE](LICENSE) for details.

## Support

For issues and questions:
1. Check the logs for detailed error information
2. Verify your configuration matches the examples
3. Ensure your temperature sensor is working correctly
4. Check that your notification services are properly configured

## Changelog

### Version 2.0.0
- Complete rewrite with enterprise-grade features
- Added comprehensive error handling and logging
- Added type hints and documentation
- Improved configuration validation
- Enhanced temperature range logic