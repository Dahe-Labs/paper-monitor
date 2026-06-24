import json
from datetime import date
from html import escape
from typing import Dict, List, Optional
from urllib.parse import urlsplit

from .app_identity import DISPLAY_NAME
from .date_utils import display_article_date, first_iso_date
from .journal_metrics import JournalMetrics
from .keyword_analysis import AnalysisScope, build_keyword_analysis_payload


def render_dashboard(
    run: Optional[Dict[str, object]],
    candidates: List[Dict[str, object]],
    metrics: JournalMetrics,
    analysis_scope: Optional[AnalysisScope] = None,
) -> str:
    run = run or {}
    matched = [candidate for candidate in candidates if candidate.get("matched")]
    rejected = [candidate for candidate in candidates if not candidate.get("matched")]
    selected_journal_count = len(analysis_scope.selected_journals) if analysis_scope else 0
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>%s</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #1f2933; }
    header { border-bottom: 1px solid #d8dee4; margin-bottom: 24px; padding-bottom: 16px; }
    .header-main { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 8px; }
    h1 { font-size: 28px; margin: 0; }
    h2 { font-size: 18px; margin: 28px 0 12px; }
    .summary { display: flex; flex-wrap: wrap; gap: 10px; }
    .pill { border: 1px solid #d8dee4; border-radius: 6px; padding: 6px 10px; background: #f6f8fa; }
    .section-title-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: 28px 0 12px; }
    .section-title-row h2 { margin: 0; }
    .sort-control { display: flex; align-items: center; gap: 8px; color: #57606a; font-size: 13px; font-weight: 700; }
    .sort-control select { height: 32px; border: 1px solid #d8dee4; border-radius: 6px; background: #ffffff; color: #1f2933; padding: 0 8px; font-weight: 700; }
    .analysis-shell { border: 1px solid #d8dee4; border-radius: 8px; margin: 24px 0; background: #ffffff; overflow: hidden; }
    .analysis-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 16px; background: #f6f8fa; border-bottom: 1px solid #d8dee4; }
    .analysis-title-block { flex: 1 1 auto; min-width: 0; }
    .analysis-header h2 { margin: 0 0 4px; }
    .analysis-header .primary-button { flex: 0 0 auto; }
    .analysis-progress { height: 3px; width: min(420px, 100%%); margin: 6px 0 5px; border-radius: 999px; background: #dbeafe; overflow: hidden; }
    .analysis-progress[hidden], .analysis-progress-label[hidden] { display: none; }
    .analysis-progress-fill { height: 100%%; width: 0%%; border-radius: inherit; background: #0a84ff; transition: width 260ms ease; }
    .analysis-progress-label { color: #0969da; font-size: 11.5px; font-weight: 700; line-height: 1.2; margin-bottom: 4px; }
    .primary-button { border: 0; border-radius: 7px; background: #1f2933; color: #ffffff; height: 36px; padding: 0 13px; font-weight: 700; cursor: pointer; }
    .primary-button:disabled { opacity: 0.58; cursor: default; }
    .analysis-panel { padding: 16px; }
    .analysis-grid { display: grid; grid-template-columns: minmax(240px, 320px) 1fr; gap: 16px; }
    .analysis-controls, .analysis-results { min-width: 0; }
    .control-group { border: 1px solid #d8dee4; border-radius: 8px; padding: 12px; margin-bottom: 12px; }
    .control-group h3 { margin: 0 0 10px; font-size: 14px; }
    .control-row { display: grid; gap: 6px; margin: 8px 0; }
    .control-row label { font-size: 12px; color: #57606a; font-weight: 700; }
    .control-row input, .control-row select, .control-row textarea { border: 1px solid #d8dee4; border-radius: 6px; padding: 0 8px; }
    .control-row input, .control-row select { height: 32px; }
    .control-row textarea { min-height: 88px; padding: 8px; resize: vertical; font: inherit; }
    .date-control { gap: 8px; }
    .date-parts { display: grid; grid-template-columns: minmax(64px, 1fr) minmax(52px, 0.75fr) minmax(52px, 0.75fr); gap: 6px; }
    .date-part { display: grid; gap: 4px; min-width: 0; }
    .date-part span { color: #57606a; font-size: 11px; font-weight: 700; }
    .date-part input { width: 100%%; box-sizing: border-box; }
    .date-control.has-error .date-part input { border-color: #cf222e; box-shadow: 0 0 0 1px #cf222e inset; }
    .date-error { color: #cf222e; font-size: 12px; font-weight: 700; line-height: 1.35; }
    .date-error[hidden] { display: none; }
    .control-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 0 0 10px; }
    .control-toolbar .meta { margin-left: auto; }
    .inline-options { display: flex; flex-wrap: wrap; gap: 8px; }
    .stepper-control { display: grid; grid-template-columns: 40px minmax(0, 1fr) 40px; align-items: stretch; border: 1px solid #d8dee4; border-radius: 7px; overflow: hidden; min-height: 36px; }
    .stepper-button { border: 0; background: #f6f8fa; color: #1f2933; cursor: pointer; font-size: 18px; font-weight: 800; }
    .stepper-value { display: flex; align-items: center; justify-content: center; padding: 0 8px; min-width: 0; font-size: 13px; font-weight: 700; text-align: center; }
    .segmented-control { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 14px; }
    .segmented-control button { border: 1px solid #d8dee4; border-radius: 6px; background: #ffffff; height: 32px; padding: 0 10px; cursor: pointer; }
    .segmented-control button[aria-pressed="true"] { background: #1f2933; color: #ffffff; border-color: #1f2933; }
    .chart-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
    .chart-heading h3 { margin: 0; }
    .category-share-total { color: #57606a; font-size: 13px; font-weight: 700; white-space: nowrap; }
    .bar-row { display: grid; grid-template-columns: 160px 1fr 124px; gap: 10px; align-items: center; font-size: 13px; margin: 9px 0; }
    .bar-track { height: 12px; border-radius: 6px; background: #eaeef2; overflow: hidden; }
    .bar-fill { height: 100%%; background: #0969da; }
    .analysis-table { width: 100%%; border-collapse: collapse; font-size: 13px; }
    .analysis-table th, .analysis-table td { border-bottom: 1px solid #d8dee4; padding: 8px; text-align: left; }
    .term-chip { display: inline-flex; align-items: center; gap: 6px; border: 1px solid #d8dee4; border-radius: 6px; padding: 5px 7px; margin: 4px; background: #f6f8fa; font-size: 12px; }
    .checkbox-list { display: grid; gap: 6px; max-height: 220px; overflow: auto; padding-right: 4px; }
    .analysis-journal-list { max-height: 240px; }
    .checkbox-option { display: flex; gap: 7px; align-items: flex-start; font-size: 13px; line-height: 1.35; }
    .checkbox-option input { flex: 0 0 auto; margin-top: 2px; }
    .secondary-button, .mini-button { border: 1px solid #d8dee4; border-radius: 6px; background: #ffffff; color: #1f2933; cursor: pointer; font-weight: 700; }
    .secondary-button { height: 32px; padding: 0 10px; }
    .mini-button { min-height: 28px; padding: 0 8px; font-size: 12px; }
    .candidate-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
    .candidate-header h3 { margin: 0; }
    .candidate-filter-toolbar { display: flex; flex-wrap: wrap; justify-content: flex-end; align-items: center; gap: 8px; }
    .candidate-filter-label { color: #57606a; font-size: 12px; font-weight: 700; }
    .block-terms-panel { border: 1px solid #d8dee4; border-radius: 8px; background: #f6f8fa; padding: 10px; margin: 0 0 10px; }
    .block-terms-panel label { display: block; color: #57606a; font-size: 12px; font-weight: 700; margin-bottom: 6px; }
    .block-terms-panel textarea { width: 100%%; box-sizing: border-box; min-height: 96px; border: 1px solid #d8dee4; border-radius: 6px; padding: 8px; resize: vertical; font: inherit; background: #ffffff; }
    .candidate-row { display: grid; grid-template-columns: minmax(140px, 1fr) auto; gap: 10px; align-items: center; border-bottom: 1px solid #d8dee4; padding: 9px 0; }
    .candidate-actions { display: flex; flex-wrap: wrap; gap: 6px; justify-content: flex-end; }
    .analysis-paper-table { width: 100%%; border-collapse: collapse; table-layout: fixed; font-size: 12.5px; }
    .analysis-paper-table th, .analysis-paper-table td { border-bottom: 1px solid #d8dee4; padding: 6px 7px; text-align: left; vertical-align: top; }
    .analysis-paper-table th { color: #57606a; font-size: 11.5px; font-weight: 800; }
    .analysis-paper-title { width: 42%%; }
    .analysis-paper-doi { width: 18%%; overflow-wrap: anywhere; }
    .analysis-paper-journal { width: 18%%; }
    .analysis-paper-authors { width: 22%%; }
    .analysis-note { color: #57606a; font-size: 13px; margin: 8px 0; }
    .taxonomy-list { display: flex; flex-wrap: wrap; gap: 6px; }
    @media (max-width: 780px) { .analysis-grid { grid-template-columns: 1fr; } .header-main, .analysis-header, .section-title-row, .candidate-header, .chart-heading { align-items: stretch; flex-direction: column; } .sort-control, .candidate-filter-toolbar { justify-content: flex-start; } .bar-row { grid-template-columns: 1fr; } }
    .date-group { position: relative; margin: 24px 0 30px; padding-left: 20px; }
    .date-group::before { content: ""; position: absolute; left: 5px; top: 18px; bottom: -22px; width: 2px; background: #d8dee4; }
    .date-heading-bar { position: sticky; top: 0; z-index: 3; display: flex; align-items: center; gap: 10px; min-height: 34px; margin: 0 0 10px; padding: 7px 10px 7px 0; background: rgba(255, 255, 255, 0.96); border-bottom: 1px solid #d8dee4; backdrop-filter: blur(6px); }
    .date-marker { position: relative; z-index: 1; flex: 0 0 auto; width: 10px; height: 10px; margin-left: -20px; border: 2px solid #ffffff; border-radius: 999px; background: #0969da; box-shadow: 0 0 0 2px #0969da; }
    .date-short-label { flex: 0 0 auto; border: 1px solid #d8dee4; border-radius: 999px; padding: 3px 8px; background: #f6f8fa; color: #1f2933; font-size: 12px; font-weight: 800; }
    .date-heading { font-size: 15px; margin: 0; color: #1f2933; }
    .date-count { margin-left: auto; color: #57606a; font-size: 12px; font-weight: 700; white-space: nowrap; }
    .paper { border: 1px solid #d8dee4; border-radius: 8px; padding: 12px 13px; margin: 8px 0; }
    .paper h3 { font-size: 15px; line-height: 1.3; margin: 0 0 6px; }
    .meta { color: #57606a; font-size: 12.5px; line-height: 1.38; }
    .journal-name { color: #1f2933; font-weight: 700; }
    .terms { margin-top: 6px; font-size: 12.5px; line-height: 1.35; }
    .rejected-candidates { margin-top: 8px; }
    .rejected-candidates summary { cursor: pointer; color: #57606a; font-size: 13px; margin-bottom: 10px; }
    a { color: #0969da; }
  </style>
</head>
<body>
  <header>
    <div class="header-main">
      <h1>%s</h1>
      <button type="button" id="keyword-analysis-nav" class="primary-button" aria-controls="keyword-analysis" aria-expanded="false">Keyword Analysis</button>
    </div>
    <div class="meta">Last run: %s · Run ID: %s</div>
  </header>
  <div id="dashboard-view">
    <section class="summary">
      <div class="pill">Fetched: %s</div>
      <div class="pill">Matched: %s</div>
      <div class="pill">New notifications: %s</div>
      <div class="pill">Skipped: %s</div>
      <div class="pill">Selected journals: %s</div>
    </section>
    <div class="section-title-row">
      <h2>Matched Papers</h2>
      <label class="sort-control" for="matched-papers-sort">Sort
        <select id="matched-papers-sort">
          <option value="time">Time</option>
          <option value="impact_factor">Impact factor</option>
        </select>
      </label>
    </div>
    <div id="matched-papers-list">%s</div>
    <script type="application/json" id="matched-papers-data">%s</script>
    <h2>Rejected Candidates</h2>
    <details class="rejected-candidates">
      <summary>Show rejected candidates (up to 100)</summary>
      %s
    </details>
  </div>
  <section id="keyword-analysis" class="analysis-shell" data-chart-view="bars" hidden>
    <div class="analysis-header">
      <div class="analysis-title-block">
        <h2>Keyword Analysis</h2>
        <div id="analysis-progress" class="analysis-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" hidden>
          <div id="analysis-progress-bar" class="analysis-progress-fill"></div>
        </div>
        <div id="analysis-progress-label" class="analysis-progress-label" hidden></div>
        <div class="meta">Classify matched papers, discover repeated terms, and draw charts from the selected scope.</div>
      </div>
      <button type="button" id="analysis-run-button" class="primary-button" data-analysis-action="run-keyword-analysis">Analyze</button>
    </div>
    <div id="analysis-panel" class="analysis-panel">
      <div class="analysis-grid">
        <aside class="analysis-controls" id="analysis-controls"></aside>
        <main class="analysis-results">
          <div id="analysis-chart-tabs" class="segmented-control"></div>
          <div id="analysis-chart"></div>
          <div id="analysis-candidates"></div>
          <div id="analysis-taxonomy"></div>
          <div id="analysis-papers"></div>
        </main>
      </div>
    </div>
  </section>
  <script type="application/json" id="keyword-analysis-data">%s</script>
  %s
</body>
</html>
""" % (
        escape(DISPLAY_NAME),
        escape(DISPLAY_NAME),
        escape(str(run.get("finished_at") or run.get("started_at") or "")),
        escape(str(run.get("id") or "")),
        escape(str(run.get("fetched", 0))),
        escape(str(run.get("matched", 0))),
        escape(str(run.get("new_matches", 0))),
        escape(str(run.get("skipped", 0))),
        escape(str(selected_journal_count)),
        _render_candidate_groups(matched, metrics, empty_text="No matched papers in this run."),
        _matched_papers_payload_json(matched, metrics, empty_text="No matched papers in this run."),
        _render_candidates(rejected[:100], metrics, empty_text="No rejected candidates in this run."),
        _keyword_analysis_payload_json(matched, metrics, analysis_scope),
        _keyword_analysis_script() + _matched_papers_script(),
    )


def write_dashboard(path, run, candidates, metrics, analysis_scope: Optional[AnalysisScope] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_dashboard(run, candidates, metrics, analysis_scope), encoding="utf-8")


def _keyword_analysis_script() -> str:
    return r"""<script>
const keywordAnalysisState = {
  storageKey: "paperMonitor.keywordAnalysis.v1",
  payload: JSON.parse(document.getElementById("keyword-analysis-data").textContent),
  chartView: "bars",
  sortMode: "time",
  analysisDepth: "fast",
  topN: 30,
  dateFrom: "",
  dateTo: "",
  selectedJournals: [],
  selectedPhraseLengths: [2, 3],
  candidateTermsOpen: false,
  blockTermsOpen: false,
  taxonomyEditorOpen: false,
  paperListOpen: false,
  analysisStatus: "idle",
  analysisError: "",
  analysisProgress: 0,
  blockedTerms: [],
  customTaxonomy: [],
  ignoredTerms: [],
  savedJournalScopeSignature: "",
  journalScopeSignature: ""
};

const MAX_CANDIDATE_TERMS = 40;
const DEFAULT_CANDIDATE_PHRASE_LENGTHS = [2, 3];
const ALLOWED_CANDIDATE_PHRASE_LENGTHS = [1, 2, 3, 4];
const ANALYSIS_SORT_MODES = [
  ["time", "Time"],
  ["impact_factor", "Impact factor"],
  ["relevance", "Relevance"]
];
let keywordAnalysisProgressTimer = null;
const DOMAIN_ANCHOR_TERMS = new Set([
  "anode", "argyrodite", "cathode", "cei", "ceramic", "coating", "composite", "conductivity",
  "current", "degradation", "dendrite", "dendrites", "density", "deposition", "diffusion",
  "electrochemical", "electrode", "electrodes", "electrolyte", "electrolytes", "garnet",
  "halide", "impedance", "interfacial", "interface", "interfaces", "interphase", "interphases",
  "ion", "ionic", "lagp", "latp", "li", "liquid", "lithium", "llto", "llzo", "mechanical",
  "nasicon", "oxide", "oxides", "perovskite", "polymer", "pressure", "resistance", "sei",
  "separator", "solid", "stability", "sulfide", "sulfides", "sulphide", "thermal", "transport"
]);
const LOW_VALUE_CANDIDATE_TOKENS = new Set([
  "a", "about", "after", "against", "all", "also", "an", "and", "are", "as", "at", "battery",
  "batteries", "be", "been", "between", "by", "can", "cell", "cells", "during", "for", "from",
  "has", "have", "high", "how", "in", "into", "is", "it", "low", "material", "materials", "new",
  "of", "on", "or", "paper", "performance", "review", "study", "that", "the", "their", "these",
  "this", "through", "to", "toward", "towards", "using", "via", "was", "were", "why", "with",
  "article", "approach", "based", "better", "different", "excellent", "general", "good",
  "important", "improved", "improves", "method", "methods", "novel", "rapid", "result",
  "results", "screening", "shows", "significant", "strategy", "system", "systems"
]);
const PUBLICATION_METADATA_TOKENS = new Set([
  "accepted", "ahead", "april", "article", "august", "december", "earlyview", "february", "issue",
  "january", "july", "june", "march", "may", "november", "october", "online", "published",
  "september", "volume", "vol"
]);
const BROAD_CANDIDATE_TOKENS = new Set([
  "battery", "batteries", "cell", "cells", "electrolyte", "electrolytes", "li", "lithium",
  "material", "materials", "solid", "state"
]);

if (typeof window !== "undefined") {
  window.paperMonitorReceiveKeywordAnalysis = receiveKeywordAnalysisPayload;
}

document.addEventListener("DOMContentLoaded", function () {
  loadSavedAnalysisState();
  initializeAnalysisDefaults();
  wireAnalysisEvents();
  renderKeywordAnalysis();
});

function loadSavedAnalysisState() {
  try {
    const raw = localStorage.getItem(keywordAnalysisState.storageKey);
    if (!raw) return;

    const saved = JSON.parse(raw);
    if (!saved || typeof saved !== "object") return;

    if (typeof saved.chartView === "string") keywordAnalysisState.chartView = saved.chartView;
    if (typeof saved.sortMode === "string") keywordAnalysisState.sortMode = saved.sortMode;
    if (typeof saved.analysisDepth === "string") keywordAnalysisState.analysisDepth = normalizeAnalysisDepth(saved.analysisDepth);
    if (typeof saved.dateFrom === "string") keywordAnalysisState.dateFrom = saved.dateFrom;
    if (typeof saved.dateTo === "string") keywordAnalysisState.dateTo = saved.dateTo;
    keywordAnalysisState.topN = coercePositiveInt(saved.topN, keywordAnalysisState.topN);
    if (Array.isArray(saved.selectedJournals)) {
      keywordAnalysisState.selectedJournals = saved.selectedJournals.map(normalizeDisplayTerm).filter(Boolean);
      keywordAnalysisState.hasJournalSelection = saved.hasJournalSelection !== false;
    }
    if (Array.isArray(saved.selectedPhraseLengths)) keywordAnalysisState.selectedPhraseLengths = normalizePhraseLengths(saved.selectedPhraseLengths);
    if (Array.isArray(saved.blockedTerms)) keywordAnalysisState.blockedTerms = saved.blockedTerms.map(normalizeDisplayTerm).filter(Boolean);
    if (Array.isArray(saved.customTaxonomy)) keywordAnalysisState.customTaxonomy = sanitizeTaxonomy(saved.customTaxonomy);
    if (Array.isArray(saved.ignoredTerms)) keywordAnalysisState.ignoredTerms = saved.ignoredTerms.map(normalizeDisplayTerm).filter(Boolean);
    if (typeof saved.paperListOpen === "boolean") keywordAnalysisState.paperListOpen = saved.paperListOpen;
    if (typeof saved.journalScopeSignature === "string") keywordAnalysisState.savedJournalScopeSignature = saved.journalScopeSignature;
    keywordAnalysisState.hasSavedState = true;
  } catch (error) {
    keywordAnalysisState.hasSavedState = false;
  }
}

function saveAnalysisState() {
  try {
    localStorage.setItem(keywordAnalysisState.storageKey, JSON.stringify({
      chartView: keywordAnalysisState.chartView,
      sortMode: keywordAnalysisState.sortMode,
      analysisDepth: normalizeAnalysisDepth(keywordAnalysisState.analysisDepth),
      topN: clampTopJournalCount(keywordAnalysisState.topN),
      dateFrom: keywordAnalysisState.dateFrom,
      dateTo: keywordAnalysisState.dateTo,
      hasJournalSelection: Boolean(keywordAnalysisState.hasJournalSelection),
      selectedJournals: keywordAnalysisState.selectedJournals,
      selectedPhraseLengths: normalizePhraseLengths(keywordAnalysisState.selectedPhraseLengths),
      blockedTerms: keywordAnalysisState.blockedTerms,
      customTaxonomy: keywordAnalysisState.customTaxonomy,
      ignoredTerms: keywordAnalysisState.ignoredTerms,
      paperListOpen: Boolean(keywordAnalysisState.paperListOpen),
      journalScopeSignature: currentJournalScopeSignature()
    }));
  } catch (error) {
    return;
  }
}

function initializeAnalysisDefaults() {
  const payload = keywordAnalysisState.payload || {};
  const scope = payload.scope || {};
  const papers = Array.isArray(payload.papers) ? payload.papers : [];
  const scopeJournals = scopedAnalysisJournals();
  const allJournals = allAnalysisJournals();
  const scopeSignature = journalScopeSignature(scopeJournals);
  const savedJournalScopeIsCurrent = keywordAnalysisState.hasSavedState && (
    !scopeJournals.length || keywordAnalysisState.savedJournalScopeSignature === scopeSignature
  );
  const defaultTopN = coercePositiveInt(scope.default_top_n || scope.top_n, 30);
  if (!keywordAnalysisState.hasSavedState) {
    keywordAnalysisState.topN = clampTopJournalCount(defaultTopN);
  } else {
    keywordAnalysisState.topN = clampTopJournalCount(keywordAnalysisState.topN);
  }
  ensureAnalysisDateDefaults(scope, papers);
  keywordAnalysisState.journalScopeSignature = scopeSignature;

  if (!keywordAnalysisState.blockedTerms.length) {
    keywordAnalysisState.blockedTerms = Array.isArray(payload.blocklist) ? payload.blocklist.map(normalizeDisplayTerm).filter(Boolean) : [];
  }
  if (!keywordAnalysisState.customTaxonomy.length) {
    keywordAnalysisState.customTaxonomy = sanitizeTaxonomy(Array.isArray(payload.taxonomy) ? payload.taxonomy : []);
  }
  if ((!keywordAnalysisState.hasSavedState || !savedJournalScopeIsCurrent) && scopeJournals.length) {
    keywordAnalysisState.selectedJournals = scopeJournals;
    keywordAnalysisState.hasJournalSelection = true;
  } else if ((!keywordAnalysisState.hasSavedState || !savedJournalScopeIsCurrent) && allJournals.length) {
    keywordAnalysisState.selectedJournals = topNAnalysisJournals();
    keywordAnalysisState.hasJournalSelection = true;
  }
  if (!["bars", "donut", "trend", "table"].includes(keywordAnalysisState.chartView)) {
    keywordAnalysisState.chartView = "bars";
  }
  if (!["time", "impact_factor", "relevance"].includes(keywordAnalysisState.sortMode)) {
    keywordAnalysisState.sortMode = "time";
  }
  if (typeof scope.analysis_depth === "string" && !keywordAnalysisState.hasSavedState) {
    keywordAnalysisState.analysisDepth = normalizeAnalysisDepth(scope.analysis_depth);
  }
  keywordAnalysisState.analysisDepth = normalizeAnalysisDepth(keywordAnalysisState.analysisDepth);
  keywordAnalysisState.selectedJournals = unique(keywordAnalysisState.selectedJournals);
  keywordAnalysisState.selectedPhraseLengths = normalizePhraseLengths(keywordAnalysisState.selectedPhraseLengths);
  keywordAnalysisState.blockedTerms = unique(keywordAnalysisState.blockedTerms);
  keywordAnalysisState.ignoredTerms = unique(keywordAnalysisState.ignoredTerms);
  if (keywordAnalysisState.candidateTermsOpen && keywordAnalysisState.blockTermsOpen) {
    keywordAnalysisState.candidateTermsOpen = false;
  }
}

function ensureAnalysisDateDefaults(scope, papers) {
  const scopeFrom = isoDateFromValue(scope && scope.date_from);
  const scopeTo = isoDateFromValue(scope && scope.date_to);
  const range = defaultDateRangeFromPapers(papers);
  if (!validISODate(keywordAnalysisState.dateFrom)) {
    keywordAnalysisState.dateFrom = scopeFrom || range.from || isoDateDaysAgo(30);
  }
  if (!validISODate(keywordAnalysisState.dateTo)) {
    keywordAnalysisState.dateTo = scopeTo || range.to || todayISODate();
  }
}

function defaultDateRangeFromPapers(papers) {
  const dates = (Array.isArray(papers) ? papers : []).map(function (paper) {
    return isoDateFromValue(paper && (paper.detected || paper.published));
  }).filter(Boolean).sort();
  if (!dates.length) return { from: "", to: "" };
  return { from: dates[0], to: dates[dates.length - 1] };
}

function isoDateFromValue(value) {
  const match = String(value || "").match(/^(\d{4}-\d{2}-\d{2})/);
  return match ? validISODate(match[1]) : "";
}

function todayISODate() {
  return isoDateFromDate(new Date());
}

function isoDateDaysAgo(days) {
  const today = new Date();
  return isoDateFromDate(new Date(today.getFullYear(), today.getMonth(), today.getDate() - Math.max(0, parseInt(days, 10) || 0)));
}

function isoDateFromDate(value) {
  return [
    value.getFullYear(),
    pad2(value.getMonth() + 1),
    pad2(value.getDate())
  ].join("-");
}

function wireAnalysisEvents() {
  const nav = document.getElementById("keyword-analysis-nav");
  const shell = document.getElementById("keyword-analysis");
  const controls = document.getElementById("analysis-controls");
  const tabs = document.getElementById("analysis-chart-tabs");
  const candidates = document.getElementById("analysis-candidates");
  const taxonomy = document.getElementById("analysis-taxonomy");
  const papers = document.getElementById("analysis-papers");

  if (nav) nav.addEventListener("click", toggleKeywordAnalysisView);
  setKeywordAnalysisNavState(false);

  if (shell) {
    shell.addEventListener("click", function (event) {
      const button = event.target.closest("[data-analysis-action]");
      if (!button) return;
      event.preventDefault();
      const action = button.getAttribute("data-analysis-action") || "";
      if (action === "run-keyword-analysis") {
        saveAnalysisState();
        requestKeywordAnalysis();
      }
    });
  }

  if (tabs) {
    tabs.addEventListener("click", function (event) {
      const button = event.target.closest("[data-chart-view]");
      if (!button) return;
      keywordAnalysisState.chartView = button.getAttribute("data-chart-view");
      saveAnalysisState();
      renderKeywordAnalysis();
    });
  }

  if (controls) {
    controls.addEventListener("input", function (event) {
      if (event.target.matches("[data-date-part]")) {
        handleAnalysisControlChange(event, false);
      }
    });
    controls.addEventListener("change", function (event) {
      handleAnalysisControlChange(event, true);
    });
    controls.addEventListener("click", function (event) {
      const stepperButton = event.target.closest("[data-stepper-action]");
      if (stepperButton) {
        event.preventDefault();
        applyAnalysisStepperAction(stepperButton.getAttribute("data-stepper-action") || "");
        saveAnalysisState();
        renderKeywordAnalysis();
        return;
      }
      const button = event.target.closest("[data-scope-action]");
      if (!button) return;
      event.preventDefault();
      const action = button.getAttribute("data-scope-action") || "";
      applyAnalysisControlAction(action);
      saveAnalysisState();
      renderKeywordAnalysis();
    });
  }

  if (candidates) {
    candidates.addEventListener("input", function (event) {
      if (event.target.id === "analysis-blocked-terms") {
        handleAnalysisCandidateFilterChange(event, false);
      }
    });
    candidates.addEventListener("change", function (event) {
      handleAnalysisCandidateFilterChange(event, true);
    });
    candidates.addEventListener("click", function (event) {
      const filterButton = event.target.closest("[data-candidate-filter-action]");
      if (filterButton) {
        event.preventDefault();
        applyCandidateFilterAction(filterButton.getAttribute("data-candidate-filter-action") || "");
        saveAnalysisState();
        renderKeywordAnalysis();
        return;
      }
      const button = event.target.closest("[data-action]");
      if (!button) return;
      const term = button.getAttribute("data-term") || "";
      const action = button.getAttribute("data-action");
      if (action === "accept-candidate") acceptCandidateTerm(term);
      if (action === "block-candidate") blockCandidateTerm(term);
      if (action === "add-search-term") addSearchTerm(term);
    });
  }

  if (taxonomy) {
    taxonomy.addEventListener("click", function (event) {
      const button = event.target.closest("[data-taxonomy-action]");
      if (!button) return;
      event.preventDefault();
      applyTaxonomyAction(button.getAttribute("data-taxonomy-action") || "");
      renderKeywordAnalysis();
    });
  }

  if (papers) {
    papers.addEventListener("click", function (event) {
      const button = event.target.closest("[data-paper-list-action]");
      if (!button) return;
      event.preventDefault();
      applyPaperListAction(button.getAttribute("data-paper-list-action") || "");
      saveAnalysisState();
      renderKeywordAnalysis();
    });
  }
}

function toggleKeywordAnalysisView() {
  const analysis = document.getElementById("keyword-analysis");
  if (analysis && !analysis.hidden) {
    showDashboardView();
    return;
  }
  showKeywordAnalysisView();
}

function showKeywordAnalysisView() {
  const dashboard = document.getElementById("dashboard-view");
  const analysis = document.getElementById("keyword-analysis");
  if (dashboard) dashboard.hidden = true;
  if (analysis) analysis.hidden = false;
  setKeywordAnalysisNavState(true);
  renderKeywordAnalysis();
  scrollToPageTop();
}

function showDashboardView() {
  const dashboard = document.getElementById("dashboard-view");
  const analysis = document.getElementById("keyword-analysis");
  if (analysis) analysis.hidden = true;
  if (dashboard) dashboard.hidden = false;
  setKeywordAnalysisNavState(false);
  scrollToPageTop();
}

function setKeywordAnalysisNavState(isAnalysisOpen) {
  const nav = document.getElementById("keyword-analysis-nav");
  if (!nav) return;
  nav.textContent = isAnalysisOpen ? "Back to Dashboard" : "Keyword Analysis";
  nav.setAttribute("aria-label", isAnalysisOpen ? "Back to dashboard" : "Open keyword analysis");
  nav.setAttribute("aria-expanded", isAnalysisOpen ? "true" : "false");
}

function scrollToPageTop() {
  if (typeof window !== "undefined" && typeof window.scrollTo === "function") {
    window.scrollTo(0, 0);
  }
}

function handleAnalysisControlChange(event, shouldRender) {
  const target = event.target;
  const controls = document.getElementById("analysis-controls");
  if (!target || !controls) return;

  const isDateControl = target.matches("[data-date-part]");
  if (target.matches("[data-date-part]")) {
    syncDateFromParts(target.getAttribute("data-date-boundary") || "");
  }
  if (target.matches("[data-journal-option]")) {
    keywordAnalysisState.selectedJournals = Array.from(controls.querySelectorAll("[data-journal-option]:checked")).map(function (checkbox) {
      return checkbox.value;
    });
    keywordAnalysisState.hasJournalSelection = true;
  }
  if (target.matches("[data-analysis-depth]")) {
    keywordAnalysisState.analysisDepth = normalizeAnalysisDepth(target.value);
  }

  saveAnalysisState();
  if (isDateControl) return;
  if (shouldRender !== false) renderKeywordAnalysis();
}

function handleAnalysisCandidateFilterChange(event, shouldRender) {
  const target = event.target;
  if (!target) return;

  if (target.id === "analysis-blocked-terms") {
    keywordAnalysisState.blockedTerms = parseEditableTerms(target.value);
  }
  if (target.matches("[data-phrase-length-option]")) {
    const candidates = document.getElementById("analysis-candidates");
    if (!candidates) return;
    keywordAnalysisState.selectedPhraseLengths = normalizePhraseLengths(Array.from(candidates.querySelectorAll("[data-phrase-length-option]:checked")).map(function (checkbox) {
      return checkbox.value;
    }));
  }

  saveAnalysisState();
  if (shouldRender !== false) renderKeywordAnalysis();
}

function applyAnalysisControlAction(action) {
  if (action === "select-all-journals") {
    keywordAnalysisState.selectedJournals = allAnalysisJournals();
    keywordAnalysisState.hasJournalSelection = true;
  }
  if (action === "clear-journals") {
    keywordAnalysisState.selectedJournals = [];
    keywordAnalysisState.hasJournalSelection = true;
  }
}

function applyAnalysisStepperAction(action) {
  if (action === "analysis-top-n-increment") {
    keywordAnalysisState.topN = clampTopJournalCount(coercePositiveInt(keywordAnalysisState.topN, 30) + 1);
    keywordAnalysisState.selectedJournals = topNAnalysisJournals();
    keywordAnalysisState.hasJournalSelection = true;
  }
  if (action === "analysis-top-n-decrement") {
    keywordAnalysisState.topN = clampTopJournalCount(coercePositiveInt(keywordAnalysisState.topN, 30) - 1);
    keywordAnalysisState.selectedJournals = topNAnalysisJournals();
    keywordAnalysisState.hasJournalSelection = true;
  }
  if (action === "analysis-sort-next") {
    keywordAnalysisState.sortMode = adjacentSortMode(1);
  }
  if (action === "analysis-sort-prev") {
    keywordAnalysisState.sortMode = adjacentSortMode(-1);
  }
}

function applyCandidateFilterAction(action) {
  if (action === "toggle-candidate-terms") {
    const nextOpen = !keywordAnalysisState.candidateTermsOpen;
    keywordAnalysisState.candidateTermsOpen = nextOpen;
    if (nextOpen) keywordAnalysisState.blockTermsOpen = false;
  }
  if (action === "toggle-block-terms") {
    const nextOpen = !keywordAnalysisState.blockTermsOpen;
    keywordAnalysisState.blockTermsOpen = nextOpen;
    if (nextOpen) keywordAnalysisState.candidateTermsOpen = false;
  }
}

function applyTaxonomyAction(action) {
  if (action === "toggle-taxonomy-editor") {
    keywordAnalysisState.taxonomyEditorOpen = !keywordAnalysisState.taxonomyEditorOpen;
  }
}

function applyPaperListAction(action) {
  if (action === "toggle-paper-list") {
    keywordAnalysisState.paperListOpen = !keywordAnalysisState.paperListOpen;
  }
}

function selectedAnalysisPapers() {
  return baseFilteredAnalysisPapers();
}

function baseFilteredAnalysisPapers() {
  const payload = keywordAnalysisState.payload || {};
  const papers = Array.isArray(payload.papers) ? payload.papers.slice() : [];
  const selectedJournalKeys = new Set(keywordAnalysisState.selectedJournals.map(normalizePhrase).filter(Boolean));
  const journalSelectionActive = Boolean(keywordAnalysisState.hasJournalSelection);

  const filtered = papers.filter(function (paper) {
    const detected = paperDate(paper);
    if (keywordAnalysisState.dateFrom && (!detected || detected < keywordAnalysisState.dateFrom)) return false;
    if (keywordAnalysisState.dateTo && (!detected || detected > keywordAnalysisState.dateTo)) return false;
    if (journalSelectionActive && (!selectedJournalKeys.size || !selectedJournalKeys.has(normalizePhrase(paper.journal)))) return false;
    return true;
  });

  filtered.sort(comparePapers);
  return filtered;
}

function allAnalysisPapers() {
  const payload = keywordAnalysisState.payload || {};
  return Array.isArray(payload.papers) ? payload.papers : [];
}

function allAnalysisJournals() {
  const catalogJournals = analysisJournalCatalog().map(function (entry) {
    return normalizeDisplayTerm(entry.journal);
  }).filter(Boolean);
  if (catalogJournals.length) return unique(catalogJournals);
  return fallbackAnalysisJournals();
}

function fallbackAnalysisJournals() {
  const scopedJournals = scopedAnalysisJournals();
  const paperJournals = allAnalysisPapers().map(function (paper) {
    return normalizeDisplayTerm(paper.journal);
  }).filter(Boolean);
  return unique(scopedJournals.concat(paperJournals)).sort(caseInsensitiveSort);
}

function analysisJournalCatalog() {
  const payload = keywordAnalysisState.payload || {};
  const catalog = Array.isArray(payload.journal_catalog) ? payload.journal_catalog : [];
  return catalog.map(function (entry) {
    if (typeof entry === "string") return { journal: entry };
    if (entry && typeof entry === "object") return { journal: normalizeDisplayTerm(entry.journal), impact_factor: Number(entry.impact_factor) };
    return { journal: "" };
  }).filter(function (entry) {
    return Boolean(entry.journal);
  });
}

function topNAnalysisJournals() {
  const journals = allAnalysisJournals();
  return journals.slice(0, clampTopJournalCount(keywordAnalysisState.topN));
}

function clampTopJournalCount(value) {
  const parsed = coercePositiveInt(value, 30);
  return Math.max(1, Math.min(50, parsed));
}

function scopedAnalysisJournals() {
  const payload = keywordAnalysisState.payload || {};
  const scope = payload.scope || {};
  return unique((Array.isArray(scope.selected_journals) ? scope.selected_journals : []).map(normalizeDisplayTerm).filter(Boolean));
}

function currentJournalScopeSignature() {
  return journalScopeSignature(scopedAnalysisJournals());
}

function journalScopeSignature(journals) {
  return unique((Array.isArray(journals) ? journals : []).map(normalizePhrase).filter(Boolean)).sort().join("|");
}

function adjacentSortMode(direction) {
  const keys = ANALYSIS_SORT_MODES.map(function (item) { return item[0]; });
  let index = keys.indexOf(keywordAnalysisState.sortMode);
  if (index < 0) index = 0;
  const nextIndex = (index + direction + keys.length) % keys.length;
  return keys[nextIndex];
}

function comparePapers(left, right) {
  if (keywordAnalysisState.sortMode === "impact_factor") {
    return compareNumber(paperImpact(right), paperImpact(left)) || compareString(paperDate(right), paperDate(left));
  }
  if (keywordAnalysisState.sortMode === "relevance") {
    return compareNumber(paperRelevance(right), paperRelevance(left)) || compareString(paperDate(right), paperDate(left));
  }
  return compareString(paperDate(right), paperDate(left)) || compareNumber(paperImpact(right), paperImpact(left));
}

function classifySelectedPapers(papers) {
  if (!papers.length) return [];

  const total = papers.length;
  const categories = sanitizeTaxonomy(keywordAnalysisState.customTaxonomy);
  const results = [];

  categories.forEach(function (category) {
    const aliases = unique([category.name].concat(category.aliases || []).map(normalizePhrase).filter(Boolean));
    const paperIds = [];

    papers.forEach(function (paper) {
      const text = analysisText(paper);
      if (aliases.some(function (alias) { return containsPhrase(text, alias); })) {
        paperIds.push(String(paper.id || ""));
      }
    });

    if (paperIds.length) {
      results.push({
        name: category.name,
        aliases: category.aliases || [],
        count: paperIds.length,
        percentage: Math.round((paperIds.length / total) * 1000) / 10,
        paperIds: paperIds
      });
    }
  });

  results.sort(function (left, right) {
    return compareNumber(right.count, left.count) || left.name.localeCompare(right.name);
  });
  return results;
}

function discoveredTerms(papers) {
  const minimumCount = 2;
  const blocked = new Set(keywordAnalysisState.blockedTerms.map(normalizePhrase).filter(Boolean));
  const ignored = new Set(keywordAnalysisState.ignoredTerms.map(normalizePhrase).filter(Boolean));
  const taxonomyPhrases = new Set();
  const counts = {};

  sanitizeTaxonomy(keywordAnalysisState.customTaxonomy).forEach(function (category) {
    [category.name].concat(category.aliases || []).forEach(function (alias) {
      const normalized = normalizePhrase(alias);
      if (normalized) taxonomyPhrases.add(normalized);
    });
  });

  papers.forEach(function (paper) {
    const paperId = String(paper.id || "");
    const paperTerms = candidatePhrases(analysisText(paper), blocked);
    paperTerms.forEach(function (term) {
      if (!isUsefulCandidateTerm(term, blocked, taxonomyPhrases, ignored)) return;
      if (!counts[term]) counts[term] = new Set();
      counts[term].add(paperId);
    });
  });

  return Object.keys(counts).map(function (term) {
    return { term: term, count: counts[term].size, paperIds: Array.from(counts[term]).sort() };
  }).filter(function (item) {
    return item.count >= minimumCount;
  }).sort(function (left, right) {
    return compareNumber(right.count, left.count) || compareNumber(left.term.split(" ").length, right.term.split(" ").length) || compareNumber(candidateTermScore(right.term), candidateTermScore(left.term)) || left.term.localeCompare(right.term);
  }).slice(0, MAX_CANDIDATE_TERMS);
}

function candidatePhrases(text, blocked) {
  let filtered = " " + normalizePhrase(text) + " ";
  const multiwordBlocked = Array.from(blocked).filter(function (term) {
    return term.indexOf(" ") >= 0;
  }).sort(function (left, right) {
    return right.length - left.length;
  });

  multiwordBlocked.forEach(function (phrase) {
    filtered = filtered.replace(new RegExp(" " + escapeRegExp(phrase) + " ", "g"), " ");
  });

  const singleBlocked = new Set(Array.from(blocked).filter(function (term) {
    return term.indexOf(" ") < 0;
  }));
  const tokens = (filtered.match(/[a-z0-9]+/g) || []).filter(function (token) {
    return !singleBlocked.has(token);
  });
  const phrases = [];

  normalizePhraseLengths(keywordAnalysisState.selectedPhraseLengths).forEach(function (width) {
    for (let index = 0; index <= tokens.length - width; index += 1) {
      const phrase = tokens.slice(index, index + width).join(" ");
      if (phrase && !blocked.has(phrase)) phrases.push(phrase);
    }
  });

  return unique(phrases);
}

function isUsefulCandidateTerm(term, blocked, taxonomyPhrases, ignored) {
  if (!term || blocked.has(term) || taxonomyPhrases.has(term) || ignored.has(term)) return false;
  const tokens = term.split(" ").filter(Boolean);
  if (!normalizePhraseLengths(keywordAnalysisState.selectedPhraseLengths).includes(tokens.length)) return false;
  if (new Set(tokens).size < tokens.length) return false;
  if (tokens.some(function (token) { return token.length < 2 && token !== "li"; })) return false;
  if (tokens.some(isPublicationMetadataToken)) return false;
  if (!tokens.some(function (token) { return DOMAIN_ANCHOR_TERMS.has(token); })) return false;
  if (tokens.every(function (token) { return BROAD_CANDIDATE_TOKENS.has(token); })) return false;
  if (tokens.every(function (token) { return LOW_VALUE_CANDIDATE_TOKENS.has(token); })) return false;
  return true;
}

function isPublicationMetadataToken(token) {
  if (PUBLICATION_METADATA_TOKENS.has(token)) return true;
  if (/^\d{4}$/.test(token)) {
    const year = parseInt(token, 10);
    return year >= 1900 && year <= 2100;
  }
  return false;
}

function candidateTermScore(term) {
  const tokens = String(term || "").split(" ").filter(Boolean);
  const anchorCount = tokens.filter(function (token) { return DOMAIN_ANCHOR_TERMS.has(token); }).length;
  const lowValueCount = tokens.filter(function (token) { return LOW_VALUE_CANDIDATE_TOKENS.has(token); }).length;
  return (anchorCount * 4) + tokens.length - lowValueCount;
}

function acceptCandidateTerm(term) {
  const clean = normalizeDisplayTerm(term);
  const normalized = normalizePhrase(clean);
  if (!clean || !normalized) return;

  const existing = sanitizeTaxonomy(keywordAnalysisState.customTaxonomy).some(function (category) {
    return [category.name].concat(category.aliases || []).map(normalizePhrase).includes(normalized);
  });
  if (!existing) {
    keywordAnalysisState.customTaxonomy.push({ name: clean, aliases: [clean] });
  }
  keywordAnalysisState.ignoredTerms = keywordAnalysisState.ignoredTerms.filter(function (item) {
    return normalizePhrase(item) !== normalized;
  });
  saveAnalysisState();
  renderKeywordAnalysis();
}

function blockCandidateTerm(term) {
  const clean = normalizeDisplayTerm(term);
  const normalized = normalizePhrase(clean);
  if (!clean || !normalized) return;
  const blocked = new Set(keywordAnalysisState.blockedTerms.map(normalizePhrase));
  if (!blocked.has(normalized)) keywordAnalysisState.blockedTerms.push(clean);
  saveAnalysisState();
  renderKeywordAnalysis();
}

function addSearchTerm(term) {
  const clean = normalizeDisplayTerm(term);
  if (!clean) return;
  const bridge = typeof window !== "undefined" && window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.paperMonitor;
  if (bridge) {
    bridge.postMessage({ type: "addSearchTerm", term: clean });
    return;
  }
  if (typeof navigator !== "undefined" && navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
    try {
      const writeResult = navigator.clipboard.writeText(clean);
      if (writeResult && typeof writeResult.catch === "function") {
        writeResult.catch(function () {
          showCopyFallback(clean);
        });
      }
      return;
    } catch (error) {
      showCopyFallback(clean);
      return;
    }
  }
  showCopyFallback(clean);
}

function requestKeywordAnalysis() {
  const datesValid = syncAnalysisDateControlsBeforeRequest();
  if (!datesValid) {
    keywordAnalysisState.analysisStatus = "error";
    keywordAnalysisState.analysisError = "Fix invalid date range before analysis.";
    updateAnalysisHeaderAction();
    updateAnalysisStatusMessage();
    return;
  }

  const request = {
    type: "analyzeKeywords",
    date_from: keywordAnalysisState.dateFrom || "",
    date_to: keywordAnalysisState.dateTo || "",
    sort_mode: keywordAnalysisState.sortMode || "time",
    analysis_depth: normalizeAnalysisDepth(keywordAnalysisState.analysisDepth),
    top_n: clampTopJournalCount(keywordAnalysisState.topN),
    journals: keywordAnalysisState.hasJournalSelection ? keywordAnalysisState.selectedJournals.slice() : allAnalysisJournals()
  };

  if (!request.date_from || !request.date_to) {
    keywordAnalysisState.analysisStatus = "error";
    keywordAnalysisState.analysisError = "Select a date range before analysis.";
    renderKeywordAnalysis();
    return;
  }

  const bridge = typeof window !== "undefined" && window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.paperMonitor;
  if (!bridge) {
    keywordAnalysisState.analysisStatus = "error";
    keywordAnalysisState.analysisError = "Open Paper Monitor to run Crossref analysis.";
    renderKeywordAnalysis();
    return;
  }

  keywordAnalysisState.analysisStatus = "loading";
  keywordAnalysisState.analysisError = "";
  renderKeywordAnalysis();
  startAnalysisProgress();
  bridge.postMessage(request);
}

function syncAnalysisDateControlsBeforeRequest() {
  const fromResult = syncDateBoundaryFromControls("from");
  const toResult = syncDateBoundaryFromControls("to");
  return fromResult.ok !== false && toResult.ok !== false;
}

function syncDateBoundaryFromControls(boundary) {
  const cleanBoundary = boundary === "to" ? "to" : "from";
  if (!dateControlExists(cleanBoundary)) return { ok: true };
  return syncDateFromParts(cleanBoundary);
}

function dateControlExists(boundary) {
  return Boolean(
    document.getElementById("analysis-date-" + boundary + "-year") ||
    document.getElementById("analysis-date-" + boundary + "-month") ||
    document.getElementById("analysis-date-" + boundary + "-day")
  );
}

function receiveKeywordAnalysisPayload(message) {
  const payload = message && message.payload && typeof message.payload === "object" ? message.payload : message;
  if (!payload || typeof payload !== "object") {
    finishAnalysisProgress(false);
    keywordAnalysisState.analysisStatus = "error";
    keywordAnalysisState.analysisError = "Keyword analysis returned no data.";
    renderKeywordAnalysis();
    return;
  }
  if (payload.error) {
    finishAnalysisProgress(false);
    keywordAnalysisState.analysisStatus = "error";
    keywordAnalysisState.analysisError = String(payload.error || "Keyword analysis failed.");
    renderKeywordAnalysis();
    return;
  }

  finishAnalysisProgress(true);
  keywordAnalysisState.payload = payload;
  syncAnalysisStateFromPayloadScope(payload.scope || {});
  keywordAnalysisState.analysisStatus = "idle";
  keywordAnalysisState.analysisError = "";
  saveAnalysisState();
  renderKeywordAnalysis();
}

function syncAnalysisStateFromPayloadScope(scope) {
  if (!scope || typeof scope !== "object") return;
  if (typeof scope.date_from === "string") keywordAnalysisState.dateFrom = scope.date_from;
  if (typeof scope.date_to === "string") keywordAnalysisState.dateTo = scope.date_to;
  if (typeof scope.sort_mode === "string" && ["time", "impact_factor", "relevance"].includes(scope.sort_mode)) {
    keywordAnalysisState.sortMode = scope.sort_mode;
  }
  if (typeof scope.analysis_depth === "string") {
    keywordAnalysisState.analysisDepth = normalizeAnalysisDepth(scope.analysis_depth);
  }
  keywordAnalysisState.topN = clampTopJournalCount(scope.top_n || keywordAnalysisState.topN);
  if (Array.isArray(scope.selected_journals)) {
    keywordAnalysisState.selectedJournals = unique(scope.selected_journals.map(normalizeDisplayTerm).filter(Boolean));
    keywordAnalysisState.hasJournalSelection = true;
  }
}

function showCopyFallback(term) {
  const clean = normalizeDisplayTerm(term);
  if (!clean) return;
  if (typeof document === "undefined") return;
  const candidates = document.getElementById("analysis-candidates");
  if (!candidates) return;

  let fallback = document.getElementById("analysis-copy-fallback");
  if (!fallback) {
    fallback = document.createElement("div");
    fallback.id = "analysis-copy-fallback";
    fallback.className = "analysis-note";
    if (candidates.firstChild) {
      candidates.insertBefore(fallback, candidates.firstChild);
    } else {
      candidates.appendChild(fallback);
    }
  }
  fallback.textContent = "Copy this search term: " + clean;
}

function renderKeywordAnalysis() {
  const shell = document.getElementById("keyword-analysis");
  const panel = document.getElementById("analysis-panel");
  const controls = document.getElementById("analysis-controls");
  const tabs = document.getElementById("analysis-chart-tabs");
  const chart = document.getElementById("analysis-chart");
  const candidates = document.getElementById("analysis-candidates");
  const taxonomy = document.getElementById("analysis-taxonomy");
  const paperList = document.getElementById("analysis-papers");
  if (!shell || !panel || !controls || !tabs || !chart || !candidates || !taxonomy || !paperList) return;

  const papers = selectedAnalysisPapers();
  const categories = classifySelectedPapers(papers);
  const terms = discoveredTerms(papers);

  shell.setAttribute("data-chart-view", keywordAnalysisState.chartView);
  panel.hidden = false;
  updateAnalysisHeaderAction();

  controls.innerHTML = renderAnalysisControls();
  tabs.innerHTML = renderChartTabs();
  if (keywordAnalysisState.chartView === "donut") chart.innerHTML = renderDonut(categories);
  else if (keywordAnalysisState.chartView === "trend") chart.innerHTML = renderTrend(papers, categories);
  else if (keywordAnalysisState.chartView === "table") chart.innerHTML = renderTable(categories);
  else chart.innerHTML = renderBars(categories, papers.length);
  candidates.innerHTML = renderCandidateTerms(terms);
  taxonomy.innerHTML = renderTaxonomyEditor(categories);
  paperList.innerHTML = renderAnalysisPaperList(papers);
}

function renderAnalysisControls() {
  const journals = allAnalysisJournals();
  const selectedJournalKeys = new Set(keywordAnalysisState.selectedJournals.map(normalizePhrase));
  const selectedJournalCount = journals.filter(function (journal) {
    return selectedJournalKeys.has(normalizePhrase(journal));
  }).length;

  return [
    '<div class="control-group">',
    '<h3>Scope</h3>',
    renderDateRangeControl("from", "Date from", keywordAnalysisState.dateFrom),
    renderDateRangeControl("to", "Date to", keywordAnalysisState.dateTo),
    '<div class="control-row"><label for="analysis-depth">Analysis Depth</label>' + renderAnalysisDepthControl() + '</div>',
    '<div class="control-row"><label>Sort</label>' + renderSortStepper() + '</div>',
    '<div class="control-row"><label>Top Journals</label>' + renderTopNStepper() + '</div>',
    renderAnalysisStatus(),
    '</div>',
    '<div class="control-group">',
    '<h3>Journals</h3>',
    '<div class="control-toolbar"><button type="button" class="mini-button" data-scope-action="select-all-journals">Select all</button><button type="button" class="mini-button" data-scope-action="clear-journals">Clear</button><span class="meta">' + escapeHtml(selectedJournalCount + " / " + journals.length + " selected") + '</span></div>',
    '<div class="checkbox-list analysis-journal-list">' + journals.map(function (journal) {
      return '<label class="checkbox-option"><input type="checkbox" data-journal-option value="' + escapeHtml(journal) + '"' + checkedAttribute(selectedJournalKeys.has(normalizePhrase(journal))) + '> <span>' + escapeHtml(journal) + '</span></label>';
    }).join("") + '</div>',
    '</div>'
  ].join("");
}

function updateAnalysisHeaderAction() {
  const button = document.getElementById("analysis-run-button");
  if (!button) return;
  const loading = keywordAnalysisState.analysisStatus === "loading";
  button.textContent = loading ? "Analyzing..." : "Analyze";
  button.disabled = loading;
  button.setAttribute("aria-busy", loading ? "true" : "false");
}

function startAnalysisProgress() {
  clearAnalysisProgressTimer();
  setAnalysisProgress(8, "Preparing Crossref search");
  if (typeof window === "undefined" || typeof window.setInterval !== "function") return;
  keywordAnalysisProgressTimer = window.setInterval(function () {
    const current = Number(keywordAnalysisState.analysisProgress || 8);
    if (current >= 88) return;
    const next = Math.min(88, current + (current < 42 ? 5 : current < 72 ? 3 : 1.5));
    const label = next < 42
      ? "Searching Crossref journal batches"
      : next < 72
        ? "Paging through Crossref results"
        : "Matching papers and preparing statistics";
    setAnalysisProgress(next, label);
  }, 1200);
}

function setAnalysisProgress(percent, label) {
  const progress = document.getElementById("analysis-progress");
  const bar = document.getElementById("analysis-progress-bar");
  const progressLabel = document.getElementById("analysis-progress-label");
  const safePercent = Math.max(0, Math.min(100, Number(percent) || 0));
  keywordAnalysisState.analysisProgress = safePercent;
  if (progress) {
    progress.hidden = false;
    progress.setAttribute("aria-valuenow", String(Math.round(safePercent)));
  }
  if (bar) {
    bar.style.width = safePercent.toFixed(safePercent % 1 ? 1 : 0) + "%";
  }
  if (progressLabel) {
    progressLabel.hidden = false;
    progressLabel.textContent = label || "";
  }
}

function finishAnalysisProgress(success) {
  clearAnalysisProgressTimer();
  if (success) {
    setAnalysisProgress(100, "Analysis complete");
    if (typeof window !== "undefined" && typeof window.setTimeout === "function") {
      window.setTimeout(hideAnalysisProgress, 700);
    }
    return;
  }
  hideAnalysisProgress();
}

function hideAnalysisProgress() {
  const progress = document.getElementById("analysis-progress");
  const bar = document.getElementById("analysis-progress-bar");
  const progressLabel = document.getElementById("analysis-progress-label");
  keywordAnalysisState.analysisProgress = 0;
  if (progress) {
    progress.hidden = true;
    progress.setAttribute("aria-valuenow", "0");
  }
  if (bar) bar.style.width = "0%";
  if (progressLabel) {
    progressLabel.hidden = true;
    progressLabel.textContent = "";
  }
}

function clearAnalysisProgressTimer() {
  if (!keywordAnalysisProgressTimer) return;
  if (typeof window !== "undefined" && typeof window.clearInterval === "function") {
    window.clearInterval(keywordAnalysisProgressTimer);
  }
  keywordAnalysisProgressTimer = null;
}

function updateAnalysisStatusMessage() {
  const status = document.getElementById("analysis-status");
  if (status) status.outerHTML = renderAnalysisStatus();
}

function renderDateRangeControl(boundary, label, value) {
  const cleanBoundary = boundary === "to" ? "to" : "from";
  const parts = datePartsFromISO(value);
  return [
    '<div id="analysis-date-' + cleanBoundary + '-control" class="control-row date-control">',
    '<label for="analysis-date-' + cleanBoundary + '-year">' + escapeHtml(label) + '</label>',
    '<div class="date-parts">',
    renderDatePartInput(cleanBoundary, "year", "Year", 4, parts.year, yearOptions()),
    renderDatePartInput(cleanBoundary, "month", "Month", 2, parts.month, numericOptions(12)),
    renderDatePartInput(cleanBoundary, "day", "Day", 2, parts.day, numericOptions(31)),
    '</div>',
    '<div id="analysis-date-' + cleanBoundary + '-error" class="date-error" role="alert" hidden></div>',
    '</div>'
  ].join("");
}

function renderDatePartInput(boundary, part, label, maxLength, selectedValue, options) {
  const id = "analysis-date-" + boundary + "-" + part;
  const listId = id + "-options";
  return [
    '<label class="date-part" for="' + escapeHtml(id) + '"><span>' + escapeHtml(label) + '</span>',
    '<input id="' + escapeHtml(id) + '" type="text" inputmode="numeric" maxlength="' + escapeHtml(maxLength) + '" autocomplete="off" list="' + escapeHtml(listId) + '" data-date-boundary="' + escapeHtml(boundary) + '" data-date-part="' + escapeHtml(part) + '" aria-describedby="analysis-date-' + escapeHtml(boundary) + '-error" value="' + escapeHtml(selectedValue) + '">',
    '<datalist id="' + escapeHtml(listId) + '">' + options.map(function (option) {
      return '<option value="' + escapeHtml(option) + '"></option>';
    }).join("") + '</datalist>',
    '</label>'
  ].join("");
}

function yearOptions() {
  const currentYear = new Date().getFullYear();
  const options = [];
  for (let year = currentYear + 1; year >= currentYear - 10; year -= 1) {
    options.push(String(year));
  }
  return options;
}

function numericOptions(max) {
  const options = [];
  for (let value = 1; value <= max; value += 1) {
    options.push(pad2(value));
  }
  return options;
}

function datePartsFromISO(value) {
  const clean = validISODate(value);
  if (!clean) return { year: "", month: "", day: "" };
  const parts = clean.split("-");
  return { year: parts[0], month: parts[1], day: parts[2] };
}

function syncDateFromParts(boundary) {
  const result = resolveDateBoundaryFromControls(boundary);
  setDateState(result.boundary, result.ok ? result.value : "");
  setDateValidationError(result.boundary, result.ok ? "" : result.message);
  if (result.ok) normalizeDateControlValues(result.boundary, result.parts);
  return result;
}

function resolveDateBoundaryFromControls(boundary) {
  const cleanBoundary = boundary === "to" ? "to" : "from";
  const year = numericFieldValue("analysis-date-" + cleanBoundary + "-year", 4);
  const monthInput = numericFieldValue("analysis-date-" + cleanBoundary + "-month", 2);
  const dayInput = numericFieldValue("analysis-date-" + cleanBoundary + "-day", 2);
  const emptyParts = { year: year, month: monthInput, day: dayInput };

  if (!year && !monthInput && !dayInput) {
    return { ok: true, empty: true, boundary: cleanBoundary, value: "", parts: emptyParts };
  }
  if (!year) {
    return { ok: false, boundary: cleanBoundary, value: "", parts: emptyParts, message: "Select year before month or day." };
  }
  if (year.length !== 4 || parseInt(year, 10) < 1000) {
    return { ok: false, boundary: cleanBoundary, value: "", parts: emptyParts, message: "Year must use four digits." };
  }

  let month = "";
  if (monthInput) {
    const monthNumber = parseInt(monthInput, 10);
    if (monthNumber < 1 || monthNumber > 12) {
      return { ok: false, boundary: cleanBoundary, value: "", parts: emptyParts, message: "Month must be between 01 and 12." };
    }
    month = pad2(monthNumber);
  }
  if (dayInput && !month) {
    return { ok: false, boundary: cleanBoundary, value: "", parts: emptyParts, message: "Select month before day." };
  }

  let day = "";
  if (dayInput) {
    const dayNumber = parseInt(dayInput, 10);
    const maxDay = daysInMonth(parseInt(year, 10), parseInt(month, 10));
    if (dayNumber < 1 || dayNumber > maxDay) {
      return { ok: false, boundary: cleanBoundary, value: "", parts: { year: year, month: month, day: dayInput }, message: "Invalid date for selected month." };
    }
    day = pad2(dayNumber);
  }

  const resolvedMonth = month || (cleanBoundary === "to" ? "12" : "01");
  const resolvedDay = day || (cleanBoundary === "to" ? pad2(daysInMonth(parseInt(year, 10), parseInt(resolvedMonth, 10))) : "01");
  return {
    ok: true,
    boundary: cleanBoundary,
    value: year + "-" + resolvedMonth + "-" + resolvedDay,
    parts: { year: year, month: month, day: day }
  };
}

function normalizeDateControlValues(boundary, parts) {
  setElementValue("analysis-date-" + boundary + "-year", parts.year || "");
  setElementValue("analysis-date-" + boundary + "-month", parts.month || "");
  setElementValue("analysis-date-" + boundary + "-day", parts.day || "");
}

function setDateValidationError(boundary, message) {
  const cleanBoundary = boundary === "to" ? "to" : "from";
  const control = document.getElementById("analysis-date-" + cleanBoundary + "-control");
  const error = document.getElementById("analysis-date-" + cleanBoundary + "-error");
  const hasError = Boolean(message);
  if (control && control.classList) {
    if (hasError) control.classList.add("has-error");
    else control.classList.remove("has-error");
  }
  if (error) {
    error.textContent = message || "";
    error.hidden = !hasError;
    if (hasError) error.removeAttribute("hidden");
    else error.setAttribute("hidden", "");
  }
  ["year", "month", "day"].forEach(function (part) {
    const element = document.getElementById("analysis-date-" + cleanBoundary + "-" + part);
    if (!element) return;
    if (hasError) element.setAttribute("aria-invalid", "true");
    else element.removeAttribute("aria-invalid");
  });
}

function daysInMonth(year, month) {
  return new Date(year, month, 0).getDate();
}

function setDateState(boundary, value) {
  if (boundary === "to") keywordAnalysisState.dateTo = value || "";
  else keywordAnalysisState.dateFrom = value || "";
}

function numericFieldValue(id, maxLength) {
  const element = document.getElementById(id);
  if (!element) return "";
  const clean = String(element.value || "").replace(/\D/g, "").slice(0, maxLength);
  if (element.value !== clean) element.value = clean;
  return clean;
}

function setElementValue(id, value) {
  const element = document.getElementById(id);
  if (element) element.value = value || "";
}

function validISODate(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return "";
  const year = parseInt(match[1], 10);
  const month = parseInt(match[2], 10);
  const day = parseInt(match[3], 10);
  const dateValue = new Date(year, month - 1, day);
  if (dateValue.getFullYear() !== year || dateValue.getMonth() !== month - 1 || dateValue.getDate() !== day) return "";
  return match[1] + "-" + match[2] + "-" + match[3];
}

function pad2(value) {
  return String(value).padStart(2, "0");
}

function renderAnalysisStatus() {
  if (keywordAnalysisState.analysisStatus === "loading") {
    return '<p id="analysis-status" class="analysis-note">Running Crossref analysis for the selected date range.</p>';
  }
  if (keywordAnalysisState.analysisError) {
    return '<p id="analysis-status" class="analysis-note">' + escapeHtml(keywordAnalysisState.analysisError) + '</p>';
  }
  const scope = keywordAnalysisState.payload && keywordAnalysisState.payload.scope ? keywordAnalysisState.payload.scope : {};
  if (scope.source === "crossref") {
    const fetched = coerceNonNegativeInt(keywordAnalysisState.payload.fetched);
    const matched = coerceNonNegativeInt(keywordAnalysisState.payload.matched);
    return '<p id="analysis-status" class="analysis-note">Crossref analysis: ' + escapeHtml(fetched) + ' fetched · ' + escapeHtml(matched) + ' matched.</p>';
  }
  return '<p id="analysis-status" class="analysis-note" hidden></p>';
}

function renderAnalysisDepthControl() {
  const selected = normalizeAnalysisDepth(keywordAnalysisState.analysisDepth);
  return '<select id="analysis-depth" data-analysis-depth>' +
    '<option value="fast"' + (selected === "fast" ? " selected" : "") + '>Fast</option>' +
    '<option value="exhaustive"' + (selected === "exhaustive" ? " selected" : "") + '>Exhaustive</option>' +
    '</select>';
}

function normalizeAnalysisDepth(value) {
  return String(value || "").toLowerCase() === "exhaustive" ? "exhaustive" : "fast";
}

function renderSortStepper() {
  return '<div class="stepper-control" role="group" aria-label="Sort">' +
    '<button type="button" class="stepper-button" data-stepper-action="analysis-sort-prev" aria-label="Previous sort mode">&lt;</button>' +
    '<div id="analysis-sort-mode" class="stepper-value" role="status">' + escapeHtml(currentSortLabel()) + '</div>' +
    '<button type="button" class="stepper-button" data-stepper-action="analysis-sort-next" aria-label="Next sort mode">&gt;</button>' +
    '</div>';
}

function renderTopNStepper() {
  return '<div class="stepper-control" role="group" aria-label="Top Journals">' +
    '<button type="button" class="stepper-button" data-stepper-action="analysis-top-n-decrement" aria-label="Decrease top journals">-</button>' +
    '<div id="analysis-top-n" class="stepper-value" role="status">' + escapeHtml(clampTopJournalCount(keywordAnalysisState.topN)) + '</div>' +
    '<button type="button" class="stepper-button" data-stepper-action="analysis-top-n-increment" aria-label="Increase top journals">+</button>' +
    '</div>';
}

function currentSortLabel() {
  const match = ANALYSIS_SORT_MODES.find(function (item) {
    return item[0] === keywordAnalysisState.sortMode;
  });
  return match ? match[1] : "Time";
}

function renderChartTabs() {
  return [
    ["bars", "Bars"],
    ["donut", "Donut"],
    ["trend", "Trend"],
    ["table", "Table"]
  ].map(function (tab) {
    const pressed = keywordAnalysisState.chartView === tab[0] ? "true" : "false";
    return '<button type="button" data-chart-view="' + escapeHtml(tab[0]) + '" aria-pressed="' + pressed + '">' + escapeHtml(tab[1]) + '</button>';
  }).join("");
}

function renderBars(categories, totalPapers) {
  const total = Math.max(0, parseInt(totalPapers, 10) || 0);
  const heading = '<div class="chart-heading"><h3>Category Share</h3><span class="category-share-total">Total papers: ' + escapeHtml(total) + '</span></div>';
  if (!categories.length) return '<div class="control-group">' + heading + '<p class="analysis-note">No taxonomy matches in the selected papers.</p></div>';
  return '<div class="control-group">' + heading + categories.map(function (category) {
    const percent = Math.max(0, Math.min(100, Number(category.percentage || 0)));
    const count = Math.max(0, parseInt(category.count, 10) || 0);
    return '<div class="bar-row"><div>' + escapeHtml(category.name) + '</div><div class="bar-track"><div class="bar-fill" style="width: ' + percent + '%"></div></div><div>' + escapeHtml(percent.toFixed(1) + '% · ' + count + ' papers') + '</div></div>';
  }).join("") + '</div>';
}

function renderDonut(categories) {
  if (!categories.length) return '<p class="analysis-note">No taxonomy matches in the selected papers.</p>';
  return '<div class="control-group"><h3>Share Summary</h3><table class="analysis-table"><thead><tr><th>Category</th><th>Share</th><th>Papers</th></tr></thead><tbody>' + categories.map(function (category) {
    return '<tr><td>' + escapeHtml(category.name) + '</td><td>' + escapeHtml(Number(category.percentage || 0).toFixed(1)) + '%</td><td>' + escapeHtml(category.count) + '</td></tr>';
  }).join("") + '</tbody></table></div>';
}

function renderTrend(papers, categories) {
  if (!papers.length) return '<p class="analysis-note">No papers match the current filters.</p>';
  const categoryByPaper = {};
  categories.forEach(function (category) {
    (category.paperIds || category.paper_ids || []).forEach(function (paperId) {
      if (!categoryByPaper[paperId]) categoryByPaper[paperId] = [];
      categoryByPaper[paperId].push(category.name);
    });
  });

  const rows = {};
  papers.forEach(function (paper) {
    const date = paperDate(paper) || "Unknown date";
    const paperId = String(paper.id || "");
    if (!rows[date]) rows[date] = { count: 0, categories: {} };
    rows[date].count += 1;
    (categoryByPaper[paperId] || []).forEach(function (name) {
      rows[date].categories[name] = (rows[date].categories[name] || 0) + 1;
    });
  });

  return '<div class="control-group"><h3>Trend by Date</h3><table class="analysis-table"><thead><tr><th>Date</th><th>Papers</th><th>Top categories</th></tr></thead><tbody>' + Object.keys(rows).sort().reverse().map(function (date) {
    const topCategories = Object.keys(rows[date].categories).sort(function (left, right) {
      return compareNumber(rows[date].categories[right], rows[date].categories[left]) || left.localeCompare(right);
    }).slice(0, 4).map(function (name) {
      return name + " (" + rows[date].categories[name] + ")";
    }).join(", ");
    return '<tr><td>' + escapeHtml(date) + '</td><td>' + escapeHtml(rows[date].count) + '</td><td>' + escapeHtml(topCategories || "No taxonomy match") + '</td></tr>';
  }).join("") + '</tbody></table></div>';
}

function renderTable(categories) {
  if (!categories.length) return '<p class="analysis-note">No taxonomy matches in the selected papers.</p>';
  return '<div class="control-group"><h3>Category Table</h3><table class="analysis-table"><thead><tr><th>Category</th><th>Papers</th><th>Share</th><th>Aliases</th></tr></thead><tbody>' + categories.map(function (category) {
    return '<tr><td>' + escapeHtml(category.name) + '</td><td>' + escapeHtml(category.count) + '</td><td>' + escapeHtml(Number(category.percentage || 0).toFixed(1)) + '%</td><td>' + escapeHtml((category.aliases || []).join(", ")) + '</td></tr>';
  }).join("") + '</tbody></table></div>';
}

function renderCandidateTerms(terms) {
  const header = renderCandidateTermsHeader();
  const termsOpen = keywordAnalysisState.candidateTermsOpen && !keywordAnalysisState.blockTermsOpen;
  if (!termsOpen) {
    return '<section class="control-group">' + header + '</section>';
  }
  if (!terms.length) {
    return '<section class="control-group">' + header + '<p class="analysis-note">No repeated candidate terms meet the current threshold.</p></section>';
  }

  return '<section class="control-group">' + header + terms.map(function (term) {
    const displayTerm = normalizeDisplayTerm(term.term);
    return '<div class="candidate-row"><div><strong>' + escapeHtml(displayTerm) + '</strong><div class="meta">' + escapeHtml(term.count) + ' papers</div></div><div class="candidate-actions"><button type="button" class="mini-button" data-action="accept-candidate" data-term="' + escapeHtml(displayTerm) + '">Accept</button><button type="button" class="mini-button" data-action="block-candidate" data-term="' + escapeHtml(displayTerm) + '">Block</button><button type="button" class="mini-button" data-action="add-search-term" data-term="' + escapeHtml(displayTerm) + '">Add to Search Terms</button></div></div>';
  }).join("") + '</section>';
}

function renderCandidateTermsHeader() {
  const phraseLengthKeys = new Set(normalizePhraseLengths(keywordAnalysisState.selectedPhraseLengths).map(String));
  const phraseLengthControls = ALLOWED_CANDIDATE_PHRASE_LENGTHS.map(function (length) {
    return '<label class="checkbox-option"><input type="checkbox" data-phrase-length-option value="' + escapeHtml(length) + '"' + checkedAttribute(phraseLengthKeys.has(String(length))) + '> <span>' + escapeHtml(length) + '</span></label>';
  }).join("");
  const expanded = keywordAnalysisState.blockTermsOpen ? "true" : "false";
  const termsOpen = keywordAnalysisState.candidateTermsOpen && !keywordAnalysisState.blockTermsOpen;
  const candidateExpanded = termsOpen ? "true" : "false";
  const candidateToggleLabel = termsOpen ? "Hide Terms" : "Show Terms";
  return [
    '<div class="candidate-header">',
    '<h3>Candidate Terms</h3>',
    '<div class="candidate-filter-toolbar">',
    '<span class="candidate-filter-label">Phrase Length</span>',
    '<div class="inline-options">' + phraseLengthControls + '</div>',
    '<button type="button" class="mini-button" data-candidate-filter-action="toggle-candidate-terms" aria-expanded="' + candidateExpanded + '">' + candidateToggleLabel + '</button>',
    '<button type="button" class="mini-button" data-candidate-filter-action="toggle-block-terms" aria-expanded="' + expanded + '">Block Terms</button>',
    '</div>',
    '</div>',
    renderBlockTermsEditor()
  ].join("");
}

function renderBlockTermsEditor() {
  if (!keywordAnalysisState.blockTermsOpen) return "";
  return '<div class="block-terms-panel"><label for="analysis-blocked-terms">Blocked terms</label><textarea id="analysis-blocked-terms">' + escapeHtml(keywordAnalysisState.blockedTerms.join("\n")) + '</textarea></div>';
}

function renderTaxonomyEditor(categories) {
  const taxonomy = sanitizeTaxonomy(keywordAnalysisState.customTaxonomy);
  const categoryNames = new Set(categories.map(function (category) {
    return normalizePhrase(category.name);
  }));
  const expanded = keywordAnalysisState.taxonomyEditorOpen ? "true" : "false";
  const toggleLabel = keywordAnalysisState.taxonomyEditorOpen ? "Hide Editor" : "Show Editor";

  const header = [
    '<div class="candidate-header">',
    '<h3>Taxonomy Editor</h3>',
    '<button type="button" class="mini-button" data-taxonomy-action="toggle-taxonomy-editor" aria-expanded="' + expanded + '">' + toggleLabel + '</button>',
    '</div>'
  ].join("");

  if (!keywordAnalysisState.taxonomyEditorOpen) {
    return '<section class="control-group">' + header + '</section>';
  }

  return [
    '<section class="control-group">',
    header,
    '<p class="analysis-note">Accepted candidate terms are saved locally and included in classification.</p>',
    '<div class="taxonomy-list">',
    taxonomy.map(function (category) {
      const active = categoryNames.has(normalizePhrase(category.name)) ? " · active" : "";
      const aliases = (category.aliases || []).length ? " · " + category.aliases.join(", ") : "";
      return '<span class="term-chip">' + escapeHtml(category.name + active + aliases) + '</span>';
    }).join(""),
    '</div>',
    '</section>'
  ].join("");
}

function renderAnalysisPaperList(papers) {
  const safePapers = Array.isArray(papers) ? papers : [];
  const expanded = keywordAnalysisState.paperListOpen ? "true" : "false";
  const toggleLabel = keywordAnalysisState.paperListOpen ? "Hide Papers" : "Show Papers";
  const header = [
    '<div class="candidate-header">',
    '<h3>Analysis Papers</h3>',
    '<div class="candidate-filter-toolbar">',
    '<span class="meta">' + escapeHtml(safePapers.length + " papers") + '</span>',
    '<button type="button" class="mini-button" data-paper-list-action="toggle-paper-list" aria-expanded="' + expanded + '">' + toggleLabel + '</button>',
    '</div>',
    '</div>'
  ].join("");

  if (!keywordAnalysisState.paperListOpen) {
    return '<section class="control-group">' + header + '</section>';
  }
  if (!safePapers.length) {
    return '<section class="control-group">' + header + '<p class="analysis-note">No papers match the current filters.</p></section>';
  }

  return [
    '<section class="control-group">',
    header,
    '<table class="analysis-paper-table">',
    '<thead><tr><th class="analysis-paper-title">Title</th><th class="analysis-paper-doi">DOI</th><th class="analysis-paper-journal">Journal</th><th class="analysis-paper-authors">Authors</th></tr></thead>',
    '<tbody>',
    safePapers.map(renderAnalysisPaperRow).join(""),
    '</tbody></table>',
    '</section>'
  ].join("");
}

function renderAnalysisPaperRow(paper) {
  const title = normalizeDisplayTerm(paper && paper.title) || "Untitled";
  const url = normalizeDisplayTerm(paper && paper.url);
  const doi = normalizeDisplayTerm(paper && paper.doi);
  const doiUrl = doi ? "https://doi.org/" + doi : "";
  const titleHtml = url
    ? '<a href="' + escapeHtml(url) + '">' + escapeHtml(title) + '</a>'
    : escapeHtml(title);
  const doiHtml = doi
    ? '<a href="' + escapeHtml(doiUrl) + '">' + escapeHtml(doi) + '</a>'
    : "";
  return [
    '<tr>',
    '<td class="analysis-paper-title">' + titleHtml + '</td>',
    '<td class="analysis-paper-doi">' + doiHtml + '</td>',
    '<td class="analysis-paper-journal">' + escapeHtml(normalizeDisplayTerm(paper && paper.journal)) + '</td>',
    '<td class="analysis-paper-authors">' + escapeHtml(formatPaperAuthors(paper)) + '</td>',
    '</tr>'
  ].join("");
}

function formatPaperAuthors(paper) {
  const authors = Array.isArray(paper && paper.authors)
    ? paper.authors.map(normalizeDisplayTerm).filter(Boolean)
    : [];
  if (!authors.length) return "Unknown authors";
  if (authors.length <= 4) return authors.join(", ");
  return authors.slice(0, 4).join(", ") + ", et al.";
}

function sanitizeTaxonomy(items) {
  if (!Array.isArray(items)) return [];
  return items.map(function (item) {
    const name = normalizeDisplayTerm(item && item.name);
    const aliases = Array.isArray(item && item.aliases) ? item.aliases.map(normalizeDisplayTerm).filter(Boolean) : [];
    if (!name) return null;
    return { name: name, aliases: unique(aliases) };
  }).filter(Boolean);
}

function normalizePhrase(value) {
  const matches = String(value || "").toLowerCase().replace(/-/g, " ").match(/[a-z0-9]+/g);
  return matches ? matches.join(" ") : "";
}

function normalizeDisplayTerm(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function parseEditableTerms(value) {
  return unique(String(value || "").split(/[\n,;]+/).map(normalizeDisplayTerm).filter(Boolean));
}

function normalizePhraseLengths(values) {
  const selected = unique((Array.isArray(values) ? values : []).map(function (value) {
    return String(parseInt(value, 10));
  })).map(function (value) {
    return parseInt(value, 10);
  }).filter(function (value) {
    return ALLOWED_CANDIDATE_PHRASE_LENGTHS.includes(value);
  }).sort(function (left, right) {
    return left - right;
  });
  return selected.length ? selected : DEFAULT_CANDIDATE_PHRASE_LENGTHS.slice();
}

function analysisText(paper) {
  const terms = Array.isArray(paper.matched_terms) ? paper.matched_terms.join(" ") : "";
  return normalizePhrase([paper.title, paper.abstract, terms].filter(Boolean).join(" "));
}

function containsPhrase(text, phrase) {
  if (!text || !phrase) return false;
  return new RegExp("(^| )" + escapeRegExp(phrase) + "( |$)").test(text);
}

function unique(values) {
  const seen = new Set();
  const results = [];
  values.forEach(function (value) {
    const clean = String(value || "");
    if (!clean || seen.has(clean)) return;
    seen.add(clean);
    results.push(clean);
  });
  return results;
}

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#x27;");
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function caseInsensitiveSort(left, right) {
  return left.localeCompare(right, undefined, { sensitivity: "base" });
}

function compareNumber(left, right) {
  return Number(left || 0) - Number(right || 0);
}

function compareString(left, right) {
  return String(left || "").localeCompare(String(right || ""));
}

function coercePositiveInt(value, fallback) {
  const parsed = parseInt(value, 10);
  if (Number.isFinite(parsed) && parsed > 0) return parsed;
  const parsedFallback = parseInt(fallback, 10);
  return Number.isFinite(parsedFallback) && parsedFallback > 0 ? parsedFallback : 1;
}

function coerceNonNegativeInt(value) {
  const parsed = parseInt(value, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}

function paperDate(paper) {
  const match = String(paper.detected || paper.published || "").match(/\d{4}-\d{2}-\d{2}/);
  return match ? match[0] : "";
}

function paperImpact(paper) {
  const value = Number(paper.impact_factor);
  return Number.isFinite(value) ? value : -1;
}

function paperRelevance(paper) {
  return Array.isArray(paper.matched_terms) ? paper.matched_terms.length : 0;
}

function checkedAttribute(value) {
  return value ? " checked" : "";
}
</script>"""


def _keyword_analysis_payload_json(
    candidates: List[Dict[str, object]],
    metrics: JournalMetrics,
    analysis_scope: Optional[AnalysisScope] = None,
) -> str:
    payload = build_keyword_analysis_payload(candidates, metrics, analysis_scope)
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def _matched_papers_payload_json(candidates: List[Dict[str, object]], metrics: JournalMetrics, empty_text: str) -> str:
    sorted_candidates = _sort_candidates_by_detected_date(candidates)
    payload = {
        "empty_html": '<p class="meta">%s</p>' % escape(empty_text),
        "items": [
            {
                "title": str(candidate.get("title") or ""),
                "html": _render_candidate(candidate, metrics),
                "detected": _date_group_sort_value(candidate),
                "detected_label": _date_group_label(candidate),
                "impact_factor": _candidate_impact_factor(candidate, metrics),
                "relevance": len(candidate.get("matched_terms", []) if isinstance(candidate.get("matched_terms"), list) else []),
                "index": index,
            }
            for index, candidate in enumerate(sorted_candidates)
        ],
    }
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def _matched_papers_script() -> str:
    return r"""<script>
document.addEventListener("DOMContentLoaded", function () {
  wireMatchedPapersSort();
});

function wireMatchedPapersSort() {
  const data = document.getElementById("matched-papers-data");
  const list = document.getElementById("matched-papers-list");
  const sort = document.getElementById("matched-papers-sort");
  if (!data || !list || !sort) return;

  let payload = {};
  try {
    payload = JSON.parse(data.textContent || "{}");
  } catch (error) {
    payload = {};
  }
  const items = Array.isArray(payload.items) ? payload.items : [];
  const emptyHtml = typeof payload.empty_html === "string" ? payload.empty_html : '<p class="meta">No matched papers in this run.</p>';

  function render() {
    list.innerHTML = renderMatchedPapers(items, sort.value || "time", emptyHtml);
  }

  sort.addEventListener("change", render);
  render();
}

function renderMatchedPapers(items, sortMode, emptyHtml) {
  const sorted = sortedMatchedPaperItems(Array.isArray(items) ? items : [], sortMode);
  if (!sorted.length) return emptyHtml || "";
  if (sortMode === "impact_factor") {
    return sorted.map(matchedPaperHtml).join("\n");
  }
  return renderMatchedPaperDateGroups(sorted);
}

function sortedMatchedPaperItems(items, sortMode) {
  return items.slice().sort(function (left, right) {
    if (sortMode === "impact_factor") {
      return matchedPaperNumber(right.impact_factor, -1) - matchedPaperNumber(left.impact_factor, -1) ||
        matchedPaperString(right.detected).localeCompare(matchedPaperString(left.detected)) ||
        matchedPaperNumber(left.index, 0) - matchedPaperNumber(right.index, 0);
    }
    return matchedPaperString(right.detected).localeCompare(matchedPaperString(left.detected)) ||
      matchedPaperNumber(right.impact_factor, -1) - matchedPaperNumber(left.impact_factor, -1) ||
      matchedPaperNumber(left.index, 0) - matchedPaperNumber(right.index, 0);
  });
}

function renderMatchedPaperDateGroups(items) {
  const sections = [];
  let currentLabel = null;
  let currentHtml = [];

  items.forEach(function (item) {
    const label = matchedPaperString(item.detected_label) || "Unknown date";
    if (currentLabel !== null && label !== currentLabel) {
      sections.push(renderMatchedPaperDateGroup(currentLabel, currentHtml));
      currentHtml = [];
    }
    currentLabel = label;
    currentHtml.push(matchedPaperHtml(item));
  });

  if (currentLabel !== null) {
    sections.push(renderMatchedPaperDateGroup(currentLabel, currentHtml));
  }
  return sections.join("\n");
}

function renderMatchedPaperDateGroup(label, htmlItems) {
  const count = Array.isArray(htmlItems) ? htmlItems.length : 0;
  return '<section class="date-group"><div class="date-heading-bar"><span class="date-marker" aria-hidden="true"></span><span class="date-short-label">' +
    escapeMatchedPaperText(dateHeadingShortLabel(label)) + '</span><h3 class="date-heading">' +
    escapeMatchedPaperText(label) + '</h3><span class="date-count">' + escapeMatchedPaperText(paperCountLabel(count)) +
    '</span></div>' + htmlItems.join("\n") + '</section>';
}

function matchedPaperHtml(item) {
  return typeof item.html === "string" ? item.html : "";
}

function matchedPaperString(value) {
  return String(value || "");
}

function matchedPaperNumber(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function dateHeadingShortLabel(label) {
  const value = matchedPaperString(label);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return value || "Unknown date";

  const parts = value.split("-").map(function (part) {
    return parseInt(part, 10);
  });
  const date = new Date(parts[0], parts[1] - 1, parts[2]);
  if (!Number.isFinite(date.getTime())) return value;

  const today = new Date();
  const todayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const dayDiff = Math.round((todayStart.getTime() - date.getTime()) / 86400000);
  if (dayDiff === 0) return "Today";
  if (dayDiff === 1) return "Yesterday";

  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return months[date.getMonth()] + " " + date.getDate();
}

function paperCountLabel(count) {
  const value = Math.max(0, parseInt(count, 10) || 0);
  return value + (value === 1 ? " paper" : " papers");
}

function escapeMatchedPaperText(value) {
  return String(value || "").replace(/[&<>"']/g, function (character) {
    return {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#x27;"
    }[character];
  });
}
</script>"""


def _render_candidates(candidates: List[Dict[str, object]], metrics: JournalMetrics, empty_text: str) -> str:
    if not candidates:
        return '<p class="meta">%s</p>' % escape(empty_text)
    return "\n".join(_render_candidate(candidate, metrics) for candidate in _sort_candidates_by_detected_date(candidates))


def _render_candidate_groups(candidates: List[Dict[str, object]], metrics: JournalMetrics, empty_text: str) -> str:
    if not candidates:
        return '<p class="meta">%s</p>' % escape(empty_text)

    sections = []
    current_label = None
    current_candidates = []
    for candidate in _sort_candidates_by_detected_date(candidates):
        label = _date_group_label(candidate)
        if current_label is not None and label != current_label:
            sections.append(_render_date_group(current_label, current_candidates, metrics))
            current_candidates = []
        current_label = label
        current_candidates.append(candidate)

    if current_label is not None:
        sections.append(_render_date_group(current_label, current_candidates, metrics))
    return "\n".join(sections)


def _render_date_group(label: str, candidates: List[Dict[str, object]], metrics: JournalMetrics) -> str:
    return """<section class="date-group">
  <div class="date-heading-bar">
    <span class="date-marker" aria-hidden="true"></span>
    <span class="date-short-label">%s</span>
    <h3 class="date-heading">%s</h3>
    <span class="date-count">%s</span>
  </div>
  %s
</section>""" % (
        escape(_date_group_short_label(label)),
        escape(label),
        escape(_paper_count_label(len(candidates))),
        "\n".join(_render_candidate(candidate, metrics) for candidate in candidates),
    )


def _date_group_short_label(label: str) -> str:
    try:
        group_date = date.fromisoformat(label)
    except ValueError:
        return label or "Unknown date"

    today = date.today()
    if group_date == today:
        return "Today"
    if (today - group_date).days == 1:
        return "Yesterday"
    return group_date.strftime("%b %d").replace(" 0", " ")


def _paper_count_label(count: int) -> str:
    return "%d %s" % (count, "paper" if count == 1 else "papers")


def _render_candidate(candidate: Dict[str, object], metrics: JournalMetrics) -> str:
    journal_name, metric = _display_journal(candidate, metrics)
    metric_text = _metric_text(metric)
    terms = ", ".join(str(term) for term in candidate.get("matched_terms", []))
    link = _safe_article_link(candidate)
    identifier = str(candidate.get("doi") or link)
    date_text = _candidate_date_text(candidate)
    return """<article class="paper">
  <h3><a href="%s" target="_blank" rel="noopener noreferrer">%s</a></h3>
  <div class="meta"><strong class="journal-name">%s</strong> · %s · %s · %s</div>
  <div class="meta">%s</div>
  <div class="terms">Reason: %s%s</div>
</article>""" % (
        escape(link, quote=True),
        escape(str(candidate.get("title") or "")),
        escape(journal_name),
        escape(date_text),
        escape(str(candidate.get("source") or "")),
        escape(identifier),
        metric_text,
        escape(str(candidate.get("reason") or "")),
        " · Terms: " + escape(terms) if terms else "",
    )


def _display_journal(candidate: Dict[str, object], metrics: JournalMetrics):
    raw_values = [
        str(candidate.get("journal") or ""),
        str(candidate.get("journal_match") or ""),
        str(candidate.get("source") or ""),
    ]
    for value in raw_values:
        if not value:
            continue
        metric = metrics.lookup(value)
        if metric is not None:
            return metric.journal, metric

    return next((value for value in raw_values if value), ""), None


def _safe_article_link(candidate: Dict[str, object]) -> str:
    link = str(candidate.get("url") or "").strip()
    if _is_web_url(link):
        return link
    doi = str(candidate.get("doi") or "").strip()
    if doi:
        return "https://doi.org/" + doi
    return ""


def _is_web_url(value: str) -> bool:
    scheme = urlsplit(value).scheme.casefold()
    return scheme in ("http", "https")


def _sort_candidates_by_detected_date(candidates: List[Dict[str, object]]) -> List[Dict[str, object]]:
    return sorted(candidates, key=_detected_sort_key, reverse=True)


def _detected_sort_key(candidate: Dict[str, object]):
    detected_date = first_iso_date(_candidate_detected_value(candidate))
    if detected_date is None:
        return (0, date.min)
    return (1, detected_date)


def _date_group_label(candidate: Dict[str, object]) -> str:
    detected_date = first_iso_date(_candidate_detected_value(candidate))
    if detected_date is None:
        return "Unknown date"
    return detected_date.isoformat()


def _date_group_sort_value(candidate: Dict[str, object]) -> str:
    detected_date = first_iso_date(_candidate_detected_value(candidate))
    return detected_date.isoformat() if detected_date is not None else ""


def _candidate_date_text(candidate: Dict[str, object]) -> str:
    detected = display_article_date(_candidate_detected_value(candidate))
    published = display_article_date(candidate.get("published"))
    parts = []
    if detected:
        parts.append("Detected: %s" % detected)
    if published and published != detected:
        parts.append("Published: %s" % published)
    return " · ".join(parts) or "Detected: Unknown date"


def _candidate_detected_value(candidate: Dict[str, object]) -> object:
    return candidate.get("detected") or candidate.get("published")


def _candidate_impact_factor(candidate: Dict[str, object], metrics: JournalMetrics) -> float:
    _, metric = _display_journal(candidate, metrics)
    if metric is not None and metric.impact_factor is not None:
        return float(metric.impact_factor)
    try:
        return float(candidate.get("impact_factor"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return -1.0


def _metric_text(metric) -> str:
    if metric is None:
        return "Journal metrics: not available in local metrics file"
    parts = []
    if metric.impact_factor is not None:
        parts.append("Impact factor: %.1f" % metric.impact_factor)
    if metric.five_year_impact_factor is not None:
        parts.append("5-year: %.1f" % metric.five_year_impact_factor)
    if metric.level:
        parts.append(escape(metric.level))
    source_url = str(metric.source_url or "").strip()
    if source_url and _is_web_url(source_url):
        parts.append('<a href="%s" target="_blank" rel="noopener noreferrer">metric source</a>' % escape(source_url, quote=True))
    return " · ".join(parts)
