#!/bin/bash

set -e

fastboot flash recovery bin/twrp.img
fastboot flash MISC bin/boot-recovery.bin
fastboot reboot

echo ""
echo "Your device will now reboot into TWRP."
echo ""
