#!/usr/bin/env python3
"""
Payload release unit: Raspberry Pi server.

- Keeps a Bluetooth Low Energy link to the ESP32 ("ESP32-BLE") and reconnects automatically.
- Serves the control page on http://<pi-ip>/  (e.g. http://192.168.2.71)

Install:   pip install -r requirements.txt
Run on the Pi:   sudo python3 payload_server.py          (port 80 needs sudo)
Run on a PC:     python payload_server.py --port 8080    then open http://localhost:8080
No ESP32 yet?    python payload_server.py --port 8080 --sim   (fake ESP32 for testing the page)
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import re
import time
from pathlib import Path

from aiohttp import web
from bleak import BleakClient, BleakScanner

DEVICE_NAME = os.environ.get("DEVICE_NAME", "ESP32-BLE")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "80"))
MAX_DEPTH_M = 100.0

RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # Pi -> ESP32
TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # ESP32 -> Pi

INDEX_HTML = Path(__file__).with_name("index.html")

# Commands the web page is allowed to send to the ESP32
SIMPLE_COMMANDS = {"latch", "unlatch", "payout", "payin", "stop", "zero", "status"}
DEPTH_RE = re.compile(r"^depth:(\d{1,3}(?:\.\d)?)$")

state = {
    "connected": False,
    "latch": "unknown",      # latched | unlatched | unknown
    "winch": "unknown",      # out | in | stop | unknown
    "target_depth": None,    # release depth in metres, or None when not set
    "depth": None,           # current line-out depth from the winch encoder
    "event": None,           # last EVENT from the ESP32, e.g. RELEASED
    "log": [],
}
client: BleakClient | None = None
SIMULATE = False
SIM_SPEED_MPS = 1.0
sim = {"latch": False, "winch": 0, "release": 0.0, "depth": 0.0, "return_at": None}
write_lock = asyncio.Lock()
rx_buffer = ""


def add_log(direction: str, msg: str) -> None:
    """direction: 'tx' (to ESP32), 'rx' (from ESP32) or 'sys'."""
    print(f"[{direction}] {msg}", flush=True)
    state["log"].append({"t": time.strftime("%H:%M:%S"), "dir": direction, "msg": msg})
    del state["log"][:-60]


def handle_line(line: str) -> None:
    parts = line.split()
    key = parts[0] if parts else ""
    if key == "LATCHED":
        state["latch"] = "latched"
        state["event"] = None
    elif key == "UNLATCHED":
        state["latch"] = "unlatched"
    elif key == "WINCH" and len(parts) > 1:
        state["winch"] = parts[1].lower()
    elif key == "DEPTH" and len(parts) > 1:
        try:
            state["target_depth"] = None if parts[1] == "NONE" else float(parts[1])
        except ValueError:
            pass
    elif key == "AT" and len(parts) > 1:
        try:
            state["depth"] = float(parts[1])
        except ValueError:
            pass
        return  # streamed several times a second, too noisy for the log
    elif key == "EVENT" and len(parts) > 1:
        state["event"] = " ".join(parts[1:])
    add_log("rx", line)


def on_notify(_sender, data: bytearray) -> None:
    global rx_buffer
    rx_buffer += data.decode("utf-8", "ignore")
    while "\n" in rx_buffer:
        line, rx_buffer = rx_buffer.split("\n", 1)
        if line.strip():
            handle_line(line.strip())


# ---------- Simulator: behaves like the ESP32 firmware (for testing without hardware) ----------

def sim_report() -> None:
    handle_line("LATCHED" if sim["latch"] else "UNLATCHED")
    handle_line("WINCH " + {1: "OUT", -1: "IN", 0: "STOP"}[sim["winch"]])
    handle_line(f"DEPTH {sim['release']:.1f}" if sim["release"] > 0 else "DEPTH NONE")
    handle_line(f"AT {sim['depth']:.1f}")


async def sim_command(cmd: str) -> None:
    await asyncio.sleep(0.05)
    if cmd == "latch":
        sim["latch"] = True
    elif cmd == "unlatch":
        sim["latch"] = False
    elif cmd in ("payout", "payin", "stop"):
        sim["winch"] = {"payout": 1, "payin": -1, "stop": 0}[cmd]
        sim["return_at"] = None
    elif cmd == "zero":
        sim["depth"] = 0.0
    elif cmd.startswith("depth:"):
        sim["release"] = float(cmd[6:])
    sim_report()


def sim_event(name: str) -> None:
    handle_line(f"EVENT {name}")
    sim_report()


async def sim_loop() -> None:
    state["connected"] = True
    add_log("sys", f"SIMULATOR: fake ESP32 linked ({SIM_SPEED_MPS:g} m/s winch)")
    sim_report()
    last_sent = None
    dt = 0.1
    while True:
        await asyncio.sleep(dt)
        sim["depth"] = max(0.0, sim["depth"] + sim["winch"] * SIM_SPEED_MPS * dt)
        d = sim["depth"]
        if sim["winch"] == 1 and sim["latch"] and sim["release"] > 0 and d >= sim["release"]:
            sim["winch"] = 0
            sim["latch"] = False
            sim["return_at"] = time.monotonic() + 3.0
            sim_event("RELEASED")
        if sim["return_at"] and time.monotonic() >= sim["return_at"]:
            sim["return_at"] = None
            sim["winch"] = -1
            sim_event("RETURNING")
        if sim["winch"] == -1 and d <= 0:
            sim["winch"] = 0
            sim_event("SURFACED")
        if last_sent is None or abs(d - last_sent) >= 0.05:
            handle_line(f"AT {d:.1f}")
            last_sent = d


async def send_command(cmd: str) -> None:
    if SIMULATE:
        add_log("tx", cmd)
        await sim_command(cmd)
        return
    c = client
    if c is None or not c.is_connected:
        raise ConnectionError("ESP32 is not connected")
    async with write_lock:
        add_log("tx", cmd)
        await c.write_gatt_char(RX_UUID, (cmd + "\n").encode(), response=True)


async def ble_loop() -> None:
    """Find the ESP32, stay connected, and reconnect whenever the link drops."""
    global client, rx_buffer
    while True:
        add_log("sys", f"Searching for {DEVICE_NAME}")
        device = None
        while device is None:
            try:
                device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10.0)
            except Exception as e:
                add_log("sys", f"Bluetooth scan error: {e}")
                await asyncio.sleep(5)

        lost = asyncio.Event()
        c = BleakClient(device, disconnected_callback=lambda _c: lost.set())
        try:
            await c.connect(timeout=15.0)
            rx_buffer = ""
            await c.start_notify(TX_UUID, on_notify)
            client = c
            state["connected"] = True
            add_log("sys", "Linked to ESP32")
            await send_command("status")
            await lost.wait()
            add_log("sys", "Link lost")
        except Exception as e:
            add_log("sys", f"Connection failed: {e}")
        finally:
            state["connected"] = False
            client = None
            if c.is_connected:
                with contextlib.suppress(Exception):
                    await c.disconnect()
        await asyncio.sleep(2)


# ---------- Web routes ----------

async def index(_request):
    return web.FileResponse(INDEX_HTML, headers={"Cache-Control": "no-store"})


async def get_status(_request):
    return web.json_response({
        "connected": state["connected"],
        "latch": state["latch"],
        "winch": state["winch"],
        "target_depth": state["target_depth"],
        "depth": state["depth"],
        "event": state["event"],
        "log": state["log"][::-1],  # newest first
    })


async def post_command(request):
    try:
        data = await request.json()
        cmd = str(data["cmd"]).strip().lower()
    except Exception:
        return web.json_response({"error": "Bad request"}, status=400)

    m = DEPTH_RE.match(cmd)
    if m:
        if not 0 <= float(m.group(1)) <= MAX_DEPTH_M:
            return web.json_response({"error": f"Depth must be 0–{MAX_DEPTH_M:g} m"}, status=400)
    elif cmd not in SIMPLE_COMMANDS:
        return web.json_response({"error": "Unknown command"}, status=400)

    try:
        await send_command(cmd)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=503)
    return web.json_response({"ok": True})


async def on_startup(app):
    app["ble_task"] = asyncio.create_task(sim_loop() if SIMULATE else ble_loop())


async def on_cleanup(app):
    app["ble_task"].cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await app["ble_task"]


def main():
    global SIMULATE
    ap = argparse.ArgumentParser(description="Payload release unit server")
    ap.add_argument("--port", type=int, default=PORT, help="web port (default 80)")
    ap.add_argument("--host", default=HOST, help="address to listen on (default all)")
    ap.add_argument("--sim", action="store_true", help="simulate the ESP32 (no Bluetooth needed)")
    args = ap.parse_args()
    SIMULATE = args.sim

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/status", get_status)
    app.router.add_post("/api/command", post_command)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    print(f"Serving on http://{args.host}:{args.port}" + ("  [SIMULATOR]" if SIMULATE else ""))
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()