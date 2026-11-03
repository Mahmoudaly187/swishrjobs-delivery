#!/usr/bin/env python3
"""Generate the synthetic evaluation corpus.

240 labelled samples: 200 positive (each carrying one or more personal-data fields,
including the awkward formats the brief calls out) and 40 negative (ordinary
recruiting prose that contains no personal data, used to measure false positives).

Run:  python3 scripts/generate_samples.py  ->  data/samples.jsonl
"""
from __future__ import annotations

import json
import random
from pathlib import Path

random.seed(20261103)

SURNAMES = list("赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦许何吕施张孔曹严华金魏陶姜谢邹喻柏窦章云苏潘葛范彭郎鲁韦昌马苗方俞任袁柳鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝安常乐于时傅皮齐康伍余顾孟平黄和穆萧尹姚邵汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支柯管卢莫房裘缪解应宗丁宣邓郁单杭洪包诸左石崔吉龚程邢裴陆荣翁荀羊惠甄封芮储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车侯宓全郗班仰秋仲伊宫宁仇栾甘厉戎祖武符刘景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍桑桂濮牛寿通边扈燕冀浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡国文寇广禄阙")
GIVEN = list("伟芳娜秀英敏静丽强磊军洋勇艳杰娟涛明超秀霞平刚桂英建华文博子轩浩然欣怡雨泽嘉懿睿哲思远梦琪若曦晨曦逸辰宇轩子墨紫萱雅静诗涵佳琪志强建国春燕晓东晓峰小燕")
FOREIGN = ["Alexander Petrov", "Maria Gonzalez", "John O'Brien", "Yuki Tanaka",
           "Jean-Luc Picard", "Priya Nair", "Ahmed Al-Rashid", "Sofia Rossi"]

CITIES = ["杭州市", "成都市", "武汉市", "西安市", "郑州市", "长沙市", "合肥市", "济南市"]
DISTRICTS = ["西湖区", "武侯区", "洪山区", "雁塔区", "金水区", "岳麓区", "蜀山区", "历下区"]
STREETS = ["文一西路", "天府大道", "珞喻路", "科技路", "花园路", "麓山南路", "长江西路", "经十路"]
STATIONS = [f"S{i:03d}" for i in range(1, 40)]

LABELS = ["姓名", "联系人", "招聘专员", "申请人", "负责人", "客户"]

ID_PREFIX = ["110101", "310101", "330106", "440305", "510107", "420111", "610113", "410105"]
ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
ID_CHARS = "10X98765432"


def make_id() -> str:
    body = random.choice(ID_PREFIX) + f"{random.randint(1960, 2004):04d}{random.randint(1, 12):02d}{random.randint(1, 28):02d}{random.randint(0, 999):03d}"
    total = sum(int(c) * w for c, w in zip(body[:17], ID_WEIGHTS))
    return body + ID_CHARS[total % 11]


def make_phone(style: str) -> str:
    core = "1" + random.choice("3456789") + "".join(random.choice("0123456789") for _ in range(9))
    if style == "plain":
        return core
    if style == "spaced":
        return " ".join(core[i : i + 4] for i in range(0, 11, 4)).strip()
    if style == "hyphen":
        return f"{core[:3]}-{core[3:7]}-{core[7:]}"
    if style == "prefix86":
        return "+86 " + core
    if style == "prefix86plain":
        return "86" + core
    return core


def make_bank_card() -> str:
    """16 digits passing Luhn, optionally grouped."""
    while True:
        prefix = random.choice(["622202", "621226", "622848", "621700", "622700"])
        body = prefix + "".join(random.choice("0123456789") for _ in range(9))
        digits = [int(c) for c in body]
        for d in range(10):
            cand = digits + [d]
            total, parity = 0, len(cand) % 2
            for i, x in enumerate(cand):
                if i % 2 == parity:
                    x *= 2
                    if x > 9:
                        x -= 9
                total += x
            if total % 10 == 0:
                value = body + str(d)
                style = random.choice(["plain", "grouped", "spaced"])
                if style == "grouped":
                    return " ".join(value[i : i + 4] for i in range(0, 16, 4))
                if style == "spaced":
                    return value
                return value


def make_address() -> str:
    return (
        random.choice(CITIES)
        + random.choice(DISTRICTS)
        + random.choice(STREETS)
        + str(random.randint(1, 999))
        + random.choice(["号", "号院"])
        + str(random.randint(1, 30))
        + random.choice(["栋", "幢", "号楼"])
        + str(random.randint(1, 20))
        + random.choice(["室", "单元"])
    )


def make_name() -> str:
    return random.choice(SURNAMES) + random.choice(GIVEN) + (random.choice(GIVEN) if random.random() < 0.25 else "")


def positive_sample(i: int) -> dict:
    kinds = random.sample(["name", "phone", "id", "bankcard", "address"], k=random.randint(2, 4))
    parts: list[str] = []
    expected: dict[str, str] = {}

    if "name" in kinds:
        name = random.choice(FOREIGN) if random.random() < 0.12 else make_name()
        parts.append(f"{random.choice(LABELS)}：{name}")
        expected["name"] = name
    if "phone" in kinds:
        phone = make_phone(random.choice(["plain", "spaced", "hyphen", "prefix86", "prefix86plain"]))
        parts.append(f"手机号 {phone}")
        expected["phone"] = phone
    if "id" in kinds:
        idc = make_id()
        parts.append(f"身份证号：{idc}")
        expected["id"] = idc
    if "bankcard" in kinds:
        card = make_bank_card()
        parts.append(f"银行卡 {card}")
        expected["bankcard"] = card
    if "address" in kinds:
        addr = make_address()
        parts.append(f"住址：{addr}")
        expected["address"] = addr

    random.shuffle(parts)
    text = "；".join(parts) + "。"
    return {"id": i, "label": "positive", "text": text, "expected": expected}


NEGATIVE_TEXTS = [
    "本周招聘目标：完成 120 名骑手的初筛，重点覆盖城南片区三个站点。",
    "站长会议要求：所有面试结果必须在系统内当日录入，逾期将在日报中提示。",
    "本批次共收到简历 87 份，其中 34 份缺少健康证明，已统一退回补充。",
    "政策更新：关于骑手意外险的说明已在知识库第 12 条，回答时必须附来源。",
    "排班规则调整通知：高峰时段为 11:00-13:00 与 17:00-19:00。",
    "培训安排：新入职骑手需在 3 日内完成线上安全课程并通过测验。",
    "系统维护窗口定于每周日凌晨 2 点至 4 点，期间暂停预约功能。",
    "本月留存率环比上升 4.2 个百分点，主要来自站点 S017 的流程优化。",
    "关于防暑物资发放的通知：各站点按实际在岗人数于 15 日前领取。",
    "考核口径说明：准时率按订单承诺时间前后 5 分钟计算，不含极端天气。",
    "骑手反映：部分区域导航偏差较大，已反馈地图供应商核查。",
    "本季度目标是新增 200 名活跃骑手，重点渠道为老带新与线下宣讲。",
    "请各站核对本月考勤数据，差异需在下周三前提交说明。",
    "知识库新增条目：关于恶劣天气补贴的适用范围与结算方式。",
    "面试流程优化：初筛通过后 24 小时内必须安排到站面谈。",
    "关于工服尺码统计的通知：请于本周五前汇总各站点需求。",
    "数据质量抽查结果：本周字段完整率为 96.4%，较上周提升 1.1 点。",
    "招募话术更新：强调收入结算周期与保险覆盖范围。",
    "站点设备盘点完成，共登记 42 台终端，其中 3 台待维修。",
    "会议纪要：下阶段重点提升到站转化率，目标从 61% 提升至 70%。",
    "关于投诉处理时限的规定：一般投诉 48 小时内闭环。",
    "渠道效果对比：线下宣讲到站率高于线上投放约 8 个百分点。",
    "请关注：部分骑手对夜间配送补贴标准存在疑问，需统一口径。",
    "系统上线公告：预约模块将于本周四灰度发布。",
    "关于数据导出权限的说明：仅运营与管理角色可发起，需二次审批。",
    "培训材料已更新至版本 3.2，请各站使用最新版本。",
    "本周重点：清理重复简历，预计影响约 6% 的记录。",
    "风控提示：同一设备短时间内多次提交需人工复核。",
    "关于节假日排班的通知：按各站点实际需求自主申报。",
    "绩效口径：以有效到站面试人数为准，不含电话初筛。",
    "关于知识库答案格式的要求：结论先行，随后给出依据与来源。",
    "本月经费使用情况已公示，详见附件表格第二页。",
    "关于骑手转介绍奖励的说明：被推荐人需在岗满 14 天。",
    "系统巡检报告：接口平均响应时间 180 毫秒，无异常。",
    "关于面试场地安排的通知：三楼会议室本周优先用于集中面谈。",
    "数据留存说明：统计类数据长期保留，个人数据按最短必要期限保存。",
    "关于异常账号处理流程的补充说明：冻结前需留痕并通知本人。",
    "本周例会时间调整为周四下午三点，地点不变。",
    "关于问卷改版的说明：新增两个关于通勤距离的问题。",
    "请各站在系统内确认本周排班，逾期将按默认方案执行。",
]


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "data" / "samples.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = [positive_sample(i) for i in range(200)]
    for j, text in enumerate(NEGATIVE_TEXTS[:40]):
        rows.append({"id": 1000 + j, "label": "negative", "text": text, "expected": {}})
    with out.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} samples -> {out}")


if __name__ == "__main__":
    main()
