import struct
import os
import sys
import time

from common import Device
from handshake import handshake
from load_payload import load_payload, UserInputThread
from logger import log

def check_modemmanager():
    pids = [pid for pid in os.listdir('/proc') if pid.isdigit()]

    for pid in pids:
        try:
            args = open(os.path.join('/proc', pid, 'cmdline'), 'rb').read().decode("utf-8").split('\0')
            if len(args) > 0 and "modemmanager" in args[0].lower():
                print("You need to temporarily disable/uninstall ModemManager before this script can proceed")
                sys.exit(1)
        except IOError:
            continue

def switch_boot0(dev):
    dev.emmc_switch(1)
    block = dev.emmc_read(0)
    if block[0:9] != b"EMMC_BOOT" and block != b"\x00" * 0x200:
        dev.reboot()
        raise RuntimeError("what's wrong with your BOOT0?")
    dev.kick_watchdog()

def flash_data(dev, data, start_block, max_size=0):
    while len(data) % 0x200 != 0:
        data += b"\x00"

    if max_size and len(data) > max_size:
        raise RuntimeError("data too big to flash")

    blocks = len(data) // 0x200
    for x in range(blocks):
        print("[{} / {}]".format(x + 1, blocks), end='\r')
        dev.emmc_write(start_block + x, data[x * 0x200:(x + 1) * 0x200])
        if x % 10 == 0:
            dev.kick_watchdog()
    print("")

def flash_binary(dev, path, start_block, max_size=0):
    with open(path, "rb") as fin:
        data = fin.read()
    while len(data) % 0x200 != 0:
        data += b"\x00"

    flash_data(dev, data, start_block, max_size=0)

def dump_binary(dev, path, start_block, max_size=0):
    with open(path, "w+b") as fout:
        blocks = max_size // 0x200
        for x in range(blocks):
            print("[{} / {}]".format(x + 1, blocks), end='\r')
            fout.write(dev.emmc_read(start_block + x))
        if x % 10 == 0:
            dev.kick_watchdog()
    print("")

def force_fastboot(dev, gpt):
    switch_user(dev)
    block = list(dev.emmc_read(gpt["MISC"][0]))
    block[0:16] = "FASTBOOT_PLEASE\x00".encode("utf-8")
    dev.emmc_write(gpt["MISC"][0], bytes(block))
    block = dev.emmc_read(gpt["MISC"][0])

def force_recovery(dev, gpt):
    switch_user(dev)
    block = list(dev.emmc_read(gpt["MISC"][0]))
    block[0:16] = "boot-recovery\x00\x00\x00".encode("utf-8")
    dev.emmc_write(gpt["MISC"][0], bytes(block))
    block = dev.emmc_read(gpt["MISC"][0])

def switch_user(dev):
    dev.emmc_switch(0)
    block = dev.emmc_read(0)
    if block[510:512] != b"\x55\xAA":
        dev.reboot()
        raise RuntimeError("what's wrong with your GPT?")
    dev.kick_watchdog()

def parse_gpt(dev):
    data = dev.emmc_read(0x400 // 0x200) + dev.emmc_read(0x600 // 0x200) + dev.emmc_read(0x800 // 0x200) + dev.emmc_read(0xA00 // 0x200)
    num = len(data) // 0x80
    parts = dict()
    for x in range(num):
        part = data[x * 0x80:(x + 1) * 0x80]
        part_name = part[0x38:].decode("utf-16le").rstrip("\x00")
        part_start = struct.unpack("<Q", part[0x20:0x28])[0]
        part_end = struct.unpack("<Q", part[0x28:0x30])[0]
        parts[part_name] = (part_start, part_end - part_start + 1)
    return parts

def main():

    minimal = False

    check_modemmanager()

    dev = Device()
    dev.find_device()

    # 0.1) Handshake
    handshake(dev)

    # 0.2) Load brom payload
    load_payload(dev, "../brom-payload/build/payload.bin")
    dev.kick_watchdog()

    if len(sys.argv) == 2 and sys.argv[1] == "minimal":
        thread = UserInputThread(msg = "Running in minimal mode, assuming LK, TZ, LK-payload and TWRP to have already been flashed.\nIf this is correct (i.e. you used \"brick\" option in step 1) press enter, otherwise terminate with Ctrl+C")
        thread.start()
        while not thread.done:
            dev.kick_watchdog()
            time.sleep(1)
        minimal = True

    # 1) Sanity check GPT
    log("Check GPT")
    switch_user(dev)

    # 1.1) Parse gpt
    gpt = parse_gpt(dev)
    log("gpt_parsed = {}".format(gpt))
    if "lk" not in gpt or "tee1" not in gpt or "boot" not in gpt or "recovery" not in gpt:
        raise RuntimeError("bad gpt")

    # 2) Sanity check boot0
    log("Check boot0")
    switch_boot0(dev)

    # 3) Sanity check rpmb
    log("Check rpmb")
    rpmb = dev.rpmb_read()
    if rpmb[0:4] != b"AMZN":
        thread = UserInputThread(msg = "rpmb looks broken; if this is expected (i.e. you're retrying the exploit) press enter, otherwise terminate with Ctrl+C")
        thread.start()
        while not thread.done:
            dev.kick_watchdog()
            time.sleep(1)

    # Clear preloader so, we get into bootrom without shorting, should the script stall (we flash preloader as last step)
    # 4) Downgrade preloader
    log("Clear preloader header")
    switch_boot0(dev)
    flash_data(dev, b"EMMC_BOOT" + b"\x00" * ((0x200 * 8) - 9), 0)

    # 5) Zero out rpmb to enable downgrade
    log("Downgrade rpmb")
    dev.rpmb_write(b"\x00" * 0x100)
    log("Recheck rpmb")
    rpmb = dev.rpmb_read()
    if rpmb != b"\x00" * 0x100:
        dev.reboot()
        raise RuntimeError("downgrade failure, giving up")
    log("rpmb downgrade ok")
    dev.kick_watchdog()

    if not minimal:
        # 6) Install preloader
        log("Flash preloader")
        switch_boot0(dev)
        flash_binary(dev, "../bin/preloader.bin", 8)
        flash_binary(dev, "../bin/preloader.bin", 520)

        # 6) Install lk-payload
        log("Flash lk-payload")
        switch_boot0(dev)
        flash_binary(dev, "../lk-payload/build/payload.bin", 1024)

        # 7) Downgrade tz
        log("Flash tz")
        switch_user(dev)
        flash_binary(dev, "../bin/tz.img", gpt["tee1"][0], gpt["tee1"][1] * 0x200)

        # 8) Downgrade lk
        log("Flash lk")
        switch_user(dev)
        flash_binary(dev, "../bin/lk.bin", gpt["lk"][0], gpt["lk"][1] * 0x200)

    # 9) Flash microloader
    log("Inject microloader")
    switch_user(dev)
    boot_hdr1 = dev.emmc_read(gpt["boot"][0]) + dev.emmc_read(gpt["boot"][0] + 1)
    boot_hdr2 = dev.emmc_read(gpt["boot"][0] + 2) + dev.emmc_read(gpt["boot"][0] + 3)
    flash_binary(dev, "../bin/microloader.bin", gpt["boot"][0], 2 * 0x200)
    if boot_hdr2[0:8] != b"ANDROID!":
        flash_data(dev, boot_hdr1, gpt["boot"][0] + 2, 2 * 0x200)

    if not minimal:
        log("Force fastboot")
        force_fastboot(dev, gpt)
    else:
        log("Force recovery")
        force_recovery(dev, gpt)

    # 10) Downgrade preloader
    log("Flash preloader header")
    switch_boot0(dev)
    flash_binary(dev, "../bin/preloader.hdr0", 0, 4)
    flash_binary(dev, "../bin/preloader.hdr1", 4, 4)

    # Reboot (to fastboot or recovery)
    log("Reboot")
    dev.reboot()


if __name__ == "__main__":
    main()
