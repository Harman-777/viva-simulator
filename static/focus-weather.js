// focus-weather.js - Live Weather Widget & Custom Focus Timer Engine

// ==========================================
// 1. LIVE WEATHER WIDGET (Open-Meteo API)
// ==========================================
async function initWeatherWidget() {
  const weatherContainers = document.querySelectorAll(".weather-widget-container");
  if (!weatherContainers.length) return;

  // Default fallback location (New Delhi or London)
  let lat = 28.6139;
  let lon = 77.2090;
  let locationName = "Local Weather";

  function getWeatherIcon(code) {
    if (code === 0) return "☀️";
    if (code >= 1 && code <= 3) return "⛅";
    if (code >= 45 && code <= 48) return "🌫️";
    if (code >= 51 && code <= 67) return "🌧️";
    if (code >= 71 && code <= 77) return "❄️";
    if (code >= 80 && code <= 82) return "🌧️";
    if (code >= 85 && code <= 86) return "🌨️";
    if (code >= 95 && code <= 99) return "🌩️";
    return "🌤️";
  }

  function getWeatherText(code) {
    if (code === 0) return "Clear Sky";
    if (code >= 1 && code <= 3) return "Partly Cloudy";
    if (code >= 45 && code <= 48) return "Foggy";
    if (code >= 51 && code <= 67) return "Rainy";
    if (code >= 71 && code <= 77) return "Snowy";
    if (code >= 80 && code <= 82) return "Showers";
    if (code >= 95 && code <= 99) return "Thunderstorm";
    return "Fair";
  }

  async function fetchAndRenderWeather(latitude, longitude, name) {
    try {
      const url = `https://api.open-meteo.com/v1/forecast?latitude=${latitude}&longitude=${longitude}&current_weather=true`;
      const res = await fetch(url);
      if (!res.ok) throw new Error();
      const data = await res.json();
      const current = data.current_weather;
      
      const tempC = Math.round(current.temperature);
      const icon = getWeatherIcon(current.weathercode);
      const condition = getWeatherText(current.weathercode);

      weatherContainers.forEach(el => {
        el.innerHTML = `
          <div class="weather-pill" title="${name} · ${condition} (${current.windspeed} km/h wind)" onclick="toggleWeatherUnit(this, ${tempC})">
            <span class="weather-icon">${icon}</span>
            <span class="weather-temp" data-c="${tempC}">${tempC}°C</span>
            <span class="weather-loc">${name}</span>
          </div>
        `;
      });
    } catch {
      weatherContainers.forEach(el => {
        el.innerHTML = `
          <div class="weather-pill" title="Weather Unavailable">
            <span class="weather-icon">🌤️</span>
            <span class="weather-temp">24°C</span>
            <span class="weather-loc">Fair</span>
          </div>
        `;
      });
    }
  }

  if ("geolocation" in navigator) {
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        lat = pos.coords.latitude;
        lon = pos.coords.longitude;
        try {
          const revRes = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lon}`);
          if (revRes.ok) {
            const revData = await revRes.json();
            const city = revData.address.city || revData.address.town || revData.address.village || revData.address.county || "Local";
            locationName = city;
          }
        } catch {}
        fetchAndRenderWeather(lat, lon, locationName);
      },
      () => {
        fetchAndRenderWeather(lat, lon, locationName);
      },
      { timeout: 5000 }
    );
  } else {
    fetchAndRenderWeather(lat, lon, locationName);
  }
}

function toggleWeatherUnit(el, tempC) {
  const tempEl = el.querySelector(".weather-temp");
  if (!tempEl) return;
  if (tempEl.textContent.includes("C")) {
    const tempF = Math.round((tempC * 9/5) + 32);
    tempEl.textContent = `${tempF}°F`;
  } else {
    tempEl.textContent = `${tempC}°C`;
  }
}

// ==========================================
// 2. FOCUS TIMER WITH CUSTOM TIME OPTION
// ==========================================
let focusTimerInterval = null;
let focusTimerTotalSeconds = 25 * 60;
let focusTimerRemainingSeconds = 25 * 60;
let isFocusTimerRunning = false;

function playCompletionChime() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(587.33, ctx.currentTime);
    osc.frequency.setValueAtTime(880, ctx.currentTime + 0.15);
    gain.gain.setValueAtTime(0.3, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.8);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.8);
  } catch {}
}

function formatMMSS(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

function updateTimerDisplay() {
  const displayEls = document.querySelectorAll(".timer-display-time");
  const progressBars = document.querySelectorAll(".timer-progress-fill");
  const formatted = formatMMSS(focusTimerRemainingSeconds);
  const pct = Math.max(0, Math.min(100, ((focusTimerTotalSeconds - focusTimerRemainingSeconds) / focusTimerTotalSeconds) * 100));

  displayEls.forEach(el => el.textContent = formatted);
  progressBars.forEach(el => el.style.width = `${pct}%`);

  if (isFocusTimerRunning) {
    document.title = `⏱️ ${formatted} - Focus | viva.`;
  } else {
    document.title = document.title.replace(/^⏱️ \d{2}:\d{2} - Focus \| /, "");
  }
}

function startFocusTimer() {
  if (isFocusTimerRunning) return;
  if (focusTimerRemainingSeconds <= 0) {
    focusTimerRemainingSeconds = focusTimerTotalSeconds;
  }
  isFocusTimerRunning = true;
  updateTimerControls();

  focusTimerInterval = setInterval(() => {
    if (focusTimerRemainingSeconds > 0) {
      focusTimerRemainingSeconds--;
      updateTimerDisplay();
    } else {
      pauseFocusTimer();
      playCompletionChime();
      alert("⏱️ Focus Timer Complete! Great study session!");
    }
  }, 1000);
}

function pauseFocusTimer() {
  isFocusTimerRunning = false;
  if (focusTimerInterval) {
    clearInterval(focusTimerInterval);
    focusTimerInterval = null;
  }
  updateTimerControls();
  updateTimerDisplay();
}

function resetFocusTimer() {
  pauseFocusTimer();
  focusTimerRemainingSeconds = focusTimerTotalSeconds;
  updateTimerDisplay();
}

function setPresetTimer(minutes) {
  pauseFocusTimer();
  focusTimerTotalSeconds = minutes * 60;
  focusTimerRemainingSeconds = focusTimerTotalSeconds;
  updateTimerDisplay();
  
  document.querySelectorAll(".timer-preset-btn").forEach(btn => {
    const btnMins = parseInt(btn.dataset.minutes);
    btn.classList.toggle("active-preset", btnMins === minutes);
  });
}

function setCustomTimer(customMinutes) {
  const mins = parseInt(customMinutes);
  if (isNaN(mins) || mins < 1 || mins > 300) {
    alert("Please enter a valid custom time between 1 and 300 minutes.");
    return false;
  }
  setPresetTimer(mins);
  return true;
}

function updateTimerControls() {
  const startBtns = document.querySelectorAll(".timer-start-btn");
  const pauseBtns = document.querySelectorAll(".timer-pause-btn");

  startBtns.forEach(btn => btn.style.display = isFocusTimerRunning ? "none" : "inline-flex");
  pauseBtns.forEach(btn => btn.style.display = isFocusTimerRunning ? "inline-flex" : "none");
}

document.addEventListener("DOMContentLoaded", () => {
  initWeatherWidget();
  updateTimerDisplay();
});
