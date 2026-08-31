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
  lastGeneratedAt: null,
  selectedRanges: {},
  customHistory: {},
  heatmap: [],
  activeView: "ledger",
  globalTrendHours: 24,
  trendPoints: [],
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
  if (snapshot.account_id === "codex-1" || snapshot.account_id === "codex-primary") return "Codex · 1";
  if (snapshot.account_id === "codex-2" || snapshot.account_id === "codex-secondary") return "Codex · 2";
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

function formatResetCountdown(timestamp) {
  if (!timestamp) return "";
  const resetTime = new Date(timestamp).getTime();
  if (Number.isNaN(resetTime)) return "";
  const diffMs = resetTime - Date.now();
  if (diffMs <= 0) return "Reset overdue";
  const diffMins = Math.round(diffMs / 60000);
  if (diffMins < 60) return `in ${diffMins}m`;
  const diffHours = Math.floor(diffMins / 60);
  const remMins = diffMins % 60;
  if (diffHours < 24) {
    return remMins > 0 ? `in ${diffHours}h ${remMins}m` : `in ${diffHours}h`;
  }
  const diffDays = Math.floor(diffHours / 24);
  const remHours = diffHours % 24;
  return remHours > 0 ? `in ${diffDays}d ${remHours}h` : `in ${diffDays}d`;
}

function formatWindow(id) {
  const labels = {
    gemini_weekly: "Gemini",
    gemini_five_hour: "Gemini",
    third_party_weekly: "Claude & GPT",
    third_party_five_hour: "Claude & GPT",
    five_hour: "5-Hour Quota",
    seven_day: "7-Day Quota",
    primary: "Session Window",
    secondary: "Weekly Window",
    weekly: "Weekly Quota",
    monthly: "Monthly Quota",
  };
  if (labels[id]) return labels[id];
  return id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// A handful of window ids share a formatWindow() label across different periods
// (e.g. gemini_weekly and gemini_five_hour both read "Gemini"), so callers that
// show multiple windows side by side need a period suffix to tell them apart.
function formatWindowPeriod(id) {
  if (id.endsWith("_five_hour")) return " · 5-Hour";
  if (id.endsWith("_weekly")) return " · Weekly";
  return "";
}

function getWindowBadge(window) {
  if (window.window_minutes) {
    if (window.window_minutes >= 10000) return "Monthly";
    if (window.window_minutes >= 1000) return "7-Day";
    if (window.window_minutes >= 60) return `${Math.round(window.window_minutes / 60)}h`;
    return `${window.window_minutes}m`;
  }
  if (window.id.includes("weekly") || window.id.includes("7_day") || window.id.includes("seven_day")) return "7-Day";
  if (window.id.includes("five_hour") || window.id.includes("5h")) return "5-Hour";
  return "Quota";
}

function formatPercent(percent) {
  return Number.isInteger(percent) ? `${percent}%` : `${percent.toFixed(1)}%`;
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



const SVG_NS = "http://www.w3.org/2000/svg";

function svgEl(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  return node;
}

function usageColorVar(percent) {
  if (percent >= 90) return "var(--danger)";
  if (percent >= 75) return "var(--warning)";
  return "var(--accent)";
}

function providerVar(provider, accountId) {
  if (provider === "codex" && accountId && (accountId.includes("secondary") || accountId.includes("-2"))) return "var(--p-codex-2)";
  return {
    codex: "var(--p-codex)",
    claude: "var(--p-claude)",
    antigravity: "var(--p-antigravity)",
  }[provider] || "var(--accent)";
}

function ringSvg(size, stroke, percent, strokeVar) {
  const radius = size / 2 - stroke / 2 - 1;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(100, percent));
  const offset = circumference * (1 - clamped / 100);
  const svg = svgEl("svg", { viewBox: `0 0 ${size} ${size}` });
  svg.append(
    svgEl("circle", { class: "gauge-track", cx: size / 2, cy: size / 2, r: radius }),
    svgEl("circle", {
      class: "gauge-arc",
      cx: size / 2,
      cy: size / 2,
      r: radius,
      stroke: strokeVar,
      "stroke-dasharray": circumference.toFixed(2),
      "stroke-dashoffset": offset.toFixed(2),
    }),
  );
  return svg;
}

function fleetPeakUsage() {
  const values = state.snapshots.flatMap((s) => (s.windows || []).map((w) => w.used_percent));
  return values.length ? Math.max(...values) : null;
}

function accountPeakUsage(snapshot) {
  const values = (snapshot.windows || []).map((w) => w.used_percent);
  return values.length ? Math.max(...values) : null;
}

function renderHeroGauge(gauge) {
  if (!gauge) return;
  gauge.replaceChildren();
  const counts = snapshotCounts();
  const total = state.snapshots.length;
  const peak = fleetPeakUsage();
  const hasPeak = peak !== null;
  const pct = hasPeak ? peak : 0;
  const arcColor = hasPeak ? usageColorVar(pct) : "var(--line-strong)";

  gauge.append(ringSvg(170, 10, pct, arcColor));

  const center = element("div", { className: "hero-gauge-center" });
  const value = element("div", { className: "gauge-value" });
  if (hasPeak) {
    value.append(document.createTextNode(String(Math.round(pct))), element("span", { text: "%" }));
  } else {
    value.append(element("span", { text: "—" }));
  }
  const attention = counts.attention + counts.unavailable;
  const sub = total
    ? `${counts.live} live · ${attention} watch`
    : state.loading
      ? "syncing"
      : "no data";
  append(
    center,
    element("div", { className: "gauge-label", text: "Peak load" }),
    value,
    element("div", { className: "gauge-sub", text: sub }),
  );
  gauge.append(center);
}

function renderHero() {
  const title = select("#page-title");
  const copy = select("#hero-copy");
  if (!title || !copy) return;

  const counts = snapshotCounts();
  const total = state.snapshots.length;
  const attention = counts.attention + counts.unavailable;
  const peak = fleetPeakUsage();
  const stormy = attention > 0 || (peak !== null && peak >= 90);
  const clear = !total || !stormy;
  const loadIssue = loadIssueMessage();
  const emptyFailure = !total && !state.loading && Boolean(loadIssue);

  const headline = emptyFailure
    ? ["No clear reading", "from the providers."]
    : clear
      ? ["A clear night", "for your quota."]
      : ["Weather moving in", "on your quota."];
  title.replaceChildren(
    element("span", { text: headline[0] }),
    element("br"),
    element("em", { text: headline[1] }),
  );

  if (!total) {
    copy.textContent = state.loading
      ? "Listening for provider usage…"
      : loadIssue || "Waiting for the first provider sync.";
  } else {
    let msg = `${counts.live} of ${total} ${total === 1 ? "account is" : "accounts are"} reporting live`;
    if (attention) msg += `; ${attention} need${attention === 1 ? "s" : ""} a look`;
    msg += peak !== null ? `. The heaviest window sits at ${formatPercent(peak)} used.` : ".";
    copy.textContent = msg;
    if (loadIssue) copy.textContent += ` Last sync issue: ${loadIssue}`;
  }

  renderHeroGauge(select("#hero-gauge"));
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
  
  const top = element("div", { className: "window-top" });
  const titleBox = element("div", { className: "window-title-box" });
  titleBox.append(
    element("span", { className: "window-name", text: formatWindow(window.id) }),
    element("span", { className: "window-badge", text: getWindowBadge(window) })
  );

  const statBox = element("div", { className: "window-stat-box" });
  const usedVal = element("span", { className: "window-used-val", text: formatPercent(window.used_percent) });
  const remainingPercent = Math.max(0, 100 - window.used_percent);
  const remainingSub = element("span", { className: "window-remaining-sub", text: `${formatPercent(remainingPercent)} left` });
  append(statBox, usedVal, remainingSub);

  append(top, titleBox, statBox);

  const track = element("div", {
    className: "meter",
    attributes: {
      role: "progressbar",
      "aria-valuemin": "0",
      "aria-valuemax": "100",
      "aria-valuenow": String(window.used_percent),
      "aria-label": `${formatWindow(window.id)} usage`,
    },
  });
  const fill = element("span", { className: "meter-fill" });
  fill.style.width = `${Math.min(100, Math.max(0, window.used_percent))}%`;
  if (window.used_percent >= 90) {
    fill.classList.add("meter-fill-critical");
  } else if (window.used_percent >= 75) {
    fill.classList.add("meter-fill-warn");
  }
  track.append(fill);

  const footer = element("div", { className: "window-footer" });
  const resetLeft = element("div", { className: "window-reset-left" });
  if (window.resets_at) {
    resetLeft.append(
      element("span", { className: "reset-clock-icon", text: "⏱" }),
      element("span", { className: "window-reset-date", text: formatReset(window.resets_at) })
    );
  } else {
    resetLeft.append(element("span", { className: "window-reset-date", text: "Rolling limit" }));
  }

  footer.append(resetLeft);
  
  const countdown = formatResetCountdown(window.resets_at);
  if (countdown) {
    footer.append(element("span", { className: "window-countdown-pill", text: countdown }));
  }

  append(wrapper, top, track, footer);
  return wrapper;
}

function renderSparkline(points, accountId, rangeHours = 24) {
  if (!points || points.length === 0) return null;
  const pts = points.length === 1 ? [points[0], points[0]] : points;
  const width = 600;
  const height = 32;

  const maxVal = Math.max(...pts.map((p) => p.used_percent));
  const minVal = Math.min(...pts.map((p) => p.used_percent));
  const latestVal = pts[pts.length - 1].used_percent;

  const coords = pts.map((p, idx) => {
    const x = (idx / (pts.length - 1)) * width;
    const y = height - (Math.min(100, Math.max(0, p.used_percent)) / 100) * (height - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const polylinePoints = coords.join(" ");
  const polygonPoints = `0,${height} ${polylinePoints} ${width},${height}`;

  const container = element("div", { className: "trend-container" });
  const trendHeader = element("div", { className: "trend-header" });
  
  const headerLeft = element("div", { className: "trend-header-left" });
  const rangeLabelText = rangeHours >= 720 ? "30-Day" : rangeHours >= 168 ? "7-Day" : "24-Hour";
  const label = element("div", { className: "trend-label", text: `${rangeLabelText} Usage Trend` });
  
  const rangeSwitcher = element("div", { className: "range-switcher" });
  [
    { label: "24h", hours: 24 },
    { label: "7d", hours: 168 },
    { label: "30d", hours: 720 },
  ].forEach((r) => {
    const btn = element("button", {
      className: `range-btn${rangeHours === r.hours ? " active" : ""}`,
      text: r.label,
      attributes: { type: "button" },
    });
    btn.addEventListener("click", async () => {
      state.selectedRanges[accountId] = r.hours;
      try {
        const data = await getJson(`/v1/history?account_id=${encodeURIComponent(accountId)}&hours=${r.hours}`);
        state.customHistory[accountId] = data;
        render();
      } catch (err) {
        console.warn("Failed to fetch range history:", err);
      }
    });
    rangeSwitcher.append(btn);
  });
  
  append(headerLeft, label, rangeSwitcher);

  const trendMeta = element("div", { className: "trend-meta", text: `Peak: ${formatPercent(maxVal)} · Current: ${formatPercent(latestVal)}` });
  append(trendHeader, headerLeft, trendMeta);

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("class", "trend-sparkline");
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("aria-label", `${rangeLabelText} usage trend`);

  const polygon = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
  polygon.setAttribute("points", polygonPoints);

  const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  polyline.setAttribute("points", polylinePoints);

  svg.append(polygon, polyline);
  append(container, trendHeader, svg);
  return container;
}

function renderCardMenu(snapshot, isCodex) {
  const wrap = element("div", { className: "card-menu" });
  const trigger = element("button", {
    className: "card-menu-trigger",
    text: "⋮",
    attributes: { type: "button", "aria-label": "More actions", "aria-haspopup": "true" },
  });
  const popover = element("div", { className: "card-menu-popover" });

  const closeMenu = () => wrap.classList.remove("open");

  if (isCodex) {
    const loginItem = element("button", {
      className: "card-menu-item",
      text: "Log in / Connect",
      attributes: { type: "button" },
    });
    loginItem.addEventListener("click", () => {
      closeMenu();
      openSetup(snapshot.account_id);
    });
    popover.append(loginItem);
  }

  if (!isCodex && snapshot.status !== "live") {
    const retryItem = element("button", {
      className: "card-menu-item",
      text: "Retry usage",
      attributes: { type: "button" },
    });
    retryItem.addEventListener("click", () => {
      closeMenu();
      void refresh(true);
    });
    popover.append(retryItem);
  }

  const deleteItem = element("button", {
    className: "card-menu-item card-menu-item-danger",
    text: "Delete account",
    attributes: { type: "button" },
  });
  deleteItem.addEventListener("click", async () => {
    closeMenu();
    const label = snapshot.configured_email || snapshot.account_id;
    if (!window.confirm(`Remove ${label} from Time-to-Sleep? This only stops tracking it here.`)) return;
    try {
      const res = await fetch(`/v1/accounts/config/${snapshot.account_id}`, { method: "DELETE" });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to delete account");
      }
      await refresh(true);
    } catch (err) {
      alert("Error: " + err.message);
    }
  });
  popover.append(deleteItem);

  trigger.addEventListener("click", (event) => {
    event.stopPropagation();
    const willOpen = !wrap.classList.contains("open");
    document.querySelectorAll(".card-menu.open").forEach((el) => el.classList.remove("open"));
    if (willOpen) wrap.classList.add("open");
  });

  append(wrap, trigger, popover);
  return wrap;
}

function renderAccount(snapshot) {
  const card = element("article", { className: `account-card status-${snapshot.status}` });
  card.style.setProperty("--provider", providerVar(snapshot.provider, snapshot.account_id));
  const header = element("div", { className: "account-card-header" });
  const identity = element("div", { className: "account-identity" });
  const monogram = element("span", {
    className: `provider-monogram provider-${snapshot.provider}`,
    text: providerLabel(snapshot.provider).slice(0, 2).toUpperCase(),
    attributes: { "aria-hidden": "true" },
  });
  const identityCopy = element("div", { className: "identity-copy" });
  
  const accAnalytics = state.analytics?.accounts?.find((a) => a.account_id === snapshot.account_id);
  
  const eyebrow = element("div", { className: "account-eyebrow" });
  const providerHeading = element("span", { className: "account-provider", text: accountLabel(snapshot) });
  eyebrow.append(providerHeading);
  
  if (snapshot.plan_type) {
    eyebrow.append(element("span", { className: "plan-badge", text: snapshot.plan_type }));
  }
  if (accAnalytics?.recommended) {
    eyebrow.append(element("span", { className: "rec-badge", text: "★ Recommended" }));
  }

  const emailHeading = element("h3", { className: "account-email", text: snapshot.configured_email });

  const metaParts = [
    snapshot.source.replaceAll("_", " "),
    `Synced ${formatAge(snapshot.observed_at)}`
  ];
  if (snapshot.observed_email && snapshot.observed_email !== snapshot.configured_email) {
    metaParts.push(`Observed: ${snapshot.observed_email}`);
  }
  const metaContainer = element("p", { className: "account-meta", text: metaParts.join(" · ") });

  append(identityCopy, eyebrow, emailHeading, metaContainer);
  append(identity, monogram, identityCopy);

  const headerRight = element("div", { className: "account-header-right" });

  const peak = accountPeakUsage(snapshot);
  if (peak !== null) {
    const gauge = element("div", {
      className: "account-gauge",
      attributes: {
        role: "img",
        "aria-label": `Peak usage ${formatPercent(peak)}`,
        title: `Peak window usage: ${formatPercent(peak)}`,
      },
    });
    gauge.append(ringSvg(54, 5, peak, usageColorVar(peak)));
    const num = element("div", { className: "account-gauge-num" });
    const numInner = element("span");
    numInner.append(document.createTextNode(String(Math.round(peak))), element("small", { text: "%" }));
    num.append(numInner);
    gauge.append(num);
    headerRight.append(gauge);
  }

  const status = element("div", { className: "status-stack" });
  const badge = element("span", { className: "status-badge", text: statusLabel(snapshot.status) });
  badge.prepend(element("span", { className: "status-dot", attributes: { "aria-hidden": "true" } }));
  append(status, badge);
  if (snapshot.observed_email && snapshot.observed_email !== snapshot.configured_email) {
    status.append(element("span", { className: "status-note", text: `Observed ${snapshot.observed_email}` }));
  }

  const cardActions = element("div", { className: "card-actions" });
  const isCodex = snapshot.provider === "codex";
  const needsLogin = isCodex && (snapshot.status !== "live" || !snapshot.windows || snapshot.windows.length === 0 || !snapshot.observed_email);
  if (needsLogin) {
    const action = element("button", {
      className: "button button-action button-sm",
      text: snapshot.status === "unavailable" ? "Set up account" : "Connect account",
      attributes: { type: "button" },
    });
    action.addEventListener("click", () => openSetup(snapshot.account_id));
    cardActions.append(action);
  }
  cardActions.append(renderCardMenu(snapshot, isCodex));
  append(headerRight, status, cardActions);

  append(header, identity, headerRight);
  card.append(header);

  // Key Analytics stats strip
  if (accAnalytics && (accAnalytics.burn_rate_per_hour || accAnalytics.minutes_to_exhaustion || accAnalytics.recommendation_reason)) {
    const statsStrip = element("div", { className: "account-stats-strip" });
    if (accAnalytics.burn_rate_per_hour) {
      const stat = element("div", { className: "stat-item" });
      const icon = element("span", { className: "stat-icon", text: "🔥" });
      const content = element("div", { className: "stat-content" });
      append(content, element("span", { className: "stat-label", text: "Burn Rate" }), element("span", { className: "stat-value", text: `${accAnalytics.burn_rate_per_hour}% / hr` }));
      append(stat, icon, content);
      statsStrip.append(stat);
    }
    if (accAnalytics.minutes_to_exhaustion) {
      const stat = element("div", { className: "stat-item" });
      const icon = element("span", { className: "stat-icon", text: "⏳" });
      const content = element("div", { className: "stat-content" });
      const hours = Math.round(accAnalytics.minutes_to_exhaustion / 60);
      append(content, element("span", { className: "stat-label", text: "Est. Runway" }), element("span", { className: "stat-value", text: `~${hours}h remaining` }));
      append(stat, icon, content);
      statsStrip.append(stat);
    }
    if (accAnalytics.recommendation_reason) {
      const stat = element("div", { className: "stat-item stat-item-reason" });
      const icon = element("span", { className: "stat-icon", text: "★" });
      const content = element("div", { className: "stat-content" });
      append(content, element("span", { className: "stat-label", text: "Smart Routing" }), element("span", { className: "stat-value", text: accAnalytics.recommendation_reason }));
      append(stat, icon, content);
      statsStrip.append(stat);
    }
    card.append(statsStrip);
  }

  if (snapshot.windows?.length) {
    const windows = element("div", { className: "window-list" });
    snapshot.windows.forEach((window) => windows.append(renderWindow(window)));
    card.append(windows);
  }

  // Render multi-range history trend sparkline if points exist
  const selectedHours = state.selectedRanges[snapshot.account_id] || 24;
  const primaryWindowId = snapshot.windows?.[0]?.id;
  const historySource = state.customHistory[snapshot.account_id] || state.history;
  const historyPoints = historySource?.filter(
    (p) => p.account_id === snapshot.account_id && (!primaryWindowId || p.window_id === primaryWindowId)
  );
  if (historyPoints?.length >= 1) {
    const sparkline = renderSparkline(historyPoints, snapshot.account_id, selectedHours);
    if (sparkline) card.append(sparkline);
  }

  const hasErrorCode = snapshot.error_code && snapshot.error_code !== "none";
  if (snapshot.message || hasErrorCode) {
    const alertBox = element("div", { className: "account-alert-banner" });
    if (hasErrorCode) {
      alertBox.append(element("span", { className: "account-error", text: snapshot.error_code.replaceAll("_", " ") }));
    }
    if (snapshot.message) {
      alertBox.append(element("p", { className: "account-message", text: snapshot.message }));
    }
    card.append(alertBox);
  }

  return card;
}

function renderAccounts() {
  const list = select("#account-list");
  if (!list) return;
  list.replaceChildren();

  if (state.analytics?.suggestions?.length) {
    for (const suggestion of state.analytics.suggestions) {
      const advice = element("div", { className: "smart-advice" });
      append(
        advice,
        element("span", { className: "smart-advice-icon", text: "💡" }),
        element("span", { className: "smart-advice-text", text: suggestion })
      );
      list.append(advice);
    }
  }

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

async function copyDeviceCode(code, badge) {
  const original = badge.textContent;
  try {
    if (!navigator.clipboard?.writeText) throw new Error("Clipboard access unavailable");
    await navigator.clipboard.writeText(code);
    badge.textContent = "✓ Copied!";
    badge.classList.add("copied");
  } catch {
    badge.textContent = "Copy failed";
  }
  window.setTimeout(() => {
    if (badge.isConnected) {
      badge.textContent = original;
      badge.classList.remove("copied");
    }
  }, 2000);
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

  const backdrop = element("div", { className: "setup-backdrop" });
  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) {
      stopLoginPolling(setup);
      state.setup = null;
      renderSetup();
    }
  });

  const modal = element("div", { className: "setup-modal" });

  // Header
  const header = element("div", { className: "setup-modal-header" });
  const headerLeft = element("div");
  const eyebrowRow = element("div", { className: "setup-eyebrow-row" });
  append(
    eyebrowRow,
    element("span", { className: "setup-provider-pill", text: "Codex OAuth" }),
    element("span", { className: "setup-account-badge", text: setup.accountId })
  );
  const title = element("h2", { className: "setup-modal-title", text: "Connect Codex Account" });
  const copy = element("p", {
    className: "setup-modal-copy",
    text: `Authorize ${setup.accountId} to track quotas and rate limits in its isolated directory.`
  });
  append(headerLeft, eyebrowRow, title, copy);

  const closeBtn = element("button", {
    className: "setup-modal-close",
    text: "✕",
    attributes: { type: "button", "aria-label": "Close" }
  });
  closeBtn.addEventListener("click", () => {
    stopLoginPolling(setup);
    state.setup = null;
    renderSetup();
  });

  append(header, headerLeft, closeBtn);
  modal.append(header);

  // Method Selector (when not in challenge screen)
  if (!setup.challenge) {
    const methodSection = element("div", { className: "setup-methods-grid" });

    // Method 1: Device Code
    const deviceCard = element("button", {
      className: `setup-method-card ${setup.method === "device_code" ? "active" : ""}`,
      attributes: { type: "button" }
    });
    deviceCard.addEventListener("click", () => {
      if (["starting", "pending"].includes(setup.status)) return;
      setup.method = "device_code";
      renderSetup();
    });
    const deviceIcon = element("span", { className: "setup-method-icon", text: "📟" });
    const deviceText = element("div", { className: "setup-method-info" });
    append(
      deviceText,
      element("div", { className: "setup-method-title", text: "Device Code" }),
      element("div", { className: "setup-method-desc", text: "Copy a one-time code to authorize on openai.com." })
    );
    append(deviceCard, deviceIcon, deviceText);

    // Method 2: Browser
    const browserCard = element("button", {
      className: `setup-method-card ${setup.method === "browser" ? "active" : ""}`,
      attributes: { type: "button" }
    });
    browserCard.addEventListener("click", () => {
      if (["starting", "pending"].includes(setup.status)) return;
      setup.method = "browser";
      renderSetup();
    });
    const browserIcon = element("span", { className: "setup-method-icon", text: "🌐" });
    const browserText = element("div", { className: "setup-method-info" });
    append(
      browserText,
      element("div", { className: "setup-method-title", text: "Browser Sign-In" }),
      element("div", { className: "setup-method-desc", text: "Direct OAuth login in your default browser." })
    );
    append(browserCard, browserIcon, browserText);

    append(methodSection, deviceCard, browserCard);
    modal.append(methodSection);
  }

  // Active Challenge Flow
  if (setup.challenge) {
    const challengeBox = element("div", { className: "setup-challenge-box" });

    if (setup.challenge.user_code) {
      const codeHeader = element("div", { className: "setup-code-header" });
      append(
        codeHeader,
        element("span", { className: "setup-step-num", text: "1" }),
        element("span", { className: "setup-step-text", text: "Click to copy your device code:" })
      );

      const codeBtn = element("button", {
        className: "setup-code-badge",
        attributes: { type: "button", title: "Click to copy code" }
      });
      const codeVal = element("span", { className: "setup-code-val", text: setup.challenge.user_code });
      const copyHint = element("span", { className: "setup-copy-hint", text: "📋 Copy" });
      append(codeBtn, codeVal, copyHint);

      codeBtn.addEventListener("click", () => {
        void copyDeviceCode(setup.challenge.user_code, copyHint);
      });

      append(challengeBox, codeHeader, codeBtn);

      if (setup.challenge.verification_url || setup.challenge.auth_url) {
        const step2 = element("div", { className: "setup-code-header", attributes: { style: "margin-top: 8px;" } });
        append(
          step2,
          element("span", { className: "setup-step-num", text: "2" }),
          element("span", { className: "setup-step-text", text: "Open verification page & paste code:" })
        );

        const openLink = element("a", {
          className: "button button-action setup-open-link",
          text: "Open OpenAI Verification Page ↗",
          attributes: {
            href: setup.challenge.verification_url || setup.challenge.auth_url,
            target: "_blank",
            rel: "noreferrer"
          }
        });
        append(challengeBox, step2, openLink);
      }
    } else if (setup.challenge.auth_url) {
      const authLink = element("a", {
        className: "button button-action setup-open-link",
        text: "Open Authorization Page ↗",
        attributes: {
          href: setup.challenge.auth_url,
          target: "_blank",
          rel: "noreferrer"
        }
      });
      challengeBox.append(authLink);
    }

    // Live waiting pulse
    const waitingBar = element("div", { className: "setup-waiting-bar" });
    const spinner = element("span", { className: "setup-spinner" });
    const waitingText = element("span", {
      className: "setup-waiting-text",
      text: setup.status === "pending" ? "Waiting for authorization in browser…" : setupStatusMessage(setup.status)
    });
    append(waitingBar, spinner, waitingText);
    challengeBox.append(waitingBar);

    modal.append(challengeBox);
  }

  // Error Banner
  if (setup.status === "error" || setup.error || setup.status === "failed") {
    const errorBox = element("div", { className: "setup-error-banner" });
    append(
      errorBox,
      element("span", { className: "setup-error-icon", text: "⚠️" }),
      element("span", { className: "setup-error-text", text: setup.error || setup.message || "Sign-in attempt failed. Please try again." })
    );
    modal.append(errorBox);
  }

  // Footer Actions
  const footer = element("div", { className: "setup-modal-footer" });
  if (!setup.challenge) {
    const cancelBtn = element("button", {
      className: "button button-secondary",
      text: "Cancel",
      attributes: { type: "button" }
    });
    cancelBtn.addEventListener("click", () => {
      stopLoginPolling(setup);
      state.setup = null;
      renderSetup();
    });

    const startBtn = element("button", {
      className: "button button-action setup-start-btn",
      text: setup.status === "starting" ? "Starting…" : "Start Sign-In →",
      attributes: { type: "button" }
    });
    startBtn.disabled = ["starting", "pending"].includes(setup.status);
    startBtn.addEventListener("click", startLogin);

    append(footer, cancelBtn, startBtn);
  } else {
    const cancelBtn = element("button", {
      className: "button button-secondary setup-cancel-btn",
      text: "Cancel Attempt",
      attributes: { type: "button" }
    });
    cancelBtn.addEventListener("click", () => cancelSetup(setup));
    footer.append(cancelBtn);
  }
  modal.append(footer);

  backdrop.append(modal);
  panel.append(backdrop);
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
    if (attempt.status === "pending") {
      const statusEl = select("#setup-panel .setup-status");
      if (statusEl) statusEl.textContent = setup.error || setup.message || setupStatusMessage(setup.status);
      setup.pollTimer = setTimeout(() => pollLogin(accountId, attemptId, pollGeneration, setup), 2000);
      return;
    }
    renderSetup();
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

const providerColors = {
  codex: "#38bdf8",
  claude: "#f97316",
  antigravity: "#d6f66c",
};

function getSeriesColor(provider, accountId, windowId) {
  if (provider === "codex") {
    if (accountId && (accountId.includes("secondary") || accountId.includes("-2"))) return "#818cf8";
    return "#38bdf8";
  }
  if (provider === "claude") {
    if (windowId === "seven_day") return "#ea580c";
    return "#f97316";
  }
  if (provider === "antigravity") {
    return "#d6f66c";
  }
  return providerColors[provider] || "#a78bfa";
}

function getAccountColor(account) {
  return getSeriesColor(account.provider, account.account_id);
}

function switchView(viewName) {
  state.activeView = viewName;
  const ledgerView = select("#view-ledger");
  const trendsView = select("#view-trends");
  const ledgerTab = select("#tab-ledger-btn");
  const trendsTab = select("#tab-trends-btn");

  if (viewName === "trends") {
    if (ledgerView) {
      ledgerView.hidden = true;
      ledgerView.classList.remove("active");
    }
    if (trendsView) {
      trendsView.hidden = false;
      trendsView.classList.add("active");
    }
    if (ledgerTab) ledgerTab.classList.remove("active");
    if (trendsTab) trendsTab.classList.add("active");
    window.location.hash = "trends";
    void loadTrendsHistory(state.globalTrendHours);
  } else {
    if (trendsView) {
      trendsView.hidden = true;
      trendsView.classList.remove("active");
    }
    if (ledgerView) {
      ledgerView.hidden = false;
      ledgerView.classList.add("active");
    }
    if (trendsTab) trendsTab.classList.remove("active");
    if (ledgerTab) ledgerTab.classList.add("active");
    window.location.hash = "ledger";
    render();
  }
}

async function loadTrendsHistory(hours = 24) {
  state.globalTrendHours = hours;
  try {
    const [historyData, heatmapData] = await Promise.all([
      getJson(`/v1/history?hours=${hours}`),
      getJson(`/v1/analytics/heatmap?days=${hours >= 720 ? 30 : hours >= 168 ? 7 : 1}`),
    ]);
    state.trendPoints = historyData || [];
    state.heatmap = heatmapData || [];
    renderTrendsPage();
  } catch (err) {
    console.warn("Failed to load trends history:", err);
  }
}

function render() {
  if (state.activeView === "ledger") {
    renderHero();
    renderSummary();
    renderAccounts();
    renderSetup();
  } else if (state.activeView === "trends") {
    renderTrendsPage();
  }
}

function renderTrendsPage() {
  renderMacroChart();
  renderDetailedSparklinesGrid();
  renderHeatmap();
  renderHistoryTable();
}

function renderMacroChart() {
  const container = select("#macro-chart-container");
  const legend = select("#macro-legend");
  if (!container) return;
  container.replaceChildren();
  if (legend) legend.replaceChildren();

  const points = state.trendPoints || [];
  if (points.length === 0) {
    container.append(element("div", { className: "empty-state", text: "No historical usage records recorded yet in this range." }));
    return;
  }

  const accountIds = [...new Set(points.map((p) => p.account_id))];
  if (accountIds.length === 0) return;

  // Render clean legend (1 item per account)
  if (legend) {
    accountIds.forEach((accId) => {
      const snap = state.snapshots.find((s) => s.account_id === accId);
      const prov = snap?.provider || (points.find((p) => p.account_id === accId)?.provider) || "codex";
      const color = getAccountColor({ provider: prov, account_id: accId });
      const item = element("div", { className: "legend-item" });
      const dot = element("span", { className: "legend-color" });
      dot.style.background = color;
      const labelText = snap ? `${accountLabel(snap)} (${accId})` : `${providerLabel(prov)} (${accId})`;
      const lbl = element("span", { text: labelText });
      append(item, dot, lbl);
      legend.append(item);
    });
  }

  // Draw Multi-series SVG (Peak quota usage per account over time)
  const width = 800;
  const height = 180;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("class", "chart-svg-interactive");
  svg.setAttribute("preserveAspectRatio", "none");

  // Gridlines & Axis labels
  [0, 25, 50, 75, 100].forEach((pct) => {
    const y = height - 20 - (pct / 100) * (height - 30);
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", "30");
    line.setAttribute("y1", String(y));
    line.setAttribute("x2", String(width));
    line.setAttribute("y2", String(y));
    line.setAttribute("class", "chart-gridline");
    svg.append(line);

    const txt = document.createElementNS("http://www.w3.org/2000/svg", "text");
    txt.setAttribute("x", "5");
    txt.setAttribute("y", String(y + 3));
    txt.setAttribute("class", "chart-axis-text");
    txt.textContent = `${pct}%`;
    svg.append(txt);
  });

  const timestamps = points.map((p) => new Date(p.observed_at).getTime());
  const minTime = Math.min(...timestamps);
  const maxTime = Math.max(...timestamps);
  const timeSpan = Math.max(maxTime - minTime, 1);

  // Plot 1 clean line per account (peak quota across windows at each timestamp)
  accountIds.forEach((accId) => {
    const accRawPoints = points.filter((p) => p.account_id === accId);
    if (accRawPoints.length === 0) return;

    // Group by timestamp and pick the peak usage window
    const timeMap = new Map();
    accRawPoints.forEach((p) => {
      const t = new Date(p.observed_at).getTime();
      const existing = timeMap.get(t);
      if (existing === undefined || p.used_percent > existing.used_percent) {
        timeMap.set(t, p);
      }
    });

    const accPoints = Array.from(timeMap.values()).sort(
      (a, b) => new Date(a.observed_at).getTime() - new Date(b.observed_at).getTime()
    );

    const snap = state.snapshots.find((s) => s.account_id === accId);
    const prov = snap?.provider || accPoints[0].provider;
    const color = getAccountColor({ provider: prov, account_id: accId });

    const coords = accPoints.map((p) => {
      const t = new Date(p.observed_at).getTime();
      const x = 32 + ((t - minTime) / timeSpan) * (width - 40);
      const y = height - 20 - (Math.min(100, Math.max(0, p.used_percent)) / 100) * (height - 30);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });

    const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    polyline.setAttribute("points", coords.join(" "));
    polyline.setAttribute("fill", "none");
    polyline.setAttribute("stroke", color);
    polyline.setAttribute("stroke-width", "2.5");
    polyline.setAttribute("stroke-linecap", "round");
    polyline.setAttribute("stroke-linejoin", "round");
    svg.append(polyline);
  });

  container.append(svg);
}

function renderDetailedSparklinesGrid() {
  const grid = select("#trends-cards-grid");
  if (!grid) return;
  grid.replaceChildren();

  const points = state.trendPoints || [];
  const accountsToRender = state.snapshots.length > 0
    ? state.snapshots
    : [...new Set(points.map((p) => p.account_id))].map((id) => ({ account_id: id, provider: points.find((p) => p.account_id === id)?.provider || "codex" }));

  if (accountsToRender.length === 0) {
    grid.append(element("div", { className: "empty-state", text: "No accounts configured or discovered." }));
    return;
  }

  accountsToRender.forEach((acc) => {
    const card = element("div", { className: "trends-detail-card" });
    card.style.setProperty("--provider", providerVar(acc.provider, acc.account_id));
    const header = element("div", { className: "trends-detail-header" });
    const idWrap = element("div", { className: "account-identity" });
    const monogram = element("span", {
      className: `provider-monogram provider-${acc.provider}`,
      text: providerLabel(acc.provider).slice(0, 2).toUpperCase(),
    });
    const info = element("div", { className: "identity-copy" });
    append(
      info,
      element("h3", { className: "account-email", text: acc.configured_email || acc.account_id }),
      element("p", { className: "account-meta", text: `${providerLabel(acc.provider)} · ID: ${acc.account_id}` })
    );
    append(idWrap, monogram, info);
    header.append(idWrap);
    card.append(header);

    // Get all windows for this account present in points
    const accAllPoints = points.filter((p) => p.account_id === acc.account_id);
    let windowIds = [...new Set(accAllPoints.map((p) => p.window_id))];
    if (windowIds.length === 0 && acc.windows?.length) {
      windowIds = acc.windows.map((w) => w.id);
    }
    if (windowIds.length === 0) windowIds.push("primary");

    windowIds.forEach((winId) => {
      const accPoints = accAllPoints
        .filter((p) => p.window_id === winId)
        .sort((a, b) => new Date(a.observed_at).getTime() - new Date(b.observed_at).getTime());

      const maxVal = accPoints.length > 0 ? Math.max(...accPoints.map((p) => p.used_percent)) : 0;
      const minVal = accPoints.length > 0 ? Math.min(...accPoints.map((p) => p.used_percent)) : 0;
      const currentVal = accPoints.length > 0 ? accPoints[accPoints.length - 1].used_percent : 0;
      const deltaVal = accPoints.length >= 2 ? currentVal - accPoints[0].used_percent : 0;

      if (windowIds.length > 1) {
        const winLabel = formatWindow(winId);
        const suffix = /window$/i.test(winLabel) ? "" : " Window";
        const winTitle = element("div", {
          className: "detail-window-title",
          text: `${winLabel}${formatWindowPeriod(winId)}${suffix}`,
        });
        card.append(winTitle);
      }

      // Stats Row
      const statsRow = element("div", { className: "detail-stats-row" });
      [
        { label: "Current", val: `${currentVal.toFixed(1)}%` },
        { label: "Peak", val: `${maxVal.toFixed(1)}%` },
        { label: "Min", val: `${minVal.toFixed(1)}%` },
        { label: "Net Change", val: `${deltaVal >= 0 ? "+" : ""}${deltaVal.toFixed(1)}%` },
      ].forEach((s) => {
        const st = element("div", { className: "detail-stat" });
        append(st, element("span", { className: "detail-stat-lbl", text: `${s.label}: ` }), element("span", { className: "detail-stat-val", text: s.val }));
        statsRow.append(st);
      });
      card.append(statsRow);

      // Full High-Res Sparkline Chart
      const chartWrap = element("div", { className: "full-sparkline-wrap" });
      if (accPoints.length >= 1) {
        const pts = accPoints.length === 1 ? [accPoints[0], accPoints[0]] : accPoints;
        const width = 500;
        const height = 110;

        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
        svg.setAttribute("class", "chart-svg-interactive");
        svg.setAttribute("preserveAspectRatio", "none");

        // Gridlines (0, 50, 100)
        [0, 50, 100].forEach((pct) => {
          const y = height - 16 - (pct / 100) * (height - 24);
          const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
          line.setAttribute("x1", "24");
          line.setAttribute("y1", String(y));
          line.setAttribute("x2", String(width));
          line.setAttribute("y2", String(y));
          line.setAttribute("class", "chart-gridline");
          svg.append(line);

          const txt = document.createElementNS("http://www.w3.org/2000/svg", "text");
          txt.setAttribute("x", "2");
          txt.setAttribute("y", String(y + 3));
          txt.setAttribute("class", "chart-axis-text");
          txt.textContent = `${pct}%`;
          svg.append(txt);
        });

        const coords = pts.map((p, idx) => {
          const x = 26 + (idx / (pts.length - 1)) * (width - 32);
          const y = height - 16 - (Math.min(100, Math.max(0, p.used_percent)) / 100) * (height - 24);
          return `${x.toFixed(1)},${y.toFixed(1)}`;
        });

        const polylinePoints = coords.join(" ");
        const polygonPoints = `26,${height - 16} ${polylinePoints} ${width - 6},${height - 16}`;

        const color = getSeriesColor(acc.provider, acc.account_id, winId);

        const polygon = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
        polygon.setAttribute("points", polygonPoints);
        polygon.setAttribute("fill", color);
        polygon.setAttribute("opacity", "0.15");

        const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
        polyline.setAttribute("points", polylinePoints);
        polyline.setAttribute("fill", "none");
        polyline.setAttribute("stroke", color);
        polyline.setAttribute("stroke-width", "2");
        polyline.setAttribute("stroke-linecap", "round");
        polyline.setAttribute("stroke-linejoin", "round");
        if (winId === "seven_day") {
          polyline.setAttribute("stroke-dasharray", "4 2");
        }

        svg.append(polygon, polyline);
        chartWrap.append(svg);
      } else {
        chartWrap.append(element("div", { className: "empty-state", text: "No observations recorded in this window." }));
      }

      card.append(chartWrap);
    });

    grid.append(card);
  });
}

function renderHistoryTable() {
  const tbody = select("#history-table-body");
  const countSpan = select("#history-log-count");
  if (!tbody) return;
  tbody.replaceChildren();

  const points = state.trendPoints || [];
  if (countSpan) countSpan.textContent = String(points.length);

  if (points.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="loading-cell">No history points recorded yet.</td></tr>';
    return;
  }

  const recent = [...points].reverse().slice(0, 100);
  recent.forEach((p) => {
    const tr = element("tr");
    const dateStr = new Date(p.observed_at).toLocaleString();
    append(
      tr,
      element("td", { text: dateStr }),
      element("td", { text: p.account_id }),
      element("td", { text: providerLabel(p.provider) }),
      element("td", { text: p.window_id }),
      element("td", { text: `${p.used_percent.toFixed(1)}%` })
    );
    tbody.append(tr);
  });
}

function exportHistoryCsv() {
  const points = state.trendPoints || [];
  if (points.length === 0) {
    alert("No history data available to export.");
    return;
  }

  const rows = [
    ["Observed At (UTC)", "Account ID", "Provider", "Window ID", "Used Percent"],
    ...points.map((p) => [
      new Date(p.observed_at).toISOString(),
      p.account_id,
      p.provider,
      p.window_id,
      p.used_percent,
    ]),
  ];

  const csvContent = "data:text/csv;charset=utf-8," + rows.map((e) => e.join(",")).join("\n");
  const encodedUri = encodeURI(csvContent);
  const link = document.createElement("a");
  link.setAttribute("href", encodedUri);
  link.setAttribute("download", `time-to-sleep-history-${state.globalTrendHours}h.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

function renderHeatmap() {
  const container = select("#heatmap-section");
  if (!container) return;
  if (!state.heatmap || state.heatmap.length === 0) {
    container.hidden = true;
    return;
  }
  const hasUsage = state.heatmap.some((h) => h.samples_count > 0 && h.average_percent > 0);
  if (!hasUsage) {
    container.hidden = true;
    return;
  }
  container.hidden = false;
  container.replaceChildren();

  const header = element("div", { className: "heatmap-header" });
  const title = element("h3", { className: "heatmap-title", text: "Hourly Usage Distribution" });
  const caption = element("span", { className: "heatmap-caption", text: "Average quota consumed by hour (UTC)" });
  append(header, title, caption);

  const grid = element("div", { className: "heatmap-grid" });
  state.heatmap.forEach((item) => {
    const col = element("div", { className: "heatmap-col" });
    const bar = element("div", {
      className: "heatmap-bar",
      attributes: {
        title: `${String(item.hour).padStart(2, "0")}:00 UTC · Avg: ${item.average_percent}% (${item.samples_count} observations)`,
      },
    });
    const heightPct = Math.min(100, Math.max(4, item.average_percent));
    bar.style.height = `${heightPct}%`;
    if (item.average_percent >= 80) bar.style.background = "var(--danger)";
    else if (item.average_percent >= 50) bar.style.background = "var(--warning)";

    const hourLabel = element("span", {
      className: "heatmap-hour",
      text: item.hour % 3 === 0 ? String(item.hour).padStart(2, "0") : "",
    });
    append(col, bar, hourLabel);
    grid.append(col);
  });

  append(container, header, grid);
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
      state.refreshForce = true;
      if (!state.refreshQueuedPromise) {
        state.refreshQueuedPromise = (async () => {
          await state.refreshPromise;
          state.refreshQueuedPromise = null;
          return refresh(true);
        })();
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
    let historyResult;
    let heatmapResult;
    try {
      render();
      [usageResult, accountsResult, historyResult, heatmapResult] = await Promise.allSettled([
        loadUsage(forceRefresh),
        loadAccounts(),
        getJson("/v1/history?hours=24"),
        getJson("/v1/analytics/heatmap?days=7"),
      ]);
      if (usageResult.status === "fulfilled") {
        state.snapshots = usageResult.value.accounts || [];
        state.lastGeneratedAt = usageResult.value.generated_at;
        updateTimestamp(state.lastGeneratedAt);
      } else {
        state.loadError = usageResult.reason?.message || "Usage could not be loaded.";
      }
      if (accountsResult.status === "fulfilled") {
        state.accounts = accountsResult.value || [];
      } else {
        state.accountLoadError = accountsResult.reason?.message || "Account metadata could not be loaded.";
      }
      if (historyResult.status === "fulfilled") {
        state.history = historyResult.value || [];
      }
      if (heatmapResult.status === "fulfilled") {
        state.heatmap = heatmapResult.value || [];
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

function setupDiscoverModal() {
  const modal = select("#discover-modal");
  const discoverBtn = select("#discover-btn");
  const closeBtn = select("#discover-close-btn");
  const cancelBtn = select("#discover-cancel-btn");
  const importAllBtn = select("#discover-import-all-btn");
  const list = select("#discover-list");

  discoverBtn?.addEventListener("click", async () => {
    if (!list) return;
    list.replaceChildren(element("div", { className: "loading-state", text: "Scanning system for AI assistant configs…" }));
    modal?.showModal();
    try {
      const candidates = await getJson("/v1/accounts/discover");
      list.replaceChildren();
      if (!candidates || candidates.length === 0) {
        list.append(element("div", { className: "empty-state", text: "No new assistant configurations found on your disk." }));
        if (importAllBtn) importAllBtn.disabled = true;
        return;
      }
      if (importAllBtn) importAllBtn.disabled = false;
      candidates.forEach((cand) => {
        const item = element("div", { className: "discover-item" });
        const info = element("div", { className: "discover-info" });
        append(
          info,
          element("span", { className: "discover-name", text: `${providerLabel(cand.provider)} (${cand.id})` }),
          element("span", { className: "discover-meta", text: `${cand.email} · ${cand.home}` })
        );
        const addBtn = element("button", {
          className: "button button-action button-sm",
          text: "Import",
          attributes: { type: "button" },
        });
        addBtn.addEventListener("click", async () => {
          addBtn.disabled = true;
          addBtn.textContent = "…";
          try {
            await getJson("/v1/accounts/discover/apply", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ account_ids: [cand.id] }),
            });
            modal?.close();
            await refresh(true);
          } catch (err) {
            alert("Error importing account: " + err.message);
          }
        });
        append(item, info, addBtn);
        list.append(item);
      });
    } catch (err) {
      list.replaceChildren(element("div", { className: "empty-state", text: "Failed to scan: " + err.message }));
    }
  });

  importAllBtn?.addEventListener("click", async () => {
    importAllBtn.disabled = true;
    importAllBtn.textContent = "Importing…";
    try {
      await getJson("/v1/accounts/discover/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      modal?.close();
      await refresh(true);
    } catch (err) {
      alert("Error: " + err.message);
    } finally {
      importAllBtn.disabled = false;
      importAllBtn.textContent = "Import All";
    }
  });

  closeBtn?.addEventListener("click", () => modal?.close());
  cancelBtn?.addEventListener("click", () => modal?.close());
}

function setupAccountModal() {
  const modal = select("#account-modal");
  const form = select("#account-form");
  const manageBtn = select("#manage-accounts-btn");
  const cancelBtn = select("#modal-cancel-btn");
  const closeBtn = select("#modal-close-btn");

  manageBtn?.addEventListener("click", () => {
    select("#acc-id").value = "";
    select("#acc-provider").value = "codex";
    select("#acc-email").value = "";
    select("#acc-home").value = "";
    select("#acc-warning").value = "80";
    select("#acc-critical").value = "95";
    if (select("#acc-auto-retrieval")) {
      select("#acc-auto-retrieval").checked = true;
    }
    modal?.showModal();
  });

  cancelBtn?.addEventListener("click", () => {
    modal?.close();
  });

  closeBtn?.addEventListener("click", () => {
    modal?.close();
  });

  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      id: select("#acc-id").value.trim(),
      provider: select("#acc-provider").value,
      email: select("#acc-email").value.trim(),
      home: select("#acc-home").value.trim(),
      warning_threshold: parseFloat(select("#acc-warning").value) || 80.0,
      critical_threshold: parseFloat(select("#acc-critical").value) || 95.0,
      auto_retrieval: select("#acc-auto-retrieval") ? select("#acc-auto-retrieval").checked : true,
    };
    try {
      const res = await fetch("/v1/accounts/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to save account");
      }
      modal?.close();
      await refresh(true);
    } catch (err) {
      alert("Error: " + err.message);
    }
  });
}

function setupPreferencesModal() {
  const modal = select("#preferences-modal");
  const form = select("#preferences-form");
  const prefsBtn = select("#preferences-btn");
  const cancelBtn = select("#prefs-cancel-btn");
  const closeBtn = select("#prefs-close-btn");

  prefsBtn?.addEventListener("click", async () => {
    try {
      const res = await fetch("/v1/settings");
      if (res.ok) {
        const settings = await res.json();
        const auto = settings.auto_retrieval || {};
        if (select("#prefs-auto-enabled")) select("#prefs-auto-enabled").checked = auto.enabled !== false;
        if (select("#prefs-poll-interval")) select("#prefs-poll-interval").value = String(auto.poll_interval_secs || 60);
        if (select("#prefs-codex-ttl")) select("#prefs-codex-ttl").value = String(auto.codex_ttl_secs || 180);
        if (select("#prefs-claude-ttl")) select("#prefs-claude-ttl").value = String(auto.claude_ttl_secs || 300);
        if (select("#prefs-antigravity-ttl")) select("#prefs-antigravity-ttl").value = String(auto.antigravity_ttl_secs || 90);
      }
    } catch (err) {
      console.warn("Failed to load settings:", err);
    }
    modal?.showModal();
  });

  cancelBtn?.addEventListener("click", () => modal?.close());
  closeBtn?.addEventListener("click", () => modal?.close());

  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const settingsRes = await fetch("/v1/settings");
      const currentSettings = settingsRes.ok ? await settingsRes.json() : { accounts: [] };

      const newSettings = {
        accounts: currentSettings.accounts || [],
        auto_retrieval: {
          enabled: select("#prefs-auto-enabled")?.checked ?? true,
          poll_interval_secs: parseInt(select("#prefs-poll-interval")?.value, 10) || 60,
          codex_ttl_secs: parseInt(select("#prefs-codex-ttl")?.value, 10) || 180,
          claude_ttl_secs: parseInt(select("#prefs-claude-ttl")?.value, 10) || 300,
          antigravity_ttl_secs: parseInt(select("#prefs-antigravity-ttl")?.value, 10) || 90,
        },
      };

      const res = await fetch("/v1/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newSettings),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to save preferences");
      }

      modal?.close();
      await refresh(true);
    } catch (err) {
      alert("Error: " + err.message);
    }
  });
}

// The server always broadcasts a "usage" and "analytics" event back-to-back for
// each update cycle, so a naive render() per event rebuilds the entire account
// list (every card, every SVG gauge) twice for one logical change. Coalesce
// same-frame updates into a single render.
let renderScheduled = false;
function scheduleRender() {
  if (renderScheduled) return;
  renderScheduled = true;
  requestAnimationFrame(() => {
    renderScheduled = false;
    render();
  });
}

function setupEventSource() {
  if (!window.EventSource) return;
  const es = new EventSource("/v1/events");
  es.addEventListener("usage", (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.accounts) {
        state.snapshots = data.accounts;
        state.lastGeneratedAt = data.generated_at;
        updateTimestamp(data.generated_at);
        scheduleRender();
      }
    } catch (err) {
      console.warn("Failed to parse SSE usage data:", err);
    }
  });
  es.addEventListener("analytics", (e) => {
    try {
      state.analytics = JSON.parse(e.data);
      scheduleRender();
    } catch (err) {
      console.warn("Failed to parse SSE analytics data:", err);
    }
  });
}

function setupNavigation() {
  select("#tab-ledger-btn")?.addEventListener("click", () => switchView("ledger"));
  select("#tab-trends-btn")?.addEventListener("click", () => switchView("trends"));
  select("#view-all-trends-btn")?.addEventListener("click", () => switchView("trends"));
  select("#export-csv-btn")?.addEventListener("click", exportHistoryCsv);

  const rangePills = document.querySelectorAll(".global-range-picker .range-pill");
  rangePills.forEach((pill) => {
    pill.addEventListener("click", () => {
      rangePills.forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      const hours = parseInt(pill.dataset.hours, 10) || 24;
      void loadTrendsHistory(hours);
    });
  });

  const hash = window.location.hash.replace("#", "");
  if (hash === "trends") {
    switchView("trends");
  }

  window.addEventListener("hashchange", () => {
    const curHash = window.location.hash.replace("#", "");
    if (curHash === "trends" && state.activeView !== "trends") {
      switchView("trends");
    } else if ((curHash === "ledger" || !curHash) && state.activeView !== "ledger") {
      switchView("ledger");
    }
  });
}

document.addEventListener("click", () => {
  document.querySelectorAll(".card-menu.open").forEach((el) => el.classList.remove("open"));
});

document.addEventListener("DOMContentLoaded", () => {
  initializeTheme();
  setupNavigation();
  setupAccountModal();
  setupDiscoverModal();
  setupPreferencesModal();
  select("#refresh-button")?.addEventListener("click", () => refresh(true));
  refresh();
  setupEventSource();
  
  // Update relative timestamps every minute when visible
  setInterval(() => {
    if (document.hidden) return;
    if (!state.loading && state.snapshots.length > 0) {
      if (state.lastGeneratedAt) {
        updateTimestamp(state.lastGeneratedAt);
      }
    }
  }, 60000);

  // Refresh relative timestamps immediately when returning to tab
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && !state.loading && state.lastGeneratedAt) {
      updateTimestamp(state.lastGeneratedAt);
    }
  });
});
