idf_component_register(
    SRCS "main.c" "test_data.c" "device_protocol.c"
    INCLUDE_DIRS "."
    REQUIRES esp_driver_usb_serial_jtag esp_timer esp_hw_support json
)
