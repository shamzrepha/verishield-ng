/* Shared utilities for VeriShield NG pages: accessibility persistence, PWA registration, escaping. */
(() => {
  "use strict";

  const TEXT_KEY = "vs_pref_large_text";
  const CONTRAST_KEY = "vs_pref_high_contrast";
  let deferredInstallPrompt = null;

  function escapeHtml(text) {
    return String(text ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function applyStoredPrefs() {
    if (localStorage.getItem(TEXT_KEY) === "true") {
      document.body.classList.add("large-text");
    }
    if (localStorage.getItem(CONTRAST_KEY) === "true") {
      document.body.classList.add("high-contrast");
    }
  }

  function bindAccessibilityControls() {
    const largeBtn = document.getElementById("toggle-large-text");
    const contrastBtn = document.getElementById("toggle-high-contrast");

    function syncButton(btn, enabled, label) {
      if (!btn) return;
      btn.setAttribute("aria-pressed", String(enabled));
      btn.textContent = `${label}: ${enabled ? "On" : "Off"}`;
    }

    if (largeBtn) {
      syncButton(largeBtn, document.body.classList.contains("large-text"), "Bigger Words");
      largeBtn.addEventListener("click", () => {
        const next = document.body.classList.toggle("large-text");
        localStorage.setItem(TEXT_KEY, String(next));
        syncButton(largeBtn, next, "Bigger Words");
      });
    }

    if (contrastBtn) {
      syncButton(contrastBtn, document.body.classList.contains("high-contrast"), "High Contrast");
      contrastBtn.addEventListener("click", () => {
        const next = document.body.classList.toggle("high-contrast");
        localStorage.setItem(CONTRAST_KEY, String(next));
        syncButton(contrastBtn, next, "High Contrast");
      });
    }
  }

  function registerPwaSupport() {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    }

    const installBtn = document.getElementById("pwa-install-btn");
    const installHint = document.getElementById("pwa-install-hint");

    window.addEventListener("beforeinstallprompt", (event) => {
      event.preventDefault();
      deferredInstallPrompt = event;
      if (installBtn) {
        installBtn.classList.remove("hidden");
      }
      if (installHint) {
        installHint.textContent = "Ready to install on your phone home screen for one-tap access.";
      }
    });

    if (installBtn) {
      installBtn.addEventListener("click", async () => {
        if (deferredInstallPrompt) {
          deferredInstallPrompt.prompt();
          await deferredInstallPrompt.userChoice;
          deferredInstallPrompt = null;
          installBtn.classList.add("hidden");
          return;
        }
        if (installHint) {
          installHint.textContent =
            "On Chrome/Android tap Menu -> Add to Home screen. On iPhone Safari tap Share -> Add to Home Screen.";
        }
      });
    }
  }

  applyStoredPrefs();
  document.addEventListener("DOMContentLoaded", () => {
    bindAccessibilityControls();
    registerPwaSupport();
  });

  window.VeriShieldShared = {
    escapeHtml,
  };
})();
