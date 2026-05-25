import unittest
from unittest.mock import patch

import main


class MainCliTests(unittest.TestCase):
    def test_confirm_prompt_shows_yes_default_value(self):
        prompts = []

        def fake_input(prompt):
            prompts.append(prompt)
            return ""

        with patch("builtins.input", fake_input):
            self.assertTrue(main.confirm("是否立即生成复习资料？", default=True))

        self.assertIn("[Y/n](y)", prompts[0])

    def test_confirm_prompt_shows_no_default_value(self):
        prompts = []

        def fake_input(prompt):
            prompts.append(prompt)
            return ""

        with patch("builtins.input", fake_input):
            self.assertFalse(main.confirm("是否立即生成复习资料？", default=False))

        self.assertIn("[y/N](n)", prompts[0])


if __name__ == "__main__":
    unittest.main()
