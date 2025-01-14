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
import sys
from pathlib import PurePosixPath
from typing import Any

import gmqtt
import yaml
from bme280 import BME280
from getmac import get_mac_address
from ltr559 import LTR559
from typing_extensions import TypeAlias

from .data import (
    DEFAULT_SENSORS,
    PMS5003_SENSORS,
    check_wifi,
    get_current_data,
    get_serial_number,
    setup_pms5003,
    setup_sensors,
)
from .mqtt import MQTTConf, get_mqtt_client, setup_mqtt_config

log = logging.getLogger(__name__)


# TODO: Should be higher but I'm impatient during testing
# WARMUP_TIME = timedelta(minutes=2).total_seconds()
WARMUP_TIME = 10


def _load_config() -> dict[str, Any]:
    with open("configuration.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)  # type: ignore


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        # level=logging.DEBUG,
        format="%(asctime)s %(name)-16s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )
    STOP = asyncio.Event()

    loop = asyncio.get_event_loop()

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

    main_task = loop.create_task(_main(loop, mqtt_conf, device_serial_number))

    def _stop(*args: Any) -> None:
        log.error("Interrupt!")
        if STOP.is_set():
            log.critical("Killed!")
            sys.exit(1)
        STOP.set()
        main_task.cancel()

    loop.add_signal_handler(signal.SIGINT, _stop)
    loop.add_signal_handler(signal.SIGTERM, _stop)

    try:
        loop.run_until_complete(main_task)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    loop.stop()


# It'd probably make my life easier to type these but I'm lazy
HADiscoveryDevice: TypeAlias = dict[str, Any]
HADiscoveryPacket: TypeAlias = dict[str, Any]


def _do_discovery(
    mqtt_conf: MQTTConf,
    mqtt_client: gmqtt.Client,
    serial: str,
    has_pms5003: bool,
) -> None:
    if not mqtt_conf["discovery"]:
        return

    data: HADiscoveryPacket
    device: HADiscoveryDevice | None = None

    if mqtt_conf["discovery_device"]:
        device = {
            "ids": serial,
            "mdl": "Enviro+ MQTT",
            "mf": "Lexi Robinson",
            "name": mqtt_conf["discovery_device_name"],
        }
        mac = get_mac_address()
        if mac:
            device["connections"] = [["mac", mac]]

    config_topic = PurePosixPath(mqtt_conf["discovery_prefix"], "sensor")
    state_topic = str(PurePosixPath(mqtt_conf["topic_prefix"], serial))

    log.info("Publishing HA discovery to %s", config_topic)

    for name, sensor in DEFAULT_SENSORS.items():
        data = {
            **sensor,
            "uniq_id": serial + "_" + name,
            "stat_t": state_topic,
        }
        if device:
            data["dev"] = device

        mqtt_client.publish(
            str(config_topic / data["uniq_id"] / "config"),
            data,
            qos=1,
            retain=mqtt_conf["discovery_retain"],
            content_type="application/json",
        )

    if not has_pms5003:
        return

    for name, sensor in PMS5003_SENSORS.items():
        data = {
            **sensor,
            "uniq_id": serial + "_" + name,
            "stat_t": state_topic,
        }
        if device:
            data["dev"] = device

        mqtt_client.publish(
            str(config_topic / data["uniq_id"] / "config"),
            data,
            qos=1,
            retain=mqtt_conf["discovery_retain"],
            content_type="application/json",
        )


async def _main(
    loop: asyncio.AbstractEventLoop,
    mqtt_conf: MQTTConf,
    serial: str,
) -> None:
    client_t = loop.create_task(get_mqtt_client(mqtt_conf))
    pms5003_setup_t = loop.create_task(setup_pms5003(loop))

    bme280, ltr559 = await loop.run_in_executor(None, setup_sensors)
    pms5003_t = await pms5003_setup_t

    logging.info("Waiting for sensors to warm up")
    await asyncio.wait(
        [
            client_t,
            asyncio.create_task(asyncio.sleep(WARMUP_TIME)),
        ],
        timeout=WARMUP_TIME,
        return_when=asyncio.FIRST_EXCEPTION,
    )

    if client_t.done():
        mqtt_client = await client_t
    else:
        logging.info("Sensors are warm, waiting for MQTT client to connect")
        # TODO: Remove timeout, for production we want this to wait indefinitely
        # in case the MQTT server is taking a while to start
        try:
            mqtt_client = await asyncio.wait_for(client_t, timeout=10)
        except asyncio.TimeoutError:
            log.exception("Timed out waiting for the MQTT client to connect")
            raise

    _do_discovery(mqtt_conf, mqtt_client, serial, pms5003_t is not None)

    mqtt_client = await client_t
    logging.info("Sensors are warm, going live")

    try:
        await _main_loop(
            mqtt_conf,
            serial,
            mqtt_client,
            bme280,
            ltr559,
        )
    except asyncio.CancelledError:
        if pms5003_t:
            pms5003_t.cancel()
        try:
            await asyncio.wait_for(mqtt_client.disconnect(), timeout=2)
        except asyncio.TimeoutError:
            log.error("Timed out trying to disconnect")


async def _main_loop(
    mqtt_conf: MQTTConf,
    serial: str,
    mqtt_client: gmqtt.Client,
    bme280: BME280,
    ltr559: LTR559,
) -> None:
    log.info("It's looping time")
    topic = mqtt_conf["topic_prefix"] + "/" + serial

    # Main loop to read data, display, and send over mqtt
    while True:
        try:
            values = get_current_data(ltr559, bme280)
            mqtt_client.publish(
                topic,
                values,
                qos=mqtt_conf["qos"],
                retain=mqtt_conf["retain"],
                content_type="application/json",
            )
            await asyncio.sleep(mqtt_conf["publish_interval"])
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Error getting data")


main()
