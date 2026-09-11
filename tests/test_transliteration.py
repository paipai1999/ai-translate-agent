import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from brain.burmese_utils import (
    replace_numbers_with_burmese,
    transliterate_english_acronyms,
    num_to_burmese,
    myanmar_digits_to_arabic,
)

class TestTransliteration(unittest.TestCase):

    def test_number_conversion(self):
        """Verify digits are converted to colloquial spoken Burmese."""
        self.assertEqual(num_to_burmese(0), "သုည")
        self.assertEqual(num_to_burmese(1), "တစ်")
        self.assertEqual(num_to_burmese(10), "ဆယ်")
        self.assertEqual(num_to_burmese(15), "ဆယ့်ငါး")
        self.assertEqual(num_to_burmese(100), "တစ်ရာ")

    def test_replace_numbers_in_sentence(self):
        """Verify inline numbers are translated into natural Burmese words."""
        text = "သူက အခန်း 105 မှာ 2.5 နာရီကြာ နေခဲ့တယ်"
        res = replace_numbers_with_burmese(text)
        self.assertNotIn("105", res)
        self.assertNotIn("2.5", res)
        self.assertIn("ဒသမ", res)

    def test_common_acronyms_transliteration(self):
        """Verify common acronyms are transliterated phonetically."""
        self.assertEqual(transliterate_english_acronyms("CCTV"), "စီစီတီဗီ")
        self.assertEqual(transliterate_english_acronyms("VIP"), "ဗွီအိုင်ပီ")
        self.assertEqual(transliterate_english_acronyms("Doctor"), "ဒေါက်တာ")
        self.assertEqual(transliterate_english_acronyms("AI"), "အေအိုင်")
        self.assertEqual(transliterate_english_acronyms("CEO"), "စီအီးအို")

    def test_character_names_transliteration(self):
        """Verify English character names are transliterated without disappearing."""
        names_sentence = "Arthur told Jack and Parker about the Titan Caldwell project."
        res = transliterate_english_acronyms(names_sentence)
        self.assertIn("အာသာ", res)
        self.assertIn("ဂျက်ခ်", res)
        self.assertIn("ပါကာ", res)
        self.assertIn("တိုက်တန်", res)
        self.assertIn("ကောလ်ဝဲလ်", res)

    def test_myanmar_digits_normalization(self):
        """Verify Myanmar digits are standardized to Arabic before word conversion."""
        self.assertEqual(myanmar_digits_to_arabic("၁၂၃"), "123")
        self.assertEqual(myanmar_digits_to_arabic("၀၄၅"), "045")

if __name__ == "__main__":
    unittest.main()
