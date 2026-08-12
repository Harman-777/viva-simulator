(function () {
  const saved = localStorage.getItem("viva_theme");
  const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  const theme = saved || (prefersDark ? "dark" : "light");
  if (theme === "dark") {
    document.documentElement.setAttribute("data-theme", "dark");
  }
})();

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme");
  const next = current === "dark" ? "light" : "dark";
  if (next === "dark") {
    document.documentElement.setAttribute("data-theme", "dark");
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
  localStorage.setItem("viva_theme", next);
  updateThemeButtons();
}

function updateThemeButtons() {
  const isDark = document.documentElement.getAttribute("data-theme") === "dark";
  document.querySelectorAll(".theme-toggle-btn").forEach(btn => {
    btn.innerHTML = isDark ? '☀️ <span class="theme-btn-text">Light</span>' : '🌙 <span class="theme-btn-text">Dark</span>';
    btn.setAttribute("aria-label", isDark ? "Switch to light theme" : "Switch to dark theme");
  });
}

document.addEventListener("DOMContentLoaded", updateThemeButtons);
