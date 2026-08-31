// Decision-first presentation layer for the quota command center.
// Loaded after app.js and runtime-fixes.js, before DOMContentLoaded.

(() => {
  const legacyRenderAccount = renderAccount;
  const legacyRenderAccounts = renderAccounts;

  function analyticsFor(accountId) {
    return state.analytics?.accounts?.find((item) => item.account_id === accountId) || null;
  }

  function pressureFor(snapshot) {
    const peak = accountPeakUsage(snapshot);
    return peak === null ? Number.POSITIVE_INFINITY : peak;
  }

  function statusRank(status) {
    return {
      live: 0,
      cached: 1,
      stale: 2,
      rate_limited: 3,
      unavailable: 4,
    }[status] ?? 5;
  }

  function isLiveRecommended(snapshot) {
    return snapshot.status === "live"
      && Boolean(analyticsFor(snapshot.account_id)?.recommended)
      && Number.isFinite(pressureFor(snapshot));
  }

  function chooseFocusAccount() {
    if (!state.snapshots?.length) return null;

    const recommended = state.snapshots
      .filter(isLiveRecommended)
      .sort((a, b) => pressureFor(a) - pressureFor(b))[0];
    if (recommended) return recommended;

    const candidates = state.snapshots
      .filter((snapshot) => snapshot.status === "live" && Number.isFinite(pressureFor(snapshot)))
      .sort((a, b) => pressureFor(a) - pressureFor(b));
    return candidates[0] || null;
  }

  function earliestResetFor(snapshot) {
    const now = Date.now();
    const resets = (snapshot?.windows || [])
      .map((window) => ({ window, time: new Date(window.resets_at || 0).getTime() }))
      .filter((item) => Number.isFinite(item.time) && item.time > now)
      .sort((a, b) => a.time - b.time);
    return resets[0] || null;
  }

  function earliestFleetReset() {
    const candidates = [];
    state.snapshots.forEach((snapshot) => {
      const next = earliestResetFor(snapshot);
      if (next) candidates.push({ snapshot, ...next });
    });
    candidates.sort((a, b) => a.time - b.time);
    return candidates[0] || null;
  }

  function fleetPeakOwner() {
    let result = null;
    for (const snapshot of state.snapshots) {
      for (const window of snapshot.windows || []) {
        if (!result || window.used_percent > result.window.used_percent) {
          result = { snapshot, window };
        }
      }
    }
    return result;
  }

  function headroomColor(headroom) {
    if (headroom <= 10) return "var(--danger)";
    if (headroom <= 25) return "var(--warning)";
    return "var(--accent)";
  }

  function quotaBarColor(percent) {
    if (percent >= 90) return "var(--danger)";
    if (percent >= 75) return "var(--warning)";
    return "var(--provider)";
  }

  updateThemeColor = function commandThemeColor(theme) {
    const meta = select('meta[name="theme-color"]');
    if (!meta) return;
    meta.setAttribute("content", theme === "light" ? "#f3f5f0" : "#090b0a");
  };

  renderHeroGauge = function commandHeroGauge(gauge) {
    if (!gauge) return;
    gauge.replaceChildren();

    const focus = chooseFocusAccount();
    const pressure = focus ? accountPeakUsage(focus) : null;
    const headroom = pressure === null ? null : Math.max(0, 100 - pressure);
    const color = headroom === null ? "var(--line-strong)" : headroomColor(headroom);

    gauge.append(ringSvg(128, 9, headroom ?? 0, color));

    const center = element("div", { className: "hero-gauge-center" });
    const value = element("div", { className: "gauge-value" });
    if (headroom === null) {
      value.append(element("span", { text: "—" }));
    } else {
      value.append(
        document.createTextNode(String(Math.round(headroom))),
        element("span", { text: "%" }),
      );
    }

    const sub = focus && pressure !== null
      ? `${formatPercent(pressure)} used · ${statusLabel(focus.status)}`
      : state.loading
        ? "syncing providers"
        : "no live reading";

    append(
      center,
      element("div", { className: "gauge-label", text: "Headroom" }),
      value,
      element("div", { className: "gauge-sub", text: sub }),
    );
    gauge.append(center);
  };

  renderHero = function commandHero() {
    const title = select("#page-title");
    const copy = select("#hero-copy");
    if (!title || !copy) return;

    const focus = chooseFocusAccount();
    const issue = loadIssueMessage();

    if (!state.snapshots.length) {
      title.textContent = state.loading ? "Syncing your accounts." : "No usable quota reading yet.";
      copy.textContent = state.loading
        ? "Reading configured providers and comparing their active quota windows."
        : issue || "Add or discover an account to start tracking quota pressure.";
      renderHeroGauge(select("#hero-gauge"));
      return;
    }

    if (!focus) {
      title.textContent = "No live account is ready.";
      copy.textContent = issue
        || "Cached and stale readings remain visible below, but Time-to-Sleep will not recommend one until a provider reports live quota data. Refresh or reconnect an account before switching.";
      renderHeroGauge(select("#hero-gauge"));
      return;
    }

    const pressure = pressureFor(focus);
    const headroom = Math.max(0, 100 - pressure);
    const analytics = analyticsFor(focus.account_id);
    const reset = earliestResetFor(focus);

    title.replaceChildren(
      document.createTextNode("Use "),
      element("em", { text: accountLabel(focus) }),
      document.createTextNode(" next."),
    );

    const parts = [
      `${focus.configured_email || focus.account_id} has ${formatPercent(headroom)} headroom in its most constrained active window.`,
    ];

    if (analytics?.recommendation_reason) {
      parts.push(analytics.recommendation_reason.replace(/\.$/, "") + ".");
    } else if (reset) {
      parts.push(`${formatWindow(reset.window.id)} resets ${formatResetCountdown(reset.window.resets_at)}.`);
    } else {
      parts.push("It currently has the lowest usable pressure among live accounts.");
    }

    if (issue) parts.push(`Last refresh note: ${issue}`);
    copy.textContent = parts.join(" ");

    renderHeroGauge(select("#hero-gauge"));
  };

  renderSummary = function commandSummary() {
    const summary = select("#summary");
    if (!summary) return;
    summary.replaceChildren();

    const focus = chooseFocusAccount();
    const focusPressure = focus ? accountPeakUsage(focus) : null;
    const counts = snapshotCounts();
    const peak = fleetPeakOwner();
    const nextReset = earliestFleetReset();
    const attention = counts.attention + counts.unavailable;

    const cards = [
      {
        label: "Best option",
        value: focus ? accountLabel(focus) : "—",
        detail: focusPressure === null ? "no live readable account" : `${formatPercent(Math.max(0, 100 - focusPressure))} headroom`,
      },
      {
        label: "Fleet peak",
        value: peak ? formatPercent(peak.window.used_percent) : "—",
        detail: peak ? `${accountLabel(peak.snapshot)} · ${formatWindow(peak.window.id)}` : "no active windows",
      },
      {
        label: "Next reset",
        value: nextReset ? formatResetCountdown(nextReset.window.resets_at).replace(/^in\s+/, "") : "—",
        detail: nextReset ? `${accountLabel(nextReset.snapshot)} · ${formatWindow(nextReset.window.id)}` : "no reset timestamp",
      },
      {
        label: "Needs attention",
        value: String(attention),
        detail: attention ? `${attention} account${attention === 1 ? "" : "s"} not fully live` : `${counts.live} live · all clear`,
        alert: attention > 0,
      },
    ];

    for (const item of cards) {
      const card = element("div", {
        className: `summary-card${item.alert ? " summary-card-alert" : ""}`,
      });
      append(
        card,
        element("div", { className: "summary-label", text: item.label }),
        element("div", { className: "summary-value", text: item.value }),
        element("div", { className: "summary-detail", text: item.detail }),
      );
      summary.append(card);
    }
    summary.classList.remove("summary-grid-four");
  };

  renderAccount = function commandAccount(snapshot) {
    const card = legacyRenderAccount(snapshot);
    card.dataset.accountId = snapshot.account_id;

    const recBadge = card.querySelector(".rec-badge");
    if (recBadge && !isLiveRecommended(snapshot)) {
      recBadge.remove();
    }

    card.querySelectorAll(".meter-fill").forEach((fill, index) => {
      const window = snapshot.windows?.[index];
      if (!window) return;
      fill.style.background = quotaBarColor(window.used_percent);
    });

    const focus = chooseFocusAccount();
    if (focus?.account_id === snapshot.account_id) {
      card.classList.add("account-card-focus");
      const eyebrow = card.querySelector(".account-eyebrow");
      if (eyebrow && !eyebrow.querySelector(".rec-badge")) {
        eyebrow.append(element("span", { className: "focus-badge", text: "Best option" }));
      }
    }

    return card;
  };

  renderAccounts = function commandAccounts() {
    const original = state.snapshots;
    state.snapshots = [...original].sort((a, b) => {
      const aRecommended = isLiveRecommended(a) ? 0 : 1;
      const bRecommended = isLiveRecommended(b) ? 0 : 1;
      if (aRecommended !== bRecommended) return aRecommended - bRecommended;

      const statusDiff = statusRank(a.status) - statusRank(b.status);
      if (statusDiff) return statusDiff;

      const pressureDiff = pressureFor(a) - pressureFor(b);
      if (Number.isFinite(pressureDiff) && pressureDiff !== 0) return pressureDiff;

      return String(a.account_id).localeCompare(String(b.account_id));
    });

    try {
      return legacyRenderAccounts();
    } finally {
      state.snapshots = original;
    }
  };

  function closeUtilityMenu() {
    const menu = select(".utility-menu");
    if (menu?.open) menu.removeAttribute("open");
  }

  document.addEventListener("DOMContentLoaded", () => {
    select(".utility-menu")?.querySelectorAll("button").forEach((button) => {
      button.addEventListener("click", closeUtilityMenu);
    });

    document.addEventListener("click", (event) => {
      const menu = select(".utility-menu");
      if (menu?.open && !menu.contains(event.target)) closeUtilityMenu();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeUtilityMenu();
        return;
      }

      const target = event.target;
      const typing = target instanceof HTMLInputElement
        || target instanceof HTMLTextAreaElement
        || target instanceof HTMLSelectElement
        || target?.isContentEditable;

      if (!typing && !event.metaKey && !event.ctrlKey && !event.altKey && event.key.toLowerCase() === "r") {
        event.preventDefault();
        void refresh(true);
      }
    });
  });
})();
