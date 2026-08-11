# ZMK のヘッダ（zmk/pm.h など）は app/include にあり、ZMK 側は
# target_include_directories(app PRIVATE include) で**自分専用**に足している。
# モジュールからは見えないので、ここで明示的に足す。
zephyr_include_directories(${ZEPHYR_ZMK_MODULE_DIR}/app/include)

if(CONFIG_HHKB_BATTERY_ALKALINE OR CONFIG_HHKB_LOW_BATTERY_SOFT_OFF)
  zephyr_library()
  zephyr_library_sources_ifdef(CONFIG_HHKB_BATTERY_ALKALINE
                               drivers/battery_alkaline.c)
  zephyr_library_sources_ifdef(CONFIG_HHKB_LOW_BATTERY_SOFT_OFF
                               src/low_battery_off.c)
endif()
