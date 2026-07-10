    const settingsContext = __SETTINGS_CONTEXT__;
    const apiBase = settingsContext.baseUrl || window.location.origin;
    const token = settingsContext.token || "";
    let presetsById = {};
    let journalCatalog = [];
    let selectedJournals = [];
    let extraJournalCandidates = [];
    let journalDualList = null;
    const DUAL_LIST_MIME = "application/x-paper-monitor-dual-list";

    function field(id) {
      return document.getElementById(id);
    }

    function setStatus(message, type) {
      const element = field("status");
      element.textContent = message;
      element.className = "status" + (type ? " " + type : "");
    }

    function setValue(id, value) {
      field(id).value = value == null ? "" : String(value);
    }

    function setChecked(id, value) {
      field(id).checked = Boolean(value);
    }

    function setLines(id, values) {
      field(id).value = Array.isArray(values) ? values.join("\n") : String(values || "");
    }

    function lines(id) {
      return field(id).value.split(/\r?\n/).map(function (line) {
        return line.trim();
      }).filter(Boolean);
    }

    function normalizeDualListValue(value) {
      return String(value || "").trim().replace(/\s+/g, " ");
    }

    function dualListKey(value) {
      return normalizeDualListValue(value).toLowerCase();
    }

    function dedupeDualListValues(values) {
      const seen = new Set();
      const result = [];
      (Array.isArray(values) ? values : []).forEach(function (value) {
        const clean = normalizeDualListValue(value);
        const key = dualListKey(clean);
        if (!clean || seen.has(key)) {
          return;
        }
        seen.add(key);
        result.push(clean);
      });
      return result;
    }

    function createDualListModel(options) {
      const config = options || {};
      const getValue = config.getValue || function (item) { return item; };
      const makeCandidate = config.makeCandidate || function (value) { return value; };
      let candidates = [];
      let selectedValues = [];

      function candidateKey(entry) {
        return dualListKey(getValue(entry));
      }

      function candidateValue(entry) {
        return normalizeDualListValue(getValue(entry));
      }

      function canonicalValue(value) {
        const clean = normalizeDualListValue(value);
        const key = dualListKey(clean);
        if (!key) return "";
        const match = candidates.find(function (entry) {
          return candidateKey(entry) === key;
        });
        return match ? candidateValue(match) : clean;
      }

      function ensureCandidate(value, candidate) {
        const clean = normalizeDualListValue(value);
        const key = dualListKey(clean);
        if (!key || candidates.some(function (entry) { return candidateKey(entry) === key; })) {
          return;
        }
        candidates.push(candidate || makeCandidate(clean));
      }

      const model = {
        setCandidates: function (values) {
          const byKey = new Map();
          (Array.isArray(values) ? values : []).forEach(function (entry) {
            const clean = candidateValue(entry);
            const key = dualListKey(clean);
            if (key && !byKey.has(key)) {
              byKey.set(key, entry);
            }
          });
          candidates = Array.from(byKey.values());
          selectedValues.forEach(function (value) {
            ensureCandidate(value, makeCandidate(value));
          });
          selectedValues = dedupeDualListValues(selectedValues.map(canonicalValue));
          return model;
        },
        setSelected: function (values) {
          selectedValues = dedupeDualListValues((Array.isArray(values) ? values : []).map(canonicalValue));
          selectedValues.forEach(function (value) {
            ensureCandidate(value, makeCandidate(value));
          });
          return model;
        },
        add: function (value) {
          const clean = normalizeDualListValue(value);
          if (!clean) return model;
          ensureCandidate(clean, makeCandidate(clean));
          selectedValues = dedupeDualListValues(selectedValues.concat([canonicalValue(clean)]));
          return model;
        },
        remove: function (value) {
          const key = dualListKey(value);
          selectedValues = selectedValues.filter(function (item) {
            return dualListKey(item) !== key;
          });
          return model;
        },
        selected: function () {
          return selectedValues.slice();
        },
        candidates: function () {
          return candidates.slice();
        },
        selectedEntries: function () {
          return selectedValues.map(function (value) {
            const key = dualListKey(value);
            return candidates.find(function (entry) {
              return candidateKey(entry) === key;
            }) || makeCandidate(value);
          });
        },
        availableEntries: function (filter, sort) {
          const selectedKeys = new Set(selectedValues.map(dualListKey));
          const items = candidates.filter(function (entry) {
            return !selectedKeys.has(candidateKey(entry)) && (!filter || filter(entry));
          });
          return sort ? items.sort(sort) : items;
        }
      };
      return model;
    }

    function setDualListDragData(event, listId, value, source) {
      if (!event.dataTransfer) return;
      const payload = JSON.stringify({
        listId: listId,
        value: normalizeDualListValue(value),
        source: source || ""
      });
      event.dataTransfer.effectAllowed = "copyMove";
      event.dataTransfer.setData(DUAL_LIST_MIME, payload);
      event.dataTransfer.setData("text/plain", normalizeDualListValue(value));
    }

    function dualListDragData(event, listId) {
      if (!event.dataTransfer) return null;
      const raw = event.dataTransfer.getData(DUAL_LIST_MIME);
      if (raw) {
        try {
          const payload = JSON.parse(raw);
          if (payload && payload.listId === listId && normalizeDualListValue(payload.value)) {
            return payload;
          }
        } catch (error) {
          return null;
        }
      }
      const fallback = normalizeDualListValue(event.dataTransfer.getData("text/plain"));
      return fallback ? { listId: listId, value: fallback, source: "" } : null;
    }

    function bindDualListDropZone(element, listId, onDrop) {
      if (!element || element.dataset.dualListDropBound === "1") return;
      element.dataset.dualListDropBound = "1";
      element.addEventListener("dragover", function (event) {
        if (!dualListDragData(event, listId)) return;
        event.preventDefault();
        element.classList.add("drag-over");
        event.dataTransfer.dropEffect = "move";
      });
      element.addEventListener("dragleave", function () {
        element.classList.remove("drag-over");
      });
      element.addEventListener("drop", function (event) {
        const payload = dualListDragData(event, listId);
        if (!payload) return;
        event.preventDefault();
        element.classList.remove("drag-over");
        onDrop(payload.value, payload);
      });
    }

    if (typeof window !== "undefined") {
      window.PaperMonitorDualList = {
        createDualListModel: createDualListModel,
        bindDualListDropZone: bindDualListDropZone,
        dedupeValues: dedupeDualListValues,
        normalizeValue: normalizeDualListValue
      };
    }

    function normalizeJournalName(value) {
      return normalizeDualListValue(value);
    }

    function journalKey(value) {
      return dualListKey(value);
    }

    function dedupeJournals(values) {
      return dedupeDualListValues(values);
    }

    function normalizeJournalEntry(entry) {
      const journal = normalizeJournalName(entry && entry.journal);
      if (!journal) {
        return null;
      }
      const impact = entry.impact_factor == null ? null : Number(entry.impact_factor);
      const rank = Number(entry.rank);
      return {
        journal: journal,
        aliases: Array.isArray(entry.aliases) ? entry.aliases.map(normalizeJournalName).filter(Boolean) : [],
        rank: Number.isFinite(rank) ? rank : null,
        impact_factor: impact != null && Number.isFinite(impact) ? impact : null,
        impact_factor_year: entry.impact_factor_year || null,
        impact_metric: String(entry.impact_metric || "Journal Impact Factor"),
        impact_label: String(entry.impact_label || "IF"),
        category: String(entry.category || "Uncategorized"),
        level: String(entry.level || ""),
        source_url: String(entry.source_url || ""),
        default_selected: entry.default_selected !== false,
        custom: Boolean(entry.custom)
      };
    }

    function rawJournalEntries() {
      const byKey = new Map();
      journalCatalog.concat(extraJournalCandidates).forEach(function (entry) {
        const normalized = normalizeJournalEntry(entry);
        if (!normalized) {
          return;
        }
        const key = journalKey(normalized.journal);
        if (!byKey.has(key)) {
          byKey.set(key, normalized);
        }
      });
      return Array.from(byKey.values());
    }

    function ensureJournalDualList() {
      if (!journalDualList) {
        journalDualList = createDualListModel({
          getValue: function (entry) {
            return entry && entry.journal;
          },
          makeCandidate: function (journal) {
            return {
              journal: journal,
              aliases: [],
              rank: null,
              impact_factor: null,
              impact_label: "Manual",
              category: "Manual",
              custom: true
            };
          }
        });
      }
      return journalDualList;
    }

    function syncJournalCandidates() {
      const model = ensureJournalDualList();
      model.setCandidates(rawJournalEntries());
      return model;
    }

    function catalogEntries() {
      return ensureJournalDualList().candidates();
    }

    function catalogEntryFor(journal) {
      const key = journalKey(journal);
      return catalogEntries().find(function (entry) {
        return journalKey(entry.journal) === key;
      }) || null;
    }

    function impactLabel(entry) {
      if (entry && entry.impact_factor != null) {
        return String(entry.impact_label || "Impact") + " " + Number(entry.impact_factor).toFixed(1);
      }
      if (entry && entry.impact_label) {
        return String(entry.impact_label);
      }
      if (entry && entry.rank != null) {
        return "#" + entry.rank;
      }
      return "Manual";
    }

    function compareJournalEntries(left, right) {
      const sortMode = field("journal_sort_mode") ? field("journal_sort_mode").value : "impact_factor";
      if (sortMode === "name") {
        return left.journal.localeCompare(right.journal);
      }
      if (sortMode === "rank") {
        const leftRank = left.rank == null ? 9999 : left.rank;
        const rightRank = right.rank == null ? 9999 : right.rank;
        if (leftRank !== rightRank) {
          return leftRank - rightRank;
        }
        return left.journal.localeCompare(right.journal);
      }
      const leftImpact = left.impact_factor;
      const rightImpact = right.impact_factor;
      if (leftImpact != null && rightImpact != null && leftImpact !== rightImpact) {
        return rightImpact - leftImpact;
      }
      if (leftImpact != null && rightImpact == null) {
        return -1;
      }
      if (leftImpact == null && rightImpact != null) {
        return 1;
      }
      const leftRank = left.rank == null ? 9999 : left.rank;
      const rightRank = right.rank == null ? 9999 : right.rank;
      if (leftRank !== rightRank) {
        return leftRank - rightRank;
      }
      return left.journal.localeCompare(right.journal);
    }

    function journalButton(entry, selected) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "journal-item";
      button.dataset.journal = entry.journal;
      button.dataset.dualListItem = "journal-filter";
      button.dataset.dualListSource = selected ? "selected" : "candidate";
      button.draggable = true;
      button.setAttribute("aria-label", (selected ? "Remove " : "Add ") + entry.journal);
      button.title = [
        selected ? "Remove " + entry.journal : "Add " + entry.journal,
        entry.category || "",
        entry.impact_metric || "",
        entry.impact_factor_year || ""
      ].filter(Boolean).join(" · ");
      button.addEventListener("click", function () {
        if (selected) {
          removeSelectedJournal(entry.journal);
        } else {
          addSelectedJournal(entry.journal);
        }
      });
      button.addEventListener("dragstart", function (event) {
        setDualListDragData(event, "journal-filter", entry.journal, selected ? "selected" : "candidate");
      });

      const name = document.createElement("span");
      name.className = "journal-name";
      name.textContent = entry.journal;
      const meta = document.createElement("span");
      meta.className = "journal-meta";
      meta.textContent = impactLabel(entry);
      button.appendChild(name);
      button.appendChild(meta);
      return button;
    }

    function renderJournalPicker() {
      const selectedList = field("selected_journal_list");
      const candidateList = field("candidate_journal_list");
      if (!selectedList || !candidateList) {
        return;
      }
      const model = ensureJournalDualList();
      selectedJournals = model.selected();
      const selectedEntries = model.selectedEntries();
      const query = field("journal_search") ? journalKey(field("journal_search").value) : "";
      const category = field("journal_category") ? field("journal_category").value : "";
      const candidates = model.availableEntries(function (entry) {
        const matchesCategory = !category || entry.category === category;
        const searchable = [entry.journal, entry.category, entry.level].concat(entry.aliases || []).join(" ");
        return matchesCategory && (!query || journalKey(searchable).includes(query));
      }).sort(compareJournalEntries);

      selectedList.textContent = "";
      candidateList.textContent = "";
      bindDualListDropZone(selectedList, "journal-filter", function (journal) {
        addSelectedJournal(journal);
      });
      bindDualListDropZone(candidateList, "journal-filter", function (journal) {
        removeSelectedJournal(journal);
      });
      selectedEntries.forEach(function (entry) {
        selectedList.appendChild(journalButton(entry, true));
      });
      candidates.forEach(function (entry) {
        candidateList.appendChild(journalButton(entry, false));
      });
      if (!selectedEntries.length) {
        const empty = document.createElement("div");
        empty.className = "journal-empty";
        empty.textContent = "No journals selected.";
        selectedList.appendChild(empty);
      }
      if (!candidates.length) {
        const empty = document.createElement("div");
        empty.className = "journal-empty";
        empty.textContent = query ? "No matching candidate journals." : "All candidate journals are selected.";
        candidateList.appendChild(empty);
      }
      field("selected_journal_count").textContent = String(selectedJournals.length) + " selected";
      field("candidate_journal_count").textContent = String(candidates.length) + " available";
      setLines("selected_journals", selectedJournals);
    }

    function setJournalPicker(catalog, selected) {
      journalCatalog = (Array.isArray(catalog) ? catalog : []).map(normalizeJournalEntry).filter(Boolean);
      const catalogKeys = new Set(journalCatalog.map(function (entry) { return journalKey(entry.journal); }));
      extraJournalCandidates = dedupeJournals(selected).filter(function (journal) {
        return !catalogKeys.has(journalKey(journal));
      }).map(function (journal) {
        return {
          journal: journal,
          aliases: [],
          rank: null,
          impact_factor: null,
          impact_label: "Manual",
          category: "Manual",
          custom: true
        };
      });
      const model = syncJournalCandidates();
      model.setSelected(selected);
      selectedJournals = model.selected();
      fillJournalCategoryOptions();
      renderJournalPicker();
    }

    function fillJournalCategoryOptions() {
      const select = field("journal_category");
      if (!select) return;
      const current = select.value;
      const categories = Array.from(new Set(journalCatalog.map(function (entry) {
        return entry.category;
      }).filter(Boolean))).sort(function (left, right) {
        return left.localeCompare(right);
      });
      select.textContent = "";
      const all = document.createElement("option");
      all.value = "";
      all.textContent = "All categories";
      select.appendChild(all);
      categories.forEach(function (category) {
        const option = document.createElement("option");
        option.value = category;
        option.textContent = category;
        select.appendChild(option);
      });
      select.value = categories.includes(current) ? current : "";
    }

    function addSelectedJournal(journal) {
      const clean = normalizeJournalName(journal);
      if (!clean) {
        return;
      }
      const key = journalKey(clean);
      if (!rawJournalEntries().some(function (entry) { return journalKey(entry.journal) === key; })) {
        extraJournalCandidates.push({
          journal: clean,
          aliases: [],
          rank: null,
          impact_factor: null,
          impact_label: "Manual",
          category: "Manual",
          custom: true
        });
      }
      const model = syncJournalCandidates();
      model.add(clean);
      selectedJournals = model.selected();
      if (journalKey(clean) === "arxiv" && field("arxiv_enabled")) {
        field("arxiv_enabled").checked = true;
      }
      renderJournalPicker();
    }

    function removeSelectedJournal(journal) {
      const model = ensureJournalDualList();
      model.remove(journal);
      selectedJournals = model.selected();
      if (journalKey(journal) === "arxiv" && field("arxiv_enabled")) {
        field("arxiv_enabled").checked = false;
      }
      renderJournalPicker();
    }

    function addManualJournal() {
      const input = field("manual_journal_name");
      const clean = normalizeJournalName(input.value);
      if (!clean) {
        return;
      }
      addSelectedJournal(clean);
      input.value = "";
    }

    function numberValue(id) {
      return Number(field(id).value);
    }

    function optionLabel(seconds) {
      const value = Number(seconds);
      if (value === 86400) {
        return "1 day";
      }
      if (value % 86400 === 0) {
        return String(value / 86400) + " day";
      }
      if (value % 3600 === 0) {
        return String(value / 3600) + "h";
      }
      return String(value) + "s";
    }

    function fillFrequencyOptions(options, selected) {
      const select = field("interval_seconds");
      const chosen = Number(selected);
      select.textContent = "";
      const seen = new Set();
      (Array.isArray(options) ? options : []).forEach(function (option) {
        const seconds = Number(option.seconds);
        if (!Number.isFinite(seconds) || seen.has(seconds)) {
          return;
        }
        seen.add(seconds);
        const element = document.createElement("option");
        element.value = String(seconds);
        element.textContent = option.label || optionLabel(seconds);
        select.appendChild(element);
      });
      if (Number.isFinite(chosen) && !seen.has(chosen)) {
        const element = document.createElement("option");
        element.value = String(chosen);
        element.textContent = optionLabel(chosen);
        select.appendChild(element);
      }
      select.value = String(chosen);
    }

    function fillSearchDirection(direction) {
      const select = field("search_direction");
      const presets = Array.isArray(direction.presets) ? direction.presets : [];
      presetsById = {};
      select.textContent = "";
      presets.forEach(function (preset) {
        presetsById[preset.id] = preset;
        const element = document.createElement("option");
        element.value = preset.id;
        element.textContent = preset.label;
        select.appendChild(element);
      });
      if (!presetsById.custom) {
        presetsById.custom = { id: "custom", label: "Custom", crossref_query: "", openalex_query: "" };
        const element = document.createElement("option");
        element.value = "custom";
        element.textContent = "Custom";
        select.appendChild(element);
      }
      select.value = presetsById[direction.preset] ? direction.preset : "custom";
      setValue("custom_direction_name", direction.label || "Custom");
      setValue("crossref_query", direction.crossref_query || "");
      setValue("openalex_query", direction.openalex_query || "");
      updateCustomState();
    }

    function updateCustomState() {
      const isCustom = field("search_direction").value === "custom";
      field("custom_direction_row").classList.toggle("visible", isCustom);
      field("custom_direction_name").disabled = !isCustom;
    }

    function applyPreset() {
      const presetId = field("search_direction").value;
      const preset = presetsById[presetId];
      if (preset && presetId !== "custom") {
        setValue("custom_direction_name", preset.label);
        setValue("crossref_query", preset.crossref_query);
        setValue("openalex_query", preset.openalex_query);
      } else if (!field("custom_direction_name").value.trim()) {
        setValue("custom_direction_name", "Custom");
      }
      updateCustomState();
    }

    function promoteToCustom() {
      if (field("search_direction").value !== "custom") {
        field("search_direction").value = "custom";
        const current = presetsById.custom || { label: "Custom" };
        if (!field("custom_direction_name").value.trim()) {
          setValue("custom_direction_name", current.label || "Custom");
        }
        updateCustomState();
      }
    }

    async function request(path, options) {
      const init = options || {};
      const headers = Object.assign({}, init.headers || {}, {
        "X-Paper-Monitor-Token": token
      });
      if (init.body !== undefined) {
        headers["Content-Type"] = "application/json; charset=utf-8";
      }
      const response = await fetch(apiBase + path, Object.assign({}, init, { headers: headers }));
      const body = await response.json().catch(function () {
        return {};
      });
      if (!response.ok || body.error) {
        throw new Error(body.error || ("Request failed with status " + response.status));
      }
      return body;
    }

    function fillForm(payload) {
      const sources = payload.sources || {};
      const crossref = sources.crossref || {};
      const openalex = sources.openalex || {};
      const arxiv = sources.arxiv || {};
      const journalScope = payload.journal_scope || {};
      const direction = payload.search_direction || {};
      const appSettings = payload.app_settings || {};

      fillFrequencyOptions(payload.refresh_frequency_options, payload.interval_seconds);
      setValue("refresh_start_time", payload.refresh_start_time || "");
      setValue("max_notifications", payload.max_notifications);
      setValue("journal_scope_top_n", journalScope.top_n);
      fillSearchDirection(direction);
      setChecked("startup_enabled", appSettings.startup_enabled);
      setChecked("show_tray_icon", appSettings.show_tray_icon);
      setChecked("notifications_enabled", appSettings.notifications_enabled);
      setChecked("silent_startup_notifications", appSettings.silent_startup_notifications);
      setChecked("refresh_on_launch", appSettings.refresh_on_launch);

      setLines("include_terms", payload.include_terms);
      setLines("exclude_terms", payload.exclude_terms);
      setJournalPicker(payload.journal_catalog, journalScope.selected_journals);

      setChecked("crossref_enabled", crossref.enabled);
      setValue("crossref_days_back", crossref.days_back);
      setValue("crossref_rows", crossref.rows);
      setValue("crossref_rows_per_journal", crossref.rows_per_journal);
      setValue("crossref_timeout_seconds", crossref.timeout_seconds);
      setValue("crossref_max_workers", crossref.max_workers);
      setValue("crossref_mailto", crossref.mailto);

      setChecked("openalex_enabled", openalex.enabled);
      setValue("openalex_days_back", openalex.days_back);
      setValue("openalex_per_page", openalex.per_page);
      setValue("openalex_max_pages", openalex.max_pages);
      setValue("openalex_api_key", openalex.api_key);

      setChecked("arxiv_enabled", arxiv.enabled);
      setValue("arxiv_days_back", arxiv.days_back);
      setValue("arxiv_max_results", arxiv.max_results);
      setValue("arxiv_search_field", arxiv.search_field || "title");
      setValue("arxiv_timeout_seconds", arxiv.timeout_seconds);
      setValue("arxiv_query", arxiv.query);
    }

    function selectedDirectionLabel() {
      const presetId = field("search_direction").value;
      if (presetId === "custom") {
        return field("custom_direction_name").value;
      }
      return (presetsById[presetId] && presetsById[presetId].label) || presetId;
    }

    function collectForm() {
      const crossrefQuery = field("crossref_query").value;
      const openalexQuery = field("openalex_query").value;
      const preset = field("search_direction").value;
      return {
        interval_seconds: numberValue("interval_seconds"),
        refresh_start_time: field("refresh_start_time").value,
        max_notifications: numberValue("max_notifications"),
        app_settings: {
          startup_enabled: field("startup_enabled").checked,
          show_tray_icon: field("show_tray_icon").checked,
          notifications_enabled: field("notifications_enabled").checked,
          silent_startup_notifications: field("silent_startup_notifications").checked,
          refresh_on_launch: field("refresh_on_launch").checked
        },
        search_direction: {
          preset: preset,
          label: selectedDirectionLabel(),
          crossref_query: crossrefQuery,
          openalex_query: openalexQuery,
          query_manually_edited: preset === "custom"
        },
        include_terms: lines("include_terms"),
        exclude_terms: lines("exclude_terms"),
        journal_scope: {
          top_n: numberValue("journal_scope_top_n"),
          selected_journals: selectedJournals.slice()
        },
        sources: {
          crossref: {
            enabled: field("crossref_enabled").checked,
            days_back: numberValue("crossref_days_back"),
            rows: numberValue("crossref_rows"),
            rows_per_journal: numberValue("crossref_rows_per_journal"),
            timeout_seconds: numberValue("crossref_timeout_seconds"),
            max_workers: numberValue("crossref_max_workers"),
            mailto: field("crossref_mailto").value,
            query: crossrefQuery
          },
          openalex: {
            enabled: field("openalex_enabled").checked,
            days_back: numberValue("openalex_days_back"),
            per_page: numberValue("openalex_per_page"),
            max_pages: numberValue("openalex_max_pages"),
            query: openalexQuery,
            api_key: field("openalex_api_key").value
          },
          arxiv: {
            enabled: field("arxiv_enabled").checked,
            days_back: numberValue("arxiv_days_back"),
            max_results: numberValue("arxiv_max_results"),
            search_field: field("arxiv_search_field").value,
            timeout_seconds: numberValue("arxiv_timeout_seconds"),
            query: field("arxiv_query").value
          }
        }
      };
    }

    async function loadSettings() {
      setStatus("Loading settings...", "");
      const payload = await request("/api/settings");
      fillForm(payload);
      setStatus("Settings loaded.", "ok");
    }

    async function restoreDefaults() {
      const defaultsButton = field("defaults-button");
      defaultsButton.disabled = true;
      setStatus("Loading defaults...", "");
      try {
        const payload = await request("/api/settings/defaults");
        fillForm(payload);
        setStatus("Defaults loaded. Save to apply.", "ok");
      } catch (error) {
        setStatus(error.message || "Default settings could not be loaded.", "error");
      } finally {
        defaultsButton.disabled = false;
      }
    }

    async function saveSettings(event) {
      event.preventDefault();
      const saveButton = field("save-button");
      saveButton.disabled = true;
      setStatus("Saving settings...", "");
      try {
        await request("/api/settings", {
          method: "POST",
          body: JSON.stringify(collectForm())
        });
        await loadSettings();
        setStatus("Settings saved.", "ok");
      } catch (error) {
        setStatus(error.message || "Settings could not be saved.", "error");
      } finally {
        saveButton.disabled = false;
      }
    }

    document.querySelectorAll(".tab").forEach(function (tab) {
      tab.addEventListener("click", function () {
        document.querySelectorAll(".tab").forEach(function (button) {
          button.setAttribute("aria-selected", button === tab ? "true" : "false");
        });
        document.querySelectorAll(".panel").forEach(function (panel) {
          panel.classList.toggle("active", panel.id === tab.dataset.panel);
        });
      });
    });

    field("dashboard-link").href = apiBase + "/";
    field("defaults-button").addEventListener("click", function () {
      restoreDefaults();
    });
    field("search_direction").addEventListener("change", applyPreset);
    field("crossref_query").addEventListener("input", promoteToCustom);
    field("openalex_query").addEventListener("input", promoteToCustom);
    field("custom_direction_name").addEventListener("input", function () {
      if (field("search_direction").value !== "custom") {
        promoteToCustom();
      }
    });
    field("journal_search").addEventListener("input", renderJournalPicker);
    field("journal_category").addEventListener("change", renderJournalPicker);
    field("arxiv_enabled").addEventListener("change", function () {
      if (field("arxiv_enabled").checked) {
        addSelectedJournal("arXiv");
      } else {
        removeSelectedJournal("arXiv");
      }
    });
    field("journal_sort_mode").addEventListener("change", renderJournalPicker);
    field("add_manual_journal").addEventListener("click", addManualJournal);
    field("manual_journal_name").addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        addManualJournal();
      }
    });
    field("settings-form").addEventListener("submit", saveSettings);
    loadSettings().catch(function (error) {
      setStatus(error.message || "Settings could not be loaded.", "error");
    });
