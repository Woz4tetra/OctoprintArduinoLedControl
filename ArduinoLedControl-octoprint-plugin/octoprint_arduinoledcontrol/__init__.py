# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
from octoprint.util import RepeatedTimer
from octoprint.events import Events
from octoprint.util import comm
import serial
import time


class CustomSettings:
    SET_EXTRUDER_TEMP_EVENT = "SetExtruderTemp"
    SET_BED_TEMP_EVENT = "SetBedTemp"
    WAITING_FOR_EXTRUDER_TEMP_EVENT = "WaitingForExtruderTemp"
    WAITING_FOR_BED_TEMP_EVENT = "WaitingForBedTemp"
    PRINTER_SENT_MESSAGE_EVENT = "PrinterSentMessage"

    OFF_COMMAND = "off"
    WHITE_COMMAND = "white"
    TEMPERATURE_COMMAND = "temperature"
    SLOW_RAINBOW_COMMAND = "slow rainbow"
    FAST_RAINBOW_COMMAND = "fast rainbow"
    WHITE_FADE_COMMAND = "white fade"
    BLUE_FADE_COMMAND = "blue fade"
    RED_FADE_COMMAND = "red fade"
    GREEN_FADE_COMMAND = "green fade"
    YELLOW_FADE_COMMAND = "yellow fade"
    WHITE_CYCLE_COMMAND = "white cycle"
    BLUE_CYCLE_COMMAND = "blue cycle"
    RED_CYCLE_COMMAND = "red cycle"
    GREEN_CYCLE_COMMAND = "green cycle"
    YELLOW_CYCLE_COMMAND = "yellow cycle"

    PORT_SETTING = "Port"
    BAUD_RATE_SETTING = "Baud Rate"
    TOOL_HEAD_SETTING = "Tool Head"

    PRINT_MESSAGE_FINISHED = 0
    PRINT_MESSAGE_HEATING = 1
    PRINT_MESSAGE_STARTING = 2
    PRINT_MESSAGE_NUM_STATES = 3


# adding custom gcode events
# comm.gcodeToEvent["M104"] = CustomSettings.SET_EXTRUDER_TEMP_EVENT
# comm.gcodeToEvent["M140"] = CustomSettings.SET_BED_TEMP_EVENT
# comm.gcodeToEvent["M109"] = CustomSettings.WAITING_FOR_EXTRUDER_TEMP_EVENT
# comm.gcodeToEvent["M190"] = CustomSettings.WAITING_FOR_BED_TEMP_EVENT
comm.gcodeToEvent["M117"] = CustomSettings.PRINTER_SENT_MESSAGE_EVENT


class ArduinoLedControlPlugin(
    octoprint.plugin.StartupPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.EventHandlerPlugin,
    octoprint.plugin.BlueprintPlugin,
    octoprint.plugin.SettingsPlugin):
    command_names = {
        CustomSettings.OFF_COMMAND         : "o",
        CustomSettings.WHITE_COMMAND       : "w",
        CustomSettings.TEMPERATURE_COMMAND : "t%03d",

        # rainbow commands
        CustomSettings.SLOW_RAINBOW_COMMAND: "rs",
        CustomSettings.FAST_RAINBOW_COMMAND: "rf",

        # fade commands
        CustomSettings.WHITE_FADE_COMMAND  : "fw",
        CustomSettings.BLUE_FADE_COMMAND   : "fb",
        CustomSettings.RED_FADE_COMMAND    : "fr",
        CustomSettings.GREEN_FADE_COMMAND  : "fg",
        CustomSettings.YELLOW_FADE_COMMAND : "fy",

        # cycle commands
        CustomSettings.WHITE_CYCLE_COMMAND : "cw",
        CustomSettings.BLUE_CYCLE_COMMAND  : "cb",
        CustomSettings.RED_CYCLE_COMMAND   : "cr",
        CustomSettings.GREEN_CYCLE_COMMAND : "cg",
        CustomSettings.YELLOW_CYCLE_COMMAND: "cy",
    }

    default_led_settings = {
        # Printer communication events
        CustomSettings.PORT_SETTING              : "/dev/ttyACM1",
        CustomSettings.BAUD_RATE_SETTING         : 9600,
        CustomSettings.TOOL_HEAD_SETTING         : "tool0",

        Events.CONNECTING                        : "white cycle",
        Events.CONNECTED                         : "white",
        Events.DISCONNECTING                     : "white fade",
        Events.DISCONNECTED                      : "off",
        Events.ERROR                             : "red fade",

        # Printing events
        Events.PRINT_FAILED                      : "red fade",
        Events.PRINT_DONE                        : "slow rainbow",
        Events.PRINT_CANCELLING                  : "red cycle",
        Events.PRINT_CANCELLED                   : "red fade",
        Events.PRINT_PAUSED                      : "blue fade",
        Events.PRINT_RESUMED                     : "white",
        CustomSettings.PRINTER_SENT_MESSAGE_EVENT: "white",

        # GCODE Processing events (not triggered when printing from SD)
        Events.HOME                              : "white fade",
        Events.Z_CHANGE                          : "white",
        Events.ALERT                             : "red cycle",
        Events.E_STOP                            : "red cycle",
        Events.POSITION_UPDATE                   : "white",
        # CustomSettings.WAITING_FOR_EXTRUDER_TEMP_EVENT: "temperature",
        # CustomSettings.SET_EXTRUDER_TEMP_EVENT        : "temperature"
    }

    def __init__(self):
        super(ArduinoLedControlPlugin, self).__init__()
        self.device = None
        self.port = ""
        self.baud = 0

        self.temp_check_tool = "tool0"
        # self.initial_temperature = None
        self.prev_target_temperature = None
        self.should_send_temperature = False
        self.check_timer_started = False
        self.check_temp_time_interval = 0.75
        self.min_temperature = 35.0  # blue light color
        self.max_temperature = 140.0  # red light color

        self.print_is_running = False
        self.print_state = CustomSettings.PRINT_MESSAGE_FINISHED
        self.printer_is_connected = False

        self.check_temp_timer = RepeatedTimer(
            self.check_temp_time_interval,
            self.check_hotend_temperature,
            run_first=True
        )

    def cancel_check_timer(self):
        self.should_send_temperature = False

    # def check_temp_timer_condition(self):
    #     return self.printer_is_connected

    def reset_check_timer(self):
        if not self.check_timer_started:
            self._logger.info("Starting temperature check timer")
            self.check_temp_timer.start()
            self.check_timer_started = True
        else:
            self._logger.info("Temperature check timer already started")

        self.temp_check_tool = self._settings.get([CustomSettings.TOOL_HEAD_SETTING])

        self._logger.info("Enabling temperature check timer")

    def check_device(self):
        try:
            port = str(self._settings.get([CustomSettings.PORT_SETTING]))
            baud = int(self._settings.get([CustomSettings.BAUD_RATE_SETTING]))
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
        self._logger.info("Get temperatures result: %s" % str(result))

        if self.temp_check_tool not in result:
            self.temp_check_tool = self._settings.get([CustomSettings.TOOL_HEAD_SETTING])
            self._logger.warning("Tool head specified wasn't found. Will keep checking for it")
            return

        target_t = result[self.temp_check_tool]["target"]
        actual_t = result[self.temp_check_tool]["actual"]

        # self._logger.info("Temperature values; target: %s, actual: %s" % (target_t, actual_t))

        # send temperature commands if a change in target temperature is detected
        if target_t != self.prev_target_temperature:
            self.should_send_temperature = True
            self.prev_target_temperature = target_t

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

        self._logger.info(
            "should_send_temperature: %s, print_is_running: %s" % (self.should_send_temperature, self.print_is_running))
        if self.should_send_temperature and not self.print_is_running:
            self._logger.info("Sending temperature command value: %s" % value)
            self.issue_command(self.command_names["temperature"] % value)

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

        if event == Events.DISCONNECTED:
            self.printer_is_connected = False

        elif event == Events.CONNECTED:
            self.printer_is_connected = True
            self.reset_check_timer()

        elif event == CustomSettings.PRINTER_SENT_MESSAGE_EVENT:
            if command == self._settings.get([CustomSettings.PRINTER_SENT_MESSAGE_EVENT]):
                self.print_state += 1
                if self.print_state >= CustomSettings.PRINT_MESSAGE_NUM_STATES:
                    self.print_state = 0

                if self.print_state == CustomSettings.PRINT_MESSAGE_STARTING:
                    self.print_is_running = True
                    self._logger.info("Print has started!")

                elif self.print_state == CustomSettings.PRINT_MESSAGE_FINISHED:
                    self.print_is_running = False
                    self._logger.info("Print has finished!")

        if command is not None:
            # if command == "temperature":
            #     self.reset_check_timer()
            #     self._logger.info("Received event to send temperature command")
            # else:
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
