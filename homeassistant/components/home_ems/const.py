"""Constants for the Home Energy Management System integration."""

DOMAIN = "home_ems"

# Configuration keys
CONF_DEVICE_TYPE = "device_type"
CONF_TARGET_DEVICE = "target_device"
CONF_PRICE_ENTITY = "price_entity"
CONF_TARGET_TIME = "target_time"
CONF_MIN_TEMPERATURE = "min_temperature"
CONF_MAX_TEMPERATURE = "max_temperature"
CONF_HEATING_DURATION = "heating_duration"
CONF_UPDATE_TIME = "update_time"
CONF_TEMPERATURE_SENSOR = "temperature_sensor"
CONF_MIN_SHOWER_TEMPERATURE = "min_shower_temperature"

# Device types
DEVICE_TYPE_WATER_HEATER = "water_heater"
DEVICE_TYPE_CLIMATE = "climate"

# Default values
DEFAULT_MIN_TEMPERATURE = 45
DEFAULT_MAX_TEMPERATURE = 60
DEFAULT_HEATING_DURATION = 2  # hours
DEFAULT_UPDATE_TIME = "14:00"
DEFAULT_TARGET_TIME = "07:00"
DEFAULT_MIN_SHOWER_TEMPERATURE = 45

# Thermal efficiency constants
DEFAULT_COOLING_RATE = 1.0  # °C per hour for well-insulated tank
DEFAULT_HEATING_RATE = 20.0  # °C per hour (will be learned from device)
DEFAULT_ENERGY_PER_DEGREE = 0.5  # kWh per °C for typical 200L tank
DEFAULT_BASE_ENERGY = 10.0  # kWh to heat full tank (typical value)
DEFAULT_MAX_GAP_MINUTES = 120  # Maximum gap between heating periods

# Learning parameters
MIN_HEATING_OBSERVATIONS = 3  # Minimum observations to calculate heating rate
MIN_COOLING_OBSERVATIONS = 5  # Minimum observations to calculate cooling rate
