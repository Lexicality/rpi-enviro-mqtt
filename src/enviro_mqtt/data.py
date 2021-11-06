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
from typing import Optional, Tuple

from bme280 import BME280
from enviroplus import gas
from ltr559 import LTR559
from pms5003 import (
    PMS5003,
    ChecksumMismatchError as PMS5003ChecksumError,
    ReadTimeoutError as PMS5003ReadTimeoutError,
    SerialTimeoutError as PMS5003SerialTimeoutError,
)

log = logging.getLogger(__name__)

BME280Result = dict  # TODO
PMS5003Result = dict  # TODO
GasResult = dict  # TODO


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


def read_ltr559(ltr559: LTR559) -> int:
    return int(ltr559.get_lux())


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
        "temperature": int(comp_temp),
        "pressure": round(int(bme280.get_pressure() * 100), -1),  # round to nearest 10
        "humidity": int(bme280.get_humidity()),
    }


def read_gas() -> GasResult:
    data = gas.read_all()
    return {
        "oxidised": int(data.oxidising / 1000),
        "reduced": int(data.reducing / 1000),
    }


_pms5003_data: Optional[PMS5003Result] = None


def _read_pms5003(pms5003: PMS5003, no_retries=False) -> Optional[PMS5003Result]:
    while True:
        try:
            pm_values = pms5003.read()
            return {
                "pm1": pm_values.pm_ug_per_m3(1),
                "pm25": pm_values.pm_ug_per_m3(2.5),
                "pm10": pm_values.pm_ug_per_m3(10),
            }
        except (PMS5003ReadTimeoutError):
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
    data = {
        **read_bme280(bme280),
        **read_gas(),
        "lux": read_ltr559(ltr559),
    }
    pms_data = read_pms5003()
    if pms_data:
        data.update(pms_data)
    return data
