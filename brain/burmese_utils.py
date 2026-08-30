import re

def num_to_burmese(num: int) -> str:
    """Converts an integer to Burmese spoken text."""
    if num == 0: return 'သုည'
    
    digits = ['','တစ်','နှစ်','သုံး','လေး','ငါး','ခြောက်','ခုနစ်','ရှစ်','ကိုး']
    powers = ['','ဆယ်','ရာ','ထောင်','သောင်း','သိန်း','သန်း']
    
    s = str(num)
    n = len(s)
    
    if n > 7:
        millions = num // 1000000
        remainder = num % 1000000
        res = num_to_burmese(millions) + 'သန်း'
        if remainder > 0:
            res += ' ' + num_to_burmese(remainder)
        return res

    res = ''
    for i, char in enumerate(s):
        d = int(char)
        if d > 0:
            power = n - i - 1
            if d == 1 and power > 0:
                res += 'တစ်' + powers[power]
            else:
                res += digits[d] + powers[power]
    return res

def myanmar_digits_to_arabic(text: str) -> str:
    """Converts Myanmar digits (၀-၉) to Arabic (0-9) to standardize."""
    mm_digits = '၀၁၂၃၄၅၆၇၈၉'
    en_digits = '0123456789'
    trans = str.maketrans(mm_digits, en_digits)
    return text.translate(trans)

def replace_numbers_with_burmese(text: str) -> str:
    """Finds all numbers in a string and replaces them with Burmese spelled-out words."""
    # First normalize any Myanmar digits to Arabic digits for easier regex matching
    text = myanmar_digits_to_arabic(text)
    
    def replacer(match):
        num_str = match.group(0)
        # Remove commas if any (e.g. 1,000)
        num_str = num_str.replace(",", "")
        try:
            return num_to_burmese(int(num_str))
        except ValueError:
            return num_str

    # Match numbers (with optional commas)
    # \d{1,3}(?:,\d{3})* matches numbers like 1,000,000 or 5000
    # Also match plain sequences of digits
    pattern = re.compile(r'\d{1,3}(?:,\d{3})+|\d+')
    return pattern.sub(replacer, text)
