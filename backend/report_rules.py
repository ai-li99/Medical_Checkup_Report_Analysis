"""体检异常判定规则库。

每条规则都带着「判定文本 + 参考来源」，会原样写进报告附录 B，
保证报告里出现的每一个异常数字都可追溯。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

import pandas as pd

# 这些列是身份/时间/组织信息，不参与「未纳入判定」清单
IDENTITY_COLUMNS = {
    "姓名",
    "id号",
    "id",
    "身份证号",
    "出生日期",
    "体检日期",
    "性别",
    "年龄",
    "部门",
    "_sheet",
    "_来源",
}


def _normalize(name: str) -> str:
    text = str(name).strip().lower()
    text = re.sub(r"[（(][^）)]*[）)]", "", text)
    text = re.sub(r"[\s\-_/]+", "", text)
    return text


def find_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> pd.Series | None:
    for name in candidates:
        if name in frame.columns:
            return frame[name]
    lookup = {_normalize(column): column for column in frame.columns}
    for name in candidates:
        key = _normalize(name)
        if key in lookup:
            return frame[lookup[key]]
    return None


def _numeric(series: pd.Series | None) -> pd.Series | None:
    if series is None:
        return None
    return pd.to_numeric(series, errors="coerce")


def gender_series(frame: pd.DataFrame) -> pd.Series | None:
    raw = find_column(frame, ("性别", "sex", "gender"))
    if raw is None:
        return None
    text = raw.astype("string").str.strip()
    male = text.isin(["男", "男性", "M", "m", "1"])
    female = text.isin(["女", "女性", "F", "f", "0", "2"])
    result = pd.Series(pd.NA, index=frame.index, dtype="string")
    result[male] = "男"
    result[female] = "女"
    return result


def age_series(frame: pd.DataFrame) -> pd.Series | None:
    raw = find_column(frame, ("年龄", "age"))
    if raw is not None:
        numeric = _numeric(raw)
        if numeric is not None and int(numeric.notna().sum()) > 0:
            return numeric
    birth = find_column(frame, ("出生日期", "生日", "birth"))
    if birth is None:
        return None
    birth_dates = pd.to_datetime(birth, errors="coerce")
    check = find_column(frame, ("体检日期", "检查日期", "体检时间"))
    reference = pd.to_datetime(check, errors="coerce") if check is not None else None
    if reference is None or int(reference.notna().sum()) == 0:
        reference = pd.Series(pd.Timestamp.now().normalize(), index=frame.index)
    days = (reference - birth_dates).dt.days
    return (days / 365.25).floor()


def _both(left: pd.Series | None, right: pd.Series | None) -> pd.Series | None:
    if left is None and right is None:
        return None
    if left is None:
        return right
    if right is None:
        return left
    return left.fillna(False) | right.fillna(False)


@dataclass(frozen=True)
class Rule:
    key: str
    category: str
    group: str
    rule_text: str
    source: str
    fields: tuple[str, ...]
    evaluate: Callable[[pd.DataFrame], tuple[pd.Series | None, pd.Series | None]]


def _eval_blood_pressure(frame: pd.DataFrame):
    sbp = _numeric(find_column(frame, ("收缩压", "高压", "sbp")))
    dbp = _numeric(find_column(frame, ("舒张压", "低压", "dbp")))
    if sbp is None and dbp is None:
        return None, None
    abnormal = _both(
        (sbp >= 140) if sbp is not None else None,
        (dbp >= 90) if dbp is not None else None,
    )
    valid = _both(sbp.notna() if sbp is not None else None, dbp.notna() if dbp is not None else None)
    return abnormal, valid


def _eval_bmi(frame: pd.DataFrame):
    bmi = _numeric(find_column(frame, ("体质指数", "bmi", "体重指数")))
    if bmi is None:
        # 没有 BMI 列时用身高(cm)/体重(kg) 推算
        height = _numeric(find_column(frame, ("身高", "height")))
        weight = _numeric(find_column(frame, ("体重", "weight")))
        if height is None or weight is None:
            return None, None
        normalized = height.where(height < 3, height / 100)
        bmi = weight / (normalized**2)
    return bmi >= 24, bmi.notna()


def _eval_lipids(frame: pd.DataFrame):
    tc = _numeric(find_column(frame, ("总胆固醇", "tc", "chol")))
    tg = _numeric(find_column(frame, ("甘油三酯", "甘油三脂", "tg")))
    ldl = _numeric(find_column(frame, ("低密度脂蛋白", "低密度脂蛋白胆固醇", "ldl", "ldl-c")))
    if tc is None and tg is None and ldl is None:
        return None, None
    abnormal = _both(
        (tc >= 5.2) if tc is not None else None,
        _both((tg >= 1.7) if tg is not None else None, (ldl >= 3.4) if ldl is not None else None),
    )
    valid = _both(
        tc.notna() if tc is not None else None,
        _both(tg.notna() if tg is not None else None, ldl.notna() if ldl is not None else None),
    )
    return abnormal, valid


def _eval_glucose(frame: pd.DataFrame):
    glucose = _numeric(find_column(frame, ("空腹血糖", "葡萄糖", "血糖", "glu")))
    if glucose is None:
        return None, None
    return glucose >= 6.1, glucose.notna()


def _eval_uric_acid(frame: pd.DataFrame):
    uric = _numeric(find_column(frame, ("尿酸", "血尿酸", "ua")))
    if uric is None:
        return None, None
    gender = gender_series(frame)
    if gender is not None:
        male = (gender == "男").fillna(False)
        female = (gender == "女").fillna(False)
        abnormal = (male & (uric > 420)) | (female & (uric > 360))
    else:
        abnormal = uric > 420
    return abnormal, uric.notna()


def _eval_liver(frame: pd.DataFrame):
    alt = _numeric(find_column(frame, ("丙氨酸氨基转移酶", "谷丙转氨酶", "alt")))
    ast = _numeric(find_column(frame, ("天冬氨酸氨基转移酶", "谷草转氨酶", "ast")))
    if alt is None and ast is None:
        return None, None
    abnormal = _both(
        (alt > 40) if alt is not None else None,
        (ast > 40) if ast is not None else None,
    )
    valid = _both(alt.notna() if alt is not None else None, ast.notna() if ast is not None else None)
    return abnormal, valid


def _eval_hemoglobin(frame: pd.DataFrame):
    hb = _numeric(find_column(frame, ("血红蛋白", "hgb", "hb")))
    if hb is None:
        return None, None
    gender = gender_series(frame)
    if gender is not None:
        male = (gender == "男").fillna(False)
        female = (gender == "女").fillna(False)
        abnormal = (male & (hb < 130)) | (female & (hb < 115))
    else:
        abnormal = hb < 120
    return abnormal, hb.notna()


def _eval_wbc(frame: pd.DataFrame):
    wbc = _numeric(find_column(frame, ("白细胞", "白细胞计数", "wbc")))
    if wbc is None:
        return None, None
    return (wbc < 3.5) | (wbc > 9.5), wbc.notna()


def _eval_platelet(frame: pd.DataFrame):
    plt = _numeric(find_column(frame, ("血小板", "血小板计数", "plt")))
    if plt is None:
        return None, None
    return (plt < 125) | (plt > 350), plt.notna()


def _eval_creatinine(frame: pd.DataFrame):
    crea = _numeric(find_column(frame, ("肌酐", "血肌酐", "crea", "cr")))
    if crea is None:
        return None, None
    gender = gender_series(frame)
    if gender is not None:
        male = (gender == "男").fillna(False)
        female = (gender == "女").fillna(False)
        abnormal = (male & (crea > 106)) | (female & (crea > 97))
    else:
        abnormal = crea > 106
    return abnormal, crea.notna()


def _eval_homocysteine(frame: pd.DataFrame):
    hcy = _numeric(find_column(frame, ("同型半胱氨酸", "hcy")))
    if hcy is None:
        return None, None
    return hcy >= 15, hcy.notna()


RULES: tuple[Rule, ...] = (
    Rule(
        key="blood_pressure",
        category="血压升高",
        group="血压",
        rule_text="收缩压≥140 mmHg 或舒张压≥90 mmHg（单次测量）",
        source="《中国高血压防治指南（2018年修订版）》",
        fields=("收缩压", "高压", "SBP", "舒张压", "低压", "DBP"),
        evaluate=_eval_blood_pressure,
    ),
    Rule(
        key="bmi",
        category="超重或肥胖",
        group="一般检查",
        rule_text="体质指数 24.0-27.9 为超重，≥28.0 为肥胖（kg/m²），此处统计 ≥24.0",
        source="《中国成人超重和肥胖症预防控制指南》",
        fields=("体质指数", "BMI", "体重指数", "身高", "体重"),
        evaluate=_eval_bmi,
    ),
    Rule(
        key="lipids",
        category="血脂异常",
        group="血脂",
        rule_text="总胆固醇≥5.2、甘油三酯≥1.7 或低密度脂蛋白≥3.4 mmol/L（任一指标）",
        source="《中国成人血脂异常防治指南（2016年修订版）》",
        fields=("总胆固醇", "TC", "CHOL", "甘油三酯", "甘油三脂", "TG", "低密度脂蛋白", "低密度脂蛋白胆固醇", "LDL", "LDL-C"),
        evaluate=_eval_lipids,
    ),
    Rule(
        key="glucose",
        category="空腹血糖异常",
        group="血糖",
        rule_text="空腹血糖 6.1-6.9 mmol/L 为空腹血糖受损，≥7.0 mmol/L 为糖尿病范围",
        source="《中国2型糖尿病防治指南（2020年版）》",
        fields=("空腹血糖", "葡萄糖", "血糖", "GLU"),
        evaluate=_eval_glucose,
    ),
    Rule(
        key="uric_acid",
        category="高尿酸血症",
        group="尿酸",
        rule_text="血尿酸 男性>420 μmol/L、女性>360 μmol/L",
        source="《中国高尿酸血症与痛风诊疗指南（2019）》",
        fields=("尿酸", "血尿酸", "UA"),
        evaluate=_eval_uric_acid,
    ),
    Rule(
        key="liver",
        category="肝功能指标升高",
        group="肝功能",
        rule_text="丙氨酸氨基转移酶（ALT）或天冬氨酸氨基转移酶（AST）>40 U/L",
        source="常用临床参考范围",
        fields=("丙氨酸氨基转移酶", "谷丙转氨酶", "ALT", "天冬氨酸氨基转移酶", "谷草转氨酶", "AST"),
        evaluate=_eval_liver,
    ),
    Rule(
        key="hemoglobin",
        category="血红蛋白偏低",
        group="血常规",
        rule_text="血红蛋白 男性<130 g/L、女性<115 g/L",
        source="常用临床参考范围",
        fields=("血红蛋白", "HGB", "Hb"),
        evaluate=_eval_hemoglobin,
    ),
    Rule(
        key="wbc",
        category="白细胞计数异常",
        group="血常规",
        rule_text="白细胞计数 <3.5 或 >9.5 ×10⁹/L",
        source="常用临床参考范围",
        fields=("白细胞", "白细胞计数", "WBC"),
        evaluate=_eval_wbc,
    ),
    Rule(
        key="platelet",
        category="血小板计数异常",
        group="血常规",
        rule_text="血小板计数 <125 或 >350 ×10⁹/L",
        source="常用临床参考范围",
        fields=("血小板", "血小板计数", "PLT"),
        evaluate=_eval_platelet,
    ),
    Rule(
        key="creatinine",
        category="肌酐升高",
        group="肾功能",
        rule_text="血肌酐 男性>106 μmol/L、女性>97 μmol/L",
        source="常用临床参考范围",
        fields=("肌酐", "血肌酐", "CREA", "Cr"),
        evaluate=_eval_creatinine,
    ),
    Rule(
        key="homocysteine",
        category="同型半胱氨酸升高",
        group="其他",
        rule_text="同型半胱氨酸≥15 μmol/L",
        source="《高同型半胱氨酸血症诊疗专家共识》",
        fields=("同型半胱氨酸", "HCY"),
        evaluate=_eval_homocysteine,
    ),
)


def matched_columns(frame: pd.DataFrame) -> set[str]:
    used: set[str] = set()
    for rule in RULES:
        for name in rule.fields:
            for column in frame.columns:
                if _normalize(column) == _normalize(name):
                    used.add(str(column))
    return used


def unmatched_columns(frame: pd.DataFrame) -> list[str]:
    used = matched_columns(frame)
    result: list[str] = []
    for column in frame.columns:
        name = str(column)
        if name in used:
            continue
        if _normalize(name) in IDENTITY_COLUMNS:
            continue
        result.append(name)
    return result
