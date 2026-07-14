import datetime as dt
import subprocess
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from paper_monitor import windows_scheduled_task as scheduled

NS = {"task": scheduled.TASK_XML_NAMESPACE}


class WindowsScheduledTaskTests(unittest.TestCase):
    def test_build_refresh_command_supports_source_and_frozen_execution(self):
        config_path = Path(r"C:\Users\Example User\Paper Monitor\config.json")
        executable = Path(r"C:\Program Files\Paper Monitor\PaperMonitor.exe")

        frozen = scheduled.build_scheduled_refresh_command(
            config_path,
            executable=executable,
            frozen=True,
        )
        source = scheduled.build_scheduled_refresh_command(
            config_path,
            executable=Path(r"C:\Python312\python.exe"),
            frozen=False,
        )

        self.assertEqual(frozen[1:3], ["scheduled-refresh", "--config"])
        self.assertEqual(frozen[3], str(config_path.resolve()))
        self.assertEqual(
            source[1:4],
            ["-m", "paper_monitor.windows_background", "--config"],
        )
        self.assertEqual(source[4], str(config_path.resolve()))

    def test_start_boundary_uses_interval_or_configured_anchor(self):
        now = dt.datetime(2026, 7, 12, 10, 30, 0)

        self.assertEqual(
            scheduled.next_start_boundary(12, now=now),
            dt.datetime(2026, 7, 12, 22, 30, 0),
        )
        self.assertEqual(
            scheduled.next_start_boundary(6, "09:00", now=now),
            dt.datetime(2026, 7, 12, 15, 0, 0),
        )
        self.assertEqual(
            scheduled.next_start_boundary(24, "09:00", now=now),
            dt.datetime(2026, 7, 13, 9, 0, 0),
        )

    def test_task_xml_is_interactive_non_overlapping_and_runs_when_available(self):
        command = [
            r"C:\Program Files\Paper Monitor\PaperMonitor.exe",
            "scheduled-refresh",
            "--config",
            r"C:\Users\A User\Paper Monitor\config & test.json",
        ]
        payload = scheduled.build_scheduled_task_xml(
            command,
            interval_hours=168,
            start_time="08:15",
            user_name=r"DOMAIN\A User",
            now=dt.datetime(2026, 7, 12, 7, 0, 0),
            working_directory=r"C:\Program Files\Paper Monitor",
        )
        root = ET.fromstring(payload)

        self.assertEqual(root.findtext(".//task:LogonType", namespaces=NS), "InteractiveToken")
        self.assertEqual(root.findtext(".//task:RunLevel", namespaces=NS), "LeastPrivilege")
        self.assertEqual(root.findtext(".//task:Interval", namespaces=NS), "P7D")
        self.assertEqual(root.findtext(".//task:StartWhenAvailable", namespaces=NS), "true")
        self.assertEqual(root.findtext(".//task:MultipleInstancesPolicy", namespaces=NS), "IgnoreNew")
        self.assertEqual(
            root.findtext(".//task:ExecutionTimeLimit", namespaces=NS),
            scheduled.DEFAULT_EXECUTION_TIME_LIMIT,
        )
        self.assertEqual(
            root.findtext(".//task:RestartOnFailure/task:Interval", namespaces=NS),
            scheduled.DEFAULT_RESTART_INTERVAL,
        )
        self.assertEqual(
            root.findtext(".//task:RestartOnFailure/task:Count", namespaces=NS),
            str(scheduled.DEFAULT_RESTART_COUNT),
        )
        self.assertEqual(root.findtext(".//task:Command", namespaces=NS), command[0])
        arguments = root.findtext(".//task:Arguments", namespaces=NS)
        self.assertIn('"C:\\Users\\A User\\Paper Monitor\\config & test.json"', arguments)
        self.assertTrue(payload.startswith((b"\xff\xfe", b"\xfe\xff")))
        self.assertNotIn("cmd.exe", payload.decode("utf-16"))

    def test_install_uses_schtasks_argument_list_and_always_removes_temporary_xml(self):
        captured = {}

        def runner(args, **kwargs):
            if "/Query" in args:
                return subprocess.CompletedProcess(args, 0x80070002, stdout="", stderr="")
            captured["args"] = list(args)
            captured["kwargs"] = kwargs
            xml_path = Path(args[args.index("/XML") + 1])
            captured["xml_path"] = xml_path
            captured["xml"] = xml_path.read_bytes()
            self.assertTrue(xml_path.exists())
            return subprocess.CompletedProcess(args, 0, stdout="SUCCESS", stderr="")

        result = scheduled.install_or_update_scheduled_refresh(
            Path(r"C:\Users\A User\config.json"),
            12,
            "09:30",
            executable=Path(r"C:\Program Files\Paper Monitor\PaperMonitor.exe"),
            frozen=True,
            user_name=r"DOMAIN\A User",
            now=dt.datetime(2026, 7, 12, 8, 0, 0),
            runner=runner,
            schtasks_executable=r"C:\Windows\System32\schtasks.exe",
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(captured["args"][1], "/Create")
        self.assertIn("/F", captured["args"])
        self.assertNotIn("cmd.exe", captured["args"])
        self.assertTrue(captured["kwargs"]["check"])
        self.assertFalse(captured["xml_path"].exists())
        self.assertIn("scheduled-refresh", captured["xml"].decode("utf-16"))
        root = ET.fromstring(captured["xml"])
        self.assertEqual(
            root.findtext(".//task:WorkingDirectory", namespaces=NS),
            str(Path(r"C:\Program Files\Paper Monitor\PaperMonitor.exe").resolve().parent),
        )

    def test_install_removes_temporary_xml_when_schtasks_fails(self):
        captured_path = None

        def runner(args, **_kwargs):
            nonlocal captured_path
            if "/Query" in args:
                return subprocess.CompletedProcess(args, 0x80070002, stdout="", stderr="")
            captured_path = Path(args[args.index("/XML") + 1])
            raise subprocess.CalledProcessError(5, args, stderr="access denied")

        with self.assertRaises(subprocess.CalledProcessError):
            scheduled.install_or_update_scheduled_refresh(
                Path("config.json"),
                12,
                executable=Path("PaperMonitor.exe"),
                frozen=True,
                user_name="Example",
                runner=runner,
            )

        self.assertIsNotNone(captured_path)
        self.assertFalse(captured_path.exists())

    def test_install_does_not_reset_scheduler_normalized_task_start_boundary(self):
        config_path = Path(r"C:\Users\A User\config.json")
        executable = Path(r"C:\Program Files\Paper Monitor\PaperMonitor.exe")
        command = scheduled.build_scheduled_refresh_command(
            config_path,
            executable=executable,
            frozen=True,
        )
        work_dir = executable.resolve().parent
        existing_root = ET.fromstring(
            scheduled.build_scheduled_task_xml(
                command,
                interval_hours=12,
                start_time="09:30",
                user_name=r"DOMAIN\A User",
                now=dt.datetime(2026, 7, 1, 8, 0, 0),
                working_directory=work_dir,
            )
        )
        for parent_path, child_name in (
            ("./task:Triggers/task:TimeTrigger", "Enabled"),
            ("./task:Principals/task:Principal", "RunLevel"),
            ("./task:Settings", "AllowStartOnDemand"),
            ("./task:Settings", "Enabled"),
            ("./task:Settings", "WakeToRun"),
        ):
            parent = existing_root.find(parent_path, NS)
            child = parent.find(f"task:{child_name}", NS)
            parent.remove(child)
        existing_xml = ET.tostring(existing_root, encoding="unicode")
        calls = []

        def runner(args, **_kwargs):
            calls.append(list(args))
            return subprocess.CompletedProcess(args, 0, stdout=existing_xml, stderr="")

        result = scheduled.install_or_update_scheduled_refresh(
            config_path,
            12,
            "09:30",
            executable=executable,
            frozen=True,
            user_name=r"DOMAIN\A User",
            now=dt.datetime(2026, 7, 12, 8, 0, 0),
            runner=runner,
            schtasks_executable="schtasks.exe",
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)
        self.assertIn("/Query", calls[0])
        self.assertNotIn("/Create", calls[0])

    def test_fingerprint_matching_accepts_scheduler_encodings_and_rejects_oversize(self):
        fingerprint = "a" * 64
        marker = f"{scheduled.FINGERPRINT_PREFIX}{fingerprint}"
        payload = f"<Task><Description>{marker}</Description></Task>"

        self.assertTrue(scheduled.scheduled_task_xml_matches(payload, fingerprint))
        self.assertTrue(
            scheduled.scheduled_task_xml_matches(payload.encode("utf-16"), fingerprint)
        )
        self.assertFalse(scheduled.scheduled_task_xml_matches("<Task />", fingerprint))
        self.assertFalse(
            scheduled.scheduled_task_xml_matches(
                b"x" * (scheduled.MAX_EXPORTED_TASK_XML_BYTES + 1),
                fingerprint,
            )
        )

    def test_install_updates_when_schedule_fingerprint_changes(self):
        config_path = Path("config.json")
        executable = Path("PaperMonitor.exe")
        old_command = scheduled.build_scheduled_refresh_command(
            config_path,
            executable=executable,
            frozen=True,
        )
        existing_xml = scheduled.build_scheduled_task_xml(
            old_command,
            interval_hours=12,
            start_time="09:00",
            user_name="Example",
            working_directory=executable.resolve().parent,
        ).decode("utf-16")
        calls = []

        def runner(args, **_kwargs):
            calls.append(list(args))
            if "/Query" in args:
                return subprocess.CompletedProcess(args, 0, stdout=existing_xml, stderr="")
            return subprocess.CompletedProcess(args, 0, stdout="SUCCESS", stderr="")

        scheduled.install_or_update_scheduled_refresh(
            config_path,
            24,
            "09:00",
            executable=executable,
            frozen=True,
            user_name="Example",
            runner=runner,
            schtasks_executable="schtasks.exe",
        )

        self.assertEqual(len(calls), 2)
        self.assertIn("/Query", calls[0])
        self.assertIn("/Create", calls[1])

    def test_install_repairs_semantic_drift_even_when_fingerprint_is_unchanged(self):
        config_path = Path("config.json")
        executable = Path("PaperMonitor.exe")
        command = scheduled.build_scheduled_refresh_command(
            config_path,
            executable=executable,
            frozen=True,
        )
        existing_xml = scheduled.build_scheduled_task_xml(
            command,
            interval_hours=12,
            user_name="Example",
            working_directory=executable.resolve().parent,
        ).decode("utf-16")
        existing_xml = existing_xml.replace(
            "<Enabled>true</Enabled>",
            "<Enabled>false</Enabled>",
            1,
        )
        calls = []

        def runner(args, **_kwargs):
            calls.append(list(args))
            if "/Query" in args:
                return subprocess.CompletedProcess(args, 0, stdout=existing_xml, stderr="")
            return subprocess.CompletedProcess(args, 0, stdout="SUCCESS", stderr="")

        scheduled.install_or_update_scheduled_refresh(
            config_path,
            12,
            executable=executable,
            frozen=True,
            user_name="Example",
            runner=runner,
            schtasks_executable="schtasks.exe",
        )

        self.assertEqual(len(calls), 2)
        self.assertIn("/Create", calls[1])

    def test_query_permission_error_is_not_treated_as_missing(self):
        calls = []

        def runner(args, **_kwargs):
            calls.append(list(args))
            return subprocess.CompletedProcess(args, 0x80070005, stdout="", stderr="Access denied")

        with self.assertRaises(subprocess.CalledProcessError) as raised:
            scheduled.install_or_update_scheduled_refresh(
                Path("config.json"),
                12,
                executable=Path("PaperMonitor.exe"),
                frozen=True,
                user_name="Example",
                runner=runner,
                schtasks_executable="schtasks.exe",
            )

        self.assertEqual(raised.exception.returncode, 0x80070005)
        self.assertEqual(len(calls), 1)
        self.assertIn("/Query", calls[0])

    def test_source_task_uses_project_root_as_working_directory(self):
        captured_xml = None

        def runner(args, **_kwargs):
            nonlocal captured_xml
            if "/Query" in args:
                return subprocess.CompletedProcess(args, 0x80070002, stdout="", stderr="")
            xml_path = Path(args[args.index("/XML") + 1])
            captured_xml = ET.fromstring(xml_path.read_bytes())
            return subprocess.CompletedProcess(args, 0, stdout="SUCCESS", stderr="")

        scheduled.install_or_update_scheduled_refresh(
            Path("config.json"),
            12,
            executable=Path(r"C:\Python312\python.exe"),
            frozen=False,
            user_name="Example",
            runner=runner,
            schtasks_executable="schtasks.exe",
        )

        self.assertIsNotNone(captured_xml)
        self.assertEqual(
            captured_xml.findtext(".//task:WorkingDirectory", namespaces=NS),
            str(Path(scheduled.__file__).resolve().parents[1]),
        )

    def test_remove_is_idempotent_for_file_not_found_hresult(self):
        calls = []

        def missing_runner(args, **kwargs):
            calls.append((list(args), kwargs))
            return subprocess.CompletedProcess(args, 0x80070002, stdout="", stderr="")

        removed = scheduled.remove_scheduled_refresh(
            runner=missing_runner,
            schtasks_executable="schtasks.exe",
        )

        self.assertFalse(removed)
        self.assertEqual(calls[0][0][1], "/Delete")
        self.assertIn("/HResult", calls[0][0])
        self.assertFalse(calls[0][1]["check"])

    def test_sync_disabled_only_deletes_and_enabled_installs(self):
        def successful_runner(args, **_kwargs):
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with patch.object(scheduled, "remove_scheduled_refresh", return_value=False) as remove:
            self.assertTrue(
                scheduled.sync_scheduled_refresh(
                    Path("config.json"),
                    False,
                    12,
                    runner=successful_runner,
                )
            )
        self.assertEqual(remove.call_count, 2)

        with patch.object(scheduled, "install_or_update_scheduled_refresh") as install:
            self.assertTrue(
                scheduled.sync_scheduled_refresh(
                    Path("config.json"),
                    True,
                    12,
                    runner=successful_runner,
                )
            )
        install.assert_called_once()

    def test_default_task_name_is_stable_and_isolated_by_account(self):
        first = scheduled.default_task_name(r"LAB\Researcher One")
        same = scheduled.default_task_name(r"lab\researcher one")
        second = scheduled.default_task_name(r"LAB\Researcher Two")

        self.assertEqual(first, same)
        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith(scheduled.TASK_NAME_PREFIX))
        self.assertNotIn("Researcher", first)

    def test_rejects_invalid_intervals_times_and_control_characters(self):
        for interval in (0, 721, True, 1.5):
            with self.subTest(interval=interval):
                with self.assertRaises(ValueError):
                    scheduled.next_start_boundary(interval)
        for start_time in ("9:00", "24:00", "12:60", "noon"):
            with self.subTest(start_time=start_time):
                with self.assertRaises(ValueError):
                    scheduled.next_start_boundary(12, start_time)
        with self.assertRaises(ValueError):
            scheduled.build_schtasks_delete_args(task_name="unsafe\nname")
        with self.assertRaises(ValueError):
            scheduled.build_scheduled_refresh_command(Path("unsafe\nconfig.json"))

    def test_current_user_and_system_schtasks_path_do_not_use_shell_lookup(self):
        env = {
            "USERNAME": "Researcher",
            "USERDOMAIN": "LAB",
            "SystemRoot": r"D:\Windows",
        }

        self.assertEqual(scheduled.current_windows_user(env), r"LAB\Researcher")
        self.assertEqual(
            scheduled.default_schtasks_executable(env),
            r"D:\Windows\System32\schtasks.exe",
        )


if __name__ == "__main__":
    unittest.main()
