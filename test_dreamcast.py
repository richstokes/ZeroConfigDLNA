"""Tests for --dreamcast-mode stream sizing and ffmpeg arguments."""

import unittest

import dreamcast

FULL_HD = {"width": 1920, "height": 1080, "sar": 1.0, "fps": 24000 / 1001}
DVD_43 = {"width": 720, "height": 480, "sar": 8 / 9, "fps": 30000 / 1001}


class OutputSizeTest(unittest.TestCase):
    """The picture fits the box and the decode budget in whole macroblocks."""

    def profile(self, **overrides):
        profile = dict(dreamcast.DEFAULT_PROFILE)
        profile.update(overrides)
        return profile

    def test_sizes_are_macroblock_multiples(self):
        for budget in (3000, 7500, 12000, 20000, 40000):
            _, _, width, height = dreamcast.output_size(
                FULL_HD, self.profile(mb_per_sec=budget), 24000 / 1001
            )
            self.assertEqual(width % 16, 0)
            self.assertEqual(height % 16, 0)

    def test_budget_limits_macroblocks_per_second(self):
        fps = 24000 / 1001
        for budget in (3000, 7500, 12000, 20000):
            _, _, width, height = dreamcast.output_size(
                FULL_HD, self.profile(mb_per_sec=budget), fps
            )
            self.assertLessEqual((width // 16) * (height // 16) * fps, budget)

    def test_box_limits_size(self):
        _, _, width, height = dreamcast.output_size(
            FULL_HD, self.profile(mb_per_sec=40000), 24
        )
        self.assertEqual((width, height), (640, 352))

    def test_keeps_display_aspect_of_anamorphic_source(self):
        scaled_w, scaled_h, _, _ = dreamcast.output_size(
            DVD_43, self.profile(mb_per_sec=40000), 30
        )
        self.assertAlmostEqual(scaled_w / scaled_h, 4 / 3, delta=0.02)

    def test_never_upscales(self):
        tiny = {"width": 160, "height": 120, "sar": 1.0, "fps": 25}
        _, _, width, height = dreamcast.output_size(tiny, self.profile(), 25)
        self.assertEqual((width, height), (160, 112))


class OutputRateTest(unittest.TestCase):
    """Frame rates are ones MPEG-1 can signal, at most max_fps."""

    def test_film_rate_kept(self):
        self.assertEqual(dreamcast.output_rate(24000 / 1001, 30)[0], "24000/1001")

    def test_sixty_halved(self):
        self.assertEqual(dreamcast.output_rate(60000 / 1001, 30)[0], "30000/1001")

    def test_fifty_halved(self):
        self.assertEqual(dreamcast.output_rate(50, 30)[0], "25")


class CommandTest(unittest.TestCase):
    """Query parameters reach ffmpeg."""

    def test_query_overrides(self):
        profile = dreamcast.parse_profile(
            {"t": ["90.5"], "d": ["10"], "a": ["pcm"], "mbs": ["20000"], "w": ["9999"]}
        )
        self.assertEqual(profile["start"], 90.5)
        self.assertEqual(profile["length"], 10)
        self.assertEqual(profile["audio"], "pcm")
        self.assertEqual(profile["mb_per_sec"], 20000)
        self.assertEqual(profile["width"], 640)

        command = dreamcast.build_command("in.mkv", profile, FULL_HD)
        self.assertEqual(command[command.index("-ss") + 1], "90.500")
        self.assertEqual(command[command.index("-t") + 1], "10.000")
        self.assertEqual(command[command.index("-c:v") + 1], "mpeg1video")
        self.assertEqual(command[command.index("-bf") + 1], "0")
        self.assertEqual(command[command.index("-c:a") + 1], "pcm_s16le")
        self.assertEqual(command[-3:], ["-f", "avi", "pipe:1"])

    def test_fill_crops_widescreen_to_four_by_three(self):
        profile = dreamcast.parse_profile({"fill": ["1.333"], "mbs": ["40000"]})
        command = dreamcast.build_command("in.mkv", profile, FULL_HD)
        video_filter = command[command.index("-vf") + 1]
        self.assertTrue(video_filter.startswith("crop=1438:1080,scale=640:480"))

    def test_fill_leaves_narrow_pictures_alone(self):
        info, crop = dreamcast.crop_to_fill(DVD_43, 1.333)
        self.assertEqual(crop, "")
        self.assertIs(info, DVD_43)

    def test_audio_only(self):
        command = dreamcast.build_command("song.flac", dreamcast.parse_profile({}), None)
        self.assertIn("-vn", command)
        self.assertNotIn("-c:v", command)


if __name__ == "__main__":
    unittest.main()
