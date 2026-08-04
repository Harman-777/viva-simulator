// focus-timer.js - Advanced Student Focus & Study Productivity Suite

(function () {
  // Timer State
  let timerInterval = null;
  let timerMode = "focus"; // 'focus', 'shortBreak', 'longBreak'
  let totalSeconds = 25 * 60;
  let remainingSeconds = 25 * 60;
  let isRunning = false;
  let completedSessionsToday = 0;
  let totalMinutesToday = 0;

  let audioCtx = null;
  const STORAGE_ANALYTICS_KEY = "viva_focus_analytics_" + new Date().toISOString().slice(0, 10);
  const STORAGE_GOAL_KEY = "viva_focus_current_goal";

  // Load analytics
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

  // Play clean dual-tone completion chime
  function playCompletionChime() {
    try {
      const ctx = getAudioContext();
      const osc1 = ctx.createOscillator();
      const osc2 = ctx.createOscillator();
      const gain = ctx.createGain();

      osc1.type = "sine";
      osc2.type = "triangle";
      osc1.frequency.setValueAtTime(523.25, ctx.currentTime); // C5
      osc2.frequency.setValueAtTime(659.25, ctx.currentTime + 0.15); // E5

      gain.gain.setValueAtTime(0.25, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.9);

      osc1.connect(gain);
      osc2.connect(gain);
      gain.connect(ctx.destination);

      osc1.start();
      osc2.start(ctx.currentTime + 0.15);
      osc1.stop(ctx.currentTime + 0.9);
      osc2.stop(ctx.currentTime + 0.9);
    } catch {}
  }

  function formatMMSS(sec) {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }

  function updateTimerUI() {
    const displayEls = document.querySelectorAll(".timer-display-time");
    const progressFills = document.querySelectorAll(".timer-progress-fill");
    const modeBadges = document.querySelectorAll(".timer-mode-badge");
    const analyticsText = document.querySelectorAll(".timer-analytics-text");

    const formatted = formatMMSS(remainingSeconds);
    const pct = Math.max(0, Math.min(100, ((totalSeconds - remainingSeconds) / totalSeconds) * 100));

    displayEls.forEach(el => el.textContent = formatted);
    progressFills.forEach(el => el.style.width = `${pct}%`);

    const modeLabels = {
      focus: "🎯 Focus Session",
      shortBreak: "☕ Short Break (5m)",
      longBreak: "🧘 Long Break (15m)"
    };
    modeBadges.forEach(el => {
      el.textContent = modeLabels[timerMode] || "🎯 Focus Session";
      el.className = `timer-mode-badge mode-${timerMode}`;
    });

    analyticsText.forEach(el => {
      el.textContent = `${completedSessionsToday} sessions completed today (${totalMinutesToday} mins total)`;
    });

    if (isRunning) {
      document.title = `⏱️ ${formatted} (${timerMode === 'focus' ? 'Focus' : 'Break'}) - viva.`;
    } else {
      document.title = document.title.replace(/^⏱️ \d{2}:\d{2} \([^\)]+\) - viva\.?/, "");
    }
  }

  function startTimer() {
    if (isRunning) return;
    if (remainingSeconds <= 0) {
      remainingSeconds = totalSeconds;
    }
    isRunning = true;
    updateTimerControlsUI();

    timerInterval = setInterval(() => {
      if (remainingSeconds > 0) {
        remainingSeconds--;
        updateTimerUI();
      } else {
        onTimerComplete();
      }
    }, 1000);
  }

  function pauseTimer() {
    isRunning = false;
    if (timerInterval) {
      clearInterval(timerInterval);
      timerInterval = null;
    }
    updateTimerControlsUI();
    updateTimerUI();
  }

  function resetTimer() {
    pauseTimer();
    remainingSeconds = totalSeconds;
    updateTimerUI();
  }

  function onTimerComplete() {
    pauseTimer();
    playCompletionChime();

    if (timerMode === "focus") {
      const minsSpent = Math.round(totalSeconds / 60);
      completedSessionsToday++;
      totalMinutesToday += minsSpent;
      saveAnalytics();
      updateTimerUI();

      alert(`🎉 Focus Session Complete! You studied for ${minsSpent} minutes. Time for a 5-minute break!`);
      setTimerMode("shortBreak", 5);
    } else {
      alert("☕ Break Complete! Ready to start your next Focus Session?");
      setTimerMode("focus", 25);
    }
  }

  function setTimerMode(mode, minutes) {
    pauseTimer();
    timerMode = mode;
    totalSeconds = minutes * 60;
    remainingSeconds = totalSeconds;

    document.querySelectorAll(".timer-preset-btn").forEach(btn => {
      const btnMins = parseInt(btn.dataset.minutes);
      btn.classList.toggle("active-preset", btnMins === minutes);
    });

    updateTimerUI();
  }

  function setCustomTimer(customMinutes) {
    const mins = parseInt(customMinutes);
    if (isNaN(mins) || mins < 1 || mins > 300) {
      alert("Please enter a valid custom time between 1 and 300 minutes.");
      return false;
    }
    setTimerMode("focus", mins);
    return true;
  }

  function updateTimerControlsUI() {
    const startBtns = document.querySelectorAll(".timer-start-btn");
    const pauseBtns = document.querySelectorAll(".timer-pause-btn");

    startBtns.forEach(btn => btn.style.display = isRunning ? "none" : "inline-flex");
    pauseBtns.forEach(btn => btn.style.display = isRunning ? "inline-flex" : "none");
  }

  // Global functions exposed to inline onclick events
  window.startFocusTimer = startTimer;
  window.pauseFocusTimer = pauseTimer;
  window.resetFocusTimer = resetTimer;
  window.setPresetTimer = (mins) => {
    if (mins === 5) setTimerMode("shortBreak", 5);
    else if (mins === 15) setTimerMode("longBreak", 15);
    else setTimerMode("focus", mins);
  };
  window.setCustomTimer = setCustomTimer;

  document.addEventListener("DOMContentLoaded", () => {
    updateTimerUI();

    // Goal Input restore & save listener
    const goalInput = document.getElementById("focusGoalInput");
    if (goalInput) {
      goalInput.value = localStorage.getItem(STORAGE_GOAL_KEY) || "";
      goalInput.addEventListener("input", () => {
        localStorage.setItem(STORAGE_GOAL_KEY, goalInput.value);
      });
    }
  });
})();
