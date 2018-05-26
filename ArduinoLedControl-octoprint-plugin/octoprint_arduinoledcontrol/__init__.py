# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
from octoprint.util import RepeatedTimer
from octoprint.events import Events
from octoprint.util import comm
import serial
import time

# adding custom gcode events
comm.gcodeToEvent["M104"] = "SetExtruderTemp"
comm.gcodeToEvent["M140"] = "SetBedTemp"
comm.gcodeToEvent["M109"] = "WaitingForExtruderTemp"
comm.gcodeToEvent["M190"] = "WaitingForBedTemp"
comm.gcodeToEvent["M117"] = "PrinterSentMessage"


class ArduinoLedControlPlugin(
    octoprint.plugin.StartupPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.EventHandlerPlugin,
    octoprint.plugin.BlueprintPlugin,
    octoprint.plugin.SettingsPlugin):
    command_names = {
        "off"         : "o",
        "white"       : "w",
        "temperature" : "t%03d",

        # rainbow commands
        "slow rainbow": "rs",
        "fast rainbow": "rf",

        # fade commands
        "white fade"  : "fw",
        "blue fade"   : "fb",
        "red fade"    : "fr",
        "green fade"  : "fg",
        "yellow fade" : "fy",

        # cycle commands
        "white cycle" : "cw",
        "blue cycle"  : "cb",
        "red cycle"   : "cr",
        "green cycle" : "cg",
        "yellow cycle": "cy",
    }

    default_led_settings = {
        # Printer communication events
        "Port"                  : "/dev/ttyACM1",
        "Baud Rate"             : 9600,
        "Tool Head"             : "tool0",
        "Print started message" : "Mini Printing...",
        "Print finished message": "Cooling please wait",

        Events.CONNECTING       : "white cycle",
        Events.CONNECTED        : "white",
        Events.DISCONNECTING    : "white fade",
        Events.DISCONNECTED     : "off",
        Events.ERROR            : "red fade",

        # Printing events
        Events.PRINT_FAILED     : "red fade",
        Events.PRINT_DONE       : "slow rainbow",
        Events.PRINT_CANCELLING : "red cycle",
        Events.PRINT_CANCELLED  : "red fade",
        Events.PRINT_PAUSED     : "blue fade",
        Events.PRINT_RESUMED    : "white",
        "PrinterSentMessage"    : "white",

        # GCODE Processing events (not triggered when printing from SD)
        Events.HOME             : "white fade",
        Events.Z_CHANGE         : "white",
        # Events.DWELL            : "temperature",
        # Events.COOLING          : "temperature",
        Events.ALERT            : "red cycle",
        Events.E_STOP           : "red cycle",
        # Events.POSITION_UPDATE  : "white",
        "WaitingForExtruderTemp": "temperature",
        "SetExtruderTemp"       : "temperature"
    }

    def __init__(self):
        super(ArduinoLedControlPlugin, self).__init__()
        self.device = None
        self.port = ""
        self.baud = 0

        self.temp_check_tool = "tool0"
        # self.initial_temperature = None
        # self.prev_target_temperature = None
        self.should_send_temperature = False
        self.check_timer_started = False
        self.check_temp_time_interval = 1.0
        self.min_temperature = 35.0  # blue light color
        self.max_temperature = 140.0  # red light color

        self.print_is_running = False

        self.check_temp_timer = RepeatedTimer(
            self.check_temp_time_interval,
            self.check_hotend_temperature,
            run_first=True
        )

    def cancel_check_timer(self):
        self.should_send_temperature = False

    def reset_check_timer(self):
        if not self.check_timer_started:
            self._logger.info("Starting temperature check timer")
            self.check_temp_timer.start()
            self.check_timer_started = True
        else:
            self._logger.info("Temperature check timer already started")

        result = self._printer.get_current_temperatures()
        self.temp_check_tool = self._settings.get(["ToolHead"])
        target_t = result[self.temp_check_tool]["target"]

        # if self.prev_target_temperature == target_t:
        #     self._logger.info("Target temp '%s' is the same as previous command. Skipping." % target_t)
        #     return
        # self.prev_target_temperature = target_t

        # self.initial_temperature = None
        self.should_send_temperature = True

        self._logger.info("Enabling temperature check timer to '%s'" % target_t)

    def check_device(self):
        try:
            port = str(self._settings.get(["Port"]))
            baud = int(self._settings.get(["Baud Rate"]))
        except BaseException as e:
            return e

        if self.device is None or port != self.port or baud != self.baud:
            self._logger.info("Opening device on port '%s'" % port)

            self.port = port
            self.baud = baud

            if self.device is not None:
                self.device.close()

            try:
                self.device = serial.Serial(port, baud)
                time.sleep(2)  # wait for arduino to connect
                return None
            except OSError as e:
                return e
        else:
            if not self.device.isOpen():
                return RuntimeError("LED Arduino is not open for writing!!")
            else:
                return None

    def issue_command(self, command):
        result = self.check_device()
        if result is not None:
            response = "Device not found: '%s'" % result
            self._logger.warn(response)
            # with self._app_session_manager:
            # return flask.make_response(response, 500)
            return response
        self.device.write(command + "\n")

        self._logger.info("Command '%s' sent" % command)

        # with self._app_session_manager:
        # return flask.make_response("Command '%s' sent" % command, 200)
        return "Command '%s' sent" % command

    def check_hotend_temperature(self):
        result = self._printer.get_current_temperatures()
        target_t = result[self.temp_check_tool]["target"]
        actual_t = result[self.temp_check_tool]["actual"]

        # if self.initial_temperature is None:
        #     self.initial_temperature = actual_t

        # value = int(255.0 / (target_t - self.initial_temperature) * (actual_t - self.initial_temperature))
        value = int(255.0 / (self.max_temperature - self.min_temperature) * (actual_t - self.min_temperature))
        if value < 0:
            value = 0
        if value > 255:
            value = 255

        # if target_t < actual_t:  # cooling down
        #     value = 255 - value

        if self.should_send_temperature and not self.print_is_running:
            self._logger.info(
                "Sending temperature command value: %s. Target: %s, Actual: %s" % (value, target_t, actual_t))
            self.issue_command(self.command_names["temperature"] % value)
        else:
            self._logger.info(
                "Skipping temperature command value: %s. Target: %s, Actual: %s" % (value, target_t, actual_t))

    # octoprint.plugin.StartupPlugin
    def on_after_startup(self):
        self._logger.info("Arduino LED Control plugin is awake")

    # octoprint.plugin.TemplatePlugin
    def get_template_configs(self):
        return [
            dict(type="tab", custom_bindings=False),
            dict(type="settings", custom_bindings=False),
            # dict(type="tab", template="Illuminatrix_tab.jinja2")
            # dict(type="settings", template="Illuminatrix_settings.jinja2")
        ]

    # octoprint.plugin.EventHandlerPlugin
    def on_event(self, event, payload):
        command = self._settings.get([event])
        self._logger.info("received event: '%s', payload: '%s', command: '%s'" % (event, payload, command))

        if event == "PrinterSentMessage":
            if command == self._settings.get(["Print started message"]):
                self.print_is_running = True
            elif command == self._settings.get(["Print finished message"]):
                self.print_is_running = False

        if command is not None:
            if command == "temperature":
                self.reset_check_timer()
            else:
                self.cancel_check_timer()
                self.issue_command(self.command_names[command])
                self._logger.info("Received event to send command '%s'" % command)

    # octoprint.plugin.BlueprintPlugin
    @octoprint.plugin.BlueprintPlugin.route("/white", methods=["GET"])
    def set_white(self):
        self._logger.info("Calling set_white route")
        self.cancel_check_timer()
        return self.issue_command(self.command_names["white"])

    @octoprint.plugin.BlueprintPlugin.route("/off", methods=["GET"])
    def set_off(self):
        self._logger.info("Calling set_off route")
        self.cancel_check_timer()
        return self.issue_command(self.command_names["off"])

    @octoprint.plugin.BlueprintPlugin.route("/rainbow", methods=["GET"])
    def set_rainbow(self):
        self._logger.info("Calling set_rainbow route")
        self.cancel_check_timer()
        return self.issue_command(self.command_names["fast rainbow"])

    @octoprint.plugin.BlueprintPlugin.route("/is_connected", methods=["GET"])
    def check_if_connected(self):
        self._logger.info("Checking if device is open.")
        if self.check_device() is None:
            return "open"
        else:
            return "closed"

    def is_blueprint_protected(self):
        return False

    def get_settings_defaults(self):
        return self.default_led_settings


# If you want your plugin to be registered within OctoPrint under a different name than what you defined in setup.py,
# you may define that here. Same goes for the other metadata derived from setup.py that
# can be overwritten via __plugin_xyz__ control properties. See the documentation for that.

__plugin_name__ = "Arduino LED Control"
__plugin_implementation__ = ArduinoLedControlPlugin()
