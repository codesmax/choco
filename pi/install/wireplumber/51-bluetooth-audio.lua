-- Disable logind integration for headless service operation
-- Allows Bluetooth to work without a logged-in user session
bluez_monitor.properties["with-logind"] = false

-- Auto-connect to Bluetooth audio devices with headset-head-unit profile
table.insert(bluez_monitor.rules, {
  matches = {
    {
      { "device.name", "matches", "bluez_card.*" },
    },
  },
  apply_properties = {
    ["bluez5.auto-connect"]  = "[ hfp_hf hsp_hs a2dp_sink ]",
    ["device.profile"] = "headset-head-unit",
  },
})
