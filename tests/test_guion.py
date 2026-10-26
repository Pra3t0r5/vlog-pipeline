import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "pipeline"))

import ffx
import guion


def make(shots, media=None):
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "inv").mkdir()
    media = media or [
        {"id": "drone.A", "path": "/x/A.MP4", "kind": "video", "w": 3840, "h": 2160, "dur": 20.0, "has_audio": False},
        {"id": "phone.B", "path": "/x/B.mp4", "kind": "video", "w": 1080, "h": 1920, "dur": 10.0, "has_audio": True, "audio_lufs": -20},
        {"id": "phone.C", "path": "/x/C.jpg", "kind": "photo", "w": 3060, "h": 4080},
    ]
    (d / "inv" / "media.json").write_text(json.dumps(media))
    (d / "g.json").write_text(json.dumps({"name": "t", "shots": shots}))
    G = guion.Guion(d / "g.json", "preview")
    G.resolve(ffx.Report())
    return G


class GuionTest(unittest.TestCase):
    def test_layout_overlaps(self):
        G = make([{"id": "drone.A", "in": 0, "out": 5}, {"id": "drone.A", "in": 5, "out": 10}, {"id": "drone.A", "in": 10, "out": 15, "transition": "cut"}])
        a, b, c = G.shots
        self.assertEqual(b.start, a.n - b.xn)
        self.assertEqual(c.xn, 0)
        self.assertEqual(c.start, b.start + b.n)
        self.assertEqual(G.total_frames, c.start + c.n)

    def test_src_stem_and_clip_to_available(self):
        G = make([{"src": "A", "in": 15, "out": 30}])
        self.assertEqual(G.shots[0].rec["id"], "drone.A")
        self.assertLess(G.shots[0].dur, 5)

    def test_audio_keep_needs_audio(self):
        r = ffx.Report()
        G = make([{"id": "drone.A", "dur": 3, "audio": "keep"}, {"id": "phone.B", "dur": 3, "audio": "keep"}])
        self.assertEqual([s.audio for s in G.shots], ["mute", "keep"])

    def test_too_short_for_transitions(self):
        with self.assertRaises(ffx.RenderError):
            make([{"id": "drone.A", "dur": 3}, {"id": "drone.A", "dur": 0.5}, {"id": "drone.A", "dur": 3}])

    def test_unknown_media(self):
        with self.assertRaises(ffx.RenderError):
            make([{"id": "nope"}])


if __name__ == "__main__":
    unittest.main()
