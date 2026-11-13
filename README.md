# 公务员行测真题 · 命令行刷题

基于 [ERRRC/xingcezhenti](https://github.com/ERRRC/xingcezhenti) 真题库（2016–2026，515 套卷 / 58,890 题）的本地刷题工具。

## 快速开始

```bash
# 任意目录直接启动（已装到 /usr/local/bin/civil-exam）
civil-exam

# 常用参数
civil-exam --module 数量关系 --year 2024 --random 20
civil-exam --random 10           # 全库随机 10 题
civil-exam --list                # 查看模块/年份

# 等价于
python3 /root/civil-service-examination/tiku.py
```

## 交互流程

```
主菜单
 ├─ 1 按模块 + 年份刷真题   ← 选类型 → 选年份 → 随机/按试卷 → 答题
 ├─ 2 按模块随机刷题
 ├─ 3 全库随机刷题
 ├─ 4 指定试卷逐题刷
 ├─ 5 错题重练（本会话）
 ├─ 6 题库统计
 └─ 7 刷新图片索引
```

答题时：

| 输入 | 作用 |
|---|---|
| `A`…`H` | 作答（按该题实际选项） |
| `?` | 先看答案与解析 |
| `s` | 跳过 |
| `q` | 结束本组 |

## 图片渲染（双路）

| 类型 | 占位符 | 处理方式 |
|---|---|---|
| **公式/数字**（3.3 万张） | `{{tex:…}}` | **OCR 转真文本**（tesseract 多策略）→ 内联显示如 `3.4%`；无映射时小图 chafa 兜底 |
| **图表/题图**（6 千张） | `{{img:…}}` | **chafa 真彩块字符**，72×24 高分辨率保留结构；失败回退盲文 |

- 公式映射表：`bank/formula_text.json`（断点续传，`ocr_formulas.py` 维护）
- 图表依赖 [chafa](https://github.com/hpjansson/chafa)（可选，缺失自动盲文）
- 公式文本以青色内联，与正文区分

```bash
# 补跑/增量 OCR 公式
python3 ocr_formulas.py
```

- **图片已全部下载**：39,461 张（367MB），索引 `bank/image_index.json`
- 引用覆盖率 122,603/122,605（99.998%）；源仓库本身缺失 2 张，见 `bank/known_missing_images.json`
- 图片有增减时：菜单选 `7` 或 `civil-exam --refresh-index`

## 文件结构

```
civil-service-examination/
├── tiku.py                 # 刷题 CLI（主入口）
├── parse_bank.py           # md → 结构化题库
├── download_images.py      # 后台并行下载图片
├── bank/
│   ├── tiku.db             # SQLite 题库
│   ├── questions.jsonl     # JSONL 备份
│   └── image_index.json    # 图片文件名 → 路径索引
└── xingcezhenti/           # 真题 md + 图片（sparse clone）
    ├── 01-政治理论/ … 06-资料分析/
    └── 90-图片/{公式图,题目图}/
```

## 维护

```bash
# 重新解析题库（改了 md 之后）
python3 parse_bank.py

# 图片下载（断点续传，可反复跑）
python3 download_images.py -j 8

# 下载完成后刷新索引
python3 -c "from tiku import refresh_image_index; print(refresh_image_index())"
# 或 civil-exam --refresh-index
```

## 题库统计

| 模块 | 题量 |
|---|---|
| 判断推理 | 16,859 |
| 言语理解与表达 | 16,000 |
| 常识判断 | 9,163 |
| 资料分析 | 8,115 |
| 数量关系 | 6,448 |
| 政治理论 | 2,305 |
| **合计** | **58,890** |

- 年份 2016–2026，**515 套试卷**，**0 缺答案 / 0 空选项**
- 判断题（正确/错误）已补 A/B 选项；少量 A–H 八选项题完整支持
- 含图题目 20,581 道，图片引用基本 100% 就位

数据修复脚本：`fix_bank.py`（幂等，可重复执行）。
