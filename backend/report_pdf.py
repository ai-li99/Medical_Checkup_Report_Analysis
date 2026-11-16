"""把统计数据与 LLM 叙述渲染成 A4 PDF 报告。"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from report_rules import RULES

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN_X = 20 * mm
MARGIN_TOP = 22 * mm
MARGIN_BOTTOM = 18 * mm
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN_X

FONT_REGULAR = "CJK"
FONT_BOLD = "CJK-Bold"
BOLD_NAME = FONT_REGULAR

_FONT_CANDIDATES = (
    (r"C:\Windows\Fonts\msyh.ttc", 0),
    (r"C:\Windows\Fonts\simhei.ttf", None),
    (r"C:\Windows\Fonts\simsun.ttc", 0),
    (r"C:\Windows\Fonts\Deng.ttf", None),
    (r"/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
    (r"/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
)
_BOLD_CANDIDATES = (
    (r"C:\Windows\Fonts\msyhbd.ttc", 0),
    (r"C:\Windows\Fonts\simhei.ttf", None),
    (r"/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0),
)

_registered = False


def _try_font(path: str, index: int | None, name: str) -> bool:
    try:
        if index is None:
            pdfmetrics.registerFont(TTFont(name, path))
        else:
            pdfmetrics.registerFont(TTFont(name, path, subfontIndex=index))
        return True
    except Exception:  # noqa: BLE001 - 继续尝试下一个候选
        return False


def register_fonts() -> None:
    global _registered, BOLD_NAME
    if _registered:
        return
    for path, index in _FONT_CANDIDATES:
        if _try_font(path, index, FONT_REGULAR):
            break
    else:
        raise RuntimeError("未找到可用的中文字体（微软雅黑/黑体/宋体等），无法生成 PDF")
    for path, index in _BOLD_CANDIDATES:
        if _try_font(path, index, FONT_BOLD):
            BOLD_NAME = FONT_BOLD
            break
    _registered = True


def _styles() -> dict[str, ParagraphStyle]:
    bold = BOLD_NAME
    return {
        "cover_unit": ParagraphStyle("cover_unit", fontName=FONT_REGULAR, fontSize=18, leading=26, alignment=TA_CENTER),
        "cover_title": ParagraphStyle("cover_title", fontName=bold, fontSize=28, leading=40, alignment=TA_CENTER),
        "cover_note": ParagraphStyle("cover_note", fontName=FONT_REGULAR, fontSize=10, leading=16, alignment=TA_CENTER, textColor=colors.HexColor("#666666")),
        "h1": ParagraphStyle("h1", fontName=bold, fontSize=15, leading=24, spaceBefore=10, spaceAfter=6, wordWrap="CJK"),
        "h2": ParagraphStyle("h2", fontName=bold, fontSize=11.5, leading=19, spaceBefore=8, spaceAfter=4, wordWrap="CJK"),
        "body": ParagraphStyle("body", fontName=FONT_REGULAR, fontSize=10.5, leading=18, alignment=TA_LEFT, spaceAfter=4, wordWrap="CJK"),
        "list": ParagraphStyle("list", fontName=FONT_REGULAR, fontSize=10.5, leading=18, alignment=TA_LEFT, leftIndent=12, spaceAfter=2, wordWrap="CJK"),
        "cell": ParagraphStyle("cell", fontName=FONT_REGULAR, fontSize=8.5, leading=13, alignment=TA_LEFT, wordWrap="CJK"),
        "cell_center": ParagraphStyle("cell_center", fontName=FONT_REGULAR, fontSize=8.5, leading=13, alignment=TA_CENTER, wordWrap="CJK"),
        "head": ParagraphStyle("head", fontName=bold, fontSize=8.5, leading=13, alignment=TA_CENTER, wordWrap="CJK"),
    }


def _p(text: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(text if text is not None else "")), style)


def _table(
    rows: list[list[Any]],
    widths: list[float],
    styles: dict[str, ParagraphStyle],
    aligns: list[str] | None = None,
) -> Table:
    data: list[list[Any]] = []
    for row_index, row in enumerate(rows):
        cells: list[Any] = []
        for column_index, value in enumerate(row):
            if row_index == 0:
                cells.append(_p(value, styles["head"]))
            else:
                align = aligns[column_index] if aligns and column_index < len(aligns) else "center"
                cells.append(_p(value, styles["cell"] if align == "left" else styles["cell_center"]))
        data.append(cells)

    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2F7")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B4BCC8")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _ratio(part: int, total: int) -> float:
    return round(part / total * 100, 1) if total > 0 else 0.0


def _period_text(stats: dict[str, Any]) -> str:
    start, end = stats["meta"].get("period_start"), stats["meta"].get("period_end")
    if start and end and start != end:
        return f"{start} 至 {end}"
    return start or "未提供"


def _fallback_distribution(item: dict[str, Any]) -> str:
    by_gender = [group for group in item.get("by_gender") or [] if group.get("valid")]
    if len(by_gender) >= 2:
        return "、".join(f"{group['label']} {group['rate']}%" for group in by_gender) + "，组间差异需结合样本量判断。"
    return "本次样本量有限，未作分组分析。"


def _fallback_narrative(stats: dict[str, Any]) -> dict[str, Any]:
    people = stats["people"]
    focus = stats["focus"]
    categories = "、".join(item["category"] for item in focus[:3]) or "可量化指标"
    return {
        "summary": (
            f"本报告对{stats['meta']['unit_name']}的团体健康体检结果进行汇总分析，共纳入 {people['total']} 人。"
            f"本次重点关注的异常类别包括{categories}，各项检出情况见正文与附录。"
        ),
        "key_findings": [
            f"{item['category']}检出 {item['abnormal_count']} 人，检出率 {item['rate']}%" for item in focus[:3]
        ],
        "priority_actions": [
            "对检出异常的人员安排复测并登记结果。",
            "按类别开展针对性的健康教育与生活方式指导。",
            "完善体检数据采集，减少缺项。",
        ],
        "problem_insights": [
            {
                "category": item["category"],
                "distribution": _fallback_distribution(item),
                "interpretation": "建议结合复测结果与个人病史进一步评估，单次检查结果不能代替临床诊断。",
            }
            for item in focus
        ],
        "group_observation": f"本次共 {stats['cooccurrence']['people_with_two_or_more']} 人同时存在两项及以上异常。",
        "review_plan": "建议按既定流程联系相关受检者，记录复核与转诊状态；团体报告不列个人信息。",
        "management_advice": {
            "short_term": "按类别组织复测与结果回收。",
            "collective": "开展膳食、运动与体重管理宣教。",
            "next_checkup": "完善检查项目与数据录入，减少缺项。",
        },
        "conclusion": f"本次体检的主要异常集中在{categories}，建议按类别组织复核并开展集体干预。",
        "limitations": "本次分析受数据完整性限制，部分项目未纳入量化判定；单次检查结果不能代替确诊。",
    }


def _insight_map(narrative: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for item in narrative.get("problem_insights") or []:
        if isinstance(item, dict) and item.get("category"):
            mapping[str(item["category"])] = item
    return mapping


def _cover(story: list[Any], stats: dict[str, Any], info: dict[str, Any], styles: dict[str, ParagraphStyle]) -> None:
    story.append(Spacer(1, 45 * mm))
    story.append(_p(info["unit_name"], styles["cover_unit"]))
    story.append(Spacer(1, 6 * mm))
    story.append(_p("团体健康体检分析报告", styles["cover_title"]))
    story.append(Spacer(1, 20 * mm))

    rows = [
        ["项目", "内容"],
        ["受检单位", info["unit_name"]],
        ["体检时间", _period_text(stats)],
        ["数据来源", stats["meta"].get("source_file", "")],
        ["纳入人数", f"{stats['people']['total']} 人"],
        ["报告日期与版本", f"{info['report_date']}；版本 {info['version']}"],
        ["编制与审核", f"编制：{info['prepared_by']}；医学审核：{info['reviewed_by']}"],
    ]
    story.append(_table(rows, [CONTENT_WIDTH * 0.3, CONTENT_WIDTH * 0.7], styles, ["left", "left"]))
    story.append(Spacer(1, 28 * mm))
    story.append(_p("本报告依据本次体检数据汇总生成，仅用于团体健康管理。", styles["cover_note"]))
    story.append(PageBreak())


def _summary(story: list[Any], narrative: dict[str, Any], styles: dict[str, ParagraphStyle]) -> None:
    story.append(_p("报告摘要", styles["h1"]))
    story.append(_p(narrative.get("summary", ""), styles["body"]))
    findings = [str(item) for item in narrative.get("key_findings") or [] if str(item).strip()]
    if findings:
        story.append(_p("主要发现：", styles["body"]))
        for index, item in enumerate(findings, start=1):
            story.append(_p(f"{index}. {item}", styles["list"]))
    actions = [str(item) for item in narrative.get("priority_actions") or [] if str(item).strip()]
    if actions:
        story.append(Spacer(1, 2 * mm))
        story.append(_p("建议优先采取的措施：", styles["body"]))
        for index, item in enumerate(actions, start=1):
            story.append(_p(f"{index}. {item}", styles["list"]))
    story.append(Spacer(1, 2 * mm))
    story.append(_p("本报告反映本次体检所见情况，不能代替个人临床诊断。", styles["body"]))


def _data_scope(story: list[Any], stats: dict[str, Any], styles: dict[str, ParagraphStyle]) -> None:
    story.append(_p("一、数据范围与统计说明", styles["h1"]))
    story.append(_p("1.1 数据范围", styles["h2"]))
    categories = "、".join(item["category"] for item in stats["completeness"]) or "各检查项目"
    story.append(_p(
        f"本次分析基于 1 份数据文件（{stats['meta'].get('source_file', '')}），覆盖{categories}等检查项目。"
        f"分析对象为该文件中的全部记录，共 {stats['people']['total']} 人；未进行跨文件去重。"
        "若部分人员未完成某项检查，该项统计仅使用有有效检查结果的人数。",
        styles["body"],
    ))

    story.append(_p("1.2 数据完整性", styles["h2"]))
    rows: list[list[Any]] = [["检查类别", "应检或纳入人数", "有效结果人数", "说明"]]
    for item in stats["completeness"]:
        note = f"含{item['items']}" + (f"；{item['missing']} 人无有效结果" if item["missing"] else "")
        rows.append([item["category"], item["expected"], item["valid"], note])
    story.append(_table(
        rows,
        [CONTENT_WIDTH * 0.16, CONTENT_WIDTH * 0.2, CONTENT_WIDTH * 0.2, CONTENT_WIDTH * 0.44],
        styles,
        ["left", "center", "center", "left"],
    ))
    story.append(Spacer(1, 2 * mm))

    story.append(_p("1.3 统计口径与判定依据", styles["h2"]))
    story.append(_p(
        "异常检出率＝符合该异常判定规则的人数÷该项目有效检查人数×100%。不同项目的有效检查人数可能不同；"
        "同一人可以出现多类异常，因此各类异常人数和比例不能直接相加。",
        styles["body"],
    ))
    story.append(_p(
        "异常类别、所用字段、判定规则与参考来源见附录 B；单次检查升高等筛查结果应与已经明确的疾病诊断分开表述。",
        styles["body"],
    ))


def _people(story: list[Any], stats: dict[str, Any], styles: dict[str, ParagraphStyle]) -> None:
    story.append(_p("二、受检人员基本情况", styles["h1"]))
    people = stats["people"]
    parts = [f"本次纳入 {people['total']} 人"]
    if people.get("male") is not None and people.get("female") is not None:
        parts.append(f"其中男性 {people['male']} 人、女性 {people['female']} 人")
    if people.get("age_min") is not None:
        parts.append(f"年龄范围 {people['age_min']}-{people['age_max']} 岁（平均 {people['age_mean']} 岁）")
    story.append(_p("，".join(parts) + "。", styles["body"]))

    rows: list[list[Any]] = [["分组", "人数", "占纳入人数比例"]]
    if people.get("male") is not None:
        rows.append(["男性", people["male"], f"{_ratio(people['male'], people['total'])}%"])
        rows.append(["女性", people["female"], f"{_ratio(people['female'], people['total'])}%"])
    for group in people.get("age_groups") or []:
        if group["count"] > 0:
            rows.append([group["label"], group["count"], f"{group['ratio']}%"])
    if len(rows) == 1:
        rows.append(["数据未提供分组字段", "-", "-"])
    story.append(_table(rows, [CONTENT_WIDTH * 0.4, CONTENT_WIDTH * 0.25, CONTENT_WIDTH * 0.35], styles, ["left", "center", "center"]))


def _overview(story: list[Any], stats: dict[str, Any], styles: dict[str, ParagraphStyle]) -> None:
    story.append(_p("三、主要异常结果总览", styles["h1"]))
    focus = stats["focus"]
    if not focus:
        story.append(_p("本次数据中未发现可按既定规则量化判定的异常类别。", styles["body"]))
        return
    story.append(_p(
        f"根据本次数据的检查覆盖情况与异常检出人数，正文选取 {len(focus)} 类重点问题进行分析。"
        "下表展示主要异常的统计结果，完整列表见附录 A。",
        styles["body"],
    ))
    rows: list[list[Any]] = [["异常类别", "有效检查人数", "异常人数", "检出率", "备注"]]
    for item in focus:
        rows.append([item["category"], item["valid_count"], item["abnormal_count"], f"{item['rate']}%", item["rule"]])
    story.append(_table(
        rows,
        [CONTENT_WIDTH * 0.2, CONTENT_WIDTH * 0.14, CONTENT_WIDTH * 0.11, CONTENT_WIDTH * 0.1, CONTENT_WIDTH * 0.45],
        styles,
        ["left", "center", "center", "center", "left"],
    ))


def _focus_section(story: list[Any], stats: dict[str, Any], narrative: dict[str, Any], styles: dict[str, ParagraphStyle]) -> None:
    story.append(_p("四、重点健康问题分析", styles["h1"]))
    focus = stats["focus"]
    if not focus:
        story.append(_p("本次数据中未发现可按既定规则量化判定的异常类别，本节不展开。", styles["body"]))
        return
    insights = _insight_map(narrative)
    for index, item in enumerate(focus, start=1):
        story.append(_p(f"4.{index} {item['category']}", styles["h2"]))
        story.append(_p(
            f"结果：{item['valid_count']} 人中，{item['abnormal_count']} 人符合{item['rule']}，"
            f"本次异常检出率为 {item['rate']}%。",
            styles["body"],
        ))
        insight = insights.get(item["category"]) or {}
        distribution = insight.get("distribution") or _fallback_distribution(item)
        interpretation = insight.get("interpretation") or "建议结合复测结果与个人病史进一步评估，单次检查结果不能代替临床诊断。"
        story.append(_p(f"分布：{distribution}", styles["body"]))
        story.append(_p(f"解读与建议：{interpretation}", styles["body"]))


def _gender_rows(stats: dict[str, Any], focus: list[dict[str, Any]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    if not focus:
        return rows
    for label in ("男", "女"):
        first_group = next((item for item in focus[0].get("by_gender") or [] if item["label"] == label), None)
        if first_group is None:
            continue
        cells: list[Any] = [label, first_group["valid"]]
        for item in focus:
            match = next((entry for entry in item.get("by_gender") or [] if entry["label"] == label), None)
            cells.append(f"{match['abnormal']}（{match['rate']}%）" if match else "-")
        rows.append(cells)
    return rows


def _group_section(story: list[Any], stats: dict[str, Any], narrative: dict[str, Any], styles: dict[str, ParagraphStyle]) -> None:
    story.append(_p("五、分组及多项异常共同出现情况", styles["h1"]))
    cooccurrence = stats["cooccurrence"]
    story.append(_p(
        f"本次共 {cooccurrence['people_with_two_or_more']} 人同时存在两项及以上异常，"
        f"占纳入人数的 {cooccurrence['ratio']}%。",
        styles["body"],
    ))
    pairs = cooccurrence.get("top_pairs") or []
    if pairs:
        pair_text = "；".join(f"{item['pair'][0]}与{item['pair'][1]} {item['count']} 人" for item in pairs)
        story.append(_p(f"最常见的共同出现组合为：{pair_text}。", styles["body"]))

    focus = stats["focus"][:3]
    rows = _gender_rows(stats, focus)
    if rows:
        header = ["分组", "有效检查人数"] + [item["category"] for item in focus]
        widths = [CONTENT_WIDTH * 0.16, CONTENT_WIDTH * 0.16] + [CONTENT_WIDTH * 0.2266] * len(focus)
        story.append(_table([header] + rows, widths, styles, ["left"] + ["center"] * (len(header) - 1)))
        story.append(Spacer(1, 2 * mm))
    story.append(_p(narrative.get("group_observation", ""), styles["body"]))


def _review_section(story: list[Any], stats: dict[str, Any], narrative: dict[str, Any], styles: dict[str, ParagraphStyle]) -> None:
    story.append(_p("六、需要重点关注的发现与复核安排", styles["h1"]))
    focus = stats["focus"]
    summary = "、".join(f"{item['category']} {item['abnormal_count']} 人" for item in focus[:4])
    story.append(_p(
        f"本次发现{summary or '若干'}等需要重点复核或医学评估的异常。"
        "团体报告只呈现汇总数量和处理建议，不列姓名、身份证号、联系方式等个人信息。",
        styles["body"],
    ))
    story.append(_p(narrative.get("review_plan", ""), styles["body"]))


def _advice_section(story: list[Any], narrative: dict[str, Any], styles: dict[str, ParagraphStyle]) -> None:
    story.append(_p("七、单位健康管理建议", styles["h1"]))
    advice = narrative.get("management_advice") or {}
    story.append(_p(f"近期优先事项：{advice.get('short_term', '')}", styles["body"]))
    story.append(_p(f"集体健康促进：{advice.get('collective', '')}", styles["body"]))
    story.append(_p(f"后续体检安排：{advice.get('next_checkup', '')}", styles["body"]))
    story.append(_p(
        "上述建议面向团体健康管理；涉及个人诊疗的决定，应由有资质的专业人员结合完整病史和复查结果作出。",
        styles["body"],
    ))


def _conclusion(story: list[Any], narrative: dict[str, Any], styles: dict[str, ParagraphStyle]) -> None:
    story.append(_p("八、结论与报告局限", styles["h1"]))
    story.append(_p(f"结论：{narrative.get('conclusion', '')}", styles["body"]))
    story.append(_p(f"局限：{narrative.get('limitations', '')}", styles["body"]))


_FIELD_DISPLAY = {
    "blood_pressure": "收缩压、舒张压",
    "bmi": "身高、体重（或体质指数）",
    "lipids": "总胆固醇、甘油三酯、低密度脂蛋白",
    "glucose": "空腹血糖（葡萄糖）",
    "uric_acid": "尿酸",
    "liver": "ALT、AST",
    "hemoglobin": "血红蛋白",
    "wbc": "白细胞计数",
    "platelet": "血小板计数",
    "creatinine": "肌酐",
    "homocysteine": "同型半胱氨酸",
}


def _appendix_a(story: list[Any], stats: dict[str, Any], styles: dict[str, ParagraphStyle]) -> None:
    story.append(PageBreak())
    story.append(_p("附录 A 主要异常统计明细", styles["h1"]))
    story.append(_p("下列异常均有明确判定规则且数据质量合格，正文未展开的问题可在此查阅。", styles["body"]))
    rows: list[list[Any]] = [["异常类别", "相关原始指标", "有效检查人数", "异常人数", "检出率"]]
    for item in stats["all_abnormalities"]:
        rows.append([
            item["category"],
            _FIELD_DISPLAY.get(item.get("key", ""), ""),
            item["valid_count"],
            item["abnormal_count"],
            f"{item['rate']}%",
        ])
    if len(rows) == 1:
        rows.append(["-", "-", "-", "-", "-"])
    story.append(_table(
        rows,
        [CONTENT_WIDTH * 0.2, CONTENT_WIDTH * 0.34, CONTENT_WIDTH * 0.16, CONTENT_WIDTH * 0.15, CONTENT_WIDTH * 0.15],
        styles,
        ["left", "left", "center", "center", "center"],
    ))


def _appendix_b(story: list[Any], stats: dict[str, Any], styles: dict[str, ParagraphStyle]) -> None:
    story.append(_p("附录 B 指标定义与判定规则", styles["h1"]))
    rows: list[list[Any]] = [["统计类别", "所用字段", "判定规则", "参考来源"]]
    keys = {item.get("key") for item in stats["all_abnormalities"]}
    for rule in RULES:
        if rule.key not in keys:
            continue
        rows.append([rule.category, _FIELD_DISPLAY.get(rule.key, ""), rule.rule_text, rule.source])
    if len(rows) == 1:
        rows.append(["-", "-", "-", "-"])
    story.append(_table(
        rows,
        [CONTENT_WIDTH * 0.16, CONTENT_WIDTH * 0.2, CONTENT_WIDTH * 0.37, CONTENT_WIDTH * 0.27],
        styles,
        ["left", "left", "left", "left"],
    ))
    story.append(Spacer(1, 3 * mm))
    story.append(_p(
        "说明：不同体检机构的参考范围可能存在差异；本报告采用上表规则进行判定，"
        "异常检出率仅用于团体层面的描述，不作为个人诊断依据。",
        styles["body"],
    ))


def _header_footer(canvas, doc) -> None:  # noqa: ANN001
    canvas.saveState()
    canvas.setFont(FONT_REGULAR, 8)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawString(MARGIN_X, PAGE_HEIGHT - 14 * mm, "团体健康体检分析报告")
    canvas.drawRightString(PAGE_WIDTH - MARGIN_X, PAGE_HEIGHT - 14 * mm, "内部资料 · 注意保密")
    canvas.setStrokeColor(colors.HexColor("#CCCCCC"))
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN_X, PAGE_HEIGHT - 16 * mm, PAGE_WIDTH - MARGIN_X, PAGE_HEIGHT - 16 * mm)
    canvas.drawCentredString(PAGE_WIDTH / 2, 10 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def _blank_page(canvas, doc) -> None:  # noqa: ANN001
    return


def build_report_pdf(
    path: Path,
    stats: dict[str, Any],
    narrative: dict[str, Any] | None,
    info: dict[str, Any],
) -> None:
    register_fonts()
    styles = _styles()
    narrative = narrative or _fallback_narrative(stats)

    story: list[Any] = []
    _cover(story, stats, info, styles)
    _summary(story, narrative, styles)
    _data_scope(story, stats, styles)
    _people(story, stats, styles)
    _overview(story, stats, styles)
    _focus_section(story, stats, narrative, styles)
    _group_section(story, stats, narrative, styles)
    _review_section(story, stats, narrative, styles)
    _advice_section(story, narrative, styles)
    _conclusion(story, narrative, styles)
    _appendix_a(story, stats, styles)
    _appendix_b(story, stats, styles)

    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=f"{info['unit_name']}团体健康体检分析报告",
        author=str(info.get("prepared_by", "")),
    )
    doc.build(story, onFirstPage=_blank_page, onLaterPages=_header_footer)
