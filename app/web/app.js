const $ = (selector) => document.querySelector(selector);
const runForm = $('#run-form');
const runButton = $('#run-btn');
const formStatus = $('#form-status');
const tokenInput = $('#api-token');

function authHeaders() {
  const token = tokenInput.value.trim();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}
function statusClass(status) {
  return status === 'passed' ? 'status-passed' : status === 'blocked' ? 'status-blocked' : 'status-failed';
}
function showReport(report) {
  $('#empty-report').hidden = true;
  const content = $('#report-content');
  content.hidden = false;
  const steps = report.steps.map((step) => `
    <div class="step-row">
      <span class="step-icon ${step.status === 'passed' ? '' : 'failed'}">${step.status === 'passed' ? '✓' : '!'}</span>
      <div class="step-detail"><strong>${escapeHtml(step.action)} · ${escapeHtml(step.status)}</strong>
      <small>${escapeHtml(step.description)}${step.error ? ` — ${escapeHtml(step.error)}` : ''}</small></div>
      <small>${step.duration_ms} ms</small>
    </div>`).join('') || '<div class="history-empty">No browser steps were executed.</div>';
  const findings = report.findings.map((finding) => `
    <div class="finding-row"><span>⚠</span><div><strong>${escapeHtml(finding.severity.toUpperCase())} · ${escapeHtml(finding.title)}</strong>
    <p>${escapeHtml(finding.description)}</p></div></div>`).join('') || '<div class="history-empty">No findings detected.</div>';
  const artifacts = Object.entries(report.artifacts || {}).map(([name, url]) => `<a href="${escapeHtml(url)}" data-artifact-url="${escapeHtml(url)}">Open ${escapeHtml(name)}</a>`).join('');
  content.innerHTML = `
    <div class="report-top"><div><div class="report-title">${escapeHtml(report.title)}</div><div class="report-meta">${escapeHtml(report.target_url)} · ${new Date(report.started_at).toLocaleString()}</div></div><span class="status-badge ${statusClass(report.status)}">${escapeHtml(report.status)}</span></div>
    <p class="report-meta">${escapeHtml(report.summary)}</p>
    <div class="metrics"><div class="metric"><strong>${report.steps.length}</strong><span>STEPS</span></div><div class="metric"><strong>${report.findings.length}</strong><span>FINDINGS</span></div><div class="metric"><strong>${report.duration_ms} ms</strong><span>DURATION</span></div></div>
    <div class="section-label">EXECUTION STEPS</div>${steps}
    <div class="section-label">FINDINGS</div>${findings}
    <div class="artifact-links">${artifacts}</div>`;
  content.dataset.runId = report.run_id;
  content.querySelectorAll('[data-artifact-url]').forEach((link) => link.addEventListener('click', async (event) => {
    event.preventDefault();
    try {
      const response = await fetch(link.dataset.artifactUrl, { headers: authHeaders() });
      if (!response.ok) throw new Error(`Artifact download failed (${response.status}).`);
      const blob = await response.blob();
      const temporaryUrl = URL.createObjectURL(blob);
      const download = document.createElement('a');
      download.href = temporaryUrl;
      download.download = link.textContent.replace(/^Open\s+/, '') === 'screenshot' ? 'screenshot.png' : 'trace.zip';
      download.click();
      window.setTimeout(() => URL.revokeObjectURL(temporaryUrl), 2000);
    } catch (error) {
      formStatus.textContent = error.message;
    }
  }));
}
async function fetchReport(runId) {
  const response = await fetch(`/runs/${runId}`, { headers: authHeaders() });
  if (!response.ok) throw new Error(`Unable to load report (${response.status}).`);
  showReport(await response.json());
}
async function refreshHistory() {
  const response = await fetch('/runs?limit=15', { headers: authHeaders() });
  if (!response.ok) {
    $('#history-list').innerHTML = `<div class="history-empty">Unable to load history (${response.status}).</div>`;
    return;
  }
  const runs = await response.json();
  $('#history-list').innerHTML = runs.length ? runs.map((run) => `
    <div class="history-item" data-run-id="${escapeHtml(run.run_id)}">
      <div><strong>${escapeHtml(run.title)}</strong><small>${escapeHtml(run.target_url)}</small></div>
      <span class="history-status status-badge ${statusClass(run.status)}">${escapeHtml(run.status)}</span>
      <span>${run.finding_count} findings</span><span class="duration">${run.duration_ms} ms</span>
    </div>`).join('') : '<div class="history-empty">No saved runs yet.</div>';
  document.querySelectorAll('.history-item').forEach((item) => item.addEventListener('click', () => fetchReport(item.dataset.runId).catch((error) => { formStatus.textContent = error.message; })));
}

$('#demo-btn').addEventListener('click', () => {
  $('#target-url').value = `${window.location.origin}/demo`;
  $('#title').value = 'Demo store homepage smoke test';
  $('#objective').value = 'Verify that the demo page loads and displays its main heading.';
  $('#expected-title').value = 'QA Demo Store';
});
$('#refresh-history').addEventListener('click', refreshHistory);
runForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  runButton.disabled = true;
  runButton.innerHTML = '<span>◌</span> Running browser checks…';
  formStatus.textContent = 'Opening browser and collecting evidence. This can take a few seconds.';
  const payload = {
    title: $('#title').value.trim(),
    target_url: $('#target-url').value.trim(),
    objective: $('#objective').value.trim(),
    expected_title: $('#expected-title').value.trim() || null,
    max_steps: Number($('#max-steps').value),
  };
  try {
    const response = await fetch('/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `QA request failed (${response.status}).`);
    }
    const created = await response.json();
    await fetchReport(created.run_id);
    formStatus.textContent = created.summary;
    await refreshHistory();
    $('#report-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    formStatus.textContent = error.message;
  } finally {
    runButton.disabled = false;
    runButton.innerHTML = '<span>✦</span> Start browser QA run <span class="arrow">→</span>';
  }
});
refreshHistory();
