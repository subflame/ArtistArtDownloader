"""Transliteration maps for non-Latin scripts (Cyrillic, CJK, Japanese, Korean).

Used by fetcher.py to convert artist names to URL-safe ASCII slugs.
All maps are module-level constants for reuse across the application.
"""

# ---------------------------------------------------------------------------
# Cyrillic -> Latin
# ---------------------------------------------------------------------------

CYRILLIC_MAP = str.maketrans({
    "\u0430": "a", "\u0431": "b", "\u0432": "v", "\u0433": "g", "\u0434": "d", "\u0435": "e", "\u0451": "yo",
    "\u0436": "zh", "\u0437": "z", "\u0438": "i", "\u0439": "y", "\u043a": "k", "\u043b": "l", "\u043c": "m",
    "\u043d": "n", "\u043e": "o", "\u043f": "p", "\u0440": "r", "\u0441": "s", "\u0442": "t", "\u0443": "u",
    "\u0444": "f", "\u0445": "kh", "\u0446": "ts", "\u0447": "ch", "\u0448": "sh", "\u0449": "shch",
    "\u044a": "", "\u044b": "y", "\u044c": "", "\u044d": "e", "\u044e": "yu", "\u044f": "ya",
    "\u0410": "A", "\u0411": "B", "\u0412": "V", "\u0413": "G", "\u0414": "D", "\u0415": "E", "\u0401": "Yo",
    "\u0416": "Zh", "\u0417": "Z", "\u0418": "I", "\u0419": "Y", "\u041a": "K", "\u041b": "L", "\u041c": "M",
    "\u041d": "N", "\u041e": "O", "\u041f": "P", "\u0420": "R", "\u0421": "S", "\u0422": "T", "\u0423": "U",
    "\u0424": "F", "\u0425": "Kh", "\u0426": "Ts", "\u0427": "Ch", "\u0428": "Sh", "\u0429": "Shch",
    "\u042a": "", "\u042b": "Y", "\u042c": "", "\u042d": "E", "\u042e": "Yu", "\u042f": "Ya",
    # Extended Cyrillic (non-Russian languages)
    "\u0452": "dj", "\u0453": "gj", "\u0454": "je", "\u0455": "s", "\u0456": "i", "\u0457": "yi",
    "\u0458": "j", "\u0459": "lj", "\u045a": "nj", "\u045b": "c", "\u045c": "k", "\u045e": "u", "\u045f": "dz",
    "\u0402": "Dj", "\u0403": "Gj", "\u0404": "Je", "\u0405": "S", "\u0406": "I", "\u0407": "Yi",
    "\u0408": "J", "\u0409": "Lj", "\u040a": "Nj", "\u040b": "C", "\u040c": "K", "\u040e": "U", "\u040f": "Dz",
})

# ---------------------------------------------------------------------------
# Japanese hiragana -> romaji
# ---------------------------------------------------------------------------

HIRAGANA_MAP = str.maketrans({
    "\u3042": "a", "\u3044": "i", "\u3046": "u", "\u3048": "e", "\u304a": "o",
    "\u304b": "ka", "\u304d": "ki", "\u304f": "ku", "\u3051": "ke", "\u3053": "ko",
    "\u3055": "sa", "\u3057": "shi", "\u3059": "su", "\u305b": "se", "\u305d": "so",
    "\u305f": "ta", "\u3061": "chi", "\u3064": "tsu", "\u3066": "te", "\u3068": "to",
    "\u306a": "na", "\u306b": "ni", "\u306c": "nu", "\u306d": "ne", "\u306e": "no",
    "\u306f": "ha", "\u3072": "hi", "\u3075": "fu", "\u3078": "he", "\u307b": "ho",
    "\u307e": "ma", "\u307f": "mi", "\u3080": "mu", "\u3081": "me", "\u3082": "mo",
    "\u3084": "ya", "\u3086": "yu", "\u3088": "yo",
    "\u3089": "ra", "\u308a": "ri", "\u308b": "ru", "\u308c": "re", "\u308d": "ro",
    "\u308f": "wa", "\u3090": "wi", "\u3091": "we", "\u3092": "wo", "\u3093": "n",
    "\u304c": "ga", "\u304e": "gi", "\u3050": "gu", "\u3052": "ge", "\u3054": "go",
    "\u3056": "za", "\u3058": "ji", "\u305a": "zu", "\u305c": "ze", "\u305e": "zo",
    "\u3060": "da", "\u3062": "ji", "\u3065": "zu", "\u3067": "de", "\u3069": "do",
    "\u3070": "ba", "\u3073": "bi", "\u3076": "bu", "\u3079": "be", "\u307c": "bo",
    "\u3071": "pa", "\u3074": "pi", "\u3077": "pu", "\u307a": "pe", "\u307d": "po",
    "\u3063": "",
    # Small kana
    "\u3041": "a", "\u3043": "i", "\u3045": "u", "\u3047": "e", "\u3049": "o",
    # Vu and small ka/ke
    "\u3094": "vu", "\u3095": "ka", "\u3096": "ke",
})

HIRAGANA_MULTI = [
    ("\u304d\u3083", "kya"), ("\u304d\u3086", "kyu"), ("\u304d\u3087", "kyo"),
    ("\u3057\u3083", "sha"), ("\u3057\u3086", "shu"), ("\u3057\u3087", "sho"),
    ("\u3061\u3083", "cha"), ("\u3061\u3086", "chu"), ("\u3061\u3087", "cho"),
    ("\u306b\u3083", "nya"), ("\u306b\u3086", "nyu"), ("\u306b\u3087", "nyo"),
    ("\u3072\u3083", "hya"), ("\u3072\u3086", "hyu"), ("\u3072\u3087", "hyo"),
    ("\u307f\u3083", "mya"), ("\u307f\u3086", "myu"), ("\u307f\u3087", "myo"),
    ("\u308a\u3083", "rya"), ("\u308a\u3086", "ryu"), ("\u308a\u3087", "ryo"),
    ("\u304e\u3083", "gya"), ("\u304e\u3086", "gyu"), ("\u304e\u3087", "gyo"),
    ("\u3058\u3083", "ja"), ("\u3058\u3086", "ju"), ("\u3058\u3087", "jo"),
    ("\u3073\u3083", "bya"), ("\u3073\u3086", "byu"), ("\u3073\u3087", "byo"),
    ("\u3074\u3083", "pya"), ("\u3074\u3086", "pyu"), ("\u3074\u3087", "pyo"),
]

# ---------------------------------------------------------------------------
# Japanese katakana -> romaji
# ---------------------------------------------------------------------------

KATAKANA_MAP = str.maketrans({
    "\u30a2": "a", "\u30a4": "i", "\u30a6": "u", "\u30a8": "e", "\u30aa": "o",
    "\u30ab": "ka", "\u30ad": "ki", "\u30af": "ku", "\u30b1": "ke", "\u30b3": "ko",
    "\u30b5": "sa", "\u30b7": "shi", "\u30b9": "su", "\u30bb": "se", "\u30bd": "so",
    "\u30bf": "ta", "\u30c1": "chi", "\u30c4": "tsu", "\u30c6": "te", "\u30c8": "to",
    "\u30ca": "na", "\u30cb": "ni", "\u30cc": "nu", "\u30cd": "ne", "\u30ce": "no",
    "\u30cf": "ha", "\u30d2": "hi", "\u30d5": "fu", "\u30d8": "he", "\u30db": "ho",
    "\u30de": "ma", "\u30df": "mi", "\u30e0": "mu", "\u30e1": "me", "\u30e2": "mo",
    "\u30e4": "ya", "\u30e6": "yu", "\u30e8": "yo",
    "\u30e9": "ra", "\u30ea": "ri", "\u30eb": "ru", "\u30ec": "re", "\u30ed": "ro",
    "\u30ef": "wa", "\u30f2": "wo", "\u30f3": "n",
    "\u30ac": "ga", "\u30ae": "gi", "\u30b0": "gu", "\u30b2": "ge", "\u30b4": "go",
    "\u30b6": "za", "\u30b8": "ji", "\u30ba": "zu", "\u30bc": "ze", "\u30be": "zo",
    "\u30c0": "da", "\u30c2": "ji", "\u30c5": "zu", "\u30c7": "de", "\u30c9": "do",
    "\u30d0": "ba", "\u30d3": "bi", "\u30d6": "bu", "\u30d9": "be", "\u30dc": "bo",
    "\u30d1": "pa", "\u30d4": "pi", "\u30d7": "pu", "\u30da": "pe", "\u30dd": "po",
    "\u30c3": "",
    # Small kana
    "\u30a1": "a", "\u30a3": "i", "\u30a5": "u", "\u30a7": "e", "\u30a9": "o",
    # Vu, small ka/ke, small wa
    "\u30f4": "vu", "\u30f5": "ka", "\u30f6": "ke", "\u30ee": "wa",
    # Archaic wi/we
    "\u30f0": "i", "\u30f1": "e",
    # Long vowel mark (remove) and middle dot (space)
    "\u30fc": "", "\u30fb": " ",
})

KATAKANA_MULTI = [
    ("\u30ad\u30e3", "kya"), ("\u30ad\u30e6", "kyu"), ("\u30ad\u30e7", "kyo"),
    ("\u30b7\u30e3", "sha"), ("\u30b7\u30e6", "shu"), ("\u30b7\u30e7", "sho"),
    ("\u30c1\u30e3", "cha"), ("\u30c1\u30e6", "chu"), ("\u30c1\u30e7", "cho"),
    ("\u30cb\u30e3", "nya"), ("\u30cb\u30e6", "nyu"), ("\u30cb\u30e7", "nyo"),
    ("\u30d2\u30e3", "hya"), ("\u30d2\u30e6", "hyu"), ("\u30d2\u30e7", "hyo"),
    ("\u30df\u30e3", "mya"), ("\u30df\u30e6", "myu"), ("\u30df\u30e7", "myo"),
    ("\u30ea\u30e3", "rya"), ("\u30ea\u30e6", "ryu"), ("\u30ea\u30e7", "ryo"),
    ("\u30ae\u30e3", "gya"), ("\u30ae\u30e6", "gyu"), ("\u30ae\u30e7", "gyo"),
    ("\u30b8\u30e3", "ja"), ("\u30b8\u30e6", "ju"), ("\u30b8\u30e7", "jo"),
    ("\u30d3\u30e3", "bya"), ("\u30d3\u30e6", "byu"), ("\u30d3\u30e7", "byo"),
    ("\u30d4\u30e3", "pya"), ("\u30d4\u30e6", "pyu"), ("\u30d4\u30e7", "pyo"),
    # Palatalized consonants with small ya/yu/yo
    ("\u30c6\u30e3", "tya"), ("\u30c6\u30e5", "tyu"), ("\u30c6\u30e7", "tyo"),
    ("\u30c7\u30e3", "dya"), ("\u30c7\u30e5", "dyu"), ("\u30c7\u30e7", "dyo"),
    ("\u30d5\u30e3", "fya"), ("\u30d5\u30e5", "fyu"), ("\u30d5\u30e7", "fyo"),
    ("\u30f4\u30e3", "vya"), ("\u30f4\u30e5", "vyu"), ("\u30f4\u30e7", "vyo"),
    # Extended katakana for loanwords
    ("\u30c6\u30a3", "ti"), ("\u30c7\u30a3", "di"),
    ("\u30c8\u30a5", "tu"), ("\u30c9\u30a5", "du"),
    ("\u30d5\u30a1", "fa"), ("\u30d5\u30a3", "fi"),
    ("\u30d5\u30a7", "fe"), ("\u30d5\u30a9", "fo"),
    ("\u30f4\u30a1", "va"), ("\u30f4\u30a3", "vi"),
    ("\u30f4\u30a7", "ve"), ("\u30f4\u30a9", "vo"),
    ("\u30a6\u30a3", "wi"), ("\u30a6\u30a7", "we"), ("\u30a6\u30a9", "wo"),
    ("\u30c4\u30a1", "tsa"), ("\u30c4\u30a3", "tsi"),
    ("\u30c4\u30a7", "tse"), ("\u30c4\u30a9", "tso"),
]

# ---------------------------------------------------------------------------
# Korean hangul -> romanization
# ---------------------------------------------------------------------------

HANGUL_MAP = str.maketrans({
    "\u1100": "g", "\u1101": "kk", "\u1102": "n", "\u1103": "d", "\u1104": "tt",
    "\u1105": "r", "\u1106": "m", "\u1107": "b", "\u1108": "pp", "\u1109": "s",
    "\u110a": "ss", "\u110b": "", "\u110c": "j", "\u110d": "jj", "\u110e": "ch",
    "\u110f": "k", "\u1110": "t", "\u1111": "p", "\u1112": "h",
    "\u1161": "a", "\u1162": "ae", "\u1163": "ya", "\u1164": "yae", "\u1165": "eo",
    "\u1166": "e", "\u1167": "yeo", "\u1168": "ye", "\u1169": "o", "\u116a": "wa",
    "\u116b": "wae", "\u116c": "wo", "\u116d": "yo", "\u116e": "u", "\u116f": "wo",
    "\u1170": "we", "\u1171": "wi", "\u1172": "yu", "\u1173": "eu", "\u1174": "ui",
    "\u1175": "i",
    # Jongseong (final consonants)
    "\u11a8": "k", "\u11a9": "kk", "\u11aa": "ks",
    "\u11ab": "n", "\u11ac": "nj", "\u11ad": "nh",
    "\u11ae": "t", "\u11af": "l", "\u11b0": "lk", "\u11b1": "lm", "\u11b2": "lb",
    "\u11b3": "ls", "\u11b4": "lt", "\u11b5": "lp", "\u11b6": "lh",
    "\u11b7": "m", "\u11b8": "b", "\u11b9": "bs",
    "\u11ba": "s", "\u11bb": "ss", "\u11bc": "ng", "\u11bd": "j",
    "\u11be": "ch", "\u11bf": "k", "\u11c0": "t", "\u11c1": "p", "\u11c2": "h",
})

# ---------------------------------------------------------------------------
# Common Chinese characters -> pinyin (common surname/artist-name characters)
# ---------------------------------------------------------------------------

CHINESE_MAP = str.maketrans({
    # Common Chinese surnames
    "\u738b": "wang", "\u674e": "li", "\u5f20": "zhang", "\u5218": "liu", "\u9648": "chen",
    "\u6768": "yang", "\u9ec4": "huang", "\u5468": "zhou", "\u5434": "wu", "\u5f90": "xu",
    "\u5b59": "sun", "\u9a6c": "ma", "\u6731": "zhu", "\u80e1": "hu", "\u90ed": "guo",
    "\u4f55": "he", "\u6797": "lin", "\u9ad8": "gao", "\u7f57": "luo", "\u6881": "liang",
    "\u5b8b": "song", "\u5510": "tang", "\u8c22": "xie", "\u97e9": "han", "\u51af": "feng",
    "\u865e": "yu", "\u8463": "dong", "\u8427": "xiao", "\u7a0b": "cheng", "\u66f9": "cao",
    "\u5143": "yuan", "\u9093": "deng", "\u8bb8": "xu", "\u5bcc": "fu", "\u6c88": "shen",
    "\u5f6d": "peng", "\u5415": "lv", "\u82cf": "su", "\u5362": "lu", "\u6c5f": "jiang",
    "\u59dc": "jiang", "\u8521": "cai", "\u4e01": "ding", "\u97e6": "wei", "\u53f6": "ye",
    "\u95fb": "wen", "\u7389": "yu", "\u6f58": "pan", "\u675c": "du", "\u6234": "dai",
    "\u590f": "xia", "\u949f": "zhong", "\u6c6a": "wang", "\u7530": "tian", "\u4ec1": "ren",
    "\u5e06": "fan", "\u65b9": "fang", "\u77f3": "shi", "\u59da": "yao", "\u8c2d": "tan",
    "\u5ed6": "liao", "\u90b9": "zou", "\u718a": "xiong", "\u91d1": "jin", "\u5b54": "kong",
    "\u767d": "bai", "\u5d14": "cui", "\u5eb7": "kang", "\u8305": "mao", "\u4ec7": "qiu",
    "\u7434": "qin", "\u4faf": "hou", "\u90b5": "shao", "\u5b5f": "meng", "\u9f99": "long",
    "\u4e07": "wan", "\u7aef": "duan", "\u96f7": "lei", "\u94b1": "qian", "\u6bb7": "yin",
    "\u798f": "fu", "\u7faa": "yi", "\u660c": "chang", "\u4fa8": "qiao", "\u8d56": "lai",
    "\u5de5": "gong", "\u6587": "wen", "\u534e": "hua", "\u65ed": "xu",
    # Artist-related characters
    "\u6b4c": "ge", "\u821e": "wu", "\u4e50": "le", "\u97f3": "yin",
    "\u58f0": "sheng", "\u8c03": "diao", "\u66f2": "qu", "\u8bcd": "ci",
    "\u8bd7": "shi", "\u4e66": "shu", "\u753b": "hua", "\u58a8": "mo",
    "\u7b14": "bi", "\u68cb": "qi", "\u9e1f": "niao", "\u9c7c": "yu",
    "\u866b": "chong", "\u517d": "shou",
})

# ---------------------------------------------------------------------------
# Combined list of all single-char transliteration maps
# ---------------------------------------------------------------------------

ALL_TRANSLIT_MAPS = [CYRILLIC_MAP, HIRAGANA_MAP, KATAKANA_MAP, HANGUL_MAP, CHINESE_MAP]

# Combined list of multi-char sequences (must run before single-char maps)
ALL_MULTI_SEQUENCES = HIRAGANA_MULTI + KATAKANA_MULTI
