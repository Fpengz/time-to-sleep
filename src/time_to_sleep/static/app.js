const THEME_KEY = "time-to-sleep-theme";
const THEME_COLORS = {
  dark: "#0f1413",
  light: "#eee9df",
};
const state = {
  snapshots: [],
  accounts: [],
  loading: false,
  refreshPromise: null,
  refreshQueuedPromise: null,
  refreshForce: false,
  theme: document.documentElement.dataset.theme || "light",
  loadError: null,
  accountLoadError: null,
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

function updateThemeColor(theme) {
  const meta = select('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", THEME_COLORS[theme] || THEME_COLORS.light);
}

function applyTheme(theme, persist = false) {
  state.theme = theme;
  document.documentElement.dataset.theme = theme;
  updateThemeColor(theme);
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
    rate_limited: "Rate limited",
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
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(reset)}`;
}

function formatWindow(id) {
  const labels = {
    third_party_weekly: "Claude + GPT Weekly",
    third_party_five_hour: "Claude + GPT Five Hour",
  };
  if (labels[id]) return labels[id];
  return id.split("_").map((part) => part[0].toUpperCase() + part.slice(1)).join(" ");
}

function formatPercent(percent) {
  return Number.isInteger(percent) ? `${percent}%` : `${percent.toFixed(1)}%`;
}

function resetCandidates() {
  return state.snapshots
    .flatMap((snapshot) => (snapshot.windows || []).map((window) => ({ snapshot, window })))
    .filter((candidate) => Number.isFinite(Date.parse(candidate.window.resets_at)))
    .sort((left, right) => Date.parse(left.window.resets_at) - Date.parse(right.window.resets_at));
}

function snapshotCounts() {
  return {
    live: state.snapshots.filter((item) => item.status === "live").length,
    attention: state.snapshots.filter((item) => ["cached", "stale", "rate_limited"].includes(item.status)).length,
    unavailable: state.snapshots.filter((item) => item.status === "unavailable").length,
  };
}

function loadIssueMessage() {
  return [state.loadError, state.accountLoadError].filter(Boolean).join(" · ");
}

function refreshAnnouncement(usageResult, accountsResult) {
  const usageFailed = usageResult.status === "rejected";
  const accountsFailed = accountsResult.status === "rejected";
  if (usageFailed && accountsFailed) return `Refresh failed: ${loadIssueMessage()}`;
  if (usageFailed) return `Usage refresh failed: ${state.loadError}`;
  if (accountsFailed) return `Account metadata refresh failed: ${state.accountLoadError}`;
  return "Usage data refreshed.";
}

function renderHero() {
  const title = select("#page-title");
  const copy = select("#hero-copy");
  const reset = select("#next-reset");
  const detail = select("#next-reset-detail");
  if (!title || !copy || !reset || !detail) return;

  const counts = snapshotCounts();
  const candidate = resetCandidates()[0] || null;
  const total = state.snapshots.length;
  const clear = !total || counts.attention + counts.unavailable === 0;
  const loadIssue = loadIssueMessage();
  const emptyFailure = !total && !state.loading && Boolean(loadIssue);

  title.replaceChildren(
    element("span", { text: emptyFailure ? "No clear reading" : clear ? "A clear night" : "A little weather" }),
    element("br"),
    element("em", { text: emptyFailure ? "from the providers." : clear ? "for your quota." : "in the forecast." }),
  );
  if (!total) {
    copy.textContent = state.loading ? "Listening for provider usage…" : loadIssue || "Waiting for the first provider sync.";
  } else if (clear) {
    copy.textContent = `${counts.live} of ${total} ${total === 1 ? "account is" : "accounts are"} reporting live.`;
  } else {
    const needsAttention = counts.attention + counts.unavailable;
    copy.textContent = `${counts.live} of ${total} ${total === 1 ? "account is" : "accounts are"} live; ${needsAttention} need${needsAttention === 1 ? "s" : ""} attention.`;
  }
  if (total && loadIssue) copy.textContent += ` Last sync issue: ${loadIssue}`;

  if (candidate) {
    const date = new Date(candidate.window.resets_at);
    reset.dateTime = date.toISOString();
    reset.textContent = formatReset(candidate.window.resets_at).replace("Resets ", "");
    detail.textContent = `${accountLabel(candidate.snapshot)} · ${formatWindow(candidate.window.id)}`;
  } else {
    reset.removeAttribute("datetime");
    reset.textContent = state.loading ? "Waiting for sync" : "Not reported";
    detail.textContent = "No reset reported";
  }
}

function renderSummary() {
  const summary = select("#summary");
  if (!summary) return;
  summary.replaceChildren();
  const counts = snapshotCounts();
  const cards = [
    ["Live now", `${counts.live} / ${state.snapshots.length}`, `${counts.live} reporting live`],
    ["Attention", String(counts.attention + counts.unavailable), counts.attention + counts.unavailable ? "accounts need a look" : "nothing needs a look"],
    ["Last sync", select("#last-updated")?.textContent?.replace("Synced ", "") || "—", loadIssueMessage() || "local provider read"],
  ];
  for (const [label, value, detail] of cards) {
    const card = element("div", { className: "summary-card" });
    append(card, element("div", { className: "summary-label", text: label }), element("div", { className: "summary-value", text: String(value) }), element("div", { className: "summary-detail", text: detail }));
    summary.append(card);
  }
  if (counts.unavailable) {
    const card = element("div", { className: "summary-card summary-card-alert" });
    append(card, element("div", { className: "summary-label", text: "Action" }), element("div", { className: "summary-value", text: String(counts.unavailable) }), element("div", { className: "summary-detail", text: counts.unavailable === 1 ? "account needs attention" : "accounts need attention" }));
    summary.append(card);
  }
  summary.classList.toggle("summary-grid-four", counts.unavailable > 0);
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
  const accountMeta = [snapshot.plan_type, snapshot.source.replaceAll("_", " "), formatAge(snapshot.observed_at)].filter(Boolean).join(" · ");
  append(identityCopy, element("p", { className: "account-provider", text: accountLabel(snapshot) }), element("h3", { text: snapshot.configured_email }), element("p", { className: "account-meta", text: accountMeta }));
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
  if (snapshot.status !== "live") {
    const isCodex = snapshot.provider === "codex";
    const action = element("button", {
      className: "button button-action",
      text: isCodex
        ? snapshot.status === "unavailable"
          ? "Set up account"
          : "Retry login"
        : "Retry usage",
      attributes: { type: "button" },
    });
    action.addEventListener("click", () => {
      if (isCodex) openSetup(snapshot.account_id);
      else void refresh(true);
    });
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

function stopLoginPolling(setup = state.setup) {
  if (!setup) return;
  if (setup.pollTimer) clearTimeout(setup.pollTimer);
  setup.pollTimer = null;
  setup.pollGeneration = (setup.pollGeneration || 0) + 1;
}

const setupMessages = {
  idle: "Choose a sign-in method to begin.",
  starting: "Opening an isolated Codex session…",
  pending: "Login attempt active. Finish the sign-in in the new window or with the device code.",
  succeeded: "Login verified for the configured account.",
  failed: "Codex completed, but the account identity did not match.",
  cancelled: "Login setup cancelled. You can start another attempt when ready.",
  expired: "This login attempt expired. Start a new one when ready.",
  error: "The login session could not be started. Check the message and try again.",
};

function setupStatusMessage(status) {
  return setupMessages[status] || setupMessages.idle;
}

async function copyDeviceCode(code, button) {
  const originalLabel = button.textContent;
  try {
    if (!navigator.clipboard?.writeText) throw new Error("Clipboard access is unavailable");
    await navigator.clipboard.writeText(code);
    button.textContent = "Copied";
  } catch {
    button.textContent = "Copy failed";
  }
  window.setTimeout(() => {
    if (button.isConnected) button.textContent = originalLabel;
  }, 1500);
}

function renderSetup() {
  const panel = select("#setup-panel");
  if (!panel) return;
  panel.replaceChildren();
  if (!state.setup) {
    panel.hidden = true;
    delete panel.dataset.status;
    return;
  }
  panel.hidden = false;
  const setup = state.setup;
  panel.dataset.status = setup.status;
  const title = element("div", { className: "setup-heading" });
  const titleCopy = element("div");
  append(titleCopy, element("p", { className: "eyebrow", text: "Account setup" }), element("h2", { id: "setup-title", text: "Connect Codex" }), element("p", { className: "setup-copy", text: `Finish the sign-in for ${setup.email || setup.accountId}. Use a private window or device code if another ChatGPT account is active.` }));
  const close = element("button", { className: "icon-button setup-close", text: "×", attributes: { type: "button", "aria-label": "Close account setup" } });
  close.addEventListener("click", () => {
    if (state.setup !== setup) return;
    stopLoginPolling(setup);
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
  method.addEventListener("change", () => {
    if (state.setup === setup) state.setup.method = method.value;
  });
  methodField.append(method);
  const start = element("button", { className: "button button-action", text: setup.status === "starting" ? "Starting…" : setup.status === "pending" ? "Waiting…" : "Start login", attributes: { type: "button" } });
  start.disabled = ["starting", "pending"].includes(setup.status);
  start.addEventListener("click", startLogin);
  const cancel = element("button", { className: "button button-secondary", text: setup.attemptId && setup.status === "pending" ? "Cancel attempt" : "Close", attributes: { type: "button" } });
  cancel.addEventListener("click", () => cancelSetup(setup));
  append(controls, methodField, start, cancel);
  panel.append(controls);

  const statusClass = ["failed", "expired", "error"].includes(setup.status)
    ? "setup-status setup-status-error"
    : "setup-status";
  const status = element("p", {
    className: statusClass,
    text: setup.error || setup.message || setupStatusMessage(setup.status),
    attributes: { role: "status", "aria-live": "polite" },
  });

  if (setup.challenge) {
    const challenge = element("div", { className: "setup-challenge" });
    challenge.append(status);
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
      const codeValue = element("button", {
        className: "setup-code",
        text: setup.challenge.user_code,
        attributes: {
          type: "button",
          "aria-label": "Copy device code",
          title: "Copy device code",
        },
      });
      codeValue.addEventListener("click", () => {
        void copyDeviceCode(setup.challenge.user_code, codeValue);
      });
      append(challenge, code, codeValue);
    }
    panel.append(challenge);
  } else {
    panel.append(status);
  }
}

function openSetup(accountId) {
  stopLoginPolling();
  const account = state.snapshots.find((snapshot) => snapshot.account_id === accountId);
  state.setup = {
    accountId,
    email: account?.configured_email || accountId,
    method: "device_code",
    attemptId: null,
    challenge: null,
    status: "idle",
    pollTimer: null,
    pollGeneration: 0,
    error: null,
    message: null,
  };
  renderSetup();
  select("#setup-panel")?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest" });
  select("#setup-method")?.focus();
}

async function startLogin() {
  if (!state.setup || ["starting", "pending"].includes(state.setup.status)) return;
  const setup = state.setup;
  stopLoginPolling(setup);
  setup.status = "starting";
  setup.error = null;
  setup.message = null;
  setup.attemptId = null;
  setup.challenge = null;
  renderSetup();
  try {
    const challenge = await getJson(`/v1/accounts/${setup.accountId}/login/start`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ method: setup.method }),
    });
    if (state.setup !== setup) return;
    setup.attemptId = challenge.attempt_id;
    setup.challenge = challenge;
    setup.status = "pending";
    renderSetup();
    await pollLogin(setup.accountId, setup.attemptId, setup.pollGeneration, setup);
  } catch (error) {
    if (state.setup !== setup) return;
    stopLoginPolling(setup);
    setup.status = "error";
    setup.error = error.message;
    setup.message = null;
    renderSetup();
  }
}

async function pollLogin(accountId, attemptId, pollGeneration = state.setup?.pollGeneration, setup = state.setup) {
  if (!setup || state.setup !== setup || setup.attemptId !== attemptId || setup.pollGeneration !== pollGeneration) return;
  try {
    const attempt = await getJson(`/v1/accounts/${accountId}/login/${attemptId}`);
    if (state.setup !== setup || setup.attemptId !== attemptId || setup.pollGeneration !== pollGeneration) return;
    setup.status = attempt.status;
    setup.message = attempt.message || null;
    renderSetup();
    if (attempt.status === "pending") {
      setup.pollTimer = setTimeout(() => pollLogin(accountId, attemptId, pollGeneration, setup), 2000);
      return;
    }
    stopLoginPolling(setup);
    if (select("#live-announcement")) select("#live-announcement").textContent = setupStatusMessage(attempt.status);
    if (attempt.status === "succeeded") {
      const successAnnouncement = setupStatusMessage("succeeded");
      await refresh(true);
      if (state.setup === setup && setup.attemptId === attemptId) {
        stopLoginPolling(setup);
        state.setup = null;
        renderSetup();
        if (select("#live-announcement")) select("#live-announcement").textContent = successAnnouncement;
      }
    }
  } catch (error) {
    if (state.setup !== setup || setup.attemptId !== attemptId || setup.pollGeneration !== pollGeneration) return;
    stopLoginPolling(setup);
    setup.status = "error";
    setup.error = error.message;
    setup.message = null;
    renderSetup();
  }
}

async function cancelSetup(setup = state.setup) {
  if (!setup || state.setup !== setup) return;
  if (!setup.attemptId || setup.status !== "pending") {
    stopLoginPolling(setup);
    state.setup = null;
    renderSetup();
    return;
  }
  stopLoginPolling(setup);
  try {
    await getJson(`/v1/accounts/${setup.accountId}/login/${setup.attemptId}/cancel`, { method: "POST" });
    if (state.setup !== setup) return;
    stopLoginPolling(setup);
    setup.status = "cancelled";
    renderSetup();
    if (select("#live-announcement")) select("#live-announcement").textContent = setupStatusMessage(setup.status);
  } catch (error) {
    if (state.setup !== setup) return;
    stopLoginPolling(setup);
    setup.status = "error";
    setup.error = error.message;
    setup.message = null;
    renderSetup();
  }
}

function render() {
  renderHero();
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
  if (state.refreshPromise) {
    if (forceRefresh && !state.refreshForce) {
      if (!state.refreshQueuedPromise) {
        state.refreshQueuedPromise = state.refreshPromise.then(
          () => {
            state.refreshQueuedPromise = null;
            return refresh(true);
          },
          () => {
            state.refreshQueuedPromise = null;
            return refresh(true);
          },
        );
      }
      return state.refreshQueuedPromise;
    }
    return state.refreshPromise;
  }
  state.refreshForce = forceRefresh;
  const activeRefresh = (async () => {
    const announcement = select("#live-announcement");
    const accountList = select("#account-list");
    const button = select("#refresh-button");
    state.loading = true;
    state.loadError = null;
    state.accountLoadError = null;
    if (announcement) announcement.textContent = forceRefresh ? "Refreshing usage data…" : "Loading usage data…";
    if (accountList) accountList.setAttribute("aria-busy", "true");
    if (button) {
      button.disabled = true;
      button.textContent = "Refreshing…";
    }
    let usageResult;
    let accountsResult;
    try {
      render();
      [usageResult, accountsResult] = await Promise.allSettled([loadUsage(forceRefresh), loadAccounts()]);
      if (usageResult.status === "fulfilled") {
        state.snapshots = usageResult.value.accounts || [];
        updateTimestamp(usageResult.value.generated_at);
      } else {
        state.loadError = usageResult.reason?.message || "Usage could not be loaded.";
      }
      if (accountsResult.status === "fulfilled") {
        state.accounts = accountsResult.value || [];
      } else {
        state.accountLoadError = accountsResult.reason?.message || "Account metadata could not be loaded.";
      }
    } finally {
      const hasQueuedRefresh = Boolean(state.refreshQueuedPromise);
      if (!hasQueuedRefresh) {
        state.loading = false;
        if (accountList) accountList.removeAttribute("aria-busy");
        if (button) {
          button.disabled = false;
          button.textContent = "Refresh usage";
        }
        if (announcement && usageResult && accountsResult) announcement.textContent = refreshAnnouncement(usageResult, accountsResult);
        render();
      }
    }
  })();
  state.refreshPromise = activeRefresh;
  try {
    return await activeRefresh;
  } finally {
    if (state.refreshPromise === activeRefresh) {
      state.refreshPromise = null;
      state.refreshForce = false;
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initializeTheme();
  select("#refresh-button")?.addEventListener("click", () => refresh(true));
  refresh();
});
