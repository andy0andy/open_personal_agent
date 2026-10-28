---
name: excel
description: 读取、清洗、汇总 Excel / CSV，并输出图表或新表格的规范。处理 .xlsx、.xls、.csv 文件时先读这份规范。
---

# 处理 Excel / CSV 的规范

## 读取

- 先看结构再处理：`pd.ExcelFile(path).sheet_names` 列出工作表；每个表先读前 5 行（`nrows=5`）确认表头在哪一行。
- 表头不在第一行时用 `header=` 指定；合并单元格造成的空值用 `ffill()` 补齐。
- CSV 先试 `encoding="utf-8"`，出现乱码再试 `gbk`。
- 大表（几万行以上）只读需要的列（`usecols=`）。

## 清洗

- 数字列里混入的文字、千分位逗号、百分号先清理再转数值（`pd.to_numeric(..., errors="coerce")`），并说明有多少行转换失败。
- 日期列统一用 `pd.to_datetime`；去重、处理空值前后都报告行数变化。

## 汇总与输出

- 汇总表保存为 `outputs/<名称>.xlsx`（`df.to_excel(..., index=False)`），多张表放进同一个文件的不同工作表。
- 图表用 matplotlib / seaborn：`plt.savefig("outputs/<名称>.png", dpi=150, bbox_inches="tight")`，保存后 `plt.close()`；标题、坐标轴用中文（已配置中文字体）。
- 回答里给出关键数字与结论，并列出产物文件的路径；不要把整张表贴进回答。
