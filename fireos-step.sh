#!/bin/bash

set -e

. functions.inc

adb wait-for-device

PAYLOAD_BLOCK=1024

max_tee=258
max_lk=1
max_pl=5

check_device "karnak" " - Amazon Fire HD 8 (2018 / 8th gen) - "

get_root

tee_version=$((`adb shell getprop ro.boot.tee_version | dos2unix`))
lk_version=$((`adb shell getprop ro.boot.lk_version | dos2unix`))
pl_version=$((`adb shell getprop ro.boot.pl_version | dos2unix`))

echo "PL version: ${pl_version} (${max_pl})"
echo "LK version: ${lk_version} (${max_lk})"
echo "TZ version: ${tee_version} (${max_tee})"
echo ""

flash_exploit() {
    echo "Flashing LK-payload"
    adb push lk-payload/build/payload.bin /data/local/tmp/
    adb shell su -c \"dd if=/data/local/tmp/payload.bin of=/dev/block/mmcblk0boot0 bs=512 seek=${PAYLOAD_BLOCK}\"

    echo "Flashing LK"
    adb push bin/lk.bin /data/local/tmp/
    adb shell su -c \"dd if=/data/local/tmp/lk.bin of=/dev/block/platform/soc/by-name/lk bs=512\" 
    echo ""

    echo "Flashing TZ"
    adb push bin/tz.img /data/local/tmp/
    adb shell su -c \"dd if=/data/local/tmp/tz.img of=/dev/block/platform/soc/by-name/tee1 bs=512\" 
    adb shell su -c \"dd if=/data/local/tmp/tz.img of=/dev/block/platform/soc/by-name/tee2 bs=512\" 
    echo ""

    echo "Flashing TWRP"
    adb push bin/twrp.img /data/local/tmp/
    adb shell su -c \"dd if=/data/local/tmp/twrp.img of=/dev/block/platform/soc/by-name/recovery bs=512\" 
    echo ""
}

if [ "$1" = "brick" ] || [ $tee_version -gt $max_tee ] || [ $lk_version -gt $max_lk ] || [ $pl_version -gt $max_pl ] ; then
  echo "TZ, Preloader or LK are too new, RPMB downgrade necessary (or brick option used)"
  echo "Brick preloader to continue via bootrom-exploit? (Type \"YES\" to continue)"
  read YES
  if [ "$YES" = "YES" ]; then
    echo "Bricking preloader"
    adb shell su -c \"echo 0 \> /sys/block/mmcblk0boot0/force_ro\"
    adb shell su -c \"dd if=/dev/zero of=/dev/block/mmcblk0boot0 bs=512 count=8\"
    adb shell su -c \"echo -n EMMC_BOOT \> /dev/block/mmcblk0boot0\"

    flash_exploit

    echo "Rebooting..., continue with bootrom-step-minimal.sh"
    adb shell reboot
    exit 0
  fi
  exit 1
fi

flash_exploit

echo "Flashing Preloader"
adb push  bin/boot0-short.bin /data/local/tmp/
adb shell su -c \"echo 0 \> /sys/block/mmcblk0boot0/force_ro\"
adb shell su -c \"dd if=/data/local/tmp/boot0-short.bin of=/dev/block/mmcblk0boot0 bs=512\" 
echo ""

adb reboot recovery
