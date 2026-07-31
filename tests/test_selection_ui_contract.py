import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from paper_monitor.analysis_refresh import _crossref_only_source_config
from paper_monitor.config import DEFAULT_CONFIG
from paper_monitor.windows_settings import default_settings_payload, save_settings, settings_payload

ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class SelectionUIContractTests(unittest.TestCase):
    def test_windows_settings_save_keeps_only_canonical_selected_journals(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            raw = json.loads(json.dumps(DEFAULT_CONFIG))
            raw["journal_scope"]["top_n"] = 10
            raw["sources"]["crossref"]["journal_titles"] = ["Stale Journal"]
            config_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            payload = default_settings_payload(config_path)
            payload["journal_scope"]["selected_journals"] = [
                " Nature Energy ",
                "nature energy",
                "Custom Journal",
                "arXiv",
                "",
            ]
            payload["sources"]["arxiv"]["enabled"] = True

            response = save_settings(config_path, payload)
            saved = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(response, {"ok": True})
        self.assertNotIn("top_n", saved["journal_scope"])
        self.assertEqual(saved["journal_scope"]["selected_journals"], ["Nature Energy", "Custom Journal", "arxiv"])
        self.assertNotIn("journals", saved)
        self.assertNotIn("journal_titles", saved["sources"]["crossref"])
        self.assertTrue(saved["sources"]["arxiv"]["enabled"])

    def test_windows_settings_save_preserves_an_explicit_empty_journal_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            raw = json.loads(json.dumps(DEFAULT_CONFIG))
            raw["journals"] = ["Nature Energy"]
            raw["journal_scope"]["selected_journals"] = ["Nature Energy"]
            config_path.write_text(json.dumps(raw), encoding="utf-8")
            payload = default_settings_payload(config_path)
            payload["journal_scope"]["selected_journals"] = []
            payload["sources"]["arxiv"]["enabled"] = False

            response = save_settings(config_path, payload)
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            reloaded = settings_payload(config_path)

        self.assertEqual(response, {"ok": True})
        self.assertEqual(saved["journal_scope"]["selected_journals"], [])
        self.assertNotIn("journals", saved)
        self.assertEqual(reloaded["journal_scope"]["selected_journals"], [])
        self.assertNotIn("journal_titles", saved["sources"]["crossref"])

    def test_keyword_analysis_crossref_config_excludes_arxiv_source_selection(self):
        source_config = {"crossref": {"enabled": True, "query": "solid electrolyte"}}

        config = _crossref_only_source_config(
            source_config,
            "2026-07-01",
            "2026-07-09",
            ["Nature Energy", " arXiv ", "Custom Journal"],
        )

        self.assertEqual(config["crossref"]["journal_titles"], ["Nature Energy", "Custom Journal"])

    def test_windows_settings_exposes_reusable_dual_list_and_drag_drop_hooks(self):
        settings_js = read_text("paper_monitor/static/windows/settings.js")
        settings_css = read_text("paper_monitor/static/windows/settings.css")

        self.assertIn("function createDualListModel", settings_js)
        self.assertIn("function bindDualListDropZone", settings_js)
        self.assertIn("window.PaperMonitorDualList", settings_js)
        self.assertIn("button.draggable = true", settings_js)
        self.assertIn("setDualListDragData", settings_js)
        self.assertIn('bindDualListDropZone(selectedList, "journal-filter"', settings_js)
        self.assertIn('bindDualListDropZone(candidateList, "journal-filter"', settings_js)
        self.assertIn(".journal-list.drag-over", settings_css)
        self.assertIn('id="journal_category"', read_text("paper_monitor/templates/windows/settings.html"))
        self.assertIn("entry.category === category", settings_js)
        self.assertIn('setLines("include_terms", preset.include_terms)', settings_js)
        self.assertIn('setLines("exclude_terms", preset.exclude_terms)', settings_js)
        self.assertIn("min-height: 30px", settings_css)

    def test_windows_dual_list_remove_survives_candidate_resync(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not available")
        settings_js = read_text("paper_monitor/static/windows/settings.js")
        start = settings_js.index("    function normalizeDualListValue")
        end = settings_js.index("    function setDualListDragData")
        model_script = settings_js[start:end]
        harness = f"""
{model_script}
const candidates = [
  {{ journal: "Nature Energy", impact_factor: 18.1 }},
  {{ journal: "IEEE Transactions on Pattern Analysis and Machine Intelligence", impact_factor: 12.2 }}
];
const model = createDualListModel({{
  getValue: function (entry) {{ return entry.journal; }},
  makeCandidate: function (journal) {{ return {{ journal: journal }}; }}
}});
model.setCandidates(candidates).setSelected(["Nature Energy"]);
model.remove(" nature energy ");
model.setCandidates(candidates);
if (model.selected().length !== 0) throw new Error("removed journal was re-selected");
if (model.availableEntries()[0].journal !== "Nature Energy") throw new Error("removed journal did not return to candidates");
"""
        result = subprocess.run([node, "-"], input=harness, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_windows_search_direction_applies_preset_queries_and_filter_terms(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not available")
        settings_js = read_text("paper_monitor/static/windows/settings.js")
        start = settings_js.index("    function applyPreset()")
        end = settings_js.index("    function promoteToCustom()")
        apply_preset_script = settings_js[start:end]
        harness = f"""
let presetsById = {{
  sodium_battery: {{
    id: "sodium_battery",
    label: "Sodium battery",
    crossref_query: "sodium-ion battery",
    openalex_query: "sodium-ion battery",
    include_terms: ["sodium-ion battery", "Na-ion battery"],
    exclude_terms: ["solid-state laser"]
  }}
}};
const fields = {{
  search_direction: {{ value: "sodium_battery" }},
  custom_direction_name: {{ value: "" }},
  crossref_query: {{ value: "" }},
  openalex_query: {{ value: "" }},
  include_terms: {{ value: "" }},
  exclude_terms: {{ value: "" }}
}};
function field(id) {{ return fields[id]; }}
function setValue(id, value) {{ fields[id].value = value; }}
function setLines(id, values) {{ fields[id].value = values.join("\\n"); }}
function updateCustomState() {{}}
{apply_preset_script}
applyPreset();
if (fields.crossref_query.value !== "sodium-ion battery") throw new Error("Crossref query was not applied");
if (fields.openalex_query.value !== "sodium-ion battery") throw new Error("OpenAlex query was not applied");
if (fields.include_terms.value !== "sodium-ion battery\\nNa-ion battery") throw new Error("include terms were not applied");
if (fields.exclude_terms.value !== "solid-state laser") throw new Error("exclude terms were not applied");
"""
        result = subprocess.run([node, "-"], input=harness, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dashboard_keyword_analysis_uses_dual_list_selection_semantics(self):
        dashboard = read_text("paper_monitor/dashboard.py")

        self.assertIn("function createDualListSelection", dashboard)
        self.assertIn("function renderAnalysisJournalDualList", dashboard)
        self.assertIn('data-analysis-journal-action="add"', dashboard)
        self.assertIn('data-analysis-journal-action="remove"', dashboard)
        self.assertIn('data-analysis-journal-drop="add"', dashboard)
        self.assertIn('data-analysis-journal-drop="remove"', dashboard)
        self.assertIn("analysis-journal-search", dashboard)
        self.assertIn("analysis-journal-category", dashboard)
        self.assertNotIn("analysis-journal-impact", dashboard)
        self.assertIn("overflow-wrap: anywhere", dashboard)
        self.assertIn("[actionLabel + entry.journal, entry.category]", dashboard)
        self.assertIn("acceptedCandidateTerms", dashboard)
        self.assertIn("function removeAcceptedCandidateTerm", dashboard)
        self.assertIn('data-candidate-term-drop="add"', dashboard)
        self.assertIn('data-candidate-term-drop="remove"', dashboard)

if __name__ == "__main__":
    unittest.main()
