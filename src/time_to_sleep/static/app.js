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
    third_party_weekly: "Claude + GPT Weekly",
    third_party_five_hour: "Claude + GPT Five Hour",
  };
  if (labels[id]) return labels[id];
  return id.split("_").map((part) => part[0].toUpperCase() + part.slice(1)).join(" ");
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
  if (provider === "codex" && accountId && accountId.includes("secondary")) return "var(--p-codex-2)";
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

  gauge.append(ringSvg(210, 12, pct, arcColor));

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
  const heading = element("div", { className: "window-heading" });
  
  const titleGroup = element("div", { className: "window-title-group" });
  titleGroup.append(element("span", { className: "window-name", text: formatWindow(window.id) }));
  if (window.window_minutes) {
    titleGroup.append(element("span", { className: "window-badge", text: window.window_minutes >= 1000 ? "7-day" : "5-hour" }));
  }

  const statGroup = element("div", { className: "window-stat-group" });
  const usedVal = element("strong", { className: "window-used-val", text: formatPercent(window.used_percent) });
  const remainingPercent = Math.max(0, 100 - window.used_percent);
  const remainingSub = element("span", { className: "window-remaining-sub", text: `${formatPercent(remainingPercent)} remaining` });
  append(statGroup, usedVal, remainingSub);

  append(heading, titleGroup, statGroup);

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

  const detail = element("div", { className: "window-detail" });
  const resetText = element("span", { className: "window-reset-date", text: formatReset(window.resets_at) });
  detail.append(resetText);
  
  const countdown = formatResetCountdown(window.resets_at);
  if (countdown) {
    detail.append(element("span", { className: "window-countdown-pill", text: countdown }));
  }

  if (window.window_minutes) {
    detail.append(element("span", { className: "window-cycle-note", text: ` · ${window.window_minutes >= 1000 ? "7-day" : "5-hour"} window` }));
  }

  append(wrapper, heading, track, detail);
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
    gauge.append(ringSvg(62, 6, peak, usageColorVar(peak)));
    const num = element("div", { className: "account-gauge-num" });
    num.append(document.createTextNode(String(Math.round(peak))), element("small", { text: "%" }));
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
  if (snapshot.status !== "live") {
    const isCodex = snapshot.provider === "codex";
    const action = element("button", {
      className: "button button-action button-sm",
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
    cardActions.append(action);
  }

  const deleteContainer = element("div", { className: "delete-container" });
  const deleteBtn = element("button", {
    className: "button button-secondary button-sm delete-btn",
    text: "Delete",
    attributes: { type: "button", title: "Remove account configuration" },
  });

  deleteBtn.addEventListener("click", () => {
    deleteContainer.replaceChildren();
    const confirmGroup = element("div", { className: "delete-confirm-group" });
    const prompt = element("span", { className: "delete-prompt", text: "Delete?" });
    const confirmBtn = element("button", {
      className: "button-danger-confirm",
      text: "Confirm",
      attributes: { type: "button" },
    });
    const cancelBtn = element("button", {
      className: "button-cancel-confirm",
      text: "Cancel",
      attributes: { type: "button" },
    });

    confirmBtn.addEventListener("click", async () => {
      try {
        confirmBtn.disabled = true;
        confirmBtn.textContent = "…";
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

    cancelBtn.addEventListener("click", () => {
      deleteContainer.replaceChildren(deleteBtn);
    });

    append(confirmGroup, prompt, confirmBtn, cancelBtn);
    deleteContainer.append(confirmGroup);
  });

  deleteContainer.append(deleteBtn);
  cardActions.append(deleteContainer);
  append(headerRight, status, cardActions);

  append(header, identity, headerRight);
  card.append(header);

  // Key Analytics stats strip
  if (accAnalytics && (accAnalytics.burn_rate_per_hour || accAnalytics.minutes_to_exhaustion || accAnalytics.recommendation_reason)) {
    const statsStrip = element("div", { className: "account-stats-strip" });
    if (accAnalytics.burn_rate_per_hour) {
      const stat = element("div", { className: "stat-item" });
      append(stat, element("span", { className: "stat-label", text: "Burn Rate" }), element("span", { className: "stat-value", text: `${accAnalytics.burn_rate_per_hour}% / hr` }));
      statsStrip.append(stat);
    }
    if (accAnalytics.minutes_to_exhaustion) {
      const stat = element("div", { className: "stat-item" });
      const hours = Math.round(accAnalytics.minutes_to_exhaustion / 60);
      append(stat, element("span", { className: "stat-label", text: "Est. Runway" }), element("span", { className: "stat-value", text: `~${hours}h remaining` }));
      statsStrip.append(stat);
    }
    if (accAnalytics.recommendation_reason) {
      const stat = element("div", { className: "stat-item stat-item-reason" });
      append(stat, element("span", { className: "stat-label", text: "Routing Note" }), element("span", { className: "stat-value", text: accAnalytics.recommendation_reason }));
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

  if (snapshot.message || snapshot.error_code) {
    const alertBox = element("div", { className: "account-alert-banner" });
    if (snapshot.error_code) {
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

function getAccountColor(account) {
  if (account.provider === "codex" && account.account_id?.includes("secondary")) {
    return "#818cf8";
  }
  return providerColors[account.provider] || "#a78bfa";
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

  // Render Legend
  if (legend) {
    accountIds.forEach((accId) => {
      const snap = state.snapshots.find((s) => s.account_id === accId);
      const prov = snap?.provider || (points.find((p) => p.account_id === accId)?.provider) || "codex";
      const color = getAccountColor({ provider: prov, account_id: accId });
      const item = element("div", { className: "legend-item" });
      const dot = element("span", { className: "legend-color" });
      dot.style.background = color;
      const lbl = element("span", { text: `${providerLabel(prov)} (${accId})` });
      append(item, dot, lbl);
      legend.append(item);
    });
  }

  // Draw Multi-series SVG
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

  // Plot path per account
  accountIds.forEach((accId) => {
    const accPoints = points
      .filter((p) => p.account_id === accId)
      .sort((a, b) => new Date(a.observed_at).getTime() - new Date(b.observed_at).getTime());
    if (accPoints.length === 0) return;

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

    // Filter points for this account
    const accPoints = points
      .filter((p) => p.account_id === acc.account_id)
      .sort((a, b) => new Date(a.observed_at).getTime() - new Date(b.observed_at).getTime());

    const maxVal = accPoints.length > 0 ? Math.max(...accPoints.map((p) => p.used_percent)) : 0;
    const minVal = accPoints.length > 0 ? Math.min(...accPoints.map((p) => p.used_percent)) : 0;
    const currentVal = accPoints.length > 0 ? accPoints[accPoints.length - 1].used_percent : 0;
    const deltaVal = accPoints.length >= 2 ? currentVal - accPoints[0].used_percent : 0;

    // Stats Row
    const statsRow = element("div", { className: "detail-stats-row" });
    [
      { label: "Current", val: `${currentVal.toFixed(1)}%` },
      { label: "Peak", val: `${maxVal.toFixed(1)}%` },
      { label: "Min", val: `${minVal.toFixed(1)}%` },
      { label: "Net Change", val: `${deltaVal >= 0 ? "+" : ""}${deltaVal.toFixed(1)}%` },
    ].forEach((s) => {
      const st = element("div", { className: "detail-stat" });
      append(st, element("span", { className: "detail-stat-lbl", text: s.label }), element("span", { className: "detail-stat-val", text: s.val }));
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

      const color = getAccountColor(acc);

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

      svg.append(polygon, polyline);
      chartWrap.append(svg);
    } else {
      chartWrap.append(element("div", { className: "empty-state", text: "No observations recorded in this window." }));
    }

    card.append(chartWrap);
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
        render();
      }
    } catch (err) {
      console.warn("Failed to parse SSE usage data:", err);
    }
  });
  es.addEventListener("analytics", (e) => {
    try {
      state.analytics = JSON.parse(e.data);
      render();
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

document.addEventListener("DOMContentLoaded", () => {
  initializeTheme();
  setupNavigation();
  setupAccountModal();
  setupDiscoverModal();
  select("#refresh-button")?.addEventListener("click", () => refresh(true));
  refresh();
  setupEventSource();
  
  // Update relative timestamps every minute
  setInterval(() => {
    if (!state.loading && state.snapshots.length > 0) {
      if (state.lastGeneratedAt) {
        updateTimestamp(state.lastGeneratedAt);
      }
    }
  }, 60000);
});
