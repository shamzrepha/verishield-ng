/* Citizen Civic AI, GPS Polling Unit Matcher, Shake-to-Alert & "I'm Safe" Witness Interview */
(() => {
  "use strict";

  const { escapeHtml } = window.VeriShieldShared;

  const stepButtons = document.querySelectorAll("[data-step-target]");
  const panels = {
    chat: document.getElementById("panel-chat"),
    safety: document.getElementById("panel-safety"),
    interview: document.getElementById("panel-interview"),
  };

  // Chat controls
  const langSelect = document.getElementById("language-select");
  const stopVoiceBtn = document.getElementById("stop-voice-btn");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const chatFile = document.getElementById("chat-file");
  const attachedFilename = document.getElementById("attached-filename");
  const chatThread = document.getElementById("chat-thread");
  const chatSubmitBtn = document.getElementById("chat-submit-btn");
  const voiceDictateBtn = document.getElementById("voice-dictate-btn");
  const demoSamplesWrap = document.getElementById("demo-sample-buttons");

  // Safety & Polling Unit controls
  const citizenAliasInput = document.getElementById("citizen-alias");
  const gpsConsentCheckbox = document.getElementById("gps-consent-checkbox");
  const findNearestGpsBtn = document.getElementById("find-nearest-gps-btn");
  const gpsStatusText = document.getElementById("gps-status-text");
  const puSelect = document.getElementById("pu-select");
  const locationForm = document.getElementById("location-form");
  const assignedPuCard = document.getElementById("assigned-pu-card");
  const shakeSensorToggle = document.getElementById("shake-sensor-toggle");
  const shakeStatusText = document.getElementById("shake-status-text");
  const shieldClusterBadge = document.getElementById("shield-cluster-badge");
  const sosPanicBtn = document.getElementById("sos-panic-btn");
  const safetyClusterCard = document.getElementById("safety-cluster-card");
  const openSafeInterviewBtn = document.getElementById("open-safe-interview-btn");

  // Multi-witness interview controls
  const interviewPuLabel = document.getElementById("interview-pu-label");
  const corroboratedStoryPanel = document.getElementById("corroborated-story-panel");
  const interviewChatThread = document.getElementById("interview-chat-thread");
  const interviewChatForm = document.getElementById("interview-chat-form");
  const interviewChatInput = document.getElementById("interview-chat-input");
  const interviewVoiceBtn = document.getElementById("interview-voice-btn");
  const safeInterviewForm = document.getElementById("safe-interview-form");
  const interviewCategory = document.getElementById("interview-category");
  const interviewNarrative = document.getElementById("interview-narrative");

  let pollingUnits = [];
  let selectedPuCode = "PU-LA-IKJ-004";
  let selectedEyewitnessType = "DIRECT_EYEWITNESS";
  let shakeListening = false;
  let lastShakeTime = 0;
  let shakePeakCount = 0;

  function activateStep(targetKey) {
    Object.entries(panels).forEach(([key, panel]) => {
      const active = key === targetKey;
      panel.classList.toggle("hidden", !active);
    });
    stepButtons.forEach((btn) => {
      const active = btn.getAttribute("data-step-target") === targetKey;
      btn.classList.toggle("active", active);
      if (btn.hasAttribute("aria-selected")) {
        btn.setAttribute("aria-selected", String(active));
      }
    });

    if (targetKey === "safety" || targetKey === "interview") {
      loadSafetyStatus(selectedPuCode);
    }
  }

  stepButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.getAttribute("data-step-target");
      if (target && panels[target]) {
        activateStep(target);
      }
    });
  });

  // Speech & Earcon helpers
  function stopSpeech() {
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
  }

  function playEarcon(toneType) {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      const ctx = new Ctx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = toneType === "danger" ? 310 : toneType === "warn" ? 440 : 640;
      gain.gain.setValueAtTime(0.08, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.25);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.26);
    } catch (_) {
      // Audio playback blocked before interaction is benign
    }
  }

  function speakText(text, langCode) {
    if (!("speechSynthesis" in window) || !text) return;
    stopSpeech();
    const utter = new SpeechSynthesisUtterance(text);
    const map = { en: "en-NG", pcm: "en-NG", ig: "ig-NG", yo: "yo-NG", ha: "ha-NG" };
    utter.lang = map[langCode] || "en-NG";
    utter.rate = 0.96;
    window.speechSynthesis.speak(utter);
  }

  stopVoiceBtn.addEventListener("click", stopSpeech);

  function attachVoiceDictation(btn, targetInput, idleLabel) {
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) {
      btn.addEventListener("click", () => {
        targetInput.focus();
        btn.querySelector("span").textContent = "Type below (no browser mic)";
      });
      return;
    }

    btn.addEventListener("click", () => {
      const rec = new SpeechRec();
      rec.lang = "en-NG";
      rec.interimResults = false;
      rec.maxAlternatives = 1;
      const span = btn.querySelector("span");
      span.textContent = "Listening...";
      rec.onresult = (event) => {
        const transcript = event.results?.[0]?.[0]?.transcript || "";
        targetInput.value = targetInput.value ? `${targetInput.value} ${transcript}` : transcript;
      };
      rec.onend = () => {
        span.textContent = idleLabel;
      };
      rec.onerror = () => {
        span.textContent = idleLabel;
      };
      rec.start();
    });
  }

  attachVoiceDictation(voiceDictateBtn, chatInput, "Speak Question");
  attachVoiceDictation(interviewVoiceBtn, interviewChatInput, "Speak Witness Account");

  // Chat Step
  chatFile.addEventListener("change", () => {
    const file = chatFile.files?.[0];
    attachedFilename.textContent = file ? `Attached: ${file.name}` : "No file attached";
  });

  function appendUserChatBubble(text, fileName) {
    const art = document.createElement("article");
    art.className = "msg msg-user";
    art.innerHTML = `
      <div class="msg-meta"><span>You</span></div>
      <p class="msg-body">${escapeHtml(text || "(Media uploaded for authenticity check)")}</p>
      ${fileName ? `<div class="small" style="margin-top:6px;">File: ${escapeHtml(fileName)}</div>` : ""}
    `;
    chatThread.appendChild(art);
    chatThread.scrollTop = chatThread.scrollHeight;
  }

  function appendAiChatBubble(data) {
    const art = document.createElement("article");
    art.className = "msg msg-ai";

    const guidanceHtml =
      data.guidance_steps && data.guidance_steps.length
        ? `<ol class="guidance-list small">${data.guidance_steps.map((s) => `<li>${escapeHtml(s)}</li>`).join("")}</ol>`
        : "";

    const citationsHtml =
      data.citations && data.citations.length
        ? `
          <div class="citation-list">
            ${data.citations
              .map(
                (c) => `
                <a class="citation-link" href="${escapeHtml(c.source_url)}" target="_blank" rel="noopener noreferrer">
                  <strong>${escapeHtml(c.title)} (${escapeHtml(c.published_date)})</strong>
                  <span class="muted">${escapeHtml(c.summary)}</span>
                </a>
              `
              )
              .join("")}
          </div>
        `
        : "";

    let techHtml = "";
    if (data.media_verification) {
      const mv = data.media_verification;
      techHtml = `
        <details class="details-box">
          <summary>Technical Forensics Summary (${escapeHtml(mv.verdict_label)})</summary>
          <p class="small" style="margin:6px 0;"><strong>Confidence:</strong> ${(mv.confidence * 100).toFixed(0)}%</p>
          <ul class="small" style="margin:6px 0; padding-left:18px;">
            ${mv.signals.map((sig) => `<li><strong>${escapeHtml(sig.name)}:</strong> ${sig.score.toFixed(2)} — ${escapeHtml(sig.detail)}</li>`).join("")}
          </ul>
        </details>
      `;
    }

    const spokenText = data.spoken_verdict?.text || data.friendly_answer;
    const spokenWavB64 = data.spoken_verdict?.audio_b64_wav || "";
    const earcon =
      data.media_verification?.verdict_code === "SYNTHETIC_OR_TAMPER_INDICATORS" ||
      data.media_verification?.verdict_code === "CONTRADICTS_OFFICIAL_NOTICE"
        ? "warn"
        : "ok";
    playEarcon(earcon);

    const safetyShortcutHtml =
      data.suggested_tab === "safety"
        ? `<button type="button" class="btn btn-sm btn-danger jump-safety-btn">Open Location &amp; Shake Shield</button>`
        : "";

    art.innerHTML = `
      <div class="msg-meta">
        <span>VeriShield Helper</span>
        <span class="badge badge-info">${escapeHtml(data.detected_intent.replaceAll("_", " "))}</span>
      </div>
      <p class="msg-body">${escapeHtml(data.friendly_answer)}</p>
      ${guidanceHtml}
      ${citationsHtml}
      ${techHtml}
      <div class="row-wrap" style="margin-top:10px;">
        <button type="button" class="btn btn-sm listen-btn">
          <svg class="icon" aria-hidden="true"><use href="#icon-volume"/></svg>
          <span>Listen (${escapeHtml(data.spoken_verdict?.language_name || "English")})</span>
        </button>
        ${safetyShortcutHtml}
      </div>
    `;

    art.querySelector(".listen-btn").addEventListener("click", () => {
      if ("speechSynthesis" in window && spokenText) {
        speakText(spokenText, langSelect.value);
      } else if (spokenWavB64) {
        new Audio(`data:audio/wav;base64,${spokenWavB64}`).play().catch(() => {});
      }
    });

    const jumpBtn = art.querySelector(".jump-safety-btn");
    if (jumpBtn) {
      jumpBtn.addEventListener("click", () => activateStep("safety"));
    }

    chatThread.appendChild(art);
    chatThread.scrollTop = chatThread.scrollHeight;
  }

  async function sendCivicChat(message, fileObj) {
    const cleanMsg = (message || "").trim();
    if (!cleanMsg && !fileObj) return;

    appendUserChatBubble(cleanMsg, fileObj?.name);
    chatSubmitBtn.disabled = true;
    chatSubmitBtn.querySelector("span").textContent = "Checking truth...";

    try {
      const form = new FormData();
      form.append("message", cleanMsg);
      form.append("language", langSelect.value);
      if (fileObj) {
        form.append("file", fileObj);
      }

      const resp = await fetch("/api/v1/module-a/chat", { method: "POST", body: form });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.detail || "Unable to verify right now.");
      }
      appendAiChatBubble(data);
    } catch (err) {
      appendAiChatBubble({
        detected_intent: "ERROR",
        friendly_answer: `Sorry, something went wrong: ${err.message}. Verify critical news directly at inecnigeria.org.`,
        guidance_steps: [],
        citations: [],
        spoken_verdict: { language_name: "English", script: "Please verify directly on the official INEC website." },
        suggested_tab: "chat",
      });
    } finally {
      chatSubmitBtn.disabled = false;
      chatSubmitBtn.querySelector("span").textContent = "Check Truth & Explain Simply";
      chatInput.value = "";
      chatFile.value = "";
      attachedFilename.textContent = "No file attached";
    }
  }

  chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    sendCivicChat(chatInput.value, chatFile.files?.[0]);
  });

  document.querySelectorAll(".quick-ask").forEach((btn) => {
    btn.addEventListener("click", () => {
      const q = btn.getAttribute("data-query");
      if (q) sendCivicChat(q, null);
    });
  });

  async function loadDemoSamples() {
    try {
      const resp = await fetch("/api/v1/demo-samples");
      if (!resp.ok) return;
      const data = await resp.json();
      const citizenSamples = (data.samples || []).filter((s) => s.category !== "portraits").slice(0, 3);
      if (!citizenSamples.length) return;

      demoSamplesWrap.innerHTML = '<span class="small muted" style="width:100%;">Or test a sample WhatsApp flyer/voice note:</span>';
      citizenSamples.forEach((sample) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "btn btn-sm";
        b.textContent = sample.label;
        b.addEventListener("click", async () => {
          const sampleResp = await fetch(`/api/v1/demo-samples/${encodeURIComponent(sample.category)}/${encodeURIComponent(sample.filename)}`);
          const blob = await sampleResp.blob();
          const fakeFile = new File([blob], sample.filename, { type: blob.type || "application/octet-stream" });
          await sendCivicChat(`Check this forwarded sample (${sample.label})`, fakeFile);
        });
        demoSamplesWrap.appendChild(b);
      });
    } catch (_) {
      // Optional samples non-fatal
    }
  }

  // Polling Unit Location + Explicit GPS Consent
  function renderPollingUnitCard(pu, registeredCount, distanceKm) {
    selectedPuCode = pu.pu_code;
    if (puSelect.value !== pu.pu_code) {
      puSelect.value = pu.pu_code;
    }
    interviewPuLabel.textContent = `${pu.pu_code} — ${pu.pu_name}`;

    assignedPuCard.innerHTML = `
      <div class="row-wrap" style="justify-content:space-between; margin-bottom:6px;">
        <strong>${escapeHtml(pu.pu_code)} — ${escapeHtml(pu.pu_name)}</strong>
        <span class="badge badge-info">${escapeHtml(pu.state)} / ${escapeHtml(pu.lga)}</span>
      </div>
      <div class="small muted">Ward: ${escapeHtml(pu.ward)} • Demo Citizens Active Here: ${registeredCount ?? 1}</div>
      ${typeof distanceKm === "number" ? `<div class="small" style="margin-top:4px;"><strong>Ephemeral GPS Match Distance:</strong> ${distanceKm.toFixed(2)} km (raw GPS coordinates already discarded)</div>` : ""}
      <div class="small" style="margin-top:6px;"><strong>Accessibility note:</strong> ${escapeHtml(pu.accessibility_note)}</div>
      <div class="small" style="margin-top:6px;">
        <a href="${escapeHtml(pu.official_lookup_url)}" target="_blank" rel="noopener noreferrer">Official INEC Voter Verification Portal (voters.inecnigeria.org)</a>
      </div>
    `;
  }

  async function loadPollingUnitDirectory() {
    const resp = await fetch("/api/v1/location/directory");
    const data = await resp.json();
    pollingUnits = data.polling_units || [];
    puSelect.innerHTML = pollingUnits
      .map((pu) => `<option value="${escapeHtml(pu.pu_code)}">${escapeHtml(pu.state)} — ${escapeHtml(pu.lga)} (${escapeHtml(pu.pu_name)})</option>`)
      .join("");
    if (pollingUnits.length > 0) {
      renderPollingUnitCard(pollingUnits[0], 1, null);
    }
  }

  puSelect.addEventListener("change", () => {
    const match = pollingUnits.find((p) => p.pu_code === puSelect.value);
    if (match) {
      renderPollingUnitCard(match, 1, null);
      loadSafetyStatus(match.pu_code);
    }
  });

  locationForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const match = pollingUnits.find((p) => p.pu_code === puSelect.value) || pollingUnits[0];
    if (!match) return;
    const alias = citizenAliasInput.value.trim() || "Voter-Lagos-01";
    const resp = await fetch("/api/v1/location/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        citizen_alias: alias,
        state: match.state,
        lga: match.lga,
        ward: match.ward,
      }),
    });
    if (resp.ok) {
      const data = await resp.json();
      renderPollingUnitCard(data.polling_unit, data.nearby_registered_demo_users, null);
      await loadSafetyStatus(data.polling_unit.pu_code);
    }
  });

  gpsConsentCheckbox.addEventListener("change", () => {
    const consented = gpsConsentCheckbox.checked;
    findNearestGpsBtn.disabled = !consented;
    gpsStatusText.textContent = consented
      ? "Consent recorded. Tap the button to match your nearest Polling Unit ephemerally."
      : "Check the GPS consent box above to enable.";
  });

  findNearestGpsBtn.addEventListener("click", () => {
    if (!gpsConsentCheckbox.checked) return;
    if (!("geolocation" in navigator)) {
      gpsStatusText.textContent = "Browser GPS is unavailable here — select your State/LGA manually below.";
      return;
    }

    findNearestGpsBtn.disabled = true;
    gpsStatusText.textContent = "Reading GPS once (coordinates discarded immediately after match)...";
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          const alias = citizenAliasInput.value.trim() || "Voter-Lagos-01";
          const resp = await fetch("/api/v1/location/nearest", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              citizen_alias: alias,
              lat: pos.coords.latitude,
              lon: pos.coords.longitude,
            }),
          });
          if (!resp.ok) throw new Error("Server failed to match location.");
          const data = await resp.json();
          gpsStatusText.textContent = data.privacy_notice;
          renderPollingUnitCard(data.polling_unit, data.nearby_registered_demo_users, data.distance_km);
          await loadSafetyStatus(data.polling_unit.pu_code);
        } catch (err) {
          gpsStatusText.textContent = `GPS lookup error: ${err.message}`;
        } finally {
          findNearestGpsBtn.disabled = !gpsConsentCheckbox.checked;
        }
      },
      (err) => {
        gpsStatusText.textContent = `GPS permission declined or timed out (${err.message}). Pick your State/LGA manually below.`;
        findNearestGpsBtn.disabled = !gpsConsentCheckbox.checked;
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
    );
  });

  // Safety Dashboard & Shake-to-Alert
  function renderSafetyDashboard(data) {
    const story = data.story;
    const badgeClass =
      story.cluster_alert_level === "CLUSTER_HIGH_ALERT"
        ? "badge-danger"
        : story.cluster_alert_level === "SINGLE_ALERT_MONITORING"
        ? "badge-warn"
        : "badge-ok";

    shieldClusterBadge.className = `badge ${badgeClass}`;
    shieldClusterBadge.textContent = story.cluster_alert_level.replaceAll("_", " ");

    safetyClusterCard.innerHTML = `
      <div class="row-wrap" style="justify-content:space-between; margin-bottom:6px;">
        <strong>Ward Alert Status — ${escapeHtml(story.pu_code)}</strong>
        <span class="badge ${badgeClass}">Active SOS (10m): ${story.active_sos_count_last_10m}</span>
      </div>
      ${
        story.broadcast_warnings && story.broadcast_warnings.length
          ? `<ul class="small" style="margin:6px 0; padding-left:18px;">${story.broadcast_warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join("")}</ul>`
          : `<div class="small muted">No active danger pings in this ward right now.</div>`
      }
    `;

    const corrClass =
      story.corroboration_status === "MULTI_WITNESS_CORROBORATED"
        ? "badge-ok"
        : story.corroboration_status === "CONFLICTING_ACCOUNTS"
        ? "badge-warn"
        : "badge-info";

    corroboratedStoryPanel.innerHTML = `
      <div class="row-wrap" style="justify-content:space-between; margin-bottom:8px;">
        <strong>Multi-Witness Balanced Story (${escapeHtml(story.pu_code)})</strong>
        <span class="badge ${corrClass}">${escapeHtml(story.corroboration_status.replaceAll("_", " "))}</span>
      </div>
      <p style="margin:0 0 8px;">${escapeHtml(story.balanced_summary)}</p>
      <div class="small muted" style="margin-bottom:8px;">
        Total Witnesses: ${story.total_interviews} • Direct Eyewitnesses: ${story.direct_eyewitness_count} • Heard from Others: ${story.secondhand_count}
      </div>
      ${
        story.witness_perspectives && story.witness_perspectives.length
          ? story.witness_perspectives
              .map(
                (w) => `
              <div class="card" style="padding:10px 12px; margin-top:8px;">
                <div class="row-wrap" style="justify-content:space-between;">
                  <strong class="small">${escapeHtml(w.citizen_alias)}</strong>
                  <span class="badge ${w.eyewitness_type === "DIRECT_EYEWITNESS" ? "badge-ok" : "badge-warn"}">
                    ${w.eyewitness_type === "DIRECT_EYEWITNESS" ? "Direct Eyewitness" : "Secondhand"}
                  </span>
                </div>
                <div class="small muted" style="margin-top:4px;">${escapeHtml(w.incident_category.replaceAll("_", " "))}</div>
                <div class="small" style="margin-top:4px;">${escapeHtml(w.narrative)}</div>
              </div>
            `
              )
              .join("")
          : '<div class="small muted">No witness check-ins submitted yet for this Polling Unit.</div>'
      }
    `;
  }

  async function loadSafetyStatus(puCode) {
    const resp = await fetch(`/api/v1/safety/status?pu_code=${encodeURIComponent(puCode || selectedPuCode)}`);
    if (resp.ok) {
      const data = await resp.json();
      renderSafetyDashboard(data);
    }
  }

  async function triggerSosAlert(method) {
    const alias = citizenAliasInput.value.trim() || "Voter-Lagos-01";
    playEarcon("danger");
    const resp = await fetch("/api/v1/safety/sos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        citizen_alias: alias,
        pu_code: selectedPuCode,
        trigger_method: method,
        note: method === "SHAKE_GESTURE" ? "Triggered by rapid phone shake." : "Triggered by panic SOS button.",
      }),
    });
    if (resp.ok) {
      const data = await resp.json();
      renderSafetyDashboard(data);
    }
  }

  sosPanicBtn.addEventListener("click", () => triggerSosAlert("PANIC_BUTTON"));
  openSafeInterviewBtn.addEventListener("click", () => activateStep("interview"));

  function handleDeviceMotion(event) {
    if (!shakeListening) return;
    const acc = event.accelerationIncludingGravity || event.acceleration;
    if (!acc) return;
    const magnitude = Math.sqrt((acc.x || 0) ** 2 + (acc.y || 0) ** 2 + (acc.z || 0) ** 2);
    const now = Date.now();
    if (magnitude > 23) {
      if (now - lastShakeTime < 1500) {
        shakePeakCount += 1;
      } else {
        shakePeakCount = 1;
      }
      lastShakeTime = now;

      if (shakePeakCount >= 3) {
        shakePeakCount = 0;
        shakeStatusText.textContent = "Rapid shake detected! Sending ward SOS alert now...";
        triggerSosAlert("SHAKE_GESTURE");
      }
    }
  }

  shakeSensorToggle.addEventListener("change", async () => {
    const wantOn = shakeSensorToggle.checked;
    if (wantOn && typeof DeviceMotionEvent !== "undefined" && typeof DeviceMotionEvent.requestPermission === "function") {
      try {
        const perm = await DeviceMotionEvent.requestPermission();
        if (perm !== "granted") {
          shakeSensorToggle.checked = false;
          shakeListening = false;
          shakeStatusText.textContent = "Motion permission declined. Use the manual SOS button below.";
          return;
        }
      } catch (_) {
        shakeSensorToggle.checked = false;
        shakeListening = false;
        shakeStatusText.textContent = "Motion permission unavailable here. Use the manual SOS button below.";
        return;
      }
    }

    shakeListening = wantOn;
    if (shakeListening) {
      window.addEventListener("devicemotion", handleDeviceMotion);
      shakeStatusText.textContent = "Shake detector ARMED. Rapidly shake your phone 3 times if danger starts.";
    } else {
      window.removeEventListener("devicemotion", handleDeviceMotion);
      shakeStatusText.textContent = "Shake detector is OFF by default. Check the consent box above to arm it.";
    }
  });

  // Step 3: Multi-Witness "I Am Safe" Interview
  document.querySelectorAll(".eyewitness-pill").forEach((pill) => {
    pill.addEventListener("click", () => {
      document.querySelectorAll(".eyewitness-pill").forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      selectedEyewitnessType = pill.getAttribute("data-eyewitness") || "DIRECT_EYEWITNESS";
    });
  });

  function appendInterviewBubble(speaker, text, isUser, badgeLabel) {
    const art = document.createElement("article");
    art.className = `msg ${isUser ? "msg-user" : "msg-ai"}`;
    art.innerHTML = `
      <div class="msg-meta">
        <span>${escapeHtml(speaker)}</span>
        ${badgeLabel ? `<span class="badge badge-info">${escapeHtml(badgeLabel)}</span>` : ""}
      </div>
      <p class="msg-body">${escapeHtml(text)}</p>
    `;
    interviewChatThread.appendChild(art);
    interviewChatThread.scrollTop = interviewChatThread.scrollHeight;
  }

  async function sendWitnessChat(message) {
    const clean = (message || "").trim();
    if (clean.length < 2) return;
    const alias = citizenAliasInput.value.trim() || "Voter-Lagos-01";
    appendInterviewBubble(alias, clean, true, selectedEyewitnessType === "DIRECT_EYEWITNESS" ? "Direct" : "Secondhand");

    const resp = await fetch("/api/v1/safety/interview/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        citizen_alias: alias,
        pu_code: selectedPuCode,
        message: clean,
        eyewitness_type: selectedEyewitnessType,
      }),
    });

    if (resp.ok) {
      const data = await resp.json();
      const statusBadge = data.interview_saved ? "Report Saved & Balanced" : "Follow-up Question";
      appendInterviewBubble("VeriShield Safety Interviewer", data.reply_text, false, statusBadge);
      if (data.safety_status) {
        renderSafetyDashboard(data.safety_status);
      }
      interviewChatInput.value = "";
    }
  }

  interviewChatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    sendWitnessChat(interviewChatInput.value);
  });

  document.querySelectorAll(".quick-witness").forEach((btn) => {
    btn.addEventListener("click", () => {
      const text = btn.getAttribute("data-witness");
      if (text) sendWitnessChat(text);
    });
  });

  safeInterviewForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const alias = citizenAliasInput.value.trim() || "Voter-Lagos-01";
    const narrative = interviewNarrative.value.trim();
    if (narrative.length < 5) return;

    const resp = await fetch("/api/v1/safety/interview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        citizen_alias: alias,
        pu_code: selectedPuCode,
        is_safe_now: true,
        incident_category: interviewCategory.value,
        eyewitness_type: selectedEyewitnessType === "HEARD_FROM_OTHERS" ? "HEARD_FROM_OTHERS" : "DIRECT_EYEWITNESS",
        narrative,
      }),
    });
    if (resp.ok) {
      const data = await resp.json();
      renderSafetyDashboard(data);
      interviewNarrative.value = "";
      appendInterviewBubble("VeriShield Safety Interviewer", "Thank you — your structured witness report is saved and added to the multi-witness balance.", false, "Saved");
    }
  });

  // Boot
  loadPollingUnitDirectory().then(() => loadSafetyStatus(selectedPuCode));
  loadDemoSamples();
})();
