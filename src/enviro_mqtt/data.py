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

import asyncio
import logging
import subprocess
from typing import Any, Dict, Optional, Tuple

from bme280 import BME280
from enviroplus import gas
from ltr559 import LTR559
from pms5003 import (
    PMS5003,
    ChecksumMismatchError as PMS5003ChecksumError,
    ReadTimeoutError as PMS5003ReadTimeoutError,
    SerialTimeoutError as PMS5003SerialTimeoutError,
)
from typing_extensions import TypedDict

log = logging.getLogger(__name__)


class BME280Result(TypedDict):
    temperature: float
    pressure: float
    humidity: float


class PMS5003Result(TypedDict):
    pm1: int
    pm25: int
    pm10: int
    pl03: int
    pl05: int
    pl1: int
    pl25: int
    pl5: int
    pl10: int


class GasResult(TypedDict):
    oxidising: float
    reducing: float
    nh3: float


DEFAULT_SENSORS = {
    "lux": {
        "dev_cla": "illuminance",
        "name": "Brightness",
        "unit_of_meas": "lx",
        "val_tpl": "{{ value_json.lux }}",
    },
    "temp": {
        "dev_cla": "temperature",
        "name": "Temperature",
        "unit_of_meas": "°C",
        "val_tpl": "{{ value_json.temperature }}",
    },
    "humidity": {
        "dev_cla": "humidity",
        "name": "Humidity",
        "unit_of_meas": "%",
        "val_tpl": "{{ value_json.humidity }}",
    },
    "pressure": {
        "dev_cla": "pressure",
        "name": "Pressure",
        "unit_of_meas": "hPa",
        "val_tpl": "{{ value_json.pressure }}",
    },
    "oxidising": {
        "name": "Oxidising Gas",
        "unit_of_meas": "kΩ",
        "val_tpl": "{{ value_json.oxidising }}",
    },
    "reducing": {
        "name": "Reducing Gas",
        "unit_of_meas": "kΩ",
        "val_tpl": "{{ value_json.reducing }}",
    },
    "nh3": {
        "name": "Ammonia Gas",
        "unit_of_meas": "kΩ",
        "val_tpl": "{{ value_json.nh3 }}",
    },
}
PMS5003_SENSORS = {
    "pm1": {
        "dev_cla": "pm1",
        "name": "PM1",
        "unit_of_meas": "µg/m³",
        "val_tpl": "{{ value_json.pm1 }}",
    },
    "pm25": {
        "dev_cla": "pm25",
        "name": "PM2.5",
        "unit_of_meas": "µg/m³",
        "val_tpl": "{{ value_json.pm25 }}",
    },
    "pm10": {
        "dev_cla": "pm10",
        "name": "PM10",
        "unit_of_meas": "µg/m³",
        "val_tpl": "{{ value_json.pm10 }}",
    },
    "pl03": {
        "name": "Particles >0.3um",
        "unit_of_meas": "#/0.1L",
        "val_tpl": "{{ value_json.pl03 }}",
    },
    "pl05": {
        "name": "Particles >0.5um",
        "unit_of_meas": "#/0.1L",
        "val_tpl": "{{ value_json.pl05 }}",
    },
    "pl1": {
        "name": "Particles >1um",
        "unit_of_meas": "#/0.1L",
        "val_tpl": "{{ value_json.pl1 }}",
    },
    "pl25": {
        "name": "Particles >2.5um",
        "unit_of_meas": "#/0.1L",
        "val_tpl": "{{ value_json.pl25 }}",
    },
    "pl5": {
        "name": "Particles >5um",
        "unit_of_meas": "#/0.1L",
        "val_tpl": "{{ value_json.pl5 }}",
    },
    "pl10": {
        "name": "Particles >10um",
        "unit_of_meas": "#/0.1L",
        "val_tpl": "{{ value_json.pl10 }}",
    },
}


def setup_sensors() -> Tuple[BME280, LTR559]:
    logging.info("Setting up the ADS1015")
    gas.setup()
    gas.read_all()
    logging.info("Setting up the BME280")
    bme280 = BME280()
    bme280.setup()
    bme280.update_sensor()
    logging.info("Setting up the LTR559")
    ltr559 = LTR559()
    ltr559.update_sensor()
    return bme280, ltr559


def read_ltr559(ltr559: LTR559) -> float:
    return round(ltr559.get_lux(), 2)


# Get CPU temperature to use for compensation
def get_cpu_temperature() -> float:
    result = subprocess.run(
        ["vcgencmd", "measure_temp"],
        capture_output=True,
        text=True,
        encoding="UTF-8",
    )
    output = result.stdout
    return float(output[output.index("=") + 1 : output.rindex("'")])


# Read values from BME280 and return as dict
def read_bme280(bme280: BME280) -> BME280Result:
    # Compensation factor for temperature
    comp_factor = 2.25
    cpu_temp = get_cpu_temperature()
    raw_temp = bme280.get_temperature()  # float
    comp_temp = raw_temp - ((cpu_temp - raw_temp) / comp_factor)
    return {
        "temperature": round(comp_temp, 2),
        "pressure": round(bme280.get_pressure(), 2),
        "humidity": round(bme280.get_humidity(), 1),
    }


def read_gas() -> GasResult:
    data = gas.read_all()
    return {
        "oxidising": round(data.oxidising / 1000, 4),
        "reducing": round(data.reducing / 1000, 4),
        "nh3": round(data.nh3 / 1000, 4),
    }


_pms5003_data: Optional[PMS5003Result] = None


def _read_pms5003(pms5003: PMS5003, no_retries=False) -> Optional[PMS5003Result]:
    while True:
        try:
            pm_values = pms5003.read()
            log.debug("PMS5003: %s", str(pm_values))
            return {
                "pm1": pm_values.pm_ug_per_m3(1),
                "pm25": pm_values.pm_ug_per_m3(2.5),
                "pm10": pm_values.pm_ug_per_m3(10),
                "pl03": pm_values.pm_per_1l_air(0.3),
                "pl05": pm_values.pm_per_1l_air(0.5),
                "pl1": pm_values.pm_per_1l_air(1),
                "pl25": pm_values.pm_per_1l_air(2.5),
                "pl5": pm_values.pm_per_1l_air(5),
                "pl10": pm_values.pm_per_1l_air(10),
            }
        except PMS5003ReadTimeoutError:
            log.debug("Timed out :(")
            continue
        except (PMS5003SerialTimeoutError, PMS5003ChecksumError):
            if no_retries:
                return None
            log.exception("Fatal(ish) error reading from PMS5003")
            pms5003.reset()
            continue


async def _run_pms5003(loop: asyncio.AbstractEventLoop, pms5003: PMS5003) -> None:
    global _pms5003_data
    while True:
        _pms5003_data = await loop.run_in_executor(None, _read_pms5003, pms5003, True)


async def setup_pms5003(loop: asyncio.AbstractEventLoop) -> Optional[asyncio.Task]:
    pms5003 = await loop.run_in_executor(None, lambda: PMS5003())
    global _pms5003_data
    _pms5003_data = await loop.run_in_executor(None, _read_pms5003, pms5003, True)

    if _pms5003_data is None:
        log.info("No PMS5003 detected!")
        return None

    log.info("PMS5003 found!")

    return loop.create_task(_run_pms5003(loop, pms5003))


# Read values PMS5003 and return as dict
def read_pms5003() -> Optional[PMS5003Result]:
    return _pms5003_data


# Get Raspberry Pi serial number to use as ID
def get_serial_number() -> str:
    with open("/proc/cpuinfo", "r") as f:
        for line in f:
            if line[0:6] == "Serial":
                return line.split(":")[1].strip()

    return "0000000000000000"


# Check for Wi-Fi connection
def check_wifi() -> bool:
    return bool(subprocess.check_output(["hostname", "-I"]))


def get_current_data(ltr559: LTR559, bme280: BME280) -> dict:
    data: Dict[str, Any] = {
        **read_bme280(bme280),
        **read_gas(),
        "lux": read_ltr559(ltr559),
    }
    pms_data = read_pms5003()
    if pms_data:
        data.update(pms_data)
    return data
