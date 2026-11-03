"""Anonymization utility library.

Detects and replaces personal data with ``[type_sequence]`` placeholders, and can
reverse the substitution inside a controlled environment.

Public SDK surface (used by Tasks 1 and 3):

    masker = Masker()
    masked, mapping = masker.mask(text)
    original = masker.unmask(masked, mapping)

Detection covers Chinese names, mobile numbers, national ID numbers, bank-card
numbers and detailed addresses. Detection is deliberately conservative: a
false-positive rate that is measured and reported is worth more than a regex that
redacts half the document.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- Chinese surnames, ordered longest-first so 欧阳/司马 win over 欧/司 -----------
COMPOUND_SURNAMES = (
    "欧阳", "太史", "端木", "上官", "司马", "东方", "独孤", "南宫", "万俟", "闻人",
    "夏侯", "诸葛", "尉迟", "公羊", "赫连", "澹台", "皇甫", "宗政", "濮阳", "公冶",
    "太叔", "申屠", "公孙", "慕容", "仲孙", "钟离", "长孙", "宇文", "司徒", "鲜于",
    "司空", "闾丘", "子车", "亓官", "司寇", "巫马", "公西", "颛孙", "壤驷", "公良",
    "漆雕", "乐正", "宰父", "谷梁", "拓跋", "夹谷", "轩辕", "令狐", "段干", "百里",
    "呼延", "东郭", "南门", "羊舌", "微生", "公户", "公玉", "公仪", "梁丘", "公仲",
)
SINGLE_SURNAMES = (
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章"
    "云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安常"
    "乐于时傅皮卞齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞"
    "熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍"
    "虞万支柯昝管卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚程嵇邢滑裴陆荣翁"
    "荀羊於惠甄麹家封芮羿储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫"
    "宁仇栾暴甘钭历戎祖武符刘景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙"
    "池乔阴鬱胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍卻璩桑桂濮牛寿通边扈燕冀郏浦尚农"
    "温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡国文寇广禄阙东"
    "欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾毋沙乜养鞠须丰巢关蒯相查后荆红"
    "游竺权逯盖益桓公"
)

# --- regex building blocks -------------------------------------------------------
# Mobile: 1[3-9] + 9 digits, tolerating spaces, hyphens and a +86 / 86 prefix.
_SEP = r"[\s\-]?"
_MOBILE_CORE = r"1[3-9]\d" + (_SEP + r"\d") * 8
PHONE_RE = re.compile(r"(?:(?:\+?86)" + _SEP + r")?" + _MOBILE_CORE)

# Landline with area code, e.g. 010-12345678
LANDLINE_RE = re.compile(r"0\d{2,3}" + _SEP + r"\d{7,8}")

# National ID: 17 digits + digit/check char, checksum-validated below.
ID_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")

# Bank card: 16-19 digits, optionally grouped in fours; Luhn-validated below.
# The separator is required when one is present, so a grouped number is not
# silently truncated to its first four digits.
CARD_RE = re.compile(r"(?<!\d)(?:\d{16,19}|\d{4}(?:[ -]\d{4}){3}(?:[ -]?\d{1,3})?)(?!\d)")

# Chinese address: optional province, then a city suffix, optional district, then
# one or more detail units (road / number / building / room).
ADDRESS_RE = re.compile(
    r"(?:[\u4e00-\u9fa5]{2,8}(?:省|自治区|特别行政区))?"
    r"[\u4e00-\u9fa5]{2,8}(?:市|自治州|地区|盟)"
    r"(?:[\u4e00-\u9fa5]{2,10}(?:区|县|旗|市))?"
    r"(?:[\u4e00-\u9fa5\d]{0,20}(?:路|街|道|巷|弄|号|栋|幢|座|楼|室|单元|村|镇|乡|组|苑|园|城|大厦|广场))+"
)

# Context labels that introduce a name.
NAME_LABELS = (
    "姓名", "名字", "联系人", "收件人", "申请人", "客户", "户主", "法人", "负责人",
    "招聘专员", "站长", "身份证姓名", "真实姓名", "name", "contact",
)
# After a label, a Chinese name is 2-4 Han characters; a foreign name is two or more
# capitalised Latin tokens ("Jean-Luc Picard", "John O'Brien"). The separator is
# captured because it decides how much evidence we have that a name follows.
_CN_NAME = r"[\u4e00-\u9fa5]{2,4}"
_LATIN_NAME = r"[A-Z][A-Za-z'’\-]+(?:\s+[A-Z][A-Za-z'’\-]+)+"
NAME_LABEL_RE = re.compile(
    r"(?P<label>" + "|".join(NAME_LABELS) + r")"
    r"(?P<sep>\s*[:：=]?\s*)"
    r"(?P<name>" + _CN_NAME + r"|" + _LATIN_NAME + r")",
    re.IGNORECASE,
)

SURNAME_SET = set(SINGLE_SURNAMES) | set("".join(COMPOUND_SURNAMES))
COMPOUND_SET = set(COMPOUND_SURNAMES)

ID_CHECK_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
ID_CHECK_CHARS = "10X98765432"


def id_checksum_valid(value: str) -> bool:
    value = value.upper()
    if len(value) != 18:
        return False
    if not value[:17].isdigit():
        return False
    total = sum(int(c) * w for c, w in zip(value[:17], ID_CHECK_WEIGHTS))
    return ID_CHECK_CHARS[total % 11] == value[17]


def luhn_valid(value: str) -> bool:
    digits = [int(c) for c in re.sub(r"\D", "", value)]
    if len(digits) < 12:
        return False
    total, parity = 0, len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


@dataclass
class Span:
    kind: str
    start: int
    end: int
    text: str

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Span({self.kind}, {self.start}:{self.end}, {self.text!r})"


@dataclass
class MaskResult:
    masked: str
    mapping: dict[str, str] = field(default_factory=dict)
    spans: list[Span] = field(default_factory=list)


class Masker:
    """Detect and replace personal data, reversibly."""

    def __init__(self, redact_names_without_label: bool = False):
        # Surname-initial detection is off by default: without a label it is the main
        # source of false positives on ordinary prose.
        self.redact_names_without_label = redact_names_without_label
        self._surname_re = re.compile(
            r"(?:"
            + "|".join(sorted(COMPOUND_SURNAMES, key=len, reverse=True))
            + r"|(?:["
            + SINGLE_SURNAMES
            + r"]))[\u4e00-\u9fa5]{1,2}"
        )

    # -- detection ---------------------------------------------------------------
    def find_spans(self, text: str) -> list[Span]:
        spans: list[Span] = []

        for m in ID_RE.finditer(text):
            if id_checksum_valid(m.group()):
                spans.append(Span("id", m.start(), m.end(), m.group()))

        for m in CARD_RE.finditer(text):
            raw = m.group()
            digits = re.sub(r"\D", "", raw)
            # Skip anything that is really an ID card or a phone number.
            if 16 <= len(digits) <= 19 and luhn_valid(raw):
                spans.append(Span("bankcard", m.start(), m.end(), raw))

        for m in PHONE_RE.finditer(text):
            spans.append(Span("phone", m.start(), m.end(), m.group()))

        for m in LANDLINE_RE.finditer(text):
            spans.append(Span("phone", m.start(), m.end(), m.group()))

        for m in NAME_LABEL_RE.finditer(text):
            name = m.group("name")
            sep = m.group("sep")
            # Without an explicit separator we only have weak evidence. Accept the
            # match only if it starts with a plausible surname, so that phrases such
            # as "站长会议要求" are not read as a name.
            if not sep.strip():
                if name[0] not in SURNAME_SET and name[:2] not in COMPOUND_SET:
                    continue
            start = m.start("name")
            spans.append(Span("name", start, start + len(name), name))

        if self.redact_names_without_label:
            for m in self._surname_re.finditer(text):
                spans.append(Span("name", m.start(), m.end(), m.group()))

        for m in ADDRESS_RE.finditer(text):
            spans.append(Span("address", m.start(), m.end(), m.group()))

        return self._resolve_overlaps(spans)

    @staticmethod
    def _resolve_overlaps(spans: list[Span]) -> list[Span]:
        """Keep the most specific match when spans overlap.

        Priority: id > bankcard > phone > address > name. Longer wins on a tie.
        """
        priority = {"id": 0, "bankcard": 1, "phone": 2, "address": 3, "name": 4}
        ordered = sorted(spans, key=lambda s: (priority[s.kind], -(s.end - s.start), s.start))
        kept: list[Span] = []
        for span in ordered:
            if any(span.start < k.end and k.start < span.end for k in kept):
                continue
            kept.append(span)
        return sorted(kept, key=lambda s: s.start)

    # -- substitution ------------------------------------------------------------
    def mask(self, text: str) -> MaskResult:
        spans = self.find_spans(text)
        counters: dict[str, int] = {}
        mapping: dict[str, str] = {}
        out: list[str] = []
        cursor = 0
        for span in spans:
            counters[span.kind] = counters.get(span.kind, 0) + 1
            placeholder = f"[{span.kind}_{counters[span.kind]}]"
            mapping[placeholder] = span.text
            out.append(text[cursor : span.start])
            out.append(placeholder)
            cursor = span.end
        out.append(text[cursor:])
        return MaskResult(masked="".join(out), mapping=mapping, spans=spans)

    def unmask(self, masked: str, mapping: dict[str, str]) -> str:
        """Reverse a substitution. Controlled-environment use only."""
        result = masked
        for placeholder, original in mapping.items():
            result = result.replace(placeholder, original)
        return result

    def mask_value(self, kind: str, value: str) -> str:
        """Mask a single labelled value, e.g. ``mask_value('phone', '13800138000')``."""
        counters: dict[str, int] = {}
        spans = [s for s in self.find_spans(value) if s.kind == kind]
        if not spans:
            return value
        out, cursor = [], 0
        for span in spans:
            counters[kind] = counters.get(kind, 0) + 1
            out.append(value[cursor : span.start])
            out.append(f"[{kind}_{counters[kind]}]")
            cursor = span.end
        out.append(value[cursor:])
        return "".join(out)
