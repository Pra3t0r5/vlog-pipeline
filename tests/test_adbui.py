import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "pipeline"))
import adbui

DUMP = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy rotation="0">
<node text="Rutas" content-desc="" clickable="true" bounds="[0,400][1080,560]"/>
<node text="Exportar datos de Rutas" content-desc="" clickable="true" bounds="[0,600][1080,760]"/>
<node text="Borrar datos de Rutas" content-desc="" clickable="true" bounds="[0,760][1080,920]"/>
</hierarchy>"""

OVERLAP = """<?xml version='1.0'?>
<hierarchy><node text="Exportar datos de Rutas" bounds="[0,600][1080,760]"/>
<node text="Borrar datos de Rutas" bounds="[0,650][1080,900]"/></hierarchy>"""

NOEXPORT = """<?xml version='1.0'?>
<hierarchy><node text="Exportar datos de Rutas y más" bounds="[0,600][1080,760]"/>
<node text="Borrar datos de Rutas" bounds="[0,760][1080,920]"/></hierarchy>"""


class Fake:
    def __init__(self, dumps, downloads):
        self.dumps, self.downloads, self.taps, self.calls = list(dumps), list(downloads), [], []

    def runner(self, args, timeout):
        self.calls.append(args)
        if args[:2] == ["exec-out", "cat"]:
            return self.dumps.pop(0) if len(self.dumps) > 1 else self.dumps[0]
        if args[:2] == ["shell", "ls"]:
            return "\n".join(self.downloads.pop(0) if len(self.downloads) > 1 else self.downloads[0])
        if args[:3] == ["shell", "input", "tap"]:
            self.taps.append((int(args[3]), int(args[4])))
        return ""

    def adb(self):
        return adbui.Adb(runner=self.runner)


class T(unittest.TestCase):
    def test_exact_match_and_center(self):
        n = adbui.parse_dump(DUMP)
        self.assertEqual(adbui.safe_tap_point(n, "Exportar datos de Rutas"), (540, 680))
        self.assertEqual(adbui.safe_tap_point(n, "Rutas"), (540, 480))

    def test_partial_label_is_not_a_match(self):
        with self.assertRaises(adbui.Abort):
            adbui.safe_tap_point(adbui.parse_dump(NOEXPORT), "Exportar datos de Rutas")

    def test_overlapping_delete_aborts(self):
        with self.assertRaises(adbui.Abort):
            adbui.safe_tap_point(adbui.parse_dump(OVERLAP), "Exportar datos de Rutas")

    def test_delete_label_never_tapped(self):
        with self.assertRaises(adbui.Abort):
            adbui.safe_tap_point(adbui.parse_dump(DUMP), "Borrar datos de Rutas")

    def test_flow_taps_only_export(self):
        f = Fake([DUMP], [["a.txt"], ["a.txt"], ["a.txt", "Rutas.json"]])
        got = adbui.export_timeline(f.adb(), sleep=lambda s: None)
        self.assertEqual(got, "Rutas.json")
        self.assertEqual(f.taps, [(540, 480), (540, 680)])

    def test_flow_aborts_when_label_missing_without_tapping_export(self):
        f = Fake([DUMP.replace("Exportar datos de Rutas", "Otra cosa")], [["a.txt"]])
        with self.assertRaises(adbui.Abort):
            adbui.export_timeline(f.adb(), sleep=lambda s: None)
        self.assertNotIn((540, 680), f.taps)

    def test_timeout_without_file(self):
        f = Fake([DUMP], [["a.txt"]])
        t = iter(range(0, 1000, 50))
        with self.assertRaises(adbui.Abort):
            adbui.export_timeline(f.adb(), timeout=100, sleep=lambda s: None, now=lambda: next(t))

    def test_device_ready(self):
        self.assertEqual(adbui.device_ready("List of devices attached\nSERIAL1\tdevice\n"), "SERIAL1")
        with self.assertRaises(adbui.Abort):
            adbui.device_ready("List of devices attached\nSERIAL1\tunauthorized\n")


if __name__ == "__main__":
    unittest.main()
