/**
 * Viva AI — Theme Manager
 * Obsidian Aurora Light/Dark Theme Controller
 */
(function () {
  'use strict';

  const STORAGE_KEY = 'viva_theme_preference';

  function getPreferredTheme() {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'light' || saved === 'dark') {
      return saved;
    }
    // Default to dark mode for Obsidian Aurora aesthetic
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    const btns = document.querySelectorAll('.theme-toggle-btn');
    btns.forEach(btn => {
      if (theme === 'light') {
        btn.innerHTML = '🌙 <span class="theme-btn-text">Dark</span>';
        btn.title = 'Switch to Obsidian Dark';
      } else {
        btn.innerHTML = '☀️ <span class="theme-btn-text">Light</span>';
        btn.title = 'Switch to Luminous Light';
      }
    });
  }

  window.toggleTheme = function () {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    localStorage.setItem(STORAGE_KEY, next);
    applyTheme(next);
  };

  // Immediate execution before DOM paint to prevent flash
  const initialTheme = getPreferredTheme();
  document.documentElement.setAttribute('data-theme', initialTheme);

  document.addEventListener('DOMContentLoaded', () => {
    applyTheme(initialTheme);
  });
})();
