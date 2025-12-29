# 视频管理系统 API 文档

## 基础信息

- **基础URL**: `http://localhost:6008/api`
- **数据格式**: JSON
- **字符编码**: UTF-8

---

## 视频管理 API (`/api/videos`)

### 1. 获取视频列表

**GET** `/api/videos`

**Query参数**:
- `status` (可选): 过滤状态 - `pending`/`extracting`/`extracted`/`error`
- `train_no` (可选): 过滤车次号
- `limit` (可选): 返回数量限制
- `offset` (可选): 偏移量 (默认: 0)

**返回示例**:
```json
{
  "success": true,
  "count": 2,
  "data": [
    {
      "id": 1,
      "path": "/path/to/video.mp4",
      "filename": "video.mp4",
      "train_no": "G4926",
      "route_section": "佛山西-宜宾",
      "status": "extracted",
      "created_at": "2025-02-14 10:00:00"
    }
  ]
}
```

---

### 2. 获取视频详情

**GET** `/api/videos/<video_id>`

**返回示例**:
```json
{
  "success": true,
  "data": {
    "id": 1,
    "path": "/path/to/video.mp4",
    "filename": "video.mp4",
    "train_no": "G4926",
    "route_section": "佛山西-宜宾",
    "status": "extracted",
    "frame_count": 150,
    "processed_frame_count": 150,
    "created_at": "2025-02-14 10:00:00"
  }
}
```

---

### 3. 注册视频路径

**POST** `/api/videos/register`

**请求体**:
```json
{
  "path": "/data1/sd_webui/anomaly_video/1塑料膜.mp4",
  "train_no": "G4926",
  "route_section": "佛山西-宜宾"
}
```

**返回示例**:
```json
{
  "success": true,
  "message": "视频注册成功",
  "data": {
    "video_id": 1,
    "path": "/path/to/video.mp4"
  }
}
```

---

### 4. 上传视频文件

**POST** `/api/videos/upload`

**Content-Type**: `multipart/form-data`

**Form参数**:
- `file`: 视频文件
- `train_no` (可选): 车次号
- `route_section` (可选): 区间

**返回示例**:
```json
{
  "success": true,
  "message": "视频上传成功",
  "data": {
    "video_id": 1,
    "filename": "20250214_100000_video.mp4",
    "path": "/path/to/uploads/20250214_100000_video.mp4"
  }
}
```

---

### 5. 提取视频帧（串行执行）

**POST** `/api/videos/<video_id>/extract`

**请求体**:
```json
{
  "max_frames": 100,
  "sample_rate": 30
}
```

**参数说明**:
- `max_frames` (可选): 最大提取帧数
- `sample_rate` (可选): 采样率（每N帧采样一次）

说明：抽帧为进程内串行执行（同一时刻仅一个抽帧任务执行），不再支持异步参数。

**返回示例**:
```json
{
  "success": true,
  "video_id": 1,
  "extracted_frames": 100,
  "output_dir": "/path/to/frames"
}
```

---

### 6. AI处理视频帧

**POST** `/api/videos/<video_id>/process-ai`

**请求体**:
```json
{
  "batch_size": 50,
  "async": false
}
```

**参数说明**:
- `batch_size` (可选): 批处理大小 (默认: 50)
- `async` (可选): 是否异步执行 (默认: false)

**返回示例 (同步)**:
```json
{
  "success": true,
  "message": "AI处理完成",
  "processed_count": 100,
  "duration_sec": 45.2
}
```

---

### 7. 删除视频

**DELETE** `/api/videos/<video_id>`

**返回示例**:
```json
{
  "success": true,
  "message": "视频已删除"
}
```

---

### 8. 获取视频统计信息

**GET** `/api/videos/statistics`

**返回示例**:
```json
{
  "success": true,
  "data": {
    "total_videos": 10,
    "total_frames": 1500,
    "processed_frames": 1200,
    "pending_videos": 2,
    "extracting_videos": 1,
    "extracted_videos": 7,
    "error_videos": 0
  }
}
```

---

## 帧查询 API (`/api/frames`)

### 1. 基本帧列表查询

**GET** `/api/frames`

**Query参数**:
- `video_id` (可选): 视频ID
- `ai_processed` (可选): 是否已AI处理 - `true`/`false`
- `limit` (可选): 返回数量限制 (默认: 100)
- `offset` (可选): 偏移量 (默认: 0)

**返回示例**:
```json
{
  "success": true,
  "count": 10,
  "data": [
    {
      "id": 1,
      "video_id": 1,
      "frame_idx": 0,
      "pts_ms": 0,
      "image_path": "/path/to/frame_000.jpg",
      "ai_processed": true,
      "ocr_time": "2025-02-14T04:42:12",
      "ocr_train_no": "G4926",
      "ocr_speed": 231,
      "label_weather": "晴天",
      "label_location": "隧道内",
      "label_time_period": "白天"
    }
  ]
}
```

---

### 2. 获取单个帧详情

**GET** `/api/frames/<frame_id>`

**返回示例**:
```json
{
  "success": true,
  "data": {
    "id": 1,
    "video_id": 1,
    "frame_idx": 0,
    "pts_ms": 0,
    "image_path": "/path/to/frame_000.jpg",
    "ai_processed": true,
    "ocr_text": "车次:G4926 速度:231 区间:佛山西-宜宾",
    "ocr_time": "2025-02-14T04:42:12",
    "ocr_train_no": "G4926",
    "ocr_speed": 231,
    "ocr_route_section": "佛山西-宜宾",
    "label_weather": "晴天",
    "label_location": "隧道内",
    "label_time_period": "白天",
    "label_anomaly": null
  }
}
```

---

### 3. 高级多条件查询

**GET** `/api/frames/query`

**Query参数**:
- `start_time` (可选): 开始时间 (ISO格式: `2025-02-14T04:00:00`)
- `end_time` (可选): 结束时间 (ISO格式)
- `train_no` (可选): 车次号 (如: `G4926`)
- `route_section` (可选): 区间 (支持模糊匹配，如: `佛山`)
- `weather` (可选): 天气标签 - `晴天`/`阴天`/`雨天`/`雾天`/`雪天`
- `location` (可选): 位置标签 - `站台`/`隧道内`/`出站`/`进站`/`桥梁`/`平原`/`山区`
- `time_period` (可选): 时段标签 - `白天`/`夜晚`/`黄昏`/`黎明`
- `min_speed` (可选): 最小速度 (km/h)
- `max_speed` (可选): 最大速度 (km/h)
- `limit` (可选): 返回数量限制 (默认: 100)
- `offset` (可选): 偏移量 (默认: 0)

**示例请求**:
```
GET /api/frames/query?train_no=G4926&weather=晴天&min_speed=200&limit=20
```

**返回示例**:
```json
{
  "success": true,
  "count": 15,
  "query_params": {
    "train_no": "G4926",
    "weather": "晴天",
    "min_speed": 200,
    "limit": 20
  },
  "data": [
    {
      "id": 1,
      "video_id": 1,
      "frame_idx": 0,
      "ocr_time": "2025-02-14T04:42:12",
      "ocr_train_no": "G4926",
      "ocr_speed": 231,
      "label_weather": "晴天"
    }
  ]
}
```

---

### 4. OCR文本搜索（基于 LIKE）

**GET** `/api/frames/search`

**Query参数**:
- `keyword` (必需): 搜索关键词
- `limit` (可选): 返回数量限制 (默认: 100)

**示例请求**:
```
GET /api/frames/search?keyword=G4926&limit=20
```

**返回示例**:
```json
{
  "success": true,
  "count": 25,
  "keyword": "G4926",
  "data": [
    {
      "id": 1,
      "ocr_text": "车次:G4926 速度:231 ...",
      "ocr_train_no": "G4926"
    }
  ]
}
```

---

### 5. 获取帧图片

**GET** `/api/frames/<frame_id>/image`

**返回**: 图片文件 (JPEG)

---

### 6. 获取帧统计分布

**GET** `/api/frames/statistics`

**Query参数**: 与 `/api/frames/query` 相同

**返回示例**:
```json
{
  "success": true,
  "total_frames": 1000,
  "query_params": {},
  "distributions": {
    "weather": {
      "晴天": 600,
      "阴天": 300,
      "雨天": 100
    },
    "location": {
      "隧道内": 400,
      "站台": 200,
      "出站": 400
    },
    "time_period": {
      "白天": 700,
      "夜晚": 300
    },
    "anomaly": {
      "塑料膜": 50,
      "异物": 30
    },
    "speed_ranges": {
      "0-50": 100,
      "50-100": 200,
      "100-200": 300,
      "200-300": 350,
      "300+": 50
    }
  }
}
```

---

### 7. 获取可用标签类别

**GET** `/api/frames/labels`

**返回示例**:
```json
{
  "success": true,
  "data": {
    "weather": ["晴天", "阴天", "雨天", "雾天", "雪天"],
    "location": ["站台", "隧道内", "出站", "进站", "桥梁", "平原", "山区"],
    "time_period": ["白天", "夜晚", "黄昏", "黎明"],
    "anomaly": ["塑料膜", "异物", "裂缝", "积水", "正常"]
  }
}
```

---

### 8. 获取数据时间范围

**GET** `/api/frames/date-range`

**Query参数**:
- `train_no` (可选): 按车次过滤

**返回示例**:
```json
{
  "success": true,
  "has_data": true,
  "data": {
    "earliest_time": "2025-02-14T04:00:00",
    "latest_time": "2025-02-14T18:30:00"
  }
}
```

---

## 健康检查

### 健康检查接口

**GET** `/api/health`

**返回示例**:
```json
{
  "status": "ok",
  "message": "EasyData Demo Backend Running"
}
```

---

## 错误响应格式

所有错误响应遵循以下格式：

```json
{
  "success": false,
  "message": "错误描述信息"
}
```

常见HTTP状态码：
- `200` - 请求成功
- `400` - 请求参数错误
- `404` - 资源不存在
- `500` - 服务器内部错误

---

## 使用示例

### Python示例

```python
import requests

BASE_URL = "http://localhost:6008/api"

# 1. 注册视频
response = requests.post(f"{BASE_URL}/videos/register", json={
    "path": "/path/to/video.mp4",
    "train_no": "G4926",
    "route_section": "佛山西-宜宾"
})
video_id = response.json()['data']['video_id']

# 2. 提取帧
response = requests.post(f"{BASE_URL}/videos/{video_id}/extract", json={
    "max_frames": 100
})

# 3. AI处理
response = requests.post(f"{BASE_URL}/videos/{video_id}/process-ai", json={
    "batch_size": 50
})

# 4. 查询帧
response = requests.get(f"{BASE_URL}/frames/query", params={
    "train_no": "G4926",
    "weather": "晴天",
    "limit": 20
})
frames = response.json()['data']
```

### cURL示例

```bash
# 注册视频
curl -X POST http://localhost:6008/api/videos/register \
  -H "Content-Type: application/json" \
  -d '{"path": "/path/to/video.mp4", "train_no": "G4926"}'

# 查询帧
curl "http://localhost:6008/api/frames/query?train_no=G4926&weather=晴天&limit=20"

# OCR搜索
curl "http://localhost:6008/api/frames/search?keyword=G4926"
```

---

## 数据模型

### 视频对象 (Video)

```json
{
  "id": 1,
  "path": "/path/to/video.mp4",
  "filename": "video.mp4",
  "train_no": "G4926",
  "route_section": "佛山西-宜宾",
  "start_time": "2025-02-14T04:00:00",
  "end_time": "2025-02-14T05:00:00",
  "duration_sec": 3600,
  "fps": 24,
  "frame_count": 86400,
  "status": "extracted",
  "error_msg": null,
  "created_at": "2025-02-14 10:00:00",
  "updated_at": "2025-02-14 10:15:00"
}
```

### 帧对象 (Frame)

```json
{
  "id": 1,
  "video_id": 1,
  "frame_idx": 0,
  "pts_ms": 0,
  "image_path": "/path/to/frame.jpg",
  "ai_processed": true,
  "ocr_text": "车次:G4926 速度:231 区间:佛山西-宜宾 里程:Z6",
  "ocr_time": "2025-02-14T04:42:12",
  "ocr_train_no": "G4926",
  "ocr_car_no": 6,
  "ocr_pos_no": 8,
  "ocr_speed": 231.0,
  "ocr_mileage": 6.0,
  "ocr_route_section": "佛山西-宜宾",
  "label_weather": "晴天",
  "label_weather_score": 0.92,
  "label_location": "隧道内",
  "label_location_score": 0.87,
  "label_time_period": "白天",
  "label_time_period_score": 0.90,
  "label_anomaly": null,
  "label_anomaly_score": null,
  "created_at": "2025-02-14 10:15:00"
}
```

---

## 注意事项

1. **时间格式**: 所有时间使用ISO 8601格式 (`2025-02-14T04:42:12`)
2. **分页**: 使用 `limit` 和 `offset` 参数进行分页
3. **抽帧执行**: 抽帧为串行任务；AI处理支持 `async: true`
4. **文件路径**: 确保视频文件路径在服务器上可访问
5. **OCR搜索**: 使用 `ocr_text LIKE '%keyword%'` 的简单包含匹配（无中文分词）
6. **模糊匹配**: `route_section` 参数支持模糊匹配（LIKE查询）
7. **数据库文件**: 视频数据存储在 `data/video_data.db`；标注数据存储在 `data/easydata.db`

---

## 更新日志

### v1.0.0 (2025-02-14)
- ✅ 视频管理功能
- ✅ 智能抽帧功能
- ✅ AI处理（OCR + 分类）
- ✅ 多维度查询功能
- ✅ OCR文本搜索（LIKE）
- ✅ 统计分析功能
