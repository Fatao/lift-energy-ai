"""Starts the live data sources that are configured through environment variables."""
from .. import config
from . import status


def start_all():
    handles = []
    if config.MQTT_URL:
        from . import mqtt_client

        handles.append(mqtt_client.start(config.MQTT_URL, config.MQTT_TOPIC, config.MQTT_USER, config.MQTT_PASSWORD))
    if config.MODBUS_PORT:
        from . import modbus_rtu

        handles.append(
            modbus_rtu.start(
                config.MODBUS_PORT, config.modbus_units(), config.modbus_regmap(),
                config.MODBUS_BAUD, config.MODBUS_PARITY, config.MODBUS_STOPBITS,
                config.MODBUS_POLL_SECONDS, config.MODBUS_WORD_ORDER,
            )
        )
    return handles


def stop_all(handles):
    for h in handles:
        if hasattr(h, "loop_stop"):
            h.loop_stop()
            h.disconnect()
        elif hasattr(h, "set"):
            h.set()


def sources():
    return status.snapshot()
