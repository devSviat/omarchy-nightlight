import QtQuick
import Quickshell
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Bar widget for Night Light. All state comes from the CLI in bin/, which
// is the same thing the systemd timer drives -- the widget never computes a
// schedule of its own, so what it shows is always what is actually loaded.
//
// The panel reads top to bottom in the order someone opening it needs things:
//   hero     what the screen is doing right now, and what happens next
//   mode     the one decision made here: Auto, On or Off -- and, for On,
//            how warm
//   tonight  the whole ladder as one strip, and when each phase runs
//   footer   where the sun times come from, and a rebuild action
Panel {
  id: root
  moduleName: "sviat.nightlight"
  ipcTarget: "sviat.nightlight"
  manageIpc: false

  // One singleton owns the state; this widget is instantiated once per monitor
  // and only reads from it. See Service.qml.
  readonly property var service: bar?.shell?.serviceFor("sviat.nightlight")
  readonly property var status: service ? service.status : Model.emptyStatus()
  readonly property var steps: service ? service.steps : []
  readonly property var ladder: service ? service.ladder : ({})
  readonly property int manualTemp: service ? service.manualTemp : 0
  readonly property bool busy: service ? service.busy : false
  readonly property string stage: service ? service.stage : "day"
  readonly property bool isSetup: service ? service.isSetup : false
  readonly property bool tinted: service ? service.tinted : false
  readonly property var temperature: service ? service.temperature : null
  readonly property string mode: root.status.mode

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  readonly property var modes: [
    { value: "auto", label: "Auto", icon: "\u{F1800}", hint: "Follow dusk and dawn" },
    { value: "on", label: "On", icon: "\u{F1A4C}", hint: "Hold the night temperature" },
    { value: "off", label: "Off", icon: "\u{F14E4}", hint: "Hold untinted" }
  ]
  // Keyboard cursor on the mode row; -1 until h/l is pressed.
  property int modeCursor: -1

  function refresh() { if (root.service) root.service.refresh() }
  function rebuild() { if (root.service && !root.busy) root.service.rebuild() }
  function acceptSetup() { if (root.service) root.service.acceptSetup() }

  function setMode(value) {
    if (!root.service || root.busy || value === root.mode) return
    root.service.setMode(value)
  }

  function modeIndex(value) {
    for (var i = 0; i < root.modes.length; i++)
      if (root.modes[i].value === value) return i
    return 0
  }

  function moveModeCursor(dx) {
    var from = root.modeCursor >= 0 ? root.modeCursor : root.modeIndex(root.mode)
    root.modeCursor = Math.max(0, Math.min(root.modes.length - 1, from + dx))
  }

  function activateModeCursor() {
    if (root.modeCursor >= 0) root.setMode(root.modes[root.modeCursor].value)
  }

  function nudgeTemp(delta) {
    if (root.service && root.mode === "on") root.service.nudgeTemp(delta)
  }

  // No IpcHandler here on purpose: Service.qml already claims the
  // "sviat.nightlight" target, and two handlers cannot share one. The panel
  // is summoned the standard way, with `omarchy-shell shell toggle
  // sviat.nightlight`.

  onOpenedChanged: if (opened) {
    root.modeCursor = -1
    refresh()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  // The service polls on its own; refresh faster only while the panel is open.
  Timer { interval: 5000; running: root.opened; repeat: true; onTriggered: root.refresh() }

  Component.onCompleted: refresh()

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: Model.stageGlyph(root.stage)
    // Urgent colour is for a fault, not for the normal warm evening: the only
    // real fault here is hyprsunset being down, when nothing is applied at all.
    active: root.status.ok && !root.status.running
    tooltipText: Model.summaryLine(root.status)
    onPressed: function(b) {
      if (b === Qt.RightButton) root.setMode(root.mode === "off" ? "auto" : "off")
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    // Onboarding is wider: the disclosure is laid out in columns and wraps
    // badly if it is squeezed into the width the everyday panel needs.
    contentWidth: panel.fittedContentWidth(Style.space(root.isSetup ? 300 : 560))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onMoveRequested: function(dx, dy) {
        if (!root.isSetup) return
        if (dx !== 0) root.moveModeCursor(dx)
        else root.nudgeTemp(-dy * Model.TEMP_STEP)
      }
      onActivateRequested: if (root.isSetup) root.activateModeCursor()
      onTextKey: function(t) {
        if (!root.isSetup) return
        if (t === "r" || t === "R") root.rebuild()
        else if (t === "+" || t === "=") root.nudgeTemp(Model.TEMP_STEP)
        else if (t === "-") root.nudgeTemp(-Model.TEMP_STEP)
      }

      Column {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: Style.space(12)

        // ---------------------------------------------------------- setup
        // Nothing has been written to the user's configuration at this point.
        // The disclosure below is `nightlight setup --print` verbatim, so
        // what the button agrees to is exactly what the button then does.
        Column {
          visible: !root.isSetup
          width: parent.width
          spacing: Style.space(10)

          Text {
            text: "Night Light"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
          }

          PanelSeparator { foreground: root.foreground }

          Text {
            width: parent.width
            text: "Not set up yet. Nothing on this machine has been changed."
            color: root.foreground
            wrapMode: Text.WordWrap
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            font.bold: true
          }

          Text {
            width: parent.width
            text: root.service && root.service.disclosure !== ""
                  ? root.service.disclosure
                  : "Reading what setup would change…"
            color: root.foreground
            opacity: 0.75
            wrapMode: Text.WordWrap
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          Button {
            text: root.busy ? "Setting up…" : "I agree — enable night light"
            enabled: !root.busy && root.service && root.service.disclosure !== ""
            foreground: root.foreground
            fontFamily: root.fontFamily
            fontSize: Style.font.bodySmall
            bordered: true
            onClicked: root.acceptSetup()
          }
        }

        // ----------------------------------------------------------- hero
        // What the screen is doing now. The glyph carries the tint it applies.
        PanelHero {
          id: hero
          visible: root.isSetup
          width: parent.width
          title: "Night Light"
          detail: root.tinted ? Model.tempLabel(root.temperature) : ""
          meta: Model.heroMeta(root.status, root.tinted, root.temperature)
          foreground: root.foreground
          fontFamily: root.fontFamily
          iconOpacity: root.tinted ? 1.0 : 0.5
          iconComponent: Component {
            Text {
              textFormat: Text.PlainText
              text: Model.stageGlyph(root.stage)
              color: root.tinted ? Model.temperatureColor(root.temperature) : root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.display
            }
          }

          // The pill showing the held temperature doubles as a control. The
          // hero draws it and takes no input, so this sits over its corner.
          MouseArea {
            id: pillArea
            visible: root.mode === "on"
            anchors.right: parent.right
            anchors.top: parent.top
            width: Style.space(72)
            height: parent.height / 2
            hoverEnabled: true
            onWheel: function(wheel) {
              root.nudgeTemp(wheel.angleDelta.y > 0 ? Model.TEMP_STEP : -Model.TEMP_STEP)
            }
            onDoubleClicked: if (root.service) root.service.resetTemp()
          }

          PanelToolTip {
            parent: pillArea
            visible: pillArea.visible && pillArea.containsMouse
            text: "Scroll to adjust · double-click for " + Model.tempLabel(root.status.nightTemp)
            fontFamily: root.fontFamily
          }
        }

        Text {
          width: parent.width
          visible: root.isSetup && root.status.ok && !root.status.running
          text: "Nothing is applied. Start it with: systemctl --user start hyprsunset"
          color: root.urgent
          wrapMode: Text.WordWrap
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
        }

        PanelSeparator { visible: root.isSetup; foreground: root.foreground }

        // ----------------------------------------------------------- mode
        Column {
          visible: root.isSetup
          width: parent.width
          spacing: Style.space(8)

          PanelSectionHeader {
            text: "Mode"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          // Equal-width segments: the chosen one is highlighted, none greys
          // out. Picking the current mode again is a no-op.
          Row {
            id: modeRow
            width: parent.width
            spacing: Style.space(6)

            Repeater {
              model: root.modes

              Button {
                required property var modelData
                required property int index
                width: (modeRow.width - modeRow.spacing * (root.modes.length - 1)) / root.modes.length
                text: modelData.label
                iconText: modelData.icon
                tooltipText: modelData.hint
                selected: root.mode === modelData.value
                hasCursor: root.modeCursor === index
                bordered: true
                enabled: !root.busy
                foreground: root.foreground
                fontFamily: root.fontFamily
                fontSize: Style.font.bodySmall
                onClicked: root.setMode(modelData.value)
              }
            }
          }

          // On: how warm. The screen follows the knob as it moves, and the
          // value sticks on release. The track is the tint at each position.
          Item {
            visible: root.mode === "on"
            width: parent.width
            implicitHeight: tempSlider.implicitHeight

            Rectangle {
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              height: tempSlider.trackHeight
              radius: height / 2
              border.width: 1
              border.color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.2)
              gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Model.temperatureColor(Model.TEMP_MIN) }
                GradientStop { position: 0.25; color: Model.temperatureColor(2375) }
                GradientStop { position: 0.5; color: Model.temperatureColor(3750) }
                GradientStop { position: 0.75; color: Model.temperatureColor(5125) }
                GradientStop { position: 1.0; color: Model.temperatureColor(Model.TEMP_MAX) }
              }
            }

            PanelSlider {
              id: tempSlider
              anchors.fill: parent
              bar: root.bar
              minimum: Model.TEMP_MIN
              maximum: Model.TEMP_MAX
              step: Model.TEMP_STEP
              integer: true
              value: root.manualTemp
              trackColor: "transparent"
              fillColor: "transparent"
              onMoved: function(v) { if (root.service) root.service.previewTemp(Model.snapTemp(v)) }
              onReleased: function(v) { if (root.service) root.service.commitTemp(Model.snapTemp(v)) }
              onRightClicked: if (root.service) root.service.resetTemp()
            }
          }

          Text {
            visible: root.mode !== "on"
            width: parent.width
            text: Model.modeCaption(root.mode, root.status)
            color: root.dim
            wrapMode: Text.WordWrap
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
        }

        PanelSeparator { visible: root.isSetup; foreground: root.foreground }

        // -------------------------------------------------------- tonight
        // Dimmed while a manual hold is in place: it is what Auto would do,
        // not what is on screen.
        Column {
          visible: root.isSetup
          width: parent.width
          spacing: Style.space(8)
          opacity: root.mode === "auto" ? 1.0 : 0.45

          Item {
            width: parent.width
            implicitHeight: tonightHeader.implicitHeight

            PanelSectionHeader {
              id: tonightHeader
              text: "Tonight"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            Text {
              anchors.right: parent.right
              anchors.bottom: tonightHeader.bottom
              textFormat: Text.PlainText
              text: "sets " + root.status.sunset + "  ·  rises " + root.status.sunrise
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }

          // The ladder as one strip: each square is a step, painted in the
          // tint it applies. The live step stands taller; the night, which
          // holds at the floor instead of stepping, gets a square of its own in
          // that same tint. Hover a square for its time.
          Row {
            id: strip
            width: parent.width
            spacing: 1
            visible: root.steps.length > 0

            readonly property var gaps: Model.stepGaps(root.steps)
            readonly property int gapCount: {
              var n = 0
              for (var i = 0; i < gaps.length; i++) if (gaps[i]) n++
              return n
            }
            // Every hold takes a slot of its own, so all the squares come out
            // the same width and the strip stays evenly divided.
            readonly property int slots: root.steps.length + gapCount
            readonly property real segment: slots > 0
              ? Math.max(0, (width - spacing * (slots - 1)) / slots)
              : 0

            Repeater {
              model: root.steps

              Item {
                id: step
                required property var modelData
                required property int index
                readonly property bool gapBefore: strip.gaps[index] === true
                // The rung whose hold comes next is `current` for as long as
                // that hold lasts, so the live marker moves onto the hold: it
                // is the stretch the screen is actually in.
                readonly property bool handsOver: strip.gaps[index + 1] === true
                readonly property bool live: modelData.current === true
                  && root.mode === "auto" && !handsOver
                // What the screen sits at through the hold, and since when:
                // the step before it, which the hold simply keeps.
                readonly property var previous: index > 0 ? root.steps[index - 1] : null
                readonly property var heldTemp: previous ? previous.temperature : null
                readonly property string heldFrom: previous ? previous.time : ""
                readonly property bool holdLive: gapBefore && root.mode === "auto"
                  && previous && previous.current === true
                // Where this step's own square sits: after the hold, if any.
                readonly property real offset: gapBefore ? strip.segment + strip.spacing : 0

                width: strip.segment + offset
                height: Style.space(16)

                // The night does not step, it holds at the floor for hours.
                // Draw that hold as its own square in the tint it holds, so the
                // strip runs unbroken from dusk to day.
                Rectangle {
                  id: hold
                  visible: step.gapBefore
                  x: 0
                  width: strip.segment
                  anchors.top: parent.top
                  anchors.bottom: parent.bottom
                  anchors.topMargin: step.holdLive ? 0 : Style.space(4)
                  anchors.bottomMargin: step.holdLive ? 0 : Style.space(4)
                  radius: Math.min(2, Style.cornerRadius)
                  color: Model.temperatureColor(step.heldTemp)
                  border.width: 1
                  border.color: step.holdLive ? root.foreground
                    : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.2)
                }

                MouseArea {
                  id: holdMouse
                  visible: step.gapBefore
                  anchors.fill: hold
                  hoverEnabled: true
                }

                PanelToolTip {
                  parent: hold
                  visible: holdMouse.containsMouse
                  text: step.heldFrom + " – " + step.modelData.time + "  held at "
                        + (step.heldTemp === null ? "untinted" : step.heldTemp + "K")
                  fontFamily: root.fontFamily
                }

                Rectangle {
                  id: rung
                  x: step.offset
                  width: strip.segment
                  anchors.top: parent.top
                  anchors.bottom: parent.bottom
                  anchors.topMargin: step.live ? 0 : Style.space(4)
                  anchors.bottomMargin: step.live ? 0 : Style.space(4)
                  radius: Math.min(2, Style.cornerRadius)
                  color: Model.temperatureColor(step.modelData.temperature)
                  // A faint outline keeps the near-white daytime steps visible
                  // on light themes; the live step gets the full foreground.
                  border.width: 1
                  border.color: step.live ? root.foreground
                    : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.2)
                }

                MouseArea {
                  id: stepMouse
                  anchors.fill: rung
                  hoverEnabled: true
                }

                PanelToolTip {
                  parent: rung
                  visible: stepMouse.containsMouse
                  text: step.modelData.time + "  " + (step.modelData.temperature === null
                        ? "untinted" : step.modelData.temperature + "K")
                  fontFamily: root.fontFamily
                }
              }
            }
          }

          Column {
            width: parent.width
            spacing: Style.space(4)

            Repeater {
              model: Model.phases(root.ladder)

              Item {
                required property var modelData
                width: parent.width
                implicitHeight: phaseLabel.implicitHeight

                Text {
                  id: phaseLabel
                  textFormat: Text.PlainText
                  text: modelData.label
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.bodySmall
                }

                Text {
                  x: Style.space(64)
                  textFormat: Text.PlainText
                  text: modelData.times
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.bodySmall
                }

                Text {
                  anchors.right: parent.right
                  textFormat: Text.PlainText
                  text: modelData.temps
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.bodySmall
                }
              }
            }
          }

          Text {
            width: parent.width
            visible: root.status.estimated
            text: "The sun does not set here today; using the fallback times."
            color: root.dim
            wrapMode: Text.WordWrap
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
        }

        PanelSeparator { visible: root.isSetup; foreground: root.foreground }

        // --------------------------------------------------------- footer
        Item {
          visible: root.isSetup
          width: parent.width
          implicitHeight: Math.max(locationText.implicitHeight, rebuildButton.implicitHeight)

          Text {
            id: locationText
            anchors.left: parent.left
            anchors.right: rebuildButton.left
            anchors.rightMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: root.status.timezone + "  ·  " + Model.locationLabel(root.status)
            color: root.dim
            elide: Text.ElideRight
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          PanelActionButton {
            id: rebuildButton
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            iconText: "\u{F0450}"
            tooltipText: "Recompute tonight and reload hyprsunset (r)"
            enabled: !root.busy
            foreground: root.foreground
            fontFamily: root.fontFamily
            onClicked: root.rebuild()
          }
        }
      }
    }
  }
}
