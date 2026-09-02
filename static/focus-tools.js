/**
 * Viva AI — Focus Tools, Audio Synthesizer & Speech Suite
 * Unified Pomodoro Timer, Ambient Sound Synthesizer, Live Weather, Oral Examiner Voice (TTS), and Speech-to-Text (STT).
 */
(function (global) {
  'use strict';

  // ==========================================
  // 1. LIVE WEATHER WIDGET (Open-Meteo API)
  // ==========================================
  async function initWeatherWidget() {
    const containers = document.querySelectorAll(".weather-widget-container, #weatherPill");
    if (!containers.length) return;

    let lat = 28.6139;
    let lon = 77.2090;
    let locationName = "Local";

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

    async function fetchAndRender(latitude, longitude, name) {
      try {
        const url = `https://api.open-meteo.com/v1/forecast?latitude=${latitude}&longitude=${longitude}&current_weather=true`;
        const res = await fetch(url);
        if (!res.ok) throw new Error("Weather fetch failed");
        const data = await res.json();
        const current = data.current_weather;
        const tempC = Math.round(current.temperature);
        const icon = getWeatherIcon(current.weathercode);
        const condition = getWeatherText(current.weathercode);

        containers.forEach(el => {
          el.style.display = "inline-flex";
          el.innerHTML = `
            <span class="weather-icon">${icon}</span>
            <span class="weather-temp" data-c="${tempC}">${tempC}°C</span>
            <span class="weather-loc" style="font-size:11px; opacity:0.8;">${name}</span>
          `;
          el.title = `${name} · ${condition} (${current.windspeed} km/h wind) · Click to switch °C/°F`;
          el.onclick = () => toggleWeatherUnit(el, tempC);
        });
      } catch (e) {
        containers.forEach(el => {
          el.style.display = "inline-flex";
          el.innerHTML = `
            <span class="weather-icon">🌤️</span>
            <span class="weather-temp">24°C</span>
            <span class="weather-loc" style="font-size:11px; opacity:0.8;">Local</span>
          `;
          el.title = "Local Weather";
        });
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

    if ("geolocation" in navigator) {
      navigator.geolocation.getCurrentPosition(
        async (pos) => {
          lat = pos.coords.latitude;
          lon = pos.coords.longitude;
          try {
            const revRes = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lon}`);
            if (revRes.ok) {
              const revData = await revRes.json();
              locationName = revData.address.city || revData.address.town || revData.address.village || "Local";
            }
          } catch {}
          fetchAndRender(lat, lon, locationName);
        },
        () => fetchAndRender(lat, lon, locationName),
        { timeout: 3500 }
      );
    } else {
      fetchAndRender(lat, lon, locationName);
    }
  }

  // ==========================================
  // 2. FOCUS POMODORO & WEB AUDIO SYNTHESIZER
  // ==========================================
  let timerInterval = null;
  let timerMode = "focus";
  let totalSeconds = 25 * 60;
  let remainingSeconds = 25 * 60;
  let isRunning = false;
  let completedSessionsToday = 0;
  let totalMinutesToday = 0;
  let audioCtx = null;
  let ambientNoiseNode = null;
  let ambientGainNode = null;
  let currentAmbientType = "none";

  const STORAGE_ANALYTICS_KEY = "viva_focus_analytics_" + new Date().toISOString().slice(0, 10);
  const STORAGE_GOAL_KEY = "viva_focus_current_goal";

  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_ANALYTICS_KEY));
    if (saved) {
      completedSessionsToday = saved.sessions || 0;
      totalMinutesToday = saved.minutes || 0;
    }
  } catch {}

  function saveAnalytics() {
    try {
      localStorage.setItem(STORAGE_ANALYTICS_KEY, JSON.stringify({
        sessions: completedSessionsToday,
        minutes: totalMinutesToday
      }));
    } catch {}
  }

  function getAudioContext() {
    if (!audioCtx) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioCtx.state === "suspended") {
      audioCtx.resume();
    }
    return audioCtx;
  }

  function playCompletionChime() {
    try {
      const ctx = getAudioContext();
      const osc1 = ctx.createOscillator();
      const osc2 = ctx.createOscillator();
      const osc3 = ctx.createOscillator();
      const gain = ctx.createGain();

      osc1.type = "sine";
      osc2.type = "triangle";
      osc3.type = "sine";

      osc1.frequency.setValueAtTime(523.25, ctx.currentTime); // C5
      osc2.frequency.setValueAtTime(659.25, ctx.currentTime + 0.12); // E5
      osc3.frequency.setValueAtTime(783.99, ctx.currentTime + 0.24); // G5

      gain.gain.setValueAtTime(0.2, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 1.2);

      osc1.connect(gain);
      osc2.connect(gain);
      osc3.connect(gain);
      gain.connect(ctx.destination);

      osc1.start();
      osc2.start(ctx.currentTime + 0.12);
      osc3.start(ctx.currentTime + 0.24);

      osc1.stop(ctx.currentTime + 1.2);
      osc2.stop(ctx.currentTime + 1.2);
      osc3.stop(ctx.currentTime + 1.2);
    } catch {}
  }

  // Web Audio Ambient Noise Generator (Rain, Brown, White noise)
  function setAmbientSound(type) {
    if (ambientNoiseNode) {
      try {
        ambientNoiseNode.stop();
        ambientNoiseNode.disconnect();
      } catch {}
      ambientNoiseNode = null;
    }

    currentAmbientType = type;
    if (type === "none" || !type) return;

    try {
      const ctx = getAudioContext();
      const bufferSize = 2 * ctx.sampleRate;
      const noiseBuffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
      const output = noiseBuffer.getChannelData(0);

      if (type === "white") {
        for (let i = 0; i < bufferSize; i++) {
          output[i] = Math.random() * 2 - 1;
        }
      } else if (type === "brown") {
        let lastOut = 0.0;
        for (let i = 0; i < bufferSize; i++) {
          const white = Math.random() * 2 - 1;
          output[i] = (lastOut + (0.02 * white)) / 1.02;
          lastOut = output[i];
          output[i] *= 3.5;
        }
      } else if (type === "rain") {
        let lastOut = 0.0;
        for (let i = 0; i < bufferSize; i++) {
          const white = Math.random() * 2 - 1;
          output[i] = (lastOut + (0.05 * white)) / 1.05;
          lastOut = output[i];
          if (Math.random() > 0.998) {
            output[i] += (Math.random() * 0.4);
          }
        }
      }

      const whiteNoise = ctx.createBufferSource();
      whiteNoise.buffer = noiseBuffer;
      whiteNoise.loop = true;

      ambientGainNode = ctx.createGain();
      ambientGainNode.gain.setValueAtTime(0.06, ctx.currentTime);

      whiteNoise.connect(ambientGainNode);
      ambientGainNode.connect(ctx.destination);
      whiteNoise.start(0);

      ambientNoiseNode = whiteNoise;
    } catch (e) {
      console.warn("Could not start ambient audio:", e);
    }
  }

  function formatMMSS(sec) {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }

  function updateTimerUI() {
    const displayEls = document.querySelectorAll("#pomodoroDisplay, .timer-display-time, .timer-digits");
    const progressFills = document.querySelectorAll(".timer-progress-fill, #pomodoroProgressBar");
    const modeBadges = document.querySelectorAll(".timer-mode-badge");
    const tallyEls = document.querySelectorAll("#focusSessionTally, .timer-analytics-text");
    const startBtns = document.querySelectorAll("#pomodoroStartBtn, .timer-start-btn");

    const formatted = formatMMSS(remainingSeconds);
    const pct = Math.max(0, Math.min(100, ((totalSeconds - remainingSeconds) / totalSeconds) * 100));

    displayEls.forEach(el => el.textContent = formatted);
    progressFills.forEach(el => el.style.width = `${pct}%`);

    const modeLabels = {
      focus: "🎯 Focus Session",
      shortBreak: "☕ Short Break",
      longBreak: "🧘 Long Break"
    };

    modeBadges.forEach(el => {
      el.textContent = modeLabels[timerMode] || "🎯 Focus Session";
      el.className = `badge badge-${timerMode === 'focus' ? 'primary' : 'success'} timer-mode-badge`;
    });

    tallyEls.forEach(el => {
      el.textContent = `${completedSessionsToday} completed today (${totalMinutesToday} mins study time)`;
    });

    startBtns.forEach(btn => {
      btn.textContent = isRunning ? "Pause ⏸" : "Start Focus ▶";
      btn.className = isRunning ? "button button-secondary" : "button button-primary";
    });

    if (isRunning) {
      document.title = `⏱️ ${formatted} (${timerMode === 'focus' ? 'Focus' : 'Break'}) · Viva Simulator`;
    }
  }

  function startTimer() {
    if (isRunning) return;
    if (remainingSeconds <= 0) remainingSeconds = totalSeconds;
    isRunning = true;
    updateTimerUI();

    timerInterval = setInterval(() => {
      if (remainingSeconds > 0) {
        remainingSeconds--;
        updateTimerUI();
      } else {
        onComplete();
      }
    }, 1000);
  }

  function pauseTimer() {
    isRunning = false;
    if (timerInterval) {
      clearInterval(timerInterval);
      timerInterval = null;
    }
    updateTimerUI();
  }

  function toggleFocusTimer() {
    if (isRunning) {
      pauseTimer();
    } else {
      startTimer();
    }
  }

  function resetTimer() {
    pauseTimer();
    remainingSeconds = totalSeconds;
    updateTimerUI();
  }

  function onComplete() {
    pauseTimer();
    playCompletionChime();

    if (timerMode === "focus") {
      const minsSpent = Math.round(totalSeconds / 60);
      completedSessionsToday++;
      totalMinutesToday += minsSpent;
      saveAnalytics();
      updateTimerUI();

      if (global.Toast) {
        global.Toast.success(`🎉 Focus Session Complete! You logged ${minsSpent}m of deep viva preparation. Time for a break!`, 6000);
      }
      setMode("shortBreak", 5);
    } else {
      if (global.Toast) {
        global.Toast.info("☕ Break Complete! Ready to resume your Viva practice?", 5000);
      }
      setMode("focus", 25);
    }
  }

  function setMode(mode, minutes) {
    pauseTimer();
    timerMode = mode;
    totalSeconds = minutes * 60;
    remainingSeconds = totalSeconds;

    document.querySelectorAll(".timer-preset-btn, .button-compact").forEach(btn => {
      const txt = btn.textContent.toLowerCase();
      if (txt.includes(`${minutes}m`)) {
        btn.classList.add("active");
      } else if (txt.includes("focus") || txt.includes("break")) {
        btn.classList.remove("active");
      }
    });

    updateTimerUI();
  }

  global.startFocusTimer = startTimer;
  global.pauseFocusTimer = pauseTimer;
  global.toggleFocusTimer = toggleFocusTimer;
  global.resetFocusTimer = resetTimer;
  global.setTimerPreset = (mins) => {
    if (mins === 5) setMode("shortBreak", 5);
    else if (mins === 15) setMode("longBreak", 15);
    else setMode("focus", mins);
  };
  global.setAmbientSound = setAmbientSound;

  // ==========================================
  // 3. ORAL EXAMINER VOICE (Text-to-Speech)
  // ==========================================
  let isSpeaking = false;

  function speakExaminerQuestion(text, onEndCallback) {
    if (!("speechSynthesis" in window)) {
      if (global.Toast) global.Toast.warning("Text-to-Speech is not supported in this browser.");
      return;
    }

    window.speechSynthesis.cancel();
    if (!text || !text.trim()) return;

    const utterance = new SpeechSynthesisUtterance(text.trim());
    utterance.rate = 0.95;
    utterance.pitch = 1.0;
    utterance.lang = "en-US";

    const voices = window.speechSynthesis.getVoices();
    const englishVoice = voices.find(v => v.lang.startsWith("en") && (v.name.includes("Google") || v.name.includes("Natural") || v.name.includes("Academic") || v.name.includes("Daniel") || v.name.includes("Samantha"))) || voices.find(v => v.lang.startsWith("en"));
    if (englishVoice) {
      utterance.voice = englishVoice;
    }

    isSpeaking = true;
    utterance.onend = () => {
      isSpeaking = false;
      if (onEndCallback) onEndCallback();
    };
    utterance.onerror = () => {
      isSpeaking = false;
      if (onEndCallback) onEndCallback();
    };

    window.speechSynthesis.speak(utterance);
  }

  function stopExaminerSpeech() {
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      isSpeaking = false;
    }
  }

  global.speakExaminerQuestion = speakExaminerQuestion;
  global.stopExaminerSpeech = stopExaminerSpeech;

  // ==========================================
  // 4. WEB SPEECH ORAL DICTATION ENGINE (STT)
  // ==========================================
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  global.setupVoiceDictation = function (textarea, micBtn, onTranscript) {
    if (!SpeechRecognition) {
      if (micBtn) {
        micBtn.title = "Speech recognition is not supported in this browser (Chrome/Edge recommended)";
        micBtn.style.opacity = "0.6";
      }
      return null;
    }

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    let isRecognizing = false;

    micBtn.addEventListener("click", (e) => {
      e.preventDefault();
      if (isRecognizing) {
        recognition.stop();
      } else {
        try {
          recognition.start();
        } catch (err) {
          console.warn("Recognition already started:", err);
        }
      }
    });

    recognition.onstart = () => {
      isRecognizing = true;
      micBtn.classList.add("recording");
      micBtn.innerHTML = "🎙️ <span class=\"btn-text\">Listening... (Click to Stop)</span>";
      if (global.Toast) global.Toast.info("Microphone active. Speak your oral answer clearly.", 2000);
    };

    recognition.onend = () => {
      isRecognizing = false;
      micBtn.classList.remove("recording");
      micBtn.innerHTML = "🎙️ <span class=\"btn-text\">Speak Answer</span>";
    };

    recognition.onerror = (event) => {
      console.warn("Speech recognition error:", event.error);
      recognition.stop();
    };

    recognition.onresult = (event) => {
      let finalTranscript = "";
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        if (event.results[i].isFinal) {
          finalTranscript += event.results[i][0].transcript + " ";
        }
      }
      if (finalTranscript) {
        const start = textarea.value.trim() ? textarea.value.trim() + " " : "";
        textarea.value = start + finalTranscript.trim();
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
        if (onTranscript) onTranscript(textarea.value);
      }
    };

    return recognition;
  };

  // ==========================================
  // 5. AUTO-INITIALIZATION ON DOM LOAD
  // ==========================================
  document.addEventListener("DOMContentLoaded", () => {
    initWeatherWidget();
    updateTimerUI();

    const goalInput = document.getElementById("focusObjectiveInput") || document.getElementById("focusGoalInput");
    if (goalInput) {
      goalInput.value = localStorage.getItem(STORAGE_GOAL_KEY) || "";
      goalInput.addEventListener("input", () => {
        localStorage.setItem(STORAGE_GOAL_KEY, goalInput.value);
      });
    }

    // Auto-attach voice dictation if elements exist
    document.querySelectorAll(".voice-dictation-btn").forEach(btn => {
      const targetId = btn.getAttribute("data-target");
      const targetEl = targetId ? document.getElementById(targetId) : btn.closest(".voice-input-wrapper")?.querySelector("textarea");
      if (targetEl) {
        global.setupVoiceDictation(targetEl, btn);
      }
    });
  });

})(window);
