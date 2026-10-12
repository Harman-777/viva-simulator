/**
 * Viva Simulator — Native Mobile Bridge & Speech Engine
 * Unifies Android Native Bridge (using user phone's default TTS & SpeechRecognizer)
 * with Web Speech API fallbacks for seamless cross-platform oral examination.
 */
(function (global) {
  'use strict';

  const STORAGE_KEY_AUTO_SPEAK = 'viva_auto_speak_questions';

  const VivaMobile = {
    /**
     * Detect if running inside the official Viva Simulator Android APK
     */
    isNativeApp: function () {
      return Boolean(global.AndroidBridge && typeof global.AndroidBridge.isNativeApp === 'function');
    },

    /**
     * Query whether questions should be automatically read out when displayed
     */
    getAutoSpeak: function () {
      if (this.isNativeApp() && typeof global.AndroidBridge.getAutoSpeak === 'function') {
        try {
          return Boolean(global.AndroidBridge.getAutoSpeak());
        } catch (_) {}
      }
      return localStorage.getItem(STORAGE_KEY_AUTO_SPEAK) === 'true';
    },

    /**
     * Persist user's Auto-Speak preference
     */
    setAutoSpeak: function (enabled) {
      const val = Boolean(enabled);
      localStorage.setItem(STORAGE_KEY_AUTO_SPEAK, val ? 'true' : 'false');
      if (this.isNativeApp() && typeof global.AndroidBridge.setAutoSpeak === 'function') {
        try {
          global.AndroidBridge.setAutoSpeak(val);
        } catch (_) {}
      }
    },

    /**
     * Text-To-Speech (TTS) using user phone's default voice engine
     * Zero cloud latency, respects user device speed, pitch, and accent settings.
     */
    speak: function (text, onStart, onEnd) {
      if (!text || typeof text !== 'string') return;
      this.stopSpeaking();

      const cleanText = text.replace(/<[^>]*>/g, '').trim();
      if (!cleanText) return;

      if (this.isNativeApp() && typeof global.AndroidBridge.speak === 'function') {
        if (typeof onStart === 'function') onStart();
        global.AndroidBridge.speak(cleanText);

        // Native TTS completion watcher
        if (typeof onEnd === 'function') {
          let attempts = 0;
          const pollTimer = setInterval(function () {
            attempts++;
            const isSpeaking = global.AndroidBridge.isSpeaking && global.AndroidBridge.isSpeaking();
            if (!isSpeaking || attempts > 240) { // Max ~60 seconds
              clearInterval(pollTimer);
              onEnd();
            }
          }, 250);
        }
        return;
      }

      // Fallback: Web SpeechSynthesis (which on Android Chrome routes to the phone's default TTS)
      if ('speechSynthesis' in global) {
        global.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(cleanText);
        utterance.rate = 1.0;
        utterance.pitch = 1.0;
        if (typeof onStart === 'function') utterance.onstart = onStart;
        if (typeof onEnd === 'function') {
          utterance.onend = onEnd;
          utterance.onerror = onEnd;
        }
        global.speechSynthesis.speak(utterance);
      } else {
        if (typeof onEnd === 'function') onEnd();
      }
    },

    /**
     * Stop any currently ongoing speech playback
     */
    stopSpeaking: function () {
      if (this.isNativeApp() && typeof global.AndroidBridge.stopSpeaking === 'function') {
        try {
          global.AndroidBridge.stopSpeaking();
        } catch (_) {}
      }
      if ('speechSynthesis' in global) {
        try {
          global.speechSynthesis.cancel();
        } catch (_) {}
      }
    },

    /**
     * Speech-To-Text (STT) Dictation using user phone's default voice recognizer
     */
    _activeRecognition: null,
    _isListening: false,

    startListening: function (options) {
      const opts = options || {};
      const onResult = opts.onResult || function () {};
      const onPartial = opts.onPartial || function () {};
      const onError = opts.onError || function () {};
      const onStart = opts.onStart || function () {};
      const onEnd = opts.onEnd || function () {};

      if (this._isListening) {
        this.stopListening();
        return;
      }

      this._isListening = true;

      // Haptic feedback if supported
      this.vibrate(40);

      // 1. Native Android SpeechRecognizer Bridge
      if (this.isNativeApp() && typeof global.AndroidBridge.startListening === 'function') {
        global.onAndroidSpeechResult = function (transcript) {
          VivaMobile._isListening = false;
          onResult(transcript);
          onEnd();
        };
        global.onAndroidSpeechPartial = function (partial) {
          onPartial(partial);
        };
        global.onAndroidSpeechError = function (errCode) {
          VivaMobile._isListening = false;
          onError('Speech recognizer error: ' + errCode);
          onEnd();
        };

        if (typeof onStart === 'function') onStart();
        global.AndroidBridge.startListening();
        return;
      }

      // 2. Web Speech Recognition (Google Speech on Android Chrome, Safari dictation on iOS)
      const SpeechRecognition = global.SpeechRecognition || global.webkitSpeechRecognition;
      if (SpeechRecognition) {
        const recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = true;
        recognition.lang = navigator.language || 'en-US';

        recognition.onstart = function () {
          if (typeof onStart === 'function') onStart();
        };

        recognition.onresult = function (event) {
          let interimTranscript = '';
          let finalTranscript = '';
          for (let i = event.resultIndex; i < event.results.length; ++i) {
            if (event.results[i].isFinal) {
              finalTranscript += event.results[i][0].transcript;
            } else {
              interimTranscript += event.results[i][0].transcript;
            }
          }
          if (interimTranscript) onPartial(interimTranscript);
          if (finalTranscript) onResult(finalTranscript);
        };

        recognition.onerror = function (event) {
          VivaMobile._isListening = false;
          onError(event.error || 'Microphone error');
        };

        recognition.onend = function () {
          VivaMobile._isListening = false;
          if (typeof onEnd === 'function') onEnd();
        };

        this._activeRecognition = recognition;
        try {
          recognition.start();
        } catch (e) {
          this._isListening = false;
          onError(e.message);
          onEnd();
        }
      } else {
        this._isListening = false;
        onError('Voice recognition not supported on this device/browser.');
        onEnd();
      }
    },

    stopListening: function () {
      this._isListening = false;
      if (this.isNativeApp() && typeof global.AndroidBridge.stopListening === 'function') {
        try {
          global.AndroidBridge.stopListening();
        } catch (_) {}
      }
      if (this._activeRecognition) {
        try {
          this._activeRecognition.stop();
        } catch (_) {}
        this._activeRecognition = null;
      }
    },

    /**
     * Trigger Android or Web native share sheet
     */
    shareApp: function (customUrl, customMessage) {
      const url = customUrl || (global.location ? global.location.origin : 'https://viva-simulator-nu.vercel.app');
      const text = customMessage || 'Practice and master your technical viva oral exams with Viva Simulator — AI-scored oral examination platform: ' + url;

      if (this.isNativeApp() && typeof global.AndroidBridge.shareApp === 'function') {
        global.AndroidBridge.shareApp(url, text);
        return;
      }

      if (navigator.share) {
        navigator.share({
          title: 'Viva Simulator',
          text: text,
          url: url
        }).catch(function () {});
        return;
      }

      // Fallback: Copy to clipboard
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(function () {
          if (global.Toast) global.Toast.success('Viva Simulator download link copied to clipboard!');
        });
      } else {
        if (global.Toast) global.Toast.info('Share URL: ' + url);
      }
    },

    /**
     * Trigger haptic vibration on mobile devices
     */
    vibrate: function (ms) {
      const duration = ms || 40;
      if (this.isNativeApp() && typeof global.AndroidBridge.vibrate === 'function') {
        try {
          global.AndroidBridge.vibrate(duration);
        } catch (_) {}
        return;
      }
      if (navigator.vibrate) {
        navigator.vibrate(duration);
      }
    },

    /**
     * Download application APK directly
     */
    downloadApk: function () {
      const apkUrl = '/download/VivaSimulator.apk';
      if (this.isNativeApp() && typeof global.AndroidBridge.downloadFile === 'function') {
        global.AndroidBridge.downloadFile(
          global.location.origin + apkUrl,
          'VivaSimulator.apk',
          'application/vnd.android.package-archive'
        );
      } else {
        const a = document.createElement('a');
        a.href = apkUrl;
        a.download = 'VivaSimulator.apk';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      }
    },

    /**
     * Wire up any microphone dictation buttons present on the page
     */
    initDictationButtons: function () {
      const buttons = document.querySelectorAll('.voice-dictation-btn, #voiceDictationBtn');
      buttons.forEach(function (btn) {
        if (btn.__vivaBound) return;
        btn.__vivaBound = true;

        const targetId = btn.getAttribute('data-target');
        const targetInput = targetId ? document.getElementById(targetId) : null;
        const textSpan = btn.querySelector('.btn-text');
        const originalText = textSpan ? textSpan.textContent : 'Speak Answer';

        btn.addEventListener('click', function (e) {
          e.preventDefault();
          if (VivaMobile._isListening) {
            VivaMobile.stopListening();
            btn.classList.remove('recording');
            if (textSpan) textSpan.textContent = originalText;
            return;
          }

          let existingText = targetInput ? (targetInput.value || '') : '';
          if (existingText && !existingText.endsWith(' ') && !existingText.endsWith('\n')) {
            existingText += ' ';
          }

          VivaMobile.startListening({
            onStart: function () {
              btn.classList.add('recording');
              if (textSpan) textSpan.textContent = 'Listening...';
              if (global.Toast) global.Toast.info('Microphone active. Speak clearly into your phone.');
            },
            onPartial: function (partial) {
              if (targetInput) {
                targetInput.value = existingText + partial;
                targetInput.dispatchEvent(new Event('input', { bubbles: true }));
              }
            },
            onResult: function (finalText) {
              if (targetInput) {
                existingText += finalText + ' ';
                targetInput.value = existingText;
                targetInput.dispatchEvent(new Event('input', { bubbles: true }));
              }
            },
            onError: function (err) {
              if (global.Toast) global.Toast.warning(err);
            },
            onEnd: function () {
              btn.classList.remove('recording');
              if (textSpan) textSpan.textContent = originalText;
            }
          });
        });
      });
    }
  };

  // Expose globally
  global.VivaMobile = VivaMobile;

  // Preserve and bind legacy hooks
  global.speakExaminerQuestion = function (text, onEnd) {
    VivaMobile.speak(text, null, onEnd);
  };
  global.stopExaminerSpeech = function () {
    VivaMobile.stopSpeaking();
  };

  // Auto-init on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      VivaMobile.initDictationButtons();
    });
  } else {
    VivaMobile.initDictationButtons();
  }

})(typeof window !== 'undefined' ? window : this);
