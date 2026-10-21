.pragma library

// What the On slider covers. hyprsunset goes lower than this is useful and far
// higher; 6500K is the untinted end, past which the screen only turns blue.
var TEMP_MIN = 1000
var TEMP_MAX = 6500
var TEMP_SNAP = 50
var TEMP_STEP = 100

function clampTemp(kelvin) {
  return Math.max(TEMP_MIN, Math.min(TEMP_MAX, kelvin))
}

function snapTemp(kelvin) {
  return clampTemp(Math.round(kelvin / TEMP_SNAP) * TEMP_SNAP)
}

function emptyStatus() {
  return {
    ok: false,
    timezone: "",
    latitude: 0,
    longitude: 0,
    locationSource: "",
    sunrise: "",
    sunset: "",
    estimated: false,
    running: false,
    mode: "auto",
    daytime: false,
    generated: false,
    setup: false,
    scheduledTemperature: null,
    scheduledSince: "",
    nextTemperature: null,
    nextAt: "",
    actualTemperature: null,
    dayTemp: null,
    eveningTemp: 0,
    nightTemp: 0,
    manualTemp: 0,
    keyboardTint: false,
    keyboardAvailable: false,
    ladder: ({})
  }
}

function parseStatus(raw) {
  try {
    var data = JSON.parse(String(raw || "").trim())
    if (!data || typeof data !== "object") return emptyStatus()
    var s = emptyStatus()
    s.ok = true
    s.timezone = String(data.timezone || "")
    s.latitude = Number(data.latitude) || 0
    s.longitude = Number(data.longitude) || 0
    s.locationSource = String(data.location_source || "")
    s.sunrise = String(data.sunrise || "")
    s.sunset = String(data.sunset || "")
    s.estimated = data.estimated === true
    s.running = data.running === true
    s.mode = (data.mode === "on" || data.mode === "off") ? data.mode : "auto"
    s.daytime = data.daytime === true
    s.generated = data.generated === true
    s.setup = data.setup === true
    s.scheduledTemperature = normaliseTemp(data.scheduled_temperature)
    s.scheduledSince = String(data.scheduled_since || "")
    s.nextTemperature = normaliseTemp(data.next_temperature)
    s.nextAt = String(data.next_at || "")
    s.actualTemperature = normaliseTemp(data.actual_temperature)
    s.dayTemp = normaliseTemp(data.day_temp)
    s.eveningTemp = Number(data.evening_temp) || 0
    s.nightTemp = Number(data.night_temp) || 0
    s.manualTemp = Number(data.manual_temp) || s.nightTemp
    s.keyboardTint = data.keyboard_tint === true
    s.keyboardAvailable = data.keyboard_available === true
    s.ladder = (data.ladder && typeof data.ladder === "object") ? data.ladder : ({})
    return s
  } catch (e) {
    return emptyStatus()
  }
}

// null is meaningful: it is the untinted day profile, not a missing value.
function normaliseTemp(value) {
  return (value === null || value === undefined) ? null : Number(value)
}

function tempLabel(temp) {
  return temp === null ? "off" : (String(temp) + "K")
}

// How far through the ramp a temperature sits, 0 at the evening end and 1 at
// the deepest point. Interpolated in mireds so it matches how the ladder was
// built, and so the colour swatch tracks what the eye actually sees.
function rampFraction(temp, eveningTemp, nightTemp) {
  if (temp === null || !eveningTemp || !nightTemp) return 0
  if (eveningTemp === nightTemp) return 1
  var m = 1e6 / temp
  var a = 1e6 / eveningTemp
  var b = 1e6 / nightTemp
  var f = (m - a) / (b - a)
  return Math.max(0, Math.min(1, f))
}

// A rough sRGB rendering of a black-body temperature, for the swatch only.
// Tanner Helland's approximation; close enough to read as "this is the tint".
function temperatureColor(kelvin) {
  if (kelvin === null) return Qt.rgba(1, 1, 1, 1)
  var t = Math.max(1000, Math.min(20000, kelvin)) / 100
  var r, g, b

  if (t <= 66) {
    r = 255
  } else {
    r = 329.698727446 * Math.pow(t - 60, -0.1332047592)
  }

  if (t <= 66) {
    g = 99.4708025861 * Math.log(t) - 161.1195681661
  } else {
    g = 288.1221695283 * Math.pow(t - 60, -0.0755148492)
  }

  if (t >= 66) {
    b = 255
  } else if (t <= 19) {
    b = 0
  } else {
    b = 138.5177312231 * Math.log(t - 10) - 305.0447927307
  }

  return Qt.rgba(clamp01(r / 255), clamp01(g / 255), clamp01(b / 255), 1)
}

function clamp01(v) {
  if (!isFinite(v)) return 0
  return Math.max(0, Math.min(1, v))
}

function locationLabel(status) {
  if (!status.ok) return ""
  var lat = status.latitude.toFixed(2)
  var lon = status.longitude.toFixed(2)
  return lat + ", " + lon
}

function summaryLine(status) {
  if (!status.ok) return "Night Light"
  if (status.mode === "off") return "Night light off (manual) · click to open"
  if (status.mode === "on") return "Night light on (manual) · " + tempLabel(status.manualTemp)
  if (!status.running) return "hyprsunset is not running"
  var now = tempLabel(status.scheduledTemperature)
  if (status.nextAt) return now + " · " + tempLabel(status.nextTemperature) + " at " + status.nextAt
  return now
}

// Which stage of the evening the ramp is in. Callers map this to a glyph --
// the names stay here so the indicator mark and the panel cannot disagree
// about where the boundaries are, while the glyphs live in the QML.
function rampStage(tinted, fraction, mode) {
  if (mode === "on") return "on"
  if (mode === "off") return "off"
  if (!tinted) return "day"
  if (fraction < 0.34) return "dusk"
  if (fraction < 0.75) return "night"
  return "deep"
}

function stageLabel(stage) {
  if (stage === "day") return "Night light off"
  if (stage === "on") return "On (manual)"
  if (stage === "off") return "Off (manual)"
  if (stage === "dusk") return "Warming"
  if (stage === "night") return "Warm"
  return "Warmest"
}

function pluginDirFromUrl(url) {
  var u = String(url || "")
  if (u.indexOf("file://") === 0) u = u.slice(7)
  return u.replace(/\/$/, "")
}

// One glyph per stage, shared by the bar button and the panel hero so the two
// can never disagree. Sun, sunset, moon, new moon as the evening deepens; a
// night bulb and a crossed-out sun for the manual holds.
function stageGlyph(stage) {
  if (stage === "dusk") return "\u{F059B}"   // md-weather_sunset_down
  if (stage === "night") return "\u{F0594}"  // md-weather_night
  if (stage === "deep") return "\u{F0F64}"   // md-moon_new
  if (stage === "on") return "\u{F1A4C}"     // md-lightbulb_night
  if (stage === "off") return "\u{F14E4}"    // md-weather_sunny_off
  return "\u{F0599}"                         // md-weather_sunny
}

// The hero's second line: what the screen is doing and what happens next.
function heroMeta(status, tinted, temperature) {
  if (!status.ok) return "No schedule loaded"
  if (!status.running) return "hyprsunset is not running"
  if (status.mode === "on") return "On until you pick Auto"
  if (status.mode === "off") return "Off until you pick Auto"
  if (!tinted) return status.nextAt ? ("Starts at dusk · " + status.nextAt) : "Untinted"
  var next = status.nextTemperature
  if (temperature !== null && temperature === status.nightTemp)
    return "Warmest · " + (next === null ? "day at " : "brightens at ") + status.nextAt
  if (next === null || (temperature !== null && next > temperature))
    return "Brightening · " + (next === null ? "day" : tempLabel(next)) + " at " + status.nextAt
  return "Warming · " + tempLabel(next) + " at " + status.nextAt
}

function modeCaption(mode, status) {
  if (mode === "off") return "Held untinted around the clock."
  return "Warms at dusk, clears at sunrise."
}

// Tonight's two phases, for the rows under the strip.
function phases(ladder) {
  if (!ladder || !ladder.ramp_start) return []
  var day = (ladder.day_temp === null || ladder.day_temp === undefined) ? null : ladder.day_temp
  var out = [{
    label: "Evening",
    times: ladder.ramp_start + " – " + ladder.ramp_end,
    temps: ladder.evening_temp + "→" + ladder.night_temp + "K"
  }]
  if (ladder.morning_start) {
    out.push({
      label: "Morning",
      times: morningStart(ladder) + " – " + ladder.day_start,
      temps: ladder.night_temp + "K→" + (day === null ? "day" : day + "K")
    })
  } else {
    out.push({ label: "Day", times: ladder.day_start, temps: day === null ? "untinted" : day + "K" })
  }
  return out
}

// Minutes past midnight, for a "HH:MM" the CLI printed.
function clockMinutes(hhmm) {
  var parts = String(hhmm || "0:0").split(":")
  return Number(parts[0]) * 60 + Number(parts[1])
}

// When the morning row starts, as the strip draws it.
//
// The generator anchors the morning ramp to dawn, but its leading rungs round
// back to the floor already on screen and are dropped as no-ops, so the ladder
// begins later than `morning_start` says. Report the first rung that actually
// changes the screen -- otherwise the row names a minute where nothing happens
// and disagrees with the strip beside it.
//
// The morning window is what picks those rungs out, not the gap in the strip:
// a long-enough evening can collapse rungs of its own and open a gap there too.
// Plain clock minutes are enough to test it. The window sits between dawn and
// sunrise, and every evening rung falls outside it -- above it before midnight,
// below it after, for a ramp that runs that late.
function morningStart(ladder) {
  if (!ladder || !ladder.morning_start) return ""
  var steps = ladder.steps || []
  var from = clockMinutes(ladder.morning_start)
  var until = clockMinutes(ladder.day_start)
  for (var i = 0; i < steps.length; i++) {
    var at = clockMinutes(steps[i].time)
    if (at >= from && at < until) return steps[i].time
  }
  // Nothing of the morning survived the collapse: the floor holds until the day
  // profile takes over. Name the anchor rather than inventing a time.
  return ladder.morning_start
}

// true where a step follows a long hold (the night at the floor), so the strip
// can open a visible gap between the evening and the morning.
function stepGaps(steps) {
  var out = []
  var prev = null
  var prevDay = null
  var shift = 0
  for (var i = 0; i < steps.length; i++) {
    if (prevDay !== null && steps[i].day !== prevDay) shift += 1440
    prevDay = steps[i].day
    var minutes = clockMinutes(steps[i].time) + shift
    out.push(prev !== null && minutes - prev > 60)
    prev = minutes
  }
  return out
}
