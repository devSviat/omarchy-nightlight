import QtQuick
import qs.Ui

// Visual only. Every side effect and all state live in the sviat.nightlight
// service singleton: this file is instantiated twice over (the active strip
// and the hover fold-out) and again per monitor, so a local property plus a
// Process here would desync -- click one copy off and the others keep thinking
// it is on.
//
// The glyph tracks how deep the sunset ramp has got: sun before it starts,
// then setting sun, moon, and a new moon at the floor.
BarIndicator {
  id: root

  readonly property var sunset: bar?.shell?.serviceFor("sviat.nightlight")
  // Falls back to the stock toggle if the plugin is disabled or removed, so
  // this mark keeps working either way.
  readonly property var builtin: bar?.shell?.firstPartyServiceFor("omarchy.nightlight")

  readonly property string stage: sunset ? sunset.stage : "day"
  readonly property bool paused: sunset ? sunset.mode === "off" : false

  // Paused counts as active so the mark stays on screen. An inactive indicator
  // gets opacity 0 and interactive false, so binding this to "is the screen
  // tinted" meant one click hid the only control for undoing that click.
  // Paused is also worth seeing in daylight: it says tonight's ramp will not run.
  active: sunset ? (sunset.tinted || root.paused)
                 : (builtin ? builtin.enabled : false)

  // Same glyphs as the bar widget: crossed-out sun for off, night bulb for
  // a manual on, then sunset, moon and new moon as the evening deepens.
  activeText: paused ? "󱓤"
              : stage === "on" ? "󱩌"
              : stage === "dusk" ? "󰖛"
              : stage === "night" ? "󰖔" : "󰽤"
  inactiveText: "󰖙"

  activeTooltipText: {
    if (!root.sunset) return "Day Light"
    if (root.paused) return "Night light off - click for Auto"
    var t = root.sunset.temperature
    var now = (t === null ? "off" : t + "K")
    return root.sunset.stageLabel + " \u00b7 " + now + " - click to turn off"
  }

  inactiveTooltipText: {
    if (!root.sunset) return "Night Light"
    if (!root.sunset.isSetup) return "Night Light - open the panel to set it up"
    if (!root.sunset.running) return "hyprsunset is not running"
    return "Night light starts at sunset (" + root.sunset.status.sunset + ")"
  }

  onPressed: function() {
    if (root.sunset && root.sunset.isSetup) root.sunset.toggle()
    else if (root.builtin) root.builtin.setNightlight(!root.active)
  }
}
