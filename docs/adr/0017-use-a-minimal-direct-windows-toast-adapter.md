# Use a minimal direct Windows Toast adapter

Windows notifications will load XML through `Windows.Data.Xml.Dom`, construct `ToastNotification` objects, and submit them with `ToastNotificationManager.create_toast_notifier_with_id("DaheLabs.PaperMonitor")`. The adapter owns only XML loading, stable tag/group assignment, explicit application identity, and `show`.

The former general-purpose `win11toast` dependency defaulted notifications to the `Python` identity and pulled media, OCR, playback, speech, imaging, globalization, and other WinRT feature families that Paper Monitor did not use. Keeping only the XML and notification namespaces fixes notification ownership and reduces the installed x64 runtime without changing lifecycle delivery semantics.
