# ZMK のヘッダ（zmk/pm.h・zmk/event_manager.h など）は **zmk/app/include** に
# あり、ZMK 側は target_include_directories(app PRIVATE include) で
# **自分専用**に足している。モジュールからは見えないので明示的に足す。
#
# ⚠️ **基準を 2 回間違えた（2026-08-11）。**
#   1. `${ZEPHYR_ZMK_MODULE_DIR}` … **空になる。**ZMK のモジュールは
#      zmk/app/module にあり、その zephyr/module.yml に name: が無いので
#      ディレクトリ名から `module` と名付けられる（= ZEPHYR_MODULE_MODULE_DIR）。
#      結果 `-I/app/include` という実在しない絶対パスが渡り、
#      「zmk/event_manager.h: No such file or directory」で落ちた。
#   2. その ZEPHYR_MODULE_MODULE_DIR から `/../include` と辿るのは、
#      ZMK 側の配置に依存しすぎる。
#
# ZMK のビルドは必ず `west build -s zmk/app` なので、**CMAKE_SOURCE_DIR が
# zmk/app** になる（コンパイル行の -fmacro-prefix-map で確認した）。
zephyr_include_directories(${CMAKE_SOURCE_DIR}/include)

if(CONFIG_HHKB_BATTERY_ALKALINE OR CONFIG_HHKB_LOW_BATTERY_SOFT_OFF
   OR CONFIG_HHKB_STATUS_LED)
  zephyr_library()
  zephyr_library_sources_ifdef(CONFIG_HHKB_BATTERY_ALKALINE
                               drivers/battery_alkaline.c)
  zephyr_library_sources_ifdef(CONFIG_HHKB_LOW_BATTERY_SOFT_OFF
                               src/low_battery_off.c)
  zephyr_library_sources_ifdef(CONFIG_HHKB_STATUS_LED
                               src/status_led.c)
endif()
