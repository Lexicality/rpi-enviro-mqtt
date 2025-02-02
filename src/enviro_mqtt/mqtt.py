"""
   Copyright 2021 Lexi Robinson

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
"""
from __future__ import annotations

import logging
from typing import Any, cast

from gmqtt import Client as MQTTClient
from typing_extensions import TypedDict

log = logging.getLogger(__name__)


class MQTTConf(TypedDict):
    broker: str
    port: int
    client_id: str | None
    discovery: bool
    discovery_retain: bool
    discovery_prefix: str
    discovery_device: bool
    discovery_device_name: str
    topic_prefix: str
    username: str | None
    password: str | None
    publish_interval: int
    retain: bool
    qos: int


class MQTTConfInput(MQTTConf, total=False):
    ...


DEFAULT_MQTT_CONFIG: MQTTConf = {
    "broker": "",
    "port": 1883,
    "client_id": None,
    "discovery": True,
    "discovery_retain": True,
    "discovery_prefix": "homeassistant",
    "discovery_device": True,
    "discovery_device_name": "Mystery Pi",
    "topic_prefix": "enviroplus",
    "username": None,
    "password": None,
    "publish_interval": 60,
    "retain": True,
    "qos": 0,
}


def on_connect(
    client: MQTTClient,
    flags: int,
    rc: int,
    properties: dict[Any, Any],  # TODO - I have no idea what's in this dict
) -> None:
    log.info("Connected with flags %X and rc %X!", flags, rc)


def on_disconnect(client: MQTTClient, packet: bytes) -> None:
    log.warning(
        "Disconnected with packet %s!",
        packet.decode("utf-8", errors="replace"),
    )


def setup_mqtt_config(raw_config: MQTTConfInput) -> MQTTConf:
    mqtt_conf = cast(MQTTConf, {**DEFAULT_MQTT_CONFIG, **raw_config})

    if not mqtt_conf["broker"]:
        raise ValueError("Broker not configured!")

    return mqtt_conf


async def get_mqtt_client(mqtt_conf: MQTTConf) -> MQTTClient:
    client = MQTTClient(mqtt_conf["client_id"])
    if mqtt_conf["username"] is not None:
        client.set_auth_credentials(mqtt_conf["username"], mqtt_conf["password"])

    # wip
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    log.info("Connecting to %s:%d", mqtt_conf["broker"], mqtt_conf["port"])

    await client.connect(mqtt_conf["broker"], mqtt_conf["port"])

    return client
