// Legacy redirect bridge to unified focus-tools.js
if (!window.toggleWeatherUnit) {
  const s = document.createElement("script");
  s.src = "/static/focus-tools.js";
  document.head.appendChild(s);
}
