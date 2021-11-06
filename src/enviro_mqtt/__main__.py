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

from __future__ import annotations

import asyncio
import logging
import signal

import yaml
from bme280 import BME280
from ltr559 import LTR559

from .data import check_wifi, get_current_data, get_serial_number, run_pms5003
from .mqtt import MQTTConf, get_mqtt_client, setup_mqtt_config

log = logging.getLogger(__name__)


def _on_signal(STOP: asyncio.Event, *args):
    log.warning("SIGINT!")
    STOP.set()


def _load_config() -> dict:
    with open("configuration.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    logging.basicConfig(
        level=logging.INFO,
        # level=logging.DEBUG,
        format="%(asctime)s %(name)-16s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )
    STOP = asyncio.Event()

    loop = asyncio.get_event_loop()

    loop.add_signal_handler(signal.SIGINT, _on_signal, STOP)
    loop.add_signal_handler(signal.SIGTERM, _on_signal, STOP)

    # Raspberry Pi ID
    device_serial_number = get_serial_number()
    device_id = "raspi-" + device_serial_number

    conf = _load_config()
    raw_mqtt_conf = conf.get("mqtt", {})
    raw_mqtt_conf.setdefault("client_id", device_id)
    mqtt_conf = setup_mqtt_config(raw_mqtt_conf)

    print(
        f"""mqtt-all.py - Reads Enviro plus data and sends over mqtt.

    broker: {mqtt_conf["broker"]}
    client_id: {mqtt_conf["client_id"]}
    port: {mqtt_conf["port"]}
    topic: {mqtt_conf["topic_prefix"]}

    Press Ctrl+C to exit!

    """
    )

    # Display Raspberry Pi serial and Wi-Fi status
    print("RPi serial: {}".format(device_serial_number))
    print("Wi-Fi: {}\n".format("connected" if check_wifi() else "disconnected"))
    print("MQTT broker IP: {}".format(mqtt_conf["broker"]))

    pms5003_task = loop.create_task(run_pms5003(loop, STOP))

    loop.run_until_complete(_main_loop(loop, mqtt_conf, device_serial_number, STOP))

    pms5003_task.cancel()
    loop.stop()


async def _main_loop(
    loop: asyncio.AbstractEventLoop,
    mqtt_conf: MQTTConf,
    serial: str,
    STOP: asyncio.Event,
) -> None:
    mqtt_client = await get_mqtt_client(mqtt_conf)

    ltr559 = LTR559()
    bme280 = BME280()

    stop_waiter = loop.create_task(STOP.wait())

    log.info("It's looping time")
    topic = mqtt_conf["topic_prefix"] + "/" + serial

    # Main loop to read data, display, and send over mqtt
    while True:
        try:
            values = get_current_data(ltr559, bme280)
            print(values)
            mqtt_client.publish(
                topic,
                values,
                qos=mqtt_conf["qos"],
                retain=mqtt_conf["retain"],
                content_type="application/json",
            )
            await asyncio.wait(
                {asyncio.sleep(mqtt_conf["publish_interval"]), stop_waiter},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if STOP.is_set():
                log.info("Stopping!")
                break
        except Exception:
            log.exception("Error getting data")

    await mqtt_client.disconnect()


main()
