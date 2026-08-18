const THEME_KEY = "time-to-sleep-theme";
const state = {
  snapshots: [],
  accounts: [],
  loading: false,
  theme: document.documentElement.dataset.theme || "light",
  loadError: null,
  setup: null,
};

const providerLabels = {
  codex: "Codex",
  claude: "Claude Code",
  antigravity: "Antigravity",
};

function select(selector) {
  return document.querySelector(selector);
}

function element(tag, options = {}) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined) node.textContent = options.text;
  for (const [name, value] of Object.entries(options.attributes || {})) {
    node.setAttribute(name, value);
  }
  return node;
}

function append(parent, ...children) {
  for (const child of children) {
    if (child) parent.append(child);
  }
  return parent;
}

async function getJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // Keep the status-based message when the response is not JSON.
    }
    throw new Error(detail);
  }
  return response.json();
}

async function loadUsage(forceRefresh = false) {
  const suffix = forceRefresh ? "?force_refresh=true" : "";
  return getJson(`/v1/usage${suffix}`);
}

async function loadAccounts() {
  return getJson("/v1/accounts");
}

function systemTheme() {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme, persist = false) {
  state.theme = theme;
  document.documentElement.dataset.theme = theme;
  if (persist) localStorage.setItem(THEME_KEY, theme);
  const toggle = select("#theme-toggle");
  if (!toggle) return;
  const next = theme === "dark" ? "light" : "dark";
  toggle.setAttribute("aria-label", `Switch to ${next} theme`);
  toggle.setAttribute("title", `Switch to ${next} theme`);
  const icon = toggle.querySelector("span");
  if (icon) icon.textContent = theme === "dark" ? "☼" : "◐";
}

function initializeTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  applyTheme(saved || document.documentElement.dataset.theme || systemTheme());
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const onSystemChange = () => {
    if (!localStorage.getItem(THEME_KEY)) applyTheme(systemTheme());
  };
  if (media.addEventListener) media.addEventListener("change", onSystemChange);
  else media.addListener(onSystemChange);
  select("#theme-toggle")?.addEventListener("click", () => {
    applyTheme(state.theme === "dark" ? "light" : "dark", true);
  });
}

function providerLabel(provider) {
  return providerLabels[provider] || provider;
}

function accountLabel(snapshot) {
  if (snapshot.account_id === "codex-primary") return "Codex · primary";
  if (snapshot.account_id === "codex-secondary") return "Codex · second account";
  return providerLabel(snapshot.provider);
}

function statusLabel(status) {
  return {
    live: "Live",
    cached: "Cached",
    stale: "Stale",
    unavailable: "Unavailable",
  }[status] || "Unknown";
}

function formatAge(timestamp) {
  if (!timestamp) return "No observation";
  const ageMs = Math.max(0, Date.now() - new Date(timestamp).getTime());
  const minutes = Math.floor(ageMs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  return `${Math.floor(hours / 24)} days ago`;
}

function formatReset(timestamp) {
  if (!timestamp) return "Reset time unavailable";
  const reset = new Date(timestamp);
  if (Number.isNaN(reset.getTime())) return "Reset time unavailable";
  return `Resets ${new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  }).format(reset)}`;
}

function formatWindow(id) {
  return id.split("_").map((part) => part[0].toUpperCase() + part.slice(1)).join(" ");
}

function formatPercent(percent) {
  return Number.isInteger(percent) ? `${percent}%` : `${percent.toFixed(1)}%`;
}

function renderSummary() {
  const summary = select("#summary");
  if (!summary) return;
  summary.replaceChildren();
  if (!state.snapshots.length) {
    const card = element("div", { className: "summary-card summary-card-wide" });
    append(card, element("div", { className: "summary-label", text: "Provider sync" }), element("div", { className: "summary-value", text: state.loading ? "…" : "—" }), element("div", { className: "summary-detail", text: state.loadError || "Waiting for usage data" }));
    summary.append(card);
    return;
  }
  const live = state.snapshots.filter((item) => item.status === "live").length;
  const attention = state.snapshots.filter((item) => ["cached", "stale"].includes(item.status)).length;
  const unavailable = state.snapshots.filter((item) => item.status === "unavailable").length;
  const nextReset = state.snapshots.flatMap((item) => item.windows || []).map((window) => window.resets_at).filter(Boolean).sort()[0];
  const cards = [
    ["Healthy now", live, live === 1 ? "account reporting live" : "accounts reporting live"],
    ["Needs a look", attention, attention ? "cached or stale data" : "no stale snapshots"],
    ["Next reset", nextReset ? formatReset(nextReset).replace("Resets ", "") : "—", nextReset ? "earliest known window" : "no reset reported"],
  ];
  for (const [label, value, detail] of cards) {
    const card = element("div", { className: "summary-card" });
    append(card, element("div", { className: "summary-label", text: label }), element("div", { className: "summary-value", text: String(value) }), element("div", { className: "summary-detail", text: detail }));
    summary.append(card);
  }
  if (unavailable) {
    const card = element("div", { className: "summary-card summary-card-alert" });
    append(card, element("div", { className: "summary-label", text: "Action" }), element("div", { className: "summary-value", text: String(unavailable) }), element("div", { className: "summary-detail", text: unavailable === 1 ? "account unavailable" : "accounts unavailable" }));
    summary.append(card);
  }
  summary.classList.toggle("summary-grid-four", unavailable > 0);
}

function renderWindow(window) {
  const wrapper = element("div", { className: "usage-window" });
  const heading = element("div", { className: "window-heading" });
  append(heading, element("span", { className: "window-name", text: formatWindow(window.id) }), element("strong", { text: formatPercent(window.used_percent) }));
  const track = element("div", { className: "meter", attributes: { role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(window.used_percent), "aria-label": `${formatWindow(window.id)} usage` } });
  track.append(element("span", { className: "meter-fill" }));
  track.firstElementChild.style.width = `${Math.min(100, Math.max(0, window.used_percent))}%`;
  const detail = element("div", { className: "window-detail", text: formatReset(window.resets_at) });
  if (window.window_minutes) detail.append(element("span", { text: ` · ${window.window_minutes >= 1000 ? "7-day" : "5-hour"} window` }));
  append(wrapper, heading, track, detail);
  return wrapper;
}

function renderAccount(snapshot) {
  const card = element("article", { className: `account-card status-${snapshot.status}` });
  const header = element("div", { className: "account-card-header" });
  const identity = element("div", { className: "account-identity" });
  const monogram = element("span", { className: "provider-monogram", text: providerLabel(snapshot.provider).slice(0, 2).toUpperCase(), attributes: { "aria-hidden": "true" } });
  const identityCopy = element("div", { className: "identity-copy" });
  append(identityCopy, element("p", { className: "account-provider", text: accountLabel(snapshot) }), element("h3", { text: snapshot.configured_email }), element("p", { className: "account-meta", text: `${snapshot.source.replaceAll("_", " ")} · ${formatAge(snapshot.observed_at)}` }));
  append(identity, monogram, identityCopy);
  const status = element("div", { className: "status-stack" });
  const badge = element("span", { className: "status-badge", text: statusLabel(snapshot.status) });
  badge.prepend(element("span", { className: "status-dot", attributes: { "aria-hidden": "true" } }));
  append(status, badge, element("span", { className: "status-note", text: snapshot.observed_email && snapshot.observed_email !== snapshot.configured_email ? `Observed ${snapshot.observed_email}` : "" }));
  append(header, identity, status);
  card.append(header);

  if (snapshot.windows?.length) {
    const windows = element("div", { className: "window-list" });
    snapshot.windows.forEach((window) => windows.append(renderWindow(window)));
    card.append(windows);
  }

  if (snapshot.message) card.append(element("p", { className: "account-message", text: snapshot.message }));
  if (snapshot.error_code) card.append(element("p", { className: "account-error", text: snapshot.error_code.replaceAll("_", " ") }));
  if (snapshot.status === "unavailable" && snapshot.provider === "codex") {
    const action = element("button", { className: "button button-action", text: "Set up account", attributes: { type: "button" } });
    action.addEventListener("click", () => openSetup(snapshot.account_id));
    card.append(action);
  }
  return card;
}

function renderAccounts() {
  const list = select("#account-list");
  if (!list) return;
  list.replaceChildren();
  if (state.loading && !state.snapshots.length) {
    const loading = element("div", { className: "loading-state", attributes: { role: "status" } });
    append(loading, element("span", { className: "loading-line" }), element("span", { className: "loading-line short" }));
    list.append(loading);
    return;
  }
  if (!state.snapshots.length) {
    list.append(element("div", { className: "empty-state", text: state.loadError || "No provider records returned." }));
    return;
  }
  state.snapshots.forEach((snapshot) => list.append(renderAccount(snapshot)));
}

function stopLoginPolling() {
  if (state.setup?.pollTimer) clearTimeout(state.setup.pollTimer);
  if (state.setup) state.setup.pollTimer = null;
}

function setupStatusMessage(status) {
  return {
    starting: "Opening an isolated Codex session…",
    pending: "Waiting for Codex to confirm the login…",
    succeeded: "Login verified for the configured account.",
    failed: "Codex completed, but the account identity did not match.",
    cancelled: "Login setup cancelled.",
    expired: "This login attempt expired. Start a new one when ready.",
    error: "The login session could not be started.",
  }[status] || "Choose a login method to begin.";
}

function renderSetup() {
  const panel = select("#setup-panel");
  if (!panel) return;
  panel.replaceChildren();
  if (!state.setup) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  const setup = state.setup;
  const title = element("div", { className: "setup-heading" });
  const titleCopy = element("div");
  append(titleCopy, element("p", { className: "eyebrow", text: "Account setup" }), element("h2", { id: "setup-title", text: "Connect Codex" }), element("p", { className: "setup-copy", text: `Finish the sign-in for ${setup.accountId}. This session uses its isolated profile.` }));
  const close = element("button", { className: "icon-button setup-close", text: "×", attributes: { type: "button", "aria-label": "Close account setup" } });
  close.addEventListener("click", () => {
    stopLoginPolling();
    state.setup = null;
    renderSetup();
  });
  append(title, titleCopy, close);
  panel.append(title);

  const controls = element("div", { className: "setup-controls" });
  const methodField = element("label", { className: "setup-field" });
  append(methodField, element("span", { text: "Sign-in method" }));
  const method = element("select", { attributes: { id: "setup-method", name: "method" } });
  const browserOption = element("option", { text: "Browser sign-in", attributes: { value: "browser" } });
  const deviceOption = element("option", { text: "Device code", attributes: { value: "device_code" } });
  method.append(browserOption, deviceOption);
  method.value = setup.method;
  method.disabled = ["starting", "pending"].includes(setup.status);
  method.addEventListener("change", () => { state.setup.method = method.value; });
  methodField.append(method);
  const start = element("button", { className: "button button-action", text: setup.status === "starting" ? "Starting…" : setup.status === "pending" ? "Waiting…" : "Start login", attributes: { type: "button" } });
  start.disabled = ["starting", "pending"].includes(setup.status);
  start.addEventListener("click", startLogin);
  const cancel = element("button", { className: "button button-secondary", text: setup.attemptId && setup.status === "pending" ? "Cancel attempt" : "Close", attributes: { type: "button" } });
  cancel.addEventListener("click", cancelSetup);
  append(controls, methodField, start, cancel);
  panel.append(controls);

  if (setup.challenge) {
    const challenge = element("div", { className: "setup-challenge" });
    append(challenge, element("p", { className: "setup-status", text: setupStatusMessage(setup.status) }));
    if (setup.challenge.auth_url) {
      const link = element("a", { className: "setup-link", text: "Open authorization page ↗", attributes: { href: setup.challenge.auth_url, target: "_blank", rel: "noreferrer" } });
      challenge.append(link);
    }
    if (setup.challenge.verification_url) {
      const link = element("a", { className: "setup-link", text: "Open verification page ↗", attributes: { href: setup.challenge.verification_url, target: "_blank", rel: "noreferrer" } });
      challenge.append(link);
    }
    if (setup.challenge.user_code) {
      const code = element("p", { className: "setup-code-label", text: "Your device code" });
      const codeValue = element("code", { className: "setup-code", text: setup.challenge.user_code });
      append(challenge, code, codeValue);
    }
    panel.append(challenge);
  } else if (setup.status === "error") {
    panel.append(element("p", { className: "setup-status setup-status-error", text: setup.error || setupStatusMessage(setup.status) }));
  }
}

function openSetup(accountId) {
  stopLoginPolling();
  state.setup = { accountId, method: "browser", attemptId: null, challenge: null, status: "idle", pollTimer: null, error: null };
  renderSetup();
  select("#setup-panel")?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest" });
  select("#setup-method")?.focus();
}

async function startLogin() {
  if (!state.setup || ["starting", "pending"].includes(state.setup.status)) return;
  const setup = state.setup;
  setup.status = "starting";
  setup.error = null;
  renderSetup();
  try {
    const challenge = await getJson(`/v1/accounts/${setup.accountId}/login/start`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ method: setup.method }),
    });
    setup.attemptId = challenge.attempt_id;
    setup.challenge = challenge;
    setup.status = "pending";
    renderSetup();
    await pollLogin(setup.accountId, setup.attemptId);
  } catch (error) {
    setup.status = "error";
    setup.error = error.message;
    renderSetup();
  }
}

async function pollLogin(accountId, attemptId) {
  if (!state.setup || state.setup.attemptId !== attemptId) return;
  try {
    const attempt = await getJson(`/v1/accounts/${accountId}/login/${attemptId}`);
    if (!state.setup || state.setup.attemptId !== attemptId) return;
    state.setup.status = attempt.status;
    renderSetup();
    if (attempt.status === "pending") {
      state.setup.pollTimer = setTimeout(() => pollLogin(accountId, attemptId), 2000);
      return;
    }
    if (select("#live-announcement")) select("#live-announcement").textContent = setupStatusMessage(attempt.status);
    if (attempt.status === "succeeded") {
      await refresh();
      if (state.setup?.attemptId === attemptId) {
        stopLoginPolling();
        state.setup = null;
        renderSetup();
      }
    }
  } catch (error) {
    if (!state.setup || state.setup.attemptId !== attemptId) return;
    state.setup.status = "error";
    state.setup.error = error.message;
    renderSetup();
  }
}

async function cancelSetup() {
  if (!state.setup) return;
  if (!state.setup.attemptId || state.setup.status !== "pending") {
    stopLoginPolling();
    state.setup = null;
    renderSetup();
    return;
  }
  const setup = state.setup;
  stopLoginPolling();
  try {
    await getJson(`/v1/accounts/${setup.accountId}/login/${setup.attemptId}/cancel`, { method: "POST" });
    setup.status = "cancelled";
    renderSetup();
    if (select("#live-announcement")) select("#live-announcement").textContent = setupStatusMessage(setup.status);
  } catch (error) {
    setup.status = "error";
    setup.error = error.message;
    renderSetup();
  }
}

function render() {
  renderSummary();
  renderAccounts();
  renderSetup();
}

function updateTimestamp(generatedAt) {
  const timestamp = select("#last-updated");
  if (!timestamp || !generatedAt) return;
  const date = new Date(generatedAt);
  timestamp.dateTime = date.toISOString();
  timestamp.textContent = `Synced ${formatAge(generatedAt)}`;
}

async function refresh(forceRefresh = false) {
  state.loading = true;
  state.loadError = null;
  render();
  const button = select("#refresh-button");
  if (button) {
    button.disabled = true;
    button.textContent = "Refreshing…";
  }
  const [usageResult, accountsResult] = await Promise.allSettled([loadUsage(forceRefresh), loadAccounts()]);
  if (usageResult.status === "fulfilled") {
    state.snapshots = usageResult.value.accounts || [];
    updateTimestamp(usageResult.value.generated_at);
  } else {
    state.loadError = usageResult.reason?.message || "Usage could not be loaded.";
  }
  if (accountsResult.status === "fulfilled") state.accounts = accountsResult.value || [];
  state.loading = false;
  render();
  if (select("#live-announcement")) select("#live-announcement").textContent = usageResult.status === "fulfilled" ? "Usage data refreshed." : state.loadError;
  if (button) {
    button.disabled = false;
    button.textContent = "Refresh usage";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initializeTheme();
  select("#refresh-button")?.addEventListener("click", () => refresh(true));
  refresh();
});
