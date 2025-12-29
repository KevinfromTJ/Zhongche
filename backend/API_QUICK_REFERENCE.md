# API 快速参考

## 🚀 快速开始

```bash
# 启动服务
cd /data/chenjuntao/OtherProj/dataManage/ref_fengchen_251225/backend
python app.py

# 运行测试
python test_video_api.py
```

---

## 📋 API 端点总览

### 视频管理 (`/api/videos`)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/videos` | 获取视频列表 |
| GET | `/api/videos/<id>` | 获取视频详情 |
| POST | `/api/videos/register` | 注册视频路径 |
| POST | `/api/videos/upload` | 上传视频文件 |
| POST | `/api/videos/<id>/extract` | 提取视频帧（串行） |
| POST | `/api/videos/<id>/process-ai` | AI处理帧 |
| DELETE | `/api/videos/<id>` | 删除视频 |
| GET | `/api/videos/statistics` | 获取统计信息 |

### 帧查询 (`/api/frames`)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/frames` | 基本帧列表 |
| GET | `/api/frames/<id>` | 获取帧详情 |
| GET | `/api/frames/query` | 多条件查询 ⭐ |
| GET | `/api/frames/search` | OCR文本搜索（LIKE） 🔍 |
| GET | `/api/frames/<id>/image` | 获取帧图片 |
| GET | `/api/frames/statistics` | 获取统计分布 |
| GET | `/api/frames/labels` | 获取可用标签 |
| GET | `/api/frames/date-range` | 获取时间范围 |

---

## 🎯 常用查询示例

### 1. 注册并处理视频

```python
import requests

BASE_URL = "http://localhost:6008/api"

# 步骤1: 注册视频
response = requests.post(f"{BASE_URL}/videos/register", json={
    "path": "/data1/sd_webui/anomaly_video/1塑料膜.mp4",
    "train_no": "G4926",
    "route_section": "佛山西-宜宾"
})
video_id = response.json()['data']['video_id']
print(f"视频ID: {video_id}")

# 步骤2: 抽帧
requests.post(f"{BASE_URL}/videos/{video_id}/extract", json={
    "max_frames": 100
})

# 步骤3: AI处理
requests.post(f"{BASE_URL}/videos/{video_id}/process-ai", json={
    "batch_size": 50
})
```

### 2. 按时间范围查询

```python
# 查询2月14日的所有帧
response = requests.get(f"{BASE_URL}/frames/query", params={
    "start_time": "2025-02-14T00:00:00",
    "end_time": "2025-02-14T23:59:59",
    "limit": 100
})
frames = response.json()['data']
```

### 3. 按车次查询

```python
# 查询G4926车次的帧
response = requests.get(f"{BASE_URL}/frames/query", params={
    "train_no": "G4926",
    "limit": 50
})
frames = response.json()['data']
```

### 4. 按标签组合查询

```python
# 查询晴天+隧道内的帧
response = requests.get(f"{BASE_URL}/frames/query", params={
    "weather": "晴天",
    "location": "隧道内",
    "limit": 50
})
frames = response.json()['data']
```

### 5. 按速度范围查询

```python
# 查询速度在200-300之间的帧
response = requests.get(f"{BASE_URL}/frames/query", params={
    "min_speed": 200,
    "max_speed": 300,
    "limit": 50
})
frames = response.json()['data']
```

### 6. OCR文本搜索（LIKE）

```python
# 搜索包含 "G4926" 的所有帧（ocr_text LIKE '%G4926%'）
response = requests.get(f"{BASE_URL}/frames/search", params={
    "keyword": "G4926",
    "limit": 50
})
frames = response.json()['data']
```

### 7. 组合查询

```python
# 复杂组合查询
response = requests.get(f"{BASE_URL}/frames/query", params={
    "start_time": "2025-02-14T04:00:00",
    "end_time": "2025-02-14T05:00:00",
    "train_no": "G4926",
    "weather": "晴天",
    "location": "隧道内",
    "min_speed": 200,
    "limit": 20
})
frames = response.json()['data']
```

---

## 📊 查询参数说明

### 时间相关
- `start_time`: 开始时间 (ISO格式: `2025-02-14T04:00:00`)
- `end_time`: 结束时间 (ISO格式)

### 车次/区间相关
- `train_no`: 车次号 (如: `G4926`)
- `route_section`: 区间 (支持模糊匹配，如: `佛山`)

### 标签相关
- `weather`: 天气 - `晴天`/`阴天`/`雨天`/`雾天`/`雪天`
- `location`: 位置 - `站台`/`隧道内`/`出站`/`进站`/`桥梁`/`平原`/`山区`
- `time_period`: 时段 - `白天`/`夜晚`/`黄昏`/`黎明`

### 速度相关
- `min_speed`: 最小速度 (km/h)
- `max_speed`: 最大速度 (km/h)

### 分页相关
- `limit`: 返回数量限制 (默认: 100)
- `offset`: 偏移量 (默认: 0)

---

## 🔧 返回数据结构

### 成功响应

```json
{
  "success": true,
  "count": 10,
  "data": [...]
}
```

### 错误响应

```json
{
  "success": false,
  "message": "错误描述"
}
```

### 帧对象字段

```json
{
  "id": 1,
  "video_id": 1,
  "frame_idx": 0,
  "pts_ms": 0,
  "image_path": "/path/to/frame.jpg",
  "ai_processed": true,
  "ocr_text": "完整OCR文本",
  "ocr_time": "2025-02-14T04:42:12",
  "ocr_train_no": "G4926",
  "ocr_carriage_no": "6",
  "ocr_position_no": "8",
  "ocr_speed": 231,
  "ocr_mileage": "Z6",
  "ocr_route_section": "佛山西-宜宾",
  "label_weather": "晴天",
  "label_location": "隧道内",
  "label_time_period": "白天",
  "label_anomaly": null,
  "label_confidence": 0.95
}
```

---

## 🐛 测试与调试

### 运行完整测试

```bash
cd backend
python test_video_api.py
```

### 运行快速测试

```bash
python test_video_api.py quick
```

### 检查服务状态

```bash
curl http://localhost:6008/api/health
```

### 查看数据库

```bash
sqlite3 data/easydata.db
sqlite> .tables
sqlite> SELECT * FROM videos;
sqlite> SELECT * FROM frames LIMIT 10;
```

---

## ⚡ 性能优化建议

1. **使用分页**: 大量数据时使用 `limit` 和 `offset`
2. **异步处理**: AI处理可使用 `async: true`；抽帧为串行执行
3. **批量操作**: AI处理时合理设置 `batch_size`
4. **索引优化**: 已对常用查询字段建立索引
5. **OCR搜索**: 使用 LIKE 包含匹配；建议结合结构化条件（如 `train_no`/时间范围）提升精度与性能

---

## 📝 注意事项

1. ✅ 所有时间使用ISO 8601格式
2. ✅ 视频路径需要服务器可访问
3. ✅ 支持中文搜索和标签
4. ✅ 默认端口: 6008
5. ✅ 数据库文件: 视频数据 `data/video_data.db`；标注数据 `data/easydata.db`

---

## 🆘 常见问题

### Q: 无法连接到服务？
A: 确保后端服务已启动: `python app.py`

### Q: 视频路径不存在？
A: 检查视频文件路径是否正确，服务器是否有访问权限

### Q: 查询结果为空？
A: 检查查询条件是否正确，确保数据已完成AI处理

### Q: OCR搜索不准确？
A: OCR是模拟数据，实际部署时需要接入真实OCR模型

---

## 📚 相关文档

- 详细API文档: `API_DOCUMENTATION.md`
- 数据库设计: `sql/videodatamanage.sql`
- 测试脚本: `test_video_api.py`
