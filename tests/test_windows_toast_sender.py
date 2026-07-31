import unittest
from unittest.mock import Mock, patch

from paper_monitor import windows_toast_sender
from paper_monitor.app_identity import WINDOWS_APP_USER_MODEL_ID


class FakeDocument:
    def __init__(self):
        self.xml = ""

    def load_xml(self, value):
        self.xml = value


class FakeToast:
    def __init__(self, document):
        self.document = document
        self.tag = ""
        self.group = ""


class WindowsToastSenderTests(unittest.TestCase):
    def test_sender_uses_explicit_paper_monitor_app_identity(self):
        notifier = Mock()
        manager = Mock()
        manager.create_toast_notifier_with_id.return_value = notifier

        with patch.object(
            windows_toast_sender,
            "_winrt_types",
            return_value=(FakeDocument, FakeToast, manager),
        ):
            toast = windows_toast_sender.send_toast(
                None,
                None,
                xml='<toast><visual><binding template="ToastGeneric"/></visual></toast>',
                tag="article",
                group="pm20260729",
            )

        manager.create_toast_notifier_with_id.assert_called_once_with(
            WINDOWS_APP_USER_MODEL_ID
        )
        notifier.show.assert_called_once_with(toast)
        self.assertEqual(toast.tag, "article")
        self.assertEqual(toast.group, "pm20260729")


if __name__ == "__main__":
    unittest.main()
