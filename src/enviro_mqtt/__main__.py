#!/usr/bin/env python3
"""
   Copyright 2020 Robin Cole

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.

Run mqtt broker on localhost: sudo apt-get install mosquitto mosquitto-clients

Example run: python3 mqtt-all.py --broker 192.168.1.164 --topic enviro
"""

import argparse
import asyncio
import json
import signal

from bme280 import BME280
from ltr559 import LTR559
from smbus2 import SMBus

from .data import (
    check_wifi,
    get_serial_number,
    read_bme280,
    read_gas,
    read_ltr559,
    read_pms5003,
    run_pms5003,
)
from .mqtt import MQTTConf, get_mqtt_client, setup_mqtt_config

DEFAULT_MQTT_BROKER_IP = "localhost"
DEFAULT_MQTT_BROKER_PORT = 1883
DEFAULT_MQTT_TOPIC = "enviroplus"
DEFAULT_READ_INTERVAL = 5


def _on_signal(STOP: asyncio.Event, *args):
    STOP.set()


def main():
    parser = argparse.ArgumentParser(description="Publish enviroplus values over mqtt")
    parser.add_argument(
        "--broker",
        default=DEFAULT_MQTT_BROKER_IP,
        type=str,
        help="mqtt broker IP",
    )
    parser.add_argument(
        "--port",
        default=DEFAULT_MQTT_BROKER_PORT,
        type=int,
        help="mqtt broker port",
    )
    parser.add_argument(
        "--topic", default=DEFAULT_MQTT_TOPIC, type=str, help="mqtt topic"
    )
    parser.add_argument(
        "--interval",
        default=DEFAULT_READ_INTERVAL,
        type=int,
        help="the read interval in seconds",
    )
    args = parser.parse_args()

    STOP = asyncio.Event()

    loop = asyncio.get_event_loop()

    loop.add_signal_handler(signal.SIGINT, _on_signal, STOP)
    loop.add_signal_handler(signal.SIGTERM, _on_signal, STOP)

    # Raspberry Pi ID
    device_serial_number = get_serial_number()
    device_id = "raspi-" + device_serial_number

    print(
        f"""mqtt-all.py - Reads Enviro plus data and sends over mqtt.

    broker: {args.broker}
    client_id: {device_id}
    port: {args.port}
    topic: {args.topic}

    Press Ctrl+C to exit!

    """
    )

    mqtt_conf = setup_mqtt_config(
        {
            "broker": args.broker,
            "port": args.port,
            "client_id": device_id,
            "topic_prefix": args.topic,
        }
    )

    # Create LCD instance

    # Display Raspberry Pi serial and Wi-Fi status
    print("RPi serial: {}".format(device_serial_number))
    print("Wi-Fi: {}\n".format("connected" if check_wifi() else "disconnected"))
    print("MQTT broker IP: {}".format(args.broker))

    loop.call_soon(run_pms5003, loop, STOP)
    loop.run_until_complete(_main_loop(mqtt_conf, STOP))
    loop.stop()


async def _main_loop(mqtt_conf: MQTTConf, interval: int, STOP: asyncio.Event) -> None:
    mqtt_client = await get_mqtt_client(mqtt_conf)

    bus = SMBus(1)

    ltr559 = LTR559()

    # Create BME280 instance
    bme280 = BME280(i2c_dev=bus)

    # Main loop to read data, display, and send over mqtt
    while True:
        try:
            values = read_bme280(bme280)
            values["lux"] = read_ltr559(ltr559)
            values.update(read_gas())
            pms_values = read_pms5003()
            if pms_values:
                values.update(pms_values)
            print(values)
            mqtt_client.publish(mqtt_conf["topic_prefix"], json.dumps(values))
            await asyncio.sleep(interval)
            if STOP.is_set():
                break
        except Exception as e:
            print(e)

    await mqtt_client.disconnect()


main()
