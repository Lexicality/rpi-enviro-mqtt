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

import subprocess

from bme280 import BME280
from enviroplus import gas
from ltr559 import LTR559
from pms5003 import PMS5003, ReadTimeoutError

BME280Result = dict  # TODO
PMS5003Result = dict  # TODO
GasResult = dict  # TODO


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


# Read values PMS5003 and return as dict
def read_pms5003(pms5003: PMS5003, retry=True) -> PMS5003Result:
    try:
        pm_values = pms5003.read()  # int
        return {
            "pm1": pm_values.pm_ug_per_m3(1),
            "pm25": pm_values.pm_ug_per_m3(2.5),
            "pm10": pm_values.pm_ug_per_m3(10),
        }
    except ReadTimeoutError:
        if retry:
            return read_pms5003(pms5003, retry=False)
        raise


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
