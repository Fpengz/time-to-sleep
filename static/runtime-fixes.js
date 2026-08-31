// Loaded after app.js (both scripts are deferred) and before DOMContentLoaded.
// Keep the large dashboard bundle stable while tightening two data-semantics edges.

refresh = async function orderedRefresh(forceRefresh = false) {
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
    if (announcement) {
      announcement.textContent = forceRefresh
        ? "Refreshing usage data…"
        : "Loading usage data…";
    }
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

      // Account metadata can load alongside usage, but history and the heatmap must wait.
      // /v1/usage is the request that records the newest provider snapshot in SQLite.
      const accountsPromise = loadAccounts();
      [usageResult] = await Promise.allSettled([loadUsage(forceRefresh)]);
      [accountsResult, historyResult, heatmapResult] = await Promise.allSettled([
        accountsPromise,
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
        state.accountLoadError =
          accountsResult.reason?.message || "Account metadata could not be loaded.";
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
        if (announcement && usageResult && accountsResult) {
          announcement.textContent = refreshAnnouncement(usageResult, accountsResult);
        }
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
};

renderHeatmap = function renderRecordedQuotaHeatmap() {
  const container = select("#heatmap-section");
  if (!container) return;
  if (!state.heatmap || state.heatmap.length === 0) {
    container.hidden = true;
    return;
  }

  const hasUsage = state.heatmap.some(
    (hour) => hour.samples_count > 0 && hour.average_percent > 0,
  );
  if (!hasUsage) {
    container.hidden = true;
    return;
  }

  container.hidden = false;
  container.replaceChildren();

  const header = element("div", { className: "heatmap-header" });
  const title = element("h3", {
    className: "heatmap-title",
    text: "Hourly Recorded Quota Levels",
  });
  const caption = element("span", {
    className: "heatmap-caption",
    text: "Average recorded quota level by hour (UTC)",
  });
  append(header, title, caption);

  const grid = element("div", { className: "heatmap-grid" });
  state.heatmap.forEach((item) => {
    const col = element("div", { className: "heatmap-col" });
    const bar = element("div", {
      className: "heatmap-bar",
      attributes: {
        title: `${String(item.hour).padStart(2, "0")}:00 UTC · Avg recorded level: ${item.average_percent}% (${item.samples_count} observations)`,
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
};
