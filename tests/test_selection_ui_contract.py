import json
import tempfile
import unittest
from pathlib import Path

from paper_monitor.analysis_refresh import _crossref_only_source_config
from paper_monitor.config import DEFAULT_CONFIG
from paper_monitor.windows_settings import default_settings_payload, save_settings

ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class SelectionUIContractTests(unittest.TestCase):
    def test_windows_settings_save_syncs_selected_journals_legacy_field_and_crossref_titles(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")
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
        self.assertEqual(saved["journal_scope"]["selected_journals"], ["Nature Energy", "Custom Journal", "arxiv"])
        self.assertEqual(saved["journals"], ["Nature Energy", "Custom Journal", "arxiv"])
        self.assertEqual(saved["sources"]["crossref"]["journal_titles"], ["Nature Energy", "Custom Journal"])
        self.assertTrue(saved["sources"]["arxiv"]["enabled"])

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

    def test_dashboard_keyword_analysis_uses_dual_list_selection_semantics(self):
        dashboard = read_text("paper_monitor/dashboard.py")

        self.assertIn("function createDualListSelection", dashboard)
        self.assertIn("function renderAnalysisJournalDualList", dashboard)
        self.assertIn('data-analysis-journal-action="add"', dashboard)
        self.assertIn('data-analysis-journal-action="remove"', dashboard)
        self.assertIn('data-analysis-journal-drop="add"', dashboard)
        self.assertIn('data-analysis-journal-drop="remove"', dashboard)
        self.assertIn("acceptedCandidateTerms", dashboard)
        self.assertIn("function removeAcceptedCandidateTerm", dashboard)
        self.assertIn('data-candidate-term-drop="add"', dashboard)
        self.assertIn('data-candidate-term-drop="remove"', dashboard)

    def test_macos_journal_filter_has_dual_list_model_and_drag_drop_paths(self):
        models = read_text("macos/PaperMonitorApp/Sources/PaperMonitorCore/SettingsModels.swift")
        journal_filter = read_text("macos/PaperMonitorApp/Sources/PaperMonitorCore/JournalFilterViewController.swift")

        self.assertIn("public struct DualListSelection", models)
        self.assertIn("public mutating func remove", models)
        self.assertIn("selectedItems.removeAll", models)
        self.assertIn("static let paperMonitorJournal", journal_filter)
        self.assertIn("JournalDropStackView", journal_filter)
        self.assertIn("DraggableJournalButton", journal_filter)
        self.assertIn("pasteboardWriterForRow", journal_filter)
        self.assertIn("shouldSelectRow", journal_filter)
        self.assertIn("acceptDrop", journal_filter)


if __name__ == "__main__":
    unittest.main()
