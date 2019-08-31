#!/bin/bash

set -e

fastboot flash boot bin/boot.img
fastboot flash recovery bin/recovery.img

echo ""
echo "Hold the left volume-button, then press Enter to reboot..."
read
fastboot reboot
echo "Rebooting... keep holding the button until you see the \"amazon\" logo"
echo ""
