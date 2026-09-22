/**
 * Viva AI — Toast & Modal Notification System
 * Non-blocking, accessible, glassmorphic notifications and confirm modals.
 */
(function (global) {
  'use strict';

  // Ensure Toast container exists
  function getToastContainer() {
    let container = document.getElementById('viva-toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'viva-toast-container';
      container.className = 'toast-container';
      document.body.appendChild(container);
    }
    return container;
  }

  function showToast(message, type, duration) {
    type = type || 'info';
    duration = duration !== undefined ? duration : 3500;
    const container = getToastContainer();
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    const icons = {
      success: '✓',
      error: '✕',
      warning: '⚠️',
      info: 'ℹ️'
    };

    toast.innerHTML = `
      <span class="toast-icon">${icons[type] || 'ℹ️'}</span>
      <div class="toast-content">${escapeHtml(message)}</div>
      <button type="button" class="toast-close" aria-label="Close">✕</button>
    `;

    toast.querySelector('.toast-close').addEventListener('click', () => {
      dismissToast(toast);
    });

    container.appendChild(toast);

    // Trigger enter animation
    requestAnimationFrame(() => {
      toast.classList.add('toast-visible');
    });

    if (duration > 0) {
      setTimeout(() => {
        dismissToast(toast);
      }, duration);
    }

    return toast;
  }

  function dismissToast(toast) {
    if (!toast || !toast.parentNode) return;
    toast.classList.remove('toast-visible');
    toast.classList.add('toast-hiding');
    setTimeout(() => {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 250);
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
  }

  const Toast = {
    show: showToast,
    success(msg, duration) { return showToast(msg, 'success', duration); },
    error(msg, duration) { return showToast(msg, 'error', duration || 4500); },
    warning(msg, duration) { return showToast(msg, 'warning', duration || 4000); },
    info(msg, duration) { return showToast(msg, 'info', duration); }
  };

  // Modern Accessible Confirm Modal
  const Modal = {
    confirm(title, message, options) {
      options = options || {};
      return new Promise((resolve) => {
        const confirmText = options.confirmText || 'Confirm';
        const cancelText = options.cancelText || 'Cancel';
        const isDanger = options.danger || false;

        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.innerHTML = `
          <div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
            <h3 id="modalTitle" class="modal-title">${escapeHtml(title)}</h3>
            <p class="modal-body">${escapeHtml(message)}</p>
            <div class="modal-actions">
              <button type="button" class="button button-quiet modal-cancel-btn">${escapeHtml(cancelText)}</button>
              <button type="button" class="button ${isDanger ? 'button-danger' : 'button-primary'} modal-confirm-btn">${escapeHtml(confirmText)}</button>
            </div>
          </div>
        `;

        function cleanup() {
          overlay.classList.remove('modal-visible');
          setTimeout(() => {
            if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
          }, 200);
        }

        overlay.querySelector('.modal-cancel-btn').addEventListener('click', () => {
          cleanup();
          resolve(false);
        });

        overlay.querySelector('.modal-confirm-btn').addEventListener('click', () => {
          cleanup();
          resolve(true);
        });

        overlay.addEventListener('click', (e) => {
          if (e.target === overlay) {
            cleanup();
            resolve(false);
          }
        });

        document.body.appendChild(overlay);
        requestAnimationFrame(() => {
          overlay.classList.add('modal-visible');
          const confirmBtn = overlay.querySelector('.modal-confirm-btn');
          if (confirmBtn) confirmBtn.focus();
        });
      });
    }
  };

  global.Toast = Toast;
  global.Modal = Modal;
})(window);
