from pathlib import Path
import importlib.util
import unittest


class MacOSInstallScriptTests(unittest.TestCase):
    def test_install_script_restarts_running_app_before_opening_bundle(self):
        script = Path("scripts/install_macos_app.sh").read_text(encoding="utf-8")

        restart_index = script.find('pkill -x "PaperMonitorApp"')
        legacy_restart_index = script.find('pkill -x "SolidBatteryMonitorApp"')
        open_index = script.find('open "$APP_TARGET"')

        self.assertGreaterEqual(restart_index, 0)
        self.assertGreater(legacy_restart_index, restart_index)
        self.assertGreater(open_index, legacy_restart_index)
        self.assertGreater(open_index, restart_index)

    def test_install_script_syncs_manual_command_entrypoints_and_example_config(self):
        script = Path("scripts/install_macos_app.sh").read_text(encoding="utf-8")

        self.assertIn('if [ -f "$ROOT_DIR/PaperMonitor.command" ]; then', script)
        self.assertIn('cp "$ROOT_DIR/PaperMonitor.command" "$APP_SUPPORT/PaperMonitor.command"', script)
        self.assertIn(
            'if [ -f "$ROOT_DIR/PaperMonitorDashboard.command" ]; then',
            script,
        )
        self.assertIn(
            'cp "$ROOT_DIR/PaperMonitorDashboard.command" "$APP_SUPPORT/PaperMonitorDashboard.command"',
            script,
        )
        self.assertIn('CONFIG_SOURCE="$ROOT_DIR/config.example.json"', script)
        self.assertIn('if [ ! -f "$APP_SUPPORT/config.json" ]; then', script)
        self.assertIn('cp "$ROOT_DIR/config.example.json" "$APP_SUPPORT/config.example.json"', script)

    def test_macos_app_uses_paper_monitor_display_name(self):
        build_script = Path("scripts/build_macos_app.sh").read_text(encoding="utf-8")
        install_script = Path("scripts/install_macos_app.sh").read_text(encoding="utf-8")
        plist = Path("macos/PaperMonitorApp/Info.plist").read_text(encoding="utf-8")

        self.assertIn('APP_NAME="Paper Monitor"', build_script)
        self.assertIn('APP_NAME="Paper Monitor.app"', install_script)
        self.assertIn("<string>Paper Monitor</string>", plist)

    def test_macos_app_runs_as_menu_bar_agent_without_dock_icon(self):
        plist = Path("macos/PaperMonitorApp/Info.plist").read_text(encoding="utf-8")
        main = Path("macos/PaperMonitorApp/Sources/PaperMonitorApp/main.swift").read_text(encoding="utf-8")

        self.assertIn("<key>LSUIElement</key>", plist)
        self.assertIn("<true/>", plist)
        self.assertIn("app.setActivationPolicy(.accessory)", main)
        self.assertNotIn("app.setActivationPolicy(.regular)", main)

    def test_build_script_codesigns_final_app_bundle(self):
        script = Path("scripts/build_macos_app.sh").read_text(encoding="utf-8")

        self.assertIn('codesign --force --deep --sign - "$APP_DIR"', script)

    def test_install_script_registers_final_app_with_launch_services(self):
        script = Path("scripts/install_macos_app.sh").read_text(encoding="utf-8")

        self.assertIn('lsregister -f "$APP_TARGET"', script)

    def test_install_script_removes_old_named_app_bundle(self):
        script = Path("scripts/install_macos_app.sh").read_text(encoding="utf-8")

        self.assertIn('OLD_APP_NAME="Paper Monitor.app"', script)
        self.assertIn('rm -rf "$APP_TARGET" "$OLD_APP_TARGET"', script)

    def test_icon_generator_uses_final_source_art_not_battery_drawing(self):
        script = Path("scripts/generate_app_icons.py").read_text(encoding="utf-8")

        self.assertIn("AppIconSource.png", script)
        self.assertIn("generate_app_iconset", script)
        self.assertNotIn("battery outline", script)
        self.assertNotIn("lightning =", script)

    def test_menu_bar_icon_generator_draws_template_mask(self):
        spec = importlib.util.spec_from_file_location("generate_app_icons", "scripts/generate_app_icons.py")
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)

        image = generator.draw_menu_icon(64)
        visible_pixels = [pixel for row in image for pixel in row if pixel[3] > 0]
        colors = {tuple(pixel[:3]) for pixel in visible_pixels}

        self.assertEqual(colors, {(0, 0, 0)})
        self.assertGreater(len(visible_pixels), 100)
        self.assertGreater(
            sum(1 for row in image for pixel in row if pixel[3] == 0),
            0,
        )


if __name__ == "__main__":
    unittest.main()
