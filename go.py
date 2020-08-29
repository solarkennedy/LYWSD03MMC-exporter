#!/usr/bin/env python3
from bluepy import btle
import argparse
import os
import re
from dataclasses import dataclass
from collections import deque
import threading
import time
import signal
import traceback
import math
import logging

from collections import namedtuple

import sys
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL")
registry = CollectorRegistry()

logging.basicConfig(level=logging.DEBUG)


class MyDelegate(btle.DefaultDelegate):
    def __init__(self, label):
        self.label = label
        btle.DefaultDelegate.__init__(self)
        try:
            self.temperature = Gauge(
                "temperature_fahrenheit",
                "Temperature, fahrenheit",
                registry=registry,
                labelnames=("sensor_name",),
            )
            self.humidity = Gauge(
                "humidity_pct",
                "Humidity, percentage",
                registry=registry,
                labelnames=("sensor_name",),
            )
            self.battery_voltage = Gauge(
                "battery_voltage",
                "Battery, voltage",
                registry=registry,
                labelnames=("sensor_name",),
            )
            self.battery_level = Gauge(
                "battery_level",
                "Battery, level",
                registry=registry,
                labelnames=("sensor_name",),
            )
        except ValueError:
            pass

    def handleNotification(self, cHandle, data):
        try:
            temp = round(
                (int.from_bytes(data[0:2], byteorder="little", signed=True) / 100) * 1.8
                + 32,
                3,
            )
            print(f"Temperature: {temp}")
            # self.temperature.set_to_current_time()
            self.temperature.labels(sensor_name=self.label).set(temp)

            humidity = int.from_bytes(data[2:3], byteorder="little")
            print(f"Humidity: {humidity}")
            self.humidity.labels(sensor_name=self.label).set(humidity)

            voltage = int.from_bytes(data[3:5], byteorder="little") / 1000.0
            print(f"Battery voltage: {voltage}")
            self.battery_voltage.labels(sensor_name=self.label).set(voltage)

            batteryLevel = min(
                int(round((voltage - 2.1), 2) * 100), 100
            )  # 3.1 or above --> 100% 2.1 --> 0 %
            print("Battery level:", batteryLevel)
            self.battery_level.labels(sensor_name=self.label).set(batteryLevel)

            try:
                push_to_gateway(
                    PROMETHEUS_URL, job="btle_sensor_poller", registry=registry
                )
            except OSError as e:
                logging.error(
                    f"Couldn't connect to {PROMETHEUS_URL}. Skipping this update. ({e}"
                )

class Sensor:
    def __init__(self, label, address, interface=0):
        self.label = label
        while True:
            try:
                self.p = self.connect(address, interface)
                self.wait_for_notifications()
            except btle.BTLEDisconnectError as e:
                logging.error(
                    f"Couldn't connect to {self.label} sensor ({address}). Sleeping and trying again. ({e})"
                )
                time.sleep(30)

    def connect(self, address, interface):
        logging.info(f"Connecting to {address}...")
        p = btle.Peripheral(address, iface=interface)
        logging.info(f"Connected. ({address})")
        val = b"\x01\x00"
        p.writeCharacteristic(
            0x0038, val, True
        )  # enable notifications of Temperature, Humidity and Battery voltage
        p.writeCharacteristic(0x0046, b"\xf4\x01\x00", True)
        logging.info(f"Adding Delegate for {address}...")
        p.withDelegate(MyDelegate(label=self.label))
        logging.info(f"Added Delegate for {address}.")
        return p

    def wait_for_notifications(self):
        while True:
            if self.p.waitForNotifications(2000):
                logging.info("Processed notification")


Sensor(label=sys.argv[1], address=sys.argv[2])
