import os

# 基础路径配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DATASETS_DIR = os.path.join(DATA_DIR, 'datasets')
ANNOTATIONS_DIR = os.path.join(DATA_DIR, 'annotations')
CHECKPOINTS_DIR = os.path.join(DATA_DIR, 'checkpoints')

# 确保目录存在
for dir_path in [DATA_DIR, DATASETS_DIR, ANNOTATIONS_DIR, CHECKPOINTS_DIR]:
    os.makedirs(dir_path, exist_ok=True)

# 数据库配置
DATABASE_PATH = os.path.join(DATA_DIR, 'easydata.db')
VIDEO_DATABASE_PATH = os.path.join(DATA_DIR, 'video_data.db')
VIDEO_DB_INIT_SQL_PATH = os.path.join(BASE_DIR, 'sql', 'videodatamanage.sql')

# Flask配置
class Config:
    SECRET_KEY = 'easydata-demo-secret-key'
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 最大上传500MB
    
# SAM模型配置
SAM_CHECKPOINT = os.path.join(BASE_DIR, 'ai_models', 'segmentation', 'sam_hq_vit_b.pth')
SAM_MODEL_TYPE = 'vit_b'
SAM_DEVICE = 'cuda'

# 分类模型配置
# CLASSIFIER_CHECKPOINT = os.path.join(BASE_DIR, 'ai_models', 'classifier', 'best_resnet50_scene.pth')
CLASSIFIER_CHECKPOINT = os.getenv("CLASSIFIER_CHECKPOINT", "/data1/zhanglu/zgzc/Scene_classification/best_resnet50_scene.pth")
CLASSIFIER_NUM_CLASSES = 8
CLASSIFIER_CLASS_NAMES = [
    "穿过高架桥",
    "阴天", 
    "晴天无太阳",
    "镜头雨滴",
    "黑夜",
    "隧道内",
    "暴雨",
    "太阳光直射弓头"  # 第8类
]

# 推理设备配置
# - OCR_DEVICE_IDS: OCR使用的GPU ID列表，如 "0,1,2" 表示使用GPU 0,1,2
# - CLASSIFIER_DEVICE_IDS: 分类器使用的GPU ID列表，如 "0,1" 表示使用GPU 0,1
# - OCR_INSTANCES_PER_GPU: 每张GPU上启动的OCR实例数量
# - CLASSIFIER_BATCH_SIZE: 分类器单次批处理大小
OCR_DEVICE_IDS = os.getenv("OCR_DEVICE_IDS", "4,5").split(",")  # 默认使用GPU 5
CLASSIFIER_DEVICE_IDS = os.getenv("CLASSIFIER_DEVICE_IDS", "0").split(",")  # 最好和OCR分开放
OCR_INSTANCES_PER_GPU = int(os.getenv("OCR_INSTANCES_PER_GPU", "4"))  # 每张GPU上的OCR实例数 4差不多了
CLASSIFIER_BATCH_SIZE = int(os.getenv("CLASSIFIER_BATCH_SIZE", "32"))  # 分类器batch大小 32-64差不多了

# 兼容旧配置（单设备）
OCR_DEVICE = os.getenv("OCR_DEVICE", f"gpu:{OCR_DEVICE_IDS[0]}")
CLASSIFIER_DEVICE = os.getenv("CLASSIFIER_DEVICE", f"cuda:{CLASSIFIER_DEVICE_IDS[0]}")

# OCR引擎类型配置
# - "paddleocr": 使用 PaddleOCR (PP-OCRv5_server)，传统OCR，速度快
# - "hunyuan": 使用 HunyuanOCR (基于Transformers的VLM)，精度高但较慢
OCR_ENGINE_TYPE = os.getenv("OCR_ENGINE_TYPE", "hunyuan")

# PaddleOCR 模型配置 (当 OCR_ENGINE_TYPE="paddleocr" 时生效)
OCR_DET_MODEL_PATH = os.getenv("OCR_DET_MODEL_PATH", None)  # None表示使用默认模型名
OCR_REC_MODEL_PATH = os.getenv("OCR_REC_MODEL_PATH", None)  # None表示使用默认模型名
OCR_DET_MODEL_NAME = os.getenv("OCR_DET_MODEL_NAME", "PP-OCRv5_server_det")  # 检测模型名称
OCR_REC_MODEL_NAME = os.getenv("OCR_REC_MODEL_NAME", "PP-OCRv5_server_rec")  # 识别模型名称

# HunyuanOCR 模型配置 (当 OCR_ENGINE_TYPE="hunyuan" 时生效)
HUNYUAN_OCR_MODEL_PATH = os.getenv("HUNYUAN_OCR_MODEL_PATH", "/data1/chenjuntao/Models_ckp/HunyuanOCR")
HUNYUAN_OCR_DTYPE = os.getenv("HUNYUAN_OCR_DTYPE", "bfloat16")  # bfloat16, float16, float32
HUNYUAN_OCR_ATTN_IMPL = os.getenv("HUNYUAN_OCR_ATTN_IMPL", "sdpa")  # sdpa, eager, flash_attention_2
HUNYUAN_OCR_MAX_NEW_TOKENS = int(os.getenv("HUNYUAN_OCR_MAX_NEW_TOKENS", "64"))  # 生成最大token数
# HUNYUAN_OCR_PROMPT = os.getenv("HUNYUAN_OCR_PROMPT", "提取图片中的文本，注意规范输出，不要有多余空格")
HUNYUAN_OCR_PROMPT = os.getenv("HUNYUAN_OCR_PROMPT", "提取图片中的文本，一共有7项，按 \"XX: XXX\" \"XX: XXX-YYY\" \"XX: XXX\" \"YYYY-MM-DD HH:MM:SS\" \"XX: YXXX\" \"XXX: XXX\" \"XXX: XXX\" 格式输出，不要有多余空格")


# 服务器配置
HOST = '0.0.0.0'
PORT = 6009

# 是否在AI处理完成后删除已落地的帧图片（仅保留数据库索引，按需抽帧）
DELETE_FRAME_IMAGES_AFTER_AI = False

# 视频抽帧默认配置
DEFAULT_MAX_FRAMES = int(os.getenv("DEFAULT_MAX_FRAMES", "1000"))  # 默认最大抽帧数
DEFAULT_SAMPLE_RATE = int(os.getenv("DEFAULT_SAMPLE_RATE", "10"))  # 默认采样率（每N帧抽1帧）

# 智能标注模型目录配置
CLASSIFICATION_MODELS_DIR = os.path.join(BASE_DIR, 'ai_models', 'classification')
DETECTION_MODELS_DIR = os.path.join(BASE_DIR, 'ai_models', 'detection')
SEGMENTATION_MODELS_DIR = os.path.join(BASE_DIR, 'ai_models', 'segmentation')

# 确保模型目录存在
for model_dir in [CLASSIFICATION_MODELS_DIR, DETECTION_MODELS_DIR, SEGMENTATION_MODELS_DIR]:
    os.makedirs(model_dir, exist_ok=True)

# 检测模型类别映射（与训练时保持一致）
DETECTION_CLASS_MAPPING = {
    0: "弓头",
    1: "避雷器",
    2: "支撑绝缘子",
    3: "半刚性终端",
    4: "底座"
}