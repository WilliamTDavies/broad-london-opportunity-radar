(() => {
  "use strict";

  function readSaved(storage, key) {
    try {
      const value = JSON.parse(storage.getItem(key) || "[]");
      return new Set(Array.isArray(value) && value.every(item => typeof item === "string") ? value : []);
    } catch (_) {
      return new Set();
    }
  }

  function writeSaved(storage, key, saved) {
    try {
      storage.setItem(key, JSON.stringify([...saved]));
      return true;
    } catch (_) {
      return false;
    }
  }

  function compareCards(mode, a, b) {
    if (mode === "deadline") return a.dataset.deadline.localeCompare(b.dataset.deadline);
    if (mode === "opening") return a.dataset.opening.localeCompare(b.dataset.opening);
    if (mode === "employer") return a.dataset.employer.localeCompare(b.dataset.employer);
    if (mode === "category") return a.dataset.category.localeCompare(b.dataset.category);
    if (mode === "score") return Number(b.dataset.score) - Number(a.dataset.score);
    if (mode === "evidence") return Number(b.dataset.evidence) - Number(a.dataset.evidence);
    return b.dataset.firstSeen.localeCompare(a.dataset.firstSeen);
  }

  function categoryMatches(category, quickCategories) {
    const value = category.toLowerCase();
    return !quickCategories.length || quickCategories.some(term => value.includes(term));
  }

  function visiblePage(items, limit) {
    return items.slice(0, Math.max(0, limit));
  }

  function normaliseSearch(value) {
    return String(value || "")
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/\bc\s*\+\s*\+/gi, " cplusplus ")
      .replace(/&/g, " and ")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  }

  function matchesSearch(value, query) {
    const words = normaliseSearch(query).split(" ").filter(Boolean);
    const candidate = normaliseSearch(value);
    return !words.length || words.every(word => candidate.includes(word));
  }

  function fieldSearchScore(value, query) {
    const candidate = normaliseSearch(value);
    const phrase = normaliseSearch(query);
    if (!phrase) return 0;
    if (candidate === phrase) return 100;
    if (candidate.startsWith(phrase)) return 75;
    if (candidate.includes(phrase)) return 50;
    return matchesSearch(candidate, phrase) ? 20 : 0;
  }

  function searchScore(item, keywordQuery, companyQuery) {
    const titleScore = fieldSearchScore(item.dataset.title, keywordQuery);
    const broadScore = fieldSearchScore(item.dataset.search, keywordQuery);
    const companyScore = fieldSearchScore(item.dataset.employer, companyQuery);
    return (titleScore * 2) + broadScore + (companyScore * 3);
  }

  const testingApi = {
    readSaved,
    writeSaved,
    compareCards,
    categoryMatches,
    visiblePage,
    normaliseSearch,
    matchesSearch,
    searchScore,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = testingApi;
  if (typeof globalThis !== "undefined") globalThis.OpportunityRadar = testingApi;
  if (typeof document === "undefined") return;

  const fallbackRows = [...document.querySelectorAll(".role-row")];
  const tableBody = document.querySelector("#role-table-body");
  const filters = document.querySelector("#filters");
  const count = document.querySelector("#result-count");
  const empty = document.querySelector("#empty-state");
  const search = document.querySelector("#search");
  const companySearch = document.querySelector("#company-search");
  const sort = document.querySelector("#sort");
  const savedFilter = document.querySelector("#saved-filter");
  const showMore = document.querySelector("#show-more");
  const detailPanel = document.querySelector("#role-detail-panel");
  const detailContent = document.querySelector("#role-detail-content");
  const detailTitle = document.querySelector("#role-detail-title");
  const detailClose = document.querySelector("#detail-close");
  const storageKey = "london-radar-saved-role-ids";
  const saved = readSaved(localStorage, storageKey);
  const pageSize = 100;
  let visibleLimit = pageSize;
  let quickCategories = [];
  let roleItems = fallbackRows.map(row => ({
    id: row.dataset.roleId,
    dataset: { ...row.dataset },
    html: row.outerHTML,
  }));
  let detailPayloadPromise = null;
  let detailTrigger = null;

  function updateSaveButtons() {
    document.querySelectorAll("[data-save]").forEach(button => {
      const active = saved.has(button.dataset.save);
      button.setAttribute("aria-pressed", String(active));
      button.textContent = active ? "Saved" : "Save";
    });
  }

  function apply(resetPage = true) {
    if (resetPage) visibleLimit = pageSize;
    const query = search.value;
    const companyQuery = companySearch.value;
    const active = [...filters.querySelectorAll("select[data-filter]")].filter(el => el.value);
    const shown = roleItems.filter(item => {
      if (!matchesSearch(item.dataset.search, query)) return false;
      if (!matchesSearch(item.dataset.employer, companyQuery)) return false;
      if (savedFilter.value === "saved" && !saved.has(item.id)) return false;
      if (!categoryMatches(item.dataset.category, quickCategories)) return false;
      return active.every(el => normaliseSearch(item.dataset[el.dataset.filter]).includes(normaliseSearch(el.value)));
    });
    shown.sort((a, b) => {
      const scoreDifference = searchScore(b, query, companyQuery) - searchScore(a, query, companyQuery);
      return scoreDifference || compareCards(sort.value, a, b);
    });
    const visible = visiblePage(shown, visibleLimit);
    tableBody.innerHTML = visible.map(item => item.html).join("");
    updateSaveButtons();
    count.textContent = shown.length > visible.length
      ? `Showing ${visible.length} of ${shown.length} roles`
      : `${shown.length} role${shown.length === 1 ? "" : "s"}`;
    const hasMore = visible.length < shown.length;
    showMore.hidden = !hasMore;
    showMore.parentElement.hidden = !hasMore;
    empty.hidden = shown.length !== 0;
  }

  async function loadRoleIndex() {
    try {
      const response = await fetch("role-index.json", { credentials: "same-origin" });
      if (!response.ok) throw new Error(`Role index returned ${response.status}`);
      const payload = await response.json();
      if (!Array.isArray(payload) || payload.some(item => (
        typeof item.id !== "string"
        || typeof item.html !== "string"
        || !item.dataset
      ))) throw new Error("Role index is invalid");
      roleItems = payload;
      apply(true);
    } catch (_) {
      count.textContent += " · full index unavailable";
    }
  }

  async function getDetailPayload() {
    if (!detailPayloadPromise) {
      detailPayloadPromise = fetch("role-details.json", { credentials: "same-origin" }).then(response => {
        if (!response.ok) throw new Error(`Role details returned ${response.status}`);
        return response.json();
      });
    }
    try {
      return await detailPayloadPromise;
    } catch (error) {
      detailPayloadPromise = null;
      throw error;
    }
  }

  async function openDetail(roleId, trigger) {
    detailTrigger = trigger;
    detailTitle.textContent = trigger.querySelector("span")?.textContent || "Listing details";
    detailContent.textContent = "Loading role details…";
    detailPanel.hidden = false;
    detailClose.focus();
    try {
      const payload = await getDetailPayload();
      if (typeof payload[roleId] !== "string") throw new Error("Role details are missing");
      detailContent.innerHTML = payload[roleId];
      updateSaveButtons();
      detailContent.querySelector(".role-card")?.focus();
    } catch (_) {
      detailContent.innerHTML = "<p class=\"detail-error\">Details could not be loaded. You can still open the listing from the Check role or Apply link in the table.</p>";
    }
  }

  function closeDetail() {
    detailPanel.hidden = true;
    detailContent.textContent = "";
    detailTrigger?.focus();
  }

  filters?.addEventListener("input", () => {
    quickCategories = [];
    apply(true);
  });
  filters?.addEventListener("reset", () => {
    quickCategories = [];
    setTimeout(() => apply(true));
  });
  document.addEventListener("click", event => {
    const saveButton = event.target.closest("[data-save]");
    if (saveButton) {
      saved.has(saveButton.dataset.save) ? saved.delete(saveButton.dataset.save) : saved.add(saveButton.dataset.save);
      writeSaved(localStorage, storageKey, saved);
      updateSaveButtons();
      apply(false);
      return;
    }
    const detailButton = event.target.closest("[data-open-card]");
    if (detailButton) {
      openDetail(detailButton.dataset.openCard, detailButton);
      return;
    }
    if (event.target.closest("#detail-close")) closeDetail();
  });
  showMore?.addEventListener("click", () => {
    visibleLimit += pageSize;
    apply(false);
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !detailPanel.hidden) closeDetail();
  });
  document.querySelectorAll("[data-quick-filter]").forEach(button => button.addEventListener("click", () => {
    const select = filters.querySelector(`[data-filter="${button.dataset.quickFilter}"]`);
    select.value = "true";
    apply();
    document.querySelector("#opportunities").scrollIntoView();
  }));
  document.querySelector("[data-cycle-filter]")?.addEventListener("click", () => {
    filters.querySelector('[data-filter="cycle"]').value = "cycle_unstated";
    apply();
    document.querySelector("#opportunities").scrollIntoView();
  });
  document.querySelectorAll("[data-programme-filter]").forEach(button => button.addEventListener("click", () => {
    const select = filters.querySelector('[data-filter="programme"]');
    const requested = button.dataset.programmeFilter;
    if (requested === "vacation_scheme") {
      search.value = "vacation scheme";
      companySearch.value = "";
      select.value = "";
    } else {
      select.value = requested;
      search.value = "";
      companySearch.value = "";
    }
    apply();
    document.querySelector("#opportunities").scrollIntoView();
  }));
  document.querySelectorAll("[data-category-filter]").forEach(button => button.addEventListener("click", () => {
    quickCategories = button.dataset.categoryFilter.split("|");
    search.value = "";
    companySearch.value = "";
    apply();
    document.querySelector("#opportunities").scrollIntoView();
  }));
  const subscribe = document.querySelector("#subscribe-form");
  subscribe?.addEventListener("submit", async event => {
    event.preventDefault();
    const status = document.querySelector("#subscribe-status");
    if (!subscribe.dataset.endpoint) {
      status.textContent = "Email alerts are unavailable on this deployment.";
      return;
    }
    const body = Object.fromEntries(new FormData(subscribe));
    status.textContent = "Submitting…";
    try {
      const response = await fetch(subscribe.dataset.endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!response.ok) throw new Error("Request failed");
      status.textContent = "If this address can be subscribed, a confirmation email will arrive shortly.";
      subscribe.reset();
    } catch (_) {
      status.textContent = "Subscription is temporarily unavailable. Please try again later.";
    }
  });
  updateSaveButtons();
  apply(true);
  loadRoleIndex();
})();
