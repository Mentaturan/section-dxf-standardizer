# Section DXF Standardizer

[English](README.md) | 中文

Agent 就绪的工作流与 Python 工具，用于将成对导出的建筑剖立面 DXF 文件清洗为 AutoCAD 兼容、可编辑的多图层技术图纸。

## 功能

本项目针对建筑剖立面图纸的标准化处理——每个剖面由两个 DXF 文件导出：

- 剖切线文件：包含剖面剖切部分的重线几何
- 看线文件：包含投影/背景几何

批量工作流自动完成以下步骤：扫描编号 DXF 文件对、检测坐标偏移、将剖切线几何对齐到看线几何、去除重复与噪声线段、将实体重新分类到建筑 CAD 图层、添加轻量可编辑的结构修补线，并输出：

- 标准化 DXF 文件
- PNG 预览图
- 每个剖面的 Markdown 报告
- 全部剖面的汇总报告

## 声明

本工具是实用的制图自动化工作流，不是结构设计引擎。生成的修补线为可编辑的制图辅助，专业使用前须由建筑师或结构工程师审核。

## 环境要求

- Python 3.10+
- `ezdxf`（用于生成 AutoCAD 兼容的 DXF 文件）

安装：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

## 输入命名规则

将源 DXF 文件放在仓库根目录或当前工作目录下。

每个编号组：

- 剖切线 DXF：文件名包含组编号，且不包含看线关键词
- 看线 DXF：文件名包含组编号，且包含看线关键词，如 `看线`、`visible`、`projection`、`projected`、`viewline`、`view-line`

示例：

```text
section1.dxf
section1_visible.dxf
section2.dxf
section2_visible.dxf
```

中文导出同样支持：

```text
剖面1.dxf
剖面1看线.dxf
剖面2.dxf
剖面2看线.dxf
```

不要混用不同编号组的几何数据。

## 使用方法

运行：

```bash
python tools/standardize_section_dxf_batch.py
```

输出写入 `out/` 目录。

以组 1、2 为例，输出文件：

```text
out/standardized_section_1.dxf
out/standardized_section_1_preview.png
out/standardized_section_1_report.md
out/standardized_section_2.dxf
out/standardized_section_2_preview.png
out/standardized_section_2_report.md
out/standardized_section_all_report.md
```

## 输出图层

每个标准化 DXF 包含以下图层：

- `A-CUT-SECTION` — 剖切线
- `A-VISIBLE-PROJECTION` — 看线投影
- `A-STRUCTURE-FIX` — 结构修补
- `A-HATCH-MATERIAL` — 材料填充
- `A-CENTER-HIDDEN` — 中心隐藏线
- `A-ANNO-NOTE` — 标注注释

有效实体不应留在图层 `0` 上。

## AutoCAD 兼容性

AutoCAD 比多数 DXF 查看器更严格。本项目使用 `ezdxf` 进行最终 DXF 写出。生成的文件在专业交付前应在 AutoCAD 中审核测试。

如果 DXF 在查看器中可打开但在 AutoCAD 中报错，请确保安装了 `ezdxf` 后重新生成：

```bash
python -m pip install -r requirements.txt
python tools/standardize_section_dxf_batch.py
```

## Agent Skill

`SKILL.md` 包含可复用的 Agent 工作流，描述 AI 编码/制图 Agent 应如何：

- 扫描输入
- 匹配分组
- 对齐几何
- 分类图层
- 添加最小结构修补线
- 验证输出
- 报告限制

`AGENTS.md` 包含面向后续 Agent 和贡献者的仓库级指令。

## 不要提交的内容

默认不要提交私有项目图纸或生成产物。公开示例请使用脱敏或合成文件。

`.gitignore` 已拦截常见 CAD 源文件和生成输出目录。如需添加公开样例，放在 `examples/` 下。

## 许可证

[MIT License](LICENSE)
