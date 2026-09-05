import re

# Standard Myanmar digits and spoken words
DIGITS = ['', 'တစ်', 'နှစ်', 'သုံး', 'လေး', 'ငါး', 'ခြောက်', 'ခုနစ်', 'ရှစ်', 'ကိုး']
DIGIT_MAP = {
    '0': 'သုည', '1': 'တစ်', '2': 'နှစ်', '3': 'သုံး', '4': 'လေး',
    '5': 'ငါး', '6': 'ခြောက်', '7': 'ခုနစ်', '8': 'ရှစ်', '9': 'ကိုး'
}

# Common English movie/drama acronyms and terms -> Burmese phonetics
COMMON_ACRONYMS_MM = {
    r'\bCCTV\b': 'စီစီတီဗီ',
    r'\bVIP\b': 'ဗွီအိုင်ပီ',
    r'\bVVIP\b': 'ဗွီဗွီအိုင်ပီ',
    r'\bFBI\b': 'အက်ဖ်ဘီအိုင်',
    r'\bCIA\b': 'စီအိုင်အေ',
    r'\bCEO\b': 'စီအီးအို',
    r'\bAI\b': 'အေအိုင်',
    r'\bOK\b': 'အိုကေ',
    r'\bO\.K\.\b': 'အိုကေ',
    r'\bUSB\b': 'ယူအက်စ်ဘီ',
    r'\bSIM\b': 'ဆင်းမ်',
    r'\bGPS\b': 'ဂျီပီအက်စ်',
    r'\bTV\b': 'တီဗီ',
    r'\bPC\b': 'ပီစီ',
    r'\biPhone\b': 'အိုင်ဖုန်း',
    r'\biPad\b': 'အိုင်ပတ်',
    r'\bID\b': 'အိုင်ဒီ',
    r'\bSOS\b': 'အက်စ်အိုအက်စ်',
    r'\bPDF\b': 'ပီဒီအက်ဖ်',
    r'\bApp\b': 'အက်ပ်',
    r'\bApps\b': 'အက်ပ်များ',
    r'\bWifi\b': 'ဝိုင်ဖိုင်',
    r'\bWi-Fi\b': 'ဝိုင်ဖိုင်',
    r'\bDoctor\b': 'ဒေါက်တာ',
    r'\bDr\.\b': 'ဒေါက်တာ',
    r'\bBoss\b': 'ဘော့စ်',
    r'\bHello\b': 'ဟယ်လို',
    r'\bHi\b': 'ဟိုင်း',
    r'\bHey\b': 'ဟေး',
    r'\bBye\b': 'တာ့တာ',
    r'\bBye-bye\b': 'ဘိုင်ဘိုင်း',
    r'\bDNA\b': 'ဒီအင်န်အေ',
    r'\bATM\b': 'အေတီအမ်',
    r'\bKTV\b': 'ကေတီဗီ',
    r'\bDJ\b': 'ဒီဂျေ',
    r'\bBMW\b': 'ဘီအမ်ဒဗလျူ',
    r'\bSUV\b': 'အက်စ်ယူဗီ',
    r'\bUFO\b': 'ယူအက်ဖ်အို',
    r'\bFacebook\b': 'ဖေ့စ်ဘွတ်ခ်',
    r'\bTikTok\b': 'တစ်တော့ခ်',
    r'\bYouTube\b': 'ယူကျုဘ်',
    r'\bSMS\b': 'မက်ဆေ့ခ်ျ',
    r'\bOT\b': 'အိုတီ',
    r'\bOP\b': 'အိုပီ',
    r'\bPUBG\b': 'ပတ်ဂျီ',
    r'\bNASA\b': 'နာဆာ',
    r'\bSWAT\b': 'ဆွတ်တ်',
    r'\bSir\b': 'ဆာ',
    r'\bMadam\b': 'မဒမ်',
    r'\bMr\.\b': 'မစ္စတာ',
    r'\bMrs\.\b': 'မစ္စစ်',
    r'\bMiss\b': 'မစ်',
}

# Individual phonetic letter transliterations for remaining uppercase acronyms
EN_LETTER_TO_MM = {
    'A': 'အေ', 'B': 'ဘီ', 'C': 'စီ', 'D': 'ဒီ', 'E': 'အီး',
    'F': 'အက်ဖ်', 'G': 'ဂျီ', 'H': 'အိတ်ခ်ျ', 'I': 'အိုင်', 'J': 'ဂျေ',
    'K': 'ကေ', 'L': 'အယ်လ်', 'M': 'အမ်', 'N': 'အန်', 'O': 'အို',
    'P': 'ပီ', 'Q': 'ကျူ', 'R': 'အာရ်', 'S': 'အက်စ်', 'T': 'တီ',
    'U': 'ယူ', 'V': 'ဗွီ', 'W': 'ဒဗလျူ', 'X': 'အက်စ်', 'Y': 'ဝိုင်', 'Z': 'ဇက်'
}


def num_to_burmese(num: int) -> str:
    """
    Converts an integer to natural colloquial Burmese spoken text.
    Handles everyday spoken patterns:
      10 -> ဆယ်
      11 -> ဆယ့်တစ်, 15 -> ဆယ့်ငါး
      20 -> နှစ်ဆယ်, 25 -> နှစ်ဆယ့်ငါး
      100 -> တစ်ရာ, 105 -> တစ်ရာ့ငါး, 125 -> တစ်ရာ့နှစ်ဆယ့်ငါး
      1000 -> တစ်ထောင်, 2026 -> နှစ်ထောင့်နှစ်ဆယ့်ခြောက်
      100,000 -> တစ်သိန်း
    """
    if num == 0:
        return 'သုည'
    if num < 0:
        return 'အနှုတ် ' + num_to_burmese(-num)

    if num >= 10_000_000:
        millions = num // 1_000_000
        rem = num % 1_000_000
        res = num_to_burmese(millions) + 'သန်း'
        if rem > 0:
            res += ' ' + num_to_burmese(rem)
        return res

    # Single digit
    if num < 10:
        return DIGITS[num]

    # Exactly 10
    if num == 10:
        return 'ဆယ်'

    # Teens: 11 - 19
    if 11 <= num <= 19:
        return 'ဆယ့်' + DIGITS[num - 10]

    # Tens: 20 - 99
    if 20 <= num < 100:
        tens = num // 10
        units = num % 10
        if units == 0:
            return DIGITS[tens] + 'ဆယ်'
        return DIGITS[tens] + 'ဆယ့်' + DIGITS[units]

    # Hundreds: 100 - 999
    if num < 1000:
        h = num // 100
        rem = num % 100
        prefix = DIGITS[h] + ('ရာ' if rem == 0 else 'ရာ့')
        return prefix + (num_to_burmese(rem) if rem > 0 else '')

    # Thousands: 1,000 - 9,999
    if num < 10000:
        th = num // 1000
        rem = num % 1000
        prefix = DIGITS[th] + ('ထောင်' if rem == 0 else 'ထောင့်')
        return prefix + (num_to_burmese(rem) if rem > 0 else '')

    # Ten-thousands: 10,000 - 99,999 (သောင်း)
    if num < 100000:
        tt = num // 10000
        rem = num % 10000
        prefix = DIGITS[tt] + 'သောင်း'
        return prefix + (' ' + num_to_burmese(rem) if rem > 0 else '')

    # Lakh / Hundred-thousands: 100,000 - 9,999,999 (သိန်း)
    if num < 10000000:
        lakh = num // 100000
        rem = num % 100000
        prefix = num_to_burmese(lakh) + 'သိန်း'
        return prefix + (' ' + num_to_burmese(rem) if rem > 0 else '')

    return str(num)


def myanmar_digits_to_arabic(text: str) -> str:
    """Converts Myanmar digits (၀-၉) to Arabic (0-9) to standardize."""
    mm_digits = '၀၁၂၃၄၅၆၇၈၉'
    en_digits = '0123456789'
    trans = str.maketrans(mm_digits, en_digits)
    return text.translate(trans)


def replace_numbers_with_burmese(text: str) -> str:
    """
    Finds all numbers (integers and decimals) in a string and replaces
    them with natural Burmese spoken words.
    e.g. '2.5' -> 'နှစ် ဒသမ ငါး'
         '15'  -> 'ဆယ့်ငါး'
         '1,500' -> 'တစ်ထောင့်ငါးရာ'
    """
    if not text:
        return ""

    text = myanmar_digits_to_arabic(str(text))

    def replacer(match):
        val = match.group(0).replace(",", "")
        # Decimal numbers (e.g. 2.5, 0.05)
        if "." in val:
            parts = val.split(".")
            int_part = int(parts[0]) if parts[0] else 0
            frac_digits = ''.join(DIGIT_MAP.get(d, d) for d in parts[1])
            int_words = 'သုည' if int_part == 0 else num_to_burmese(int_part)
            return f"{int_words} ဒသမ {frac_digits}"

        try:
            return num_to_burmese(int(val))
        except ValueError:
            return match.group(0)

    # Match floats first (e.g. 1,000.50 or 2.5), then plain integers with commas or digits
    pattern = re.compile(r'\d+(?:,\d+)*\.\d+|\d{1,3}(?:,\d{3})+|\d+')
    return pattern.sub(replacer, text)


def transliterate_english_acronyms(text: str) -> str:
    """
    Transliterates English acronyms, abbreviations, and common movie terms into
    natural Burmese phonetics so TTS reads them aloud clearly without skipping.
    e.g. 'CCTV' -> 'စီစီတီဗီ'
         'VIP'  -> 'ဗွီအိုင်ပီ'
         'CEO'  -> 'စီအီးအို'
    """
    if not text:
        return ""

    # 1. Map known terms and acronyms (case-insensitive)
    for pattern, replacement in COMMON_ACRONYMS_MM.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    # 2. Phonetic transliteration for any remaining uppercase acronyms (e.g. BMW, KTV, XYZ)
    def letter_replacer(m):
        chars = [EN_LETTER_TO_MM.get(c.upper(), c) for c in m.group(0)]
        return ''.join(chars)

    text = re.sub(r'\b[A-Z]{2,6}\b', letter_replacer, text)
    return text
