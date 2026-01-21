# 系统修复总结

## 修复日期
2026-01-21

## 修复内容

### 1. 增加强制重新抽帧的参数开关

**问题描述：**
- 在debug时需要强制重新抽帧，但系统会自动跳过已标记为 `ai_processed=1` 的帧

**解决方案：**
- 在 `video_frame_extractor.py` 的 `extract_frames()` 方法中添加 `force_reprocess` 参数
- 当 `force_reprocess=True` 时，跳过 ai_processed 检查，强制重新处理
- 在 API 路由 `routes/video.py` 中添加对应的参数支持
- 在测试文件 `test_video_api.py` 中接入该参数

**修改文件：**
- `backend/services/video_frame_extractor.py`
- `backend/routes/video.py`
- `backend/test_video_api.py`

**使用示例：**
```python
# 在测试中强制重新抽帧
test_extract_frames(video_id, force_reprocess=True)

# API调用
POST /api/videos/{video_id}/extract
{
    "sample_rate": 100,
    "force_reprocess": true
}
```

---

### 2. 统一抽帧文件命名规范

**问题描述：**
- 不同抽帧方法使用不同的文件命名方式：
  - `_extract_with_imageio` 使用 `frame_{序号:06d}.jpg`（从0开始的计数器）
  - `_extract_with_ffmpeg_cli_pts` 使用 `frame_{PTS值}.jpg`（PTS时间戳）
- 导致文件名不一致，难以管理

**解决方案：**
- 统一使用 `frame_{frame_idx:08d}.jpg` 格式
- `frame_idx` 是视频中的真实帧索引位置，有明确的物理意义
- 8位数字格式（如 `frame_00000000.jpg`），支持最多9999万帧

**修改文件：**
- `backend/services/video_frame_extractor.py`
  - `_extract_with_imageio()` 方法
  - `_extract_with_ffmpeg_cli_pts()` 方法

**命名示例：**
```
frame_00000000.jpg  # 第0帧
frame_00000100.jpg  # 第100帧（如果sample_rate=100）
frame_00000200.jpg  # 第200帧
...
```

---

### 3. 优化OCR解析逻辑的鲁棒性

**问题描述：**
- OCR识别结果可能存在以下问题：
  1. 日期时间中间缺少空格：`2025-02-1404:42:12`
  2. 地名中间缺少分隔符：`广州南韶关`
  3. 字段名缺字：`间：广州南-韶关`（缺少"区"字）
  4. 字段名错字：`速魔:211km/h`（应该是"速度"）

**解决方案：**

#### 3.1 时间提取 (`_extract_time`)
- 支持标准格式：`2025-02-14 04:42:12`
- 支持缺少空格：`2025-02-1404:42:12` → 自动补充空格
- 支持多余空格：`2025-02-14  04:42:12` → 自动标准化
- 支持斜杠分隔：`2025/02/14 04:42:12` → 转换为短横线

#### 3.2 区间提取 (`_extract_route_section`)
- 支持标准格式：`区间：广州南-韶关`
- 支持缺字：`间：广州南-韶关`（缺"区"字）
- 支持错别字：`匹间：广州南-韶关`、`区问：广州南-韶关`
- 支持缺分隔符：`区间：广州南韶关` → 自动识别站点模式并添加分隔符
- 支持无标签：直接匹配中文站点对 `广州南-韶关`

#### 3.3 速度提取 (`_extract_float`)
- 支持标准格式：`速度：211.5`
- 支持错别字：`速魔：211`、`速庭：211`、`速腐：211`
- 容错模式：匹配"速"+"任意字"后跟数字

#### 3.4 里程提取 (`_extract_float`)
- 支持标准格式：`里程：Z123.5`
- 支持无Z前缀：`里程：123.5`
- 支持错别字：`呈程：Z123.5`、`里撇：123.5`、`里摆：123.5`

#### 3.5 车厢号提取 (`_extract_number`)
- 支持标准格式：`车厢号：5`
- 支持错别字：`车相号：5`、`车箱号：5`
- 支持缺'号'字：`车厢：5`

#### 3.6 位置号提取 (`_extract_number`)
- 支持标准格式：`位置号：3`
- 支持错别字：`立置号：3`、`位量号：3`
- 支持缺'号'字：`位置：3`

**修改文件：**
- `backend/services/video_ocr_service.py`
  - `_extract_time()` 方法
  - `_extract_route_section()` 方法
  - `_extract_number()` 方法
  - `_extract_float()` 方法

**测试脚本：**
- 创建了 `backend/test_ocr_robustness.py` 用于测试OCR解析的鲁棒性
- 运行方式：`python test_ocr_robustness.py`

---

## 测试建议

### 1. 测试强制重新抽帧
```bash
cd backend
# 修改 test_video_api.py 中的 force_reprocess 参数为 True
python test_video_api.py
```

### 2. 测试OCR鲁棒性
```bash
cd backend
python test_ocr_robustness.py
```

### 3. 完整系统测试
```bash
cd backend
# 启动后端服务
python app.py

# 在另一个终端运行测试
python test_video_api.py
```

---

## 注意事项

1. **向后兼容性：**
   - 所有修改都保持向后兼容
   - 新增的 `force_reprocess` 参数默认为 `False`
   - 文件命名统一不影响已有数据库记录

2. **性能影响：**
   - OCR容错匹配增加了多个正则表达式匹配，但性能影响微小
   - 建议在实际使用中监控OCR处理时间

3. **扩展性：**
   - OCR容错逻辑可以根据实际识别错误继续添加更多错别字模式
   - 建议定期收集OCR错误样本，持续优化容错规则

---

## 后续优化建议

1. **OCR错误样本收集：**
   - 建立OCR错误样本库
   - 定期分析常见错误模式
   - 持续优化容错规则

2. **机器学习优化：**
   - 考虑使用NLP技术进行智能纠错
   - 基于历史数据训练错误修正模型

3. **监控和日志：**
   - 添加OCR容错匹配的日志记录
   - 统计各类容错规则的命中率
   - 识别需要进一步优化的字段
