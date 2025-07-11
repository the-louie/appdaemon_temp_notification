from datetime import datetime
import json
import appdaemon.plugins.hass.hassapi as hass

#TempAlarmLghEntre:
#  module: i1_temp_alarm
#  class: TempAlarm
#  sensor: "sensor.v0_lgh_entre_temp"
#  notify:
#    - mobile_app_pixel_9_pro
#  name: "Äpplen"
#  limits:
#    - lt: 5
#      gt: 1
#      message: "All ok"
#      msg_cooldown: 86400
#    - lt: 1
#      gt: 0
#      message: "Getting cold"
#      msg_cooldown: 86400
#    - lt: 0
#      gt: -4
#      message: "Very coold"
#      msg_cooldown: 21600
#    - lt: -4
#      gt: -999
#      message: "Too cold!"
#      msg_cooldown: 3600

class TempAlarm(hass.Hass):
  def initialize(self):
    self.log("Loading TempAlarm()")

    self.sensor = self.args.get("sensor")
    self.recipients = self.args.get("recipients")
    self.alert_name = self.args.get("name")
    self.limits = self.args.get("limits")

    if self.sensor is None:
      self.log(" >> TempAlarm.initialize(): Warning - Not configured")
      return

    if not isinstance(self.recipients, list):
      self.recipients = [self.recipients]

    self.listen_state(self.state_change, self.sensor)
    
    self.log(" >> TempAlarm {} ==> {}".format(self.sensor,
                                                 self.recipients))

    # add some more stuff to the limits dict
    for limit in self.limits:
        limit["lmts"] = datetime(1970, 1, 1) # last message timestamp

    self.check_state(self.get_state(self.sensor))

  def state_change(self, entity, attribute, old, new, kwargs):
    if new != old and new is not None:
      self.check_state(new)


  def check_state(self, new):
    if new is None:
        return
    if new == "unavailable":
        return

    self.log("check_state({})".format(new))
    value = float(new)

    now = datetime.now()
    message = None
    for limit in self.limits:
        self.log("lim: {}".format(limit))
        if value < limit.get("lt") and value >= limit.get("gt"):
            if (now - limit.get("lmts")).total_seconds() > limit.get("msg_cooldown"):
                self.log("SEND: {}".format(limit.get("message")))
                message = "{} ({}°)".format(limit.get("message"), value)
                limit["lmts"] = datetime.now()
            else:
                self.log("Cooldown active {} {}".format((now - limit.get("lmts")).total_seconds(), limit.get("msg_cooldown")))

            break

    if message is None:
        self.log("No message, returning")
        return

    for recipient in self.recipients:
        self.log("sending '{}' to {}".format(message, recipient))
        self.call_service("notify/{}".format(recipient), title="{} temp".format(self.alert_name), message=message)
    
