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
CLASSIFIER_CHECKPOINT = os.path.join(BASE_DIR, 'ai_models', 'classifier', 'best_resnet50_scene.pth')
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

# 服务器配置
HOST = '0.0.0.0'
PORT = 6006

# ==================== 视频相关配置 ====================
VIDEO_DATABASE_PATH = os.path.join(DATA_DIR, 'video_data.db')
VIDEO_DB_INIT_SQL_PATH = os.path.join(BASE_DIR, 'sql', 'videodatamanage.sql')

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