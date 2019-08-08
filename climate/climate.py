import voluptuous as vol
import logging
import os
import sys
import select
import http.client
import time

"""Daikin SkyFi Climate"""
from homeassistant.components.climate import PLATFORM_SCHEMA

from homeassistant.components.climate import ClimateDevice
from homeassistant.components.climate.const import (
    ATTR_TARGET_TEMP_HIGH, 
    ATTR_TARGET_TEMP_LOW, 
    CURRENT_HVAC_COOL,
    CURRENT_HVAC_HEAT, 
    HVAC_MODE_DRY,
    HVAC_MODE_FAN_ONLY,
    HVAC_MODE_COOL, 
    HVAC_MODE_HEAT,
    HVAC_MODE_HEAT_COOL, 
    HVAC_MODE_OFF, 
    HVAC_MODES, 
    SUPPORT_FAN_MODE, 
    SUPPORT_TARGET_TEMPERATURE,
    SUPPORT_TARGET_TEMPERATURE_RANGE, 
    HVAC_MODE_AUTO)
from homeassistant.const import ATTR_TEMPERATURE, TEMP_CELSIUS, CONF_HOST, CONF_PASSWORD
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

SUPPORT_FLAGS = 0
CONF_OUTSIDE_TEMPERATURE = 'outside_temperature'


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
    vol.Optional(CONF_OUTSIDE_TEMPERATURE): vol.Coerce(float),
})



HA_STATE_TO_DAIKIN = {
    HVAC_MODE_FAN_ONLY: 'fan',
    HVAC_MODE_DRY: 'dry',
    HVAC_MODE_COOL: 'cool',
    HVAC_MODE_HEAT: 'heat',
    HVAC_MODE_HEAT_COOL: 'auto',
    HVAC_MODE_OFF: 'off',
}

DAIKIN_TO_HA_STATE = {
    'fan': HVAC_MODE_FAN_ONLY,
    'dry': HVAC_MODE_DRY,
    'cool': HVAC_MODE_COOL,
    'heat': HVAC_MODE_HEAT,
    'auto': HVAC_MODE_HEAT_COOL,
    'off': HVAC_MODE_OFF,
}


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the Daikin Skifi climate devices."""
    
    host = config.get(CONF_HOST)
    password = config.get(CONF_PASSWORD)
    outside_temperature = config.get(CONF_OUTSIDE_TEMPERATURE)
    
    add_entities([
        DaikinSkyFiClimate(
            name='Daikin', 
            target_temperature=20,
            unit_of_measurement=TEMP_CELSIUS, 
            host = host, 
            password = password,
            current_temperature=22,
            fan_mode='Low',
            hvac_mode=HVAC_MODE_COOL,
            hvac_action=None, #CURRENT_HVAC_COOL,
            target_temp_high=None,
            target_temp_low=None,
            outside_temperature=20,
            hvac_modes=[mode for mode in HVAC_MODES 
                        if mode != HVAC_MODE_HEAT_COOL]
        )
    ])


class DaikinSkyFiClimate(ClimateDevice):
    """Representation of a Daikin SkyFi climate device."""

    def __init__(
            self,
            name,
            target_temperature,
            unit_of_measurement,
            host,
            password,
            current_temperature,
            fan_mode,
            hvac_mode,
            hvac_action,
            target_temp_high,
            target_temp_low,
            hvac_modes,
            outside_temperature
    ):
        
        
        """Initialize the climate device."""
        self._name = name
        self._host = host
        self._password = password
        self._support_flags = SUPPORT_FLAGS
        if target_temperature is not None:
            self._support_flags = self._support_flags | SUPPORT_TARGET_TEMPERATURE
        if fan_mode is not None:
            self._support_flags = self._support_flags | SUPPORT_FAN_MODE
        if hvac_action is not None:
            self._support_flags = self._support_flags
        if (HVAC_MODE_HEAT_COOL in hvac_modes or HVAC_MODE_AUTO in hvac_modes):
            self._support_flags = self._support_flags | SUPPORT_TARGET_TEMPERATURE_RANGE
        self._target_temperature = target_temperature
        self._unit_of_measurement = unit_of_measurement
        self._outside_temperature = outside_temperature
        self._current_temperature = current_temperature
        self._current_fan_mode = fan_mode
        self._hvac_action = hvac_action
        self._hvac_mode = hvac_mode
        self._fan_mode = fan_mode
        self._fan_modes = ['Low', 'Medium', 'High']
        self._hvac_modes = ['off', 'auto', 'heat', 'dry', 'cool', 'fan_only']
        self._target_temperature_high = target_temp_high
        self._target_temperature_low = target_temp_low
        
    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._support_flags

    @property
    def should_poll(self):
        """Return the polling state."""
        return True
    
    def update(self):
        
        payload = "/ac.cgi?pass={}".format(self._password)
        data = self.doQuery(payload)
        
        plist = {}
        
        lst = data.split("&")
        for x in lst:
            v = x.split("=")
            plist[v[0]] = v[1]
            _LOGGER.warning("decode {} tried {}:".format(x, v))
            
        self._current_temperature = float(plist['roomtemp'])
        self._target_temperature = float(plist['settemp'])
        self._outside_temperature = float(plist['outsidetemp'])
        
        if int(plist['opmode']) == 0: #OFF
            self._hvac_mode = HA_STATE_TO_DAIKIN[HVAC_MODE_OFF]
        else:
            if int(plist['acmode']) == 1:
                self._hvac_mode = HA_STATE_TO_DAIKIN[HVAC_MODE_HEAT_COOL]
            elif int(plist['acmode']) == 2:
                self._hvac_mode = HA_STATE_TO_DAIKIN[HVAC_MODE_HEAT]
            elif int(plist['acmode']) == 4:
                self._hvac_mode = HA_STATE_TO_DAIKIN[HVAC_MODE_DRY]
            elif int(plist['acmode']) == 8:
                self._hvac_mode = HA_STATE_TO_DAIKIN[HVAC_MODE_COOL]
            elif int(plist['acmode']) == 16:
                self._hvac_mode = HA_STATE_TO_DAIKIN[HVAC_MODE_FAN_ONLY]
            else:
                self._hvac_mode = HA_STATE_TO_DAIKIN[HVAC_MODE_OFF] #turn off if some wierd variable is entered for acmode...
        
        self._fan_mode = self._fan_modes[int(plist["fanspeed"]) - 1]
        
    def doQuery(self, payload):
        """send query to SkyFi"""
        retry_count = 5
        while retry_count > 0:
            retry_count = retry_count - 1
            try:
                conn = http.client.HTTPConnection(self._host, 2000)
                conn.request("GET", payload)
                resp = conn.getresponse()
                data = resp.read().decode()
                conn.close()
                retry_count = 0
            except Exception as ex:
                if retry_count == 0:
                    _LOGGER.warning("Query: {} failed {}: {}".format(self._name, payload, ex))
                conn.close()
                time.sleep(2)
        return data
        
     
    @property
    def name(self):
        """Return the name of the climate device."""
        return self._name

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @property
    def outside_temperature(self):
        """Return the outside temperature."""
        return self._outside_temperature
    
    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._current_temperature

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temperature

    @property
    def target_temperature_high(self):
        """Return the highbound target temperature we try to reach."""
        return self._target_temperature_high

    @property
    def target_temperature_low(self):
        """Return the lowbound target temperature we try to reach."""
        return self._target_temperature_low

    @property
    def hvac_action(self):
        """Return current operation ie. heat, cool, idle."""
        return self._hvac_action

    @property
    def hvac_mode(self):
        """Return hvac target hvac state."""
        return self._hvac_mode

    @property
    def hvac_modes(self):
        """Return the list of available operation modes."""
        return self._hvac_modes

    @property
    def fan_mode(self):
        """Return the fan setting."""
        return self._current_fan_mode

    @property
    def fan_modes(self):
        """Return the list of available fan modes."""
        return self._fan_modes

    def set_temperature(self, **kwargs):
        """Set new target temperatures."""
        if kwargs.get(ATTR_TEMPERATURE) is not None:
            #_LOGGER.warning("ATTR_teemp {}".format(kwargs.get(ATTR_TEMPERATURE)))
            
        # if kwargs.get(ATTR_TARGET_TEMP_HIGH) is not None and \
        #   kwargs.get(ATTR_TARGET_TEMP_LOW) is not None:
        #     self._target_temperature_high = kwargs.get(ATTR_TARGET_TEMP_HIGH)
        #     self._target_temperature_low = kwargs.get(ATTR_TARGET_TEMP_LOW)
        
            self._target_temperature = kwargs.get(ATTR_TEMPERATURE) #kwargs.get(ATTR_TEMPERATURE)
        
        payload = "/set.cgi?pass={}&t={:.5f}".format(self._password, kwargs.get(ATTR_TEMPERATURE))
        
        self.doQuery(payload)
        
        self.async_write_ha_state()

    def set_fan_mode(self, fan_mode):
        """Set new fan mode."""
        
        if fan_mode == 'Low':
            fan = 1
        elif fan_mode == 'Medium':
            fan = 2
        elif fan_mode == 'High':
            fan = 3
        
        self._current_fan_mode = fan_mode
        
        payload = "/set.cgi?pass={}&f={}".format(self._password, fan)
        
        self.doQuery(payload)
        
        self.async_write_ha_state()
        
        

    async def async_set_hvac_mode(self, hvac_mode):
        
        """Set new operation mode."""
        
        if hvac_mode == 'auto':
            mode = 1
            pstate = 1
        elif hvac_mode == 'heat':
            mode = 2
            pstate = 1
        elif hvac_mode == 'dry':
            mode = 4
            pstate = 1
        elif hvac_mode == 'cool':
            mode = 8
            pstate = 1
        elif hvac_mode == 'fan_only':
            mode = 16
            pstate = 1
        elif hvac_mode == 'off':
            mode = 1
            pstate = 0
        else:
            mode = 1
            pstate = 0
        
        self._hvac_mode = hvac_mode
        
        payload = "/set.cgi?pass={}&p={}&m={}".format(self._password, pstate, mode)
        
        self.doQuery(payload)
        
        self.async_write_ha_state()
        