/**
 * viva. — Unified Teacher Auth Controller
 * Single source of truth for authentication, route protection, and session management.
 */
(function (global) {
  'use strict';

  const AUTH_ME_URL = '/api/auth/me';
  const AUTH_LOGOUT_URL = '/api/auth/logout';
  const LOGIN_PATH = '/teacher/login';

  let currentTeacher = null;

  function getTargetRedirect() {
    try {
      const params = new URLSearchParams(window.location.search);
      const target = params.get('redirect') || params.get('next');
      if (target && target.startsWith('/') && !target.startsWith('//')) {
        return target;
      }
    } catch (e) {}
    return '/teacher';
  }

  const Auth = {
    get teacher() {
      return currentTeacher;
    },

    async check() {
      const isLoginPage = window.location.pathname === LOGIN_PATH;
      try {
        const res = await fetch(AUTH_ME_URL);
        if (res.status === 401) {
          if (!isLoginPage) {
            const redirectParam = encodeURIComponent(window.location.pathname + window.location.search);
            window.location.href = `${LOGIN_PATH}?redirect=${redirectParam}`;
          }
          return null;
        }

        if (!res.ok) {
          if (isLoginPage) return null;
          console.warn('[Auth] Server returned non-ok status:', res.status);
          return currentTeacher;
        }

        const data = await res.json();
        currentTeacher = data.teacher;

        if (!currentTeacher) {
          if (!isLoginPage) {
            const redirectParam = encodeURIComponent(window.location.pathname + window.location.search);
            window.location.href = `${LOGIN_PATH}?redirect=${redirectParam}`;
          }
          return null;
        }

        // User IS authenticated
        if (isLoginPage) {
          window.location.href = getTargetRedirect();
          return currentTeacher;
        }

        // Update UI displays if elements exist
        const displayEl = document.getElementById('teacherDisplay');
        if (displayEl) {
          displayEl.textContent = `Signed in as ${currentTeacher.display_name}`;
        }
        const nameEl = document.getElementById('teacherName');
        if (nameEl && nameEl.tagName !== 'INPUT') {
          nameEl.textContent = currentTeacher.display_name;
        }

        return currentTeacher;
      } catch (err) {
        console.warn('[Auth] Network error during auth check:', err);
        if (isLoginPage) return null;
        return currentTeacher;
      }
    },

    async logout() {
      try {
        await fetch(AUTH_LOGOUT_URL, { method: 'POST' });
      } catch (e) {
        console.error('[Auth] Logout call error:', e);
      }
      window.location.href = LOGIN_PATH;
    }
  };

  global.Auth = Auth;
})(window);
