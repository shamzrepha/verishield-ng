/* INEC Module B Intake Screening Desk with persistent details state & audit trail */
(() => {
  "use strict";

  const { escapeHtml } = window.VeriShieldShared;

  const flaggedOnlyToggle = document.getElementById("flagged-only-toggle");
  const reloadBatchBtn = document.getElementById("reload-batch-btn");
  const supervisorAliasInput = document.getElementById("supervisor-alias-input");
  const intakeUploadForm = document.getElementById("intake-upload-form");
  const intakeAliasInput = document.getElementById("intake-alias-input");
  const intakeFileInput = document.getElementById("intake-file-input");
  const metricsWrap = document.getElementById("module-b-metrics");
  const queueTbody = document.getElementById("queue-tbody");

  // Preserve expanded <details> rows across refreshes & review decisions
  const openDetailIds = new Set();

  function friendlyFlags(item) {
    const tags = [];
    if (item.ai_face_likelihood >= 0.62) tags.push('<span class="badge badge-danger">Possible AI Face</span>');
    if (item.screen_spoof_likelihood >= 0.52) tags.push('<span class="badge badge-danger">Phone-Screen Spoof</span>');
    if (item.duplicate_face_cluster) tags.push(`<span class="badge badge-warn">Duplicate (${escapeHtml(item.duplicate_face_cluster)})</span>`);
    if (item.burst_anomaly_flag) tags.push('<span class="badge badge-danger">2 AM Upload Spike</span>');
    if (tags.length === 0) tags.push('<span class="badge badge-ok">Looks Normal</span>');
    return tags.join(" ");
  }

  async function submitReviewDecision(recordId, decision) {
    const supervisorAlias = (supervisorAliasInput.value || "").trim() || "SUPERVISOR-DESK-01";
    const rationale =
      decision === "CLEARED_BY_HUMAN"
        ? "Approved after human supervisor visual check."
        : decision === "RECAPTURE_REQUESTED"
        ? "Asked citizen/operator to take a clearer live photo."
        : "Escalated for physical supervisor audit — never auto-deleted.";

    const resp = await fetch(`/api/v1/module-b/review/${encodeURIComponent(recordId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision,
        supervisor_alias: supervisorAlias,
        rationale,
      }),
    });
    if (resp.ok) {
      await loadQueue();
    }
  }

  function renderMetrics(data) {
    metricsWrap.innerHTML = `
      <div class="metric-card"><div class="small muted">Records Checked</div><div class="metric-val">${data.total_records}</div></div>
      <div class="metric-card"><div class="small muted">Need Human Check</div><div class="metric-val">${data.flagged_for_review}</div></div>
      <div class="metric-card"><div class="small muted">Waiting Decision</div><div class="metric-val">${data.pending_review}</div></div>
      <div class="metric-card"><div class="small muted">2 AM Upload Spikes</div><div class="metric-val">${data.burst_anomalies_detected}</div></div>
    `;
  }

  function renderQueueRows(items) {
    if (!items || items.length === 0) {
      queueTbody.innerHTML = '<tr><td colspan="5" class="muted">No matching screening records found.</td></tr>';
      return;
    }

    queueTbody.innerHTML = "";
    items.forEach((item) => {
      const tr = document.createElement("tr");
      const statusBadge =
        item.review_status === "CLEARED_BY_HUMAN"
          ? "badge-ok"
          : item.review_status === "PENDING_REVIEW"
          ? "badge-warn"
          : "badge-danger";

      const isOpen = openDetailIds.has(item.record_id);
      const latestAudit = (item.audit_log || []).slice(-2);

      tr.innerHTML = `
        <td>
          <strong>${escapeHtml(item.record_id)}</strong><br/>
          <span class="small muted">${escapeHtml(item.synthetic_applicant_alias)}</span>
        </td>
        <td>
          <strong>${escapeHtml(item.station_code)}</strong><br/>
          <span class="small muted">${escapeHtml(item.operator_id)}</span>
        </td>
        <td>
          <div class="row-wrap">${friendlyFlags(item)}</div>
          <details class="details-box tech-details"${isOpen ? " open" : ""}>
            <summary>Inspect Score &amp; Audit Details</summary>
            <div style="margin-top:8px;">
              <img class="portrait-thumb" src="/api/v1/demo-samples/portraits/${encodeURIComponent(item.image_filename)}" alt="Synthetic intake portrait ${escapeHtml(item.record_id)}" onerror="this.style.display='none'" />
              <div class="small"><strong>Visual Verdict:</strong> ${escapeHtml(item.visual_verdict_label)}</div>
              <div class="small"><strong>AI-Face:</strong> ${item.ai_face_likelihood.toFixed(2)} | <strong>Screen-Spoof:</strong> ${item.screen_spoof_likelihood.toFixed(2)}</div>
              <div class="small" style="margin-top:4px;"><strong>Anomaly Reasons:</strong> ${item.anomaly_reasons.map(escapeHtml).join(" • ") || "None"}</div>
              ${
                latestAudit.length
                  ? `<div class="small muted" style="margin-top:6px;"><strong>Audit Trail:</strong><br/>${latestAudit
                      .map((a) => `${escapeHtml(a.actor)} -> ${escapeHtml(a.action)}: ${escapeHtml(a.rationale)}`)
                      .join("<br/>")}</div>`
                  : ""
              }
            </div>
          </details>
        </td>
        <td>
          <span class="badge ${statusBadge}">${escapeHtml(item.review_status.replaceAll("_", " "))}</span>
        </td>
        <td class="decision-cell"></td>
      `;

      const detailsEl = tr.querySelector("details.tech-details");
      detailsEl.addEventListener("toggle", () => {
        if (detailsEl.open) {
          openDetailIds.add(item.record_id);
        } else {
          openDetailIds.delete(item.record_id);
        }
      });

      const decisionCell = tr.querySelector(".decision-cell");
      const btnRow = document.createElement("div");
      btnRow.className = "row-wrap";
      [
        { label: "Approve", decision: "CLEARED_BY_HUMAN" },
        { label: "New Photo", decision: "RECAPTURE_REQUESTED" },
        { label: "Escalate", decision: "ESCALATED_FOR_AUDIT" },
      ].forEach((act) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "btn btn-sm";
        if (item.review_status === act.decision) {
          b.classList.add("btn-primary");
        }
        b.textContent = act.label;
        b.addEventListener("click", () => submitReviewDecision(item.record_id, act.decision));
        btnRow.appendChild(b);
      });
      decisionCell.appendChild(btnRow);

      queueTbody.appendChild(tr);
    });
  }

  async function loadQueue() {
    const flaggedOnly = flaggedOnlyToggle.checked;
    const resp = await fetch(`/api/v1/module-b/queue?flagged_only=${flaggedOnly}`);
    if (!resp.ok) return;
    const data = await resp.json();
    renderMetrics(data);
    renderQueueRows(data.items || []);
  }

  flaggedOnlyToggle.addEventListener("change", loadQueue);

  reloadBatchBtn.addEventListener("click", async () => {
    reloadBatchBtn.disabled = true;
    try {
      const resp = await fetch("/api/v1/module-b/reload", { method: "POST" });
      if (resp.ok) {
        const data = await resp.json();
        renderMetrics(data);
        renderQueueRows(data.items || []);
      }
    } finally {
      reloadBatchBtn.disabled = false;
    }
  });

  intakeUploadForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const file = intakeFileInput.files?.[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("synthetic_applicant_alias", intakeAliasInput.value.trim() || "SYNTH-APPLICANT-CUSTOM");

    const resp = await fetch("/api/v1/module-b/analyze-intake", {
      method: "POST",
      body: form,
    });
    if (resp.ok) {
      const newItem = await resp.json();
      openDetailIds.add(newItem.record_id);
      intakeFileInput.value = "";
      await loadQueue();
    }
  });

  loadQueue();
})();
