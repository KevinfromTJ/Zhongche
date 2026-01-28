"""
视频OCR服务
支持多种OCR后端：
1. PaddleOCR (PP-OCRv5_server) - 传统OCR，速度快
2. HunyuanOCR (基于Transformers的VLM) - 精度高但较慢

支持多进程并行推理（绕过Python GIL限制）

性能说明：
- 两种OCR都不支持真正的batch推理，每张图片需单独处理
- Python的GIL限制了多线程的真正并行
- 解决方案：使用多进程（multiprocessing）实现真正并行
- 每个进程独立加载OCR模型，在不同GPU上运行

配置说明：
- OCR_ENGINE_TYPE: 选择OCR后端 ("paddleocr" 或 "hunyuan")
- 通过环境变量或config.py配置
"""
import os
import sys
import re
import glob
from typing import Dict, List, Tuple
import time
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import multiprocessing as mp

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ============ OCR 引擎类型检测 ============

def _get_ocr_engine_type() -> str:
    """获取配置的OCR引擎类型"""
    from config import OCR_ENGINE_TYPE
    return OCR_ENGINE_TYPE.lower()


def is_hunyuan_ocr() -> bool:
    """检查是否使用 HunyuanOCR"""
    return _get_ocr_engine_type() == "hunyuan"


def is_paddle_ocr() -> bool:
    """检查是否使用 PaddleOCR"""
    return _get_ocr_engine_type() == "paddleocr"


# ============ PaddleOCR 相关代码 ============

# 全局变量：OCR实例（进程内单例）
_ocr_instance = None
_ocr_instance_lock = threading.Lock()


def _get_ocr_config():
    """获取OCR配置"""
    from config import (OCR_DET_MODEL_PATH, OCR_REC_MODEL_PATH,
                        OCR_DET_MODEL_NAME, OCR_REC_MODEL_NAME)
    return {
        'det_path': OCR_DET_MODEL_PATH,
        'rec_path': OCR_REC_MODEL_PATH,
        'det_name': OCR_DET_MODEL_NAME,
        'rec_name': OCR_REC_MODEL_NAME,
    }


def _create_ocr_instance(gpu_id: str):
    """创建OCR实例"""
    from paddleocr import PaddleOCR
    config = _get_ocr_config()
    
    device = f"gpu:{gpu_id}"
    
    # 构建模型参数
    ocr_kwargs = {
        'use_doc_orientation_classify': False,
        'use_doc_unwarping': False,
        'use_textline_orientation': False,
        'device': device,
    }
    
    # 优先使用路径配置，其次使用模型名称
    if config['det_path'] and os.path.exists(config['det_path']):
        ocr_kwargs['text_detection_model_dir'] = config['det_path']
    else:
        ocr_kwargs['text_detection_model_name'] = config['det_name']
    
    if config['rec_path'] and os.path.exists(config['rec_path']):
        ocr_kwargs['text_recognition_model_dir'] = config['rec_path']
    else:
        ocr_kwargs['text_recognition_model_name'] = config['rec_name']
    
    return PaddleOCR(**ocr_kwargs)


def get_ocr(device_id="0"):
    """获取OCR模型实例（进程内单例）"""
    global _ocr_instance
    
    with _ocr_instance_lock:
        if _ocr_instance is None:
            print(f"正在加载OCR模型 on gpu:{device_id}...")
            _ocr_instance = _create_ocr_instance(device_id)
            print("OCR模型加载完成")
        return _ocr_instance


def _parse_ocr_result(result) -> List[Dict]:
    """解析OCR结果"""
    if not result:
        return []
    
    recognized_items = []
    for page in result:
        det_polys = page.get("rec_polys", [])
        rec_texts = page.get("rec_texts", [])
        rec_scores = page.get("rec_scores", [])
        
        for i in range(len(det_polys)):
            recognized_items.append({
                'box': det_polys[i],
                'text': rec_texts[i],
                'confidence': float(rec_scores[i]) if rec_scores[i] else 1.0
            })
    
    return recognized_items


def _process_worker_init(gpu_id: str):
    """进程初始化函数：在工作进程中预加载OCR模型"""
    global _ocr_instance
    # 设置CUDA可见设备，限制此进程只能看到指定的GPU
    os.environ['CUDA_VISIBLE_DEVICES'] = gpu_id
    print(f"[PID:{os.getpid()}] 初始化OCR工作进程，GPU={gpu_id}")
    # 预加载模型（会在第一次predict时自动使用gpu:0，因为CUDA_VISIBLE_DEVICES的映射）
    _ocr_instance = _create_ocr_instance("0")  # 使用0因为CUDA_VISIBLE_DEVICES映射后只有一个GPU可见
    print(f"[PID:{os.getpid()}] OCR模型加载完成")


def _process_single_image(image_path: str) -> Tuple[str, List[Dict]]:
    """处理单张图片（在工作进程中执行）"""
    global _ocr_instance
    
    if not os.path.exists(image_path):
        return (image_path, [])
    
    try:
        result = _ocr_instance.predict(image_path)
        items = _parse_ocr_result(result)
        return (image_path, items)
    except Exception as e:
        print(f"⚠️ OCR处理失败 {image_path}: {e}")
        return (image_path, [])


# ============ 多进程池管理 ============
_process_pools = {}  # gpu_id -> ProcessPoolExecutor
_pools_lock = threading.Lock()


def _get_or_create_process_pool(gpu_id: str, workers_per_gpu: int) -> ProcessPoolExecutor:
    """获取或创建指定GPU的进程池"""
    global _process_pools
    
    with _pools_lock:
        if gpu_id not in _process_pools:
            print(f"🔧 创建GPU {gpu_id} 的进程池，工作进程数={workers_per_gpu}")
            # 使用spawn方式创建进程，避免CUDA上下文问题
            ctx = mp.get_context('spawn')
            pool = ProcessPoolExecutor(
                max_workers=workers_per_gpu,
                mp_context=ctx,
                initializer=_process_worker_init,
                initargs=(gpu_id,)
            )
            _process_pools[gpu_id] = pool
        return _process_pools[gpu_id]


def parallel_recognize_text_paddle(image_paths: List[str]) -> Dict[str, List[Dict]]:
    """
    多进程并行 PaddleOCR 识别（真正绕过GIL）
    
    使用多进程池，每个GPU一个进程池，进程数由OCR_INSTANCES_PER_GPU配置
    
    Args:
        image_paths: 图片路径列表
    
    Returns:
        {image_path: recognized_items} 的字典
    """
    if not image_paths:
        return {}
    
    from config import OCR_DEVICE_IDS, OCR_INSTANCES_PER_GPU
    
    gpu_ids = [g.strip() for g in OCR_DEVICE_IDS]
    num_gpus = len(gpu_ids)
    
    if num_gpus == 0:
        print("⚠️ 没有配置OCR GPU")
        return {}
    
    # 将图片均分到各个GPU
    gpu_tasks = {gpu_id: [] for gpu_id in gpu_ids}
    for i, img_path in enumerate(image_paths):
        gpu_id = gpu_ids[i % num_gpus]
        gpu_tasks[gpu_id].append(img_path)
    
    results = {}
    all_futures = []
    
    # 为每个GPU提交任务
    for gpu_id, tasks in gpu_tasks.items():
        if not tasks:
            continue
        
        pool = _get_or_create_process_pool(gpu_id, OCR_INSTANCES_PER_GPU)
        
        # 提交任务到进程池
        for img_path in tasks:
            future = pool.submit(_process_single_image, img_path)
            all_futures.append((future, gpu_id))
    
    # 收集结果
    for future, gpu_id in all_futures:
        try:
            img_path, items = future.result(timeout=60)  # 60秒超时
            results[img_path] = items
        except Exception as e:
            print(f"⚠️ GPU {gpu_id} OCR任务失败: {e}")
    
    return results


def parallel_recognize_text(image_paths: List[str]) -> Dict[str, List[Dict]]:
    """
    多进程并行OCR识别（自动选择后端）
    
    根据 OCR_ENGINE_TYPE 配置自动选择 PaddleOCR 或 HunyuanOCR
    
    Args:
        image_paths: 图片路径列表
    
    Returns:
        {image_path: recognized_items} 的字典
    """
    if not image_paths:
        return {}
    
    if is_hunyuan_ocr():
        # 使用 HunyuanOCR
        from services.hunyuan_ocr_service import parallel_recognize_text_hunyuan
        print(f"📝 使用 HunyuanOCR 处理 {len(image_paths)} 张图片...")
        return parallel_recognize_text_hunyuan(image_paths)
    else:
        # 默认使用 PaddleOCR
        print(f"📝 使用 PaddleOCR 处理 {len(image_paths)} 张图片...")
        return parallel_recognize_text_paddle(image_paths)


def recognize_text_paddle(image_path: str) -> List[Dict]:
    """
    使用 PaddleOCR 识别单张图片中的文字
    
    Args:
        image_path: 图片路径
    
    Returns:
        results: 识别结果列表
    """
    if not os.path.exists(image_path):
        print(f"⚠️ OCR图片不存在: {image_path}")
        return []
    
    from config import OCR_DEVICE_IDS
    gpu_id = OCR_DEVICE_IDS[0].strip() if OCR_DEVICE_IDS else "0"
    
    ocr = get_ocr(gpu_id)
    result = ocr.predict(image_path)
    return _parse_ocr_result(result)


def recognize_text(image_path: str) -> List[Dict]:
    """
    识别单张图片中的文字（自动选择后端）
    
    根据 OCR_ENGINE_TYPE 配置自动选择 PaddleOCR 或 HunyuanOCR
    
    Args:
        image_path: 图片路径
    
    Returns:
        results: 识别结果列表
    """
    if not os.path.exists(image_path):
        print(f"⚠️ OCR图片不存在: {image_path}")
        return []
    
    if is_hunyuan_ocr():
        # 使用 HunyuanOCR
        from services.hunyuan_ocr_service import recognize_text_hunyuan
        return recognize_text_hunyuan(image_path)
    else:
        # 默认使用 PaddleOCR
        return recognize_text_paddle(image_path)


class VideoOCRService:
    """视频OCR识别服务"""
    
    def __init__(self):
        pass
    
    def _parse_ocr_items(self, ocr_items: List[Dict]) -> Dict:
        """解析OCR识别结果"""
        full_text = ' '.join([item['text'] for item in ocr_items])
        avg_confidence = sum([item['confidence'] for item in ocr_items]) / len(ocr_items) if ocr_items else 0.0
        
        return {
            'ocr_text': full_text,
            'ocr_time': self._extract_time(full_text),
            'ocr_train_no': self._extract_train_no(full_text),
            'ocr_route_section': self._extract_route_section(full_text),
            'ocr_car_no': self._extract_number(full_text, r'车厢号[:：]?\s*(\d+)'),
            'ocr_pos_no': self._extract_number(full_text, r'位置号[:：]?\s*(\d+)'),
            'ocr_speed': self._extract_float(full_text, r'速度[:：]?\s*(\d+\.?\d*)'),
            'ocr_mileage': self._extract_float(full_text, r'里程[:：]?\s*[Zz]?(\d+\.?\d*)'),
            'ocr_confidence': round(avg_confidence, 3)
        }
    
    def extract_text(self, image_path: str, frame_idx: int = 0) -> Dict:
        """
        从图片中提取OCR文本并解析结构化信息
        
        Args:
            image_path: 图片路径
            frame_idx: 帧序号
        
        Returns:
            OCR结果字典
        """
        ocr_items = recognize_text(image_path)
        return self._parse_ocr_items(ocr_items)
    
    def batch_extract_parallel(self, image_paths: List[str]) -> List[Dict]:
        """
        批量并行OCR提取（多实例并行）
        
        Args:
            image_paths: 图片路径列表
        
        Returns:
            OCR结果列表，顺序与输入一致
        """
        if not image_paths:
            return []
        
        # 使用多实例并行识别
        ocr_results_dict = parallel_recognize_text(image_paths)
        
        # 按输入顺序返回结果
        results = []
        for img_path in image_paths:
            ocr_items = ocr_results_dict.get(img_path, [])
            results.append(self._parse_ocr_items(ocr_items))
        
        return results
    
    def _extract_time(self, text: str):
        """
        提取时间，支持鲁棒解析：
        - 标准格式：2025-02-14 04:42:12 或 2025/02/14 04:42:12
        - 缺少空格：2025-02-1404:42:12
        - 多余空格：2025-02-14  04:42:12
        """
        # 先匹配标准格式（有空格）
        pattern1 = r'(\d{4}[-/]\d{2}[-/]\d{2}\s+\d{2}:\d{2}:\d{2})'
        match = re.search(pattern1, text)
        if match:
            time_str = match.group(1).replace('/', '-')
            # 标准化空格
            time_str = re.sub(r'\s+', ' ', time_str)
            return time_str.replace(' ', 'T')  # 转ISO格式
        
        # 匹配缺少空格的格式：2025-02-1404:42:12
        pattern2 = r'(\d{4}[-/]\d{2}[-/]\d{2})(\d{2}:\d{2}:\d{2})'
        match = re.search(pattern2, text)
        if match:
            date_str = match.group(1).replace('/', '-')
            time_str = match.group(2)
            return f"{date_str}T{time_str}"  # ISO格式
        
        return None
    
    def _extract_train_no(self, text: str):
        """提取车次号"""
        # 匹配格式：G4926、D5678、C1234 等
        pattern = r'[CGDcgd]\d{4}'
        match = re.search(pattern, text)
        return match.group(0).upper() if match else None
    
    def _extract_route_section(self, text: str):
        """
        提取区间，支持鲁棒解析：
        - 标准格式：区间：广州南-韶关
        - 缺字格式：间：广州南-韶关（缺"区"字）
        - 缺分隔符：广州南韶关（OCR漏检"-"）
        - 错别字：区问、匹间 等
        """
        # 1. 匹配标准格式（有"区间"字样和分隔符）
        pattern1 = r'区间[:：]?\s*([\u4e00-\u9fa5]+-[\u4e00-\u9fa5]+)'
        match = re.search(pattern1, text)
        if match:
            return match.group(1)
        
        # 2. 匹配缺字格式（只有"间"或相似字）
        pattern2 = r'[区匹问]?间[:：]?\s*([\u4e00-\u9fa5]+-[\u4e00-\u9fa5]+)'
        match = re.search(pattern2, text)
        if match:
            return match.group(1)
        
        # 3. 匹配缺少分隔符的格式：识别常见站点模式
        # 常见站点后缀：南、北、东、西、站
        pattern3 = r'[区匹问]?间[:：]?\s*([\u4e00-\u9fa5]+[南北东西站])([\u4e00-\u9fa5]+[南北东西站]?)'
        match = re.search(pattern3, text)
        if match:
            station1 = match.group(1)
            station2 = match.group(2)
            # 如果识别到两个站点名，自动添加分隔符
            return f"{station1}-{station2}"
        
        # 4. 尝试匹配任何带分隔符的中文站点对（不要求"区间"字样）
        pattern4 = r'([\u4e00-\u9fa5]{2,}[南北东西站]?)\s*-\s*([\u4e00-\u9fa5]{2,}[南北东西站]?)'
        match = re.search(pattern4, text)
        if match:
            return f"{match.group(1)}-{match.group(2)}"
        
        return None
    
    def _extract_number(self, text: str, pattern: str):
        """
        提取整数，支持鲁棒解析：
        - 支持字段名错别字和缺字
        """
        # 先尝试原始模式
        match = re.search(pattern, text)
        if match:
            try:
                return int(match.group(1))
            except:
                pass
        
        # 容错匹配：处理常见错别字
        # 车厢号：车厢、车相、车箱等
        if '车厢号' in pattern:
            pattern_fuzzy = r'车[厢相箱][号导]?[:：]?\s*(\d+)'
            match = re.search(pattern_fuzzy, text)
            if match:
                try:
                    return int(match.group(1))
                except:
                    pass
        
        # 位置号：位置、立置、位量等
        if '位置号' in pattern:
            pattern_fuzzy = r'[位立][置量][号导]?[:：]?\s*(\d+)'
            match = re.search(pattern_fuzzy, text)
            if match:
                try:
                    return int(match.group(1))
                except:
                    pass
        
        return None
    
    def _extract_float(self, text: str, pattern: str):
        """
        提取浮点数，支持鲁棒解析：
        - 支持错别字：速魔 -> 速度
        """
        # 先尝试原始模式
        match = re.search(pattern, text)
        if match:
            try:
                return float(match.group(1))
            except:
                pass
        
        # 如果是速度字段，尝试容错匹配（速度、速魔、连度等错别字）
        if '速度' in pattern:
            # 容错模式：匹配"速"+"任意字" 后面跟数字
            pattern_fuzzy = r'速[度魔庭腐][:：]?\s*(\d+\.?\d*)'
            match = re.search(pattern_fuzzy, text)
            if match:
                try:
                    return float(match.group(1))
                except:
                    pass
        
        # 如果是里程字段，尝试容错匹配（里程、呈程、里撇等错别字）
        if '里程' in pattern:
            # 容错模式：匹配"里"或"呈"+"程"或类似字，支持可选的"Z"或"z"前缀
            pattern_fuzzy = r'[里呈][程撇摆][:：]?\s*[Zz]?(\d+\.?\d*)'
            match = re.search(pattern_fuzzy, text)
            if match:
                try:
                    return float(match.group(1))
                except:
                    pass
        
        return None
    
    def batch_extract(self, image_paths: list, start_frame_idx: int = 0) -> list:
        """批量提取OCR信息"""
        results = []
        for i, image_path in enumerate(image_paths):
            result = self.extract_text(image_path, start_frame_idx + i)
            results.append(result)
        return results


# 全局实例
video_ocr_service = VideoOCRService()


# ============ 工具函数 ============

def get_ocr_engine_info() -> Dict:
    """
    获取当前OCR引擎信息
    
    Returns:
        包含引擎类型和配置信息的字典
    """
    from config import OCR_ENGINE_TYPE, OCR_DEVICE_IDS, OCR_INSTANCES_PER_GPU
    
    info = {
        'engine_type': OCR_ENGINE_TYPE,
        'device_ids': OCR_DEVICE_IDS,
        'instances_per_gpu': OCR_INSTANCES_PER_GPU,
    }
    
    if is_hunyuan_ocr():
        from config import (
            HUNYUAN_OCR_MODEL_PATH,
            HUNYUAN_OCR_DTYPE,
            HUNYUAN_OCR_ATTN_IMPL,
            HUNYUAN_OCR_MAX_NEW_TOKENS,
        )
        info.update({
            'model_path': HUNYUAN_OCR_MODEL_PATH,
            'dtype': HUNYUAN_OCR_DTYPE,
            'attn_impl': HUNYUAN_OCR_ATTN_IMPL,
            'max_new_tokens': HUNYUAN_OCR_MAX_NEW_TOKENS,
        })
    else:
        from config import (
            OCR_DET_MODEL_NAME,
            OCR_REC_MODEL_NAME,
            OCR_DET_MODEL_PATH,
            OCR_REC_MODEL_PATH,
        )
        info.update({
            'det_model': OCR_DET_MODEL_PATH or OCR_DET_MODEL_NAME,
            'rec_model': OCR_REC_MODEL_PATH or OCR_REC_MODEL_NAME,
        })
    
    return info


def shutdown_ocr_pools():
    """关闭所有OCR进程池"""
    global _process_pools
    
    with _pools_lock:
        for gpu_id, pool in _process_pools.items():
            print(f"🔧 关闭 PaddleOCR GPU {gpu_id} 的进程池")
            pool.shutdown(wait=True)
        _process_pools.clear()
    
    # 如果使用 HunyuanOCR，也关闭其进程池
    if is_hunyuan_ocr():
        from services.hunyuan_ocr_service import shutdown_hunyuan_pools
        shutdown_hunyuan_pools()


if __name__ == '__main__':
    # 测试
    import sys
    if len(sys.argv) > 1:
        test_image = sys.argv[1]
    else:
        # test_image = "/data/chenjuntao/OtherProj/dataManage/ref_fengchen_251225/backend/data/video_frames/1/test_wrong/frame_00000300.jpg"
        # test_image = glob.glob("/data/chenjuntao/OtherProj/dataManage/ref_fengchen_251225/backend/data/video_frames/1/test_wrong/frame_*.jpg")

        # print("抽取数量:", len(test_image))
        test_image = "/data/chenjuntao/OtherProj/dataManage/6bd19657357ba82fa991df578e904cff.png"
    
    if test_image:  # os.path.exists(test_image):
        service = VideoOCRService()
        result = service.extract_text(test_image)
        print("\n=== OCR 结果 ===")
        for key, value in result.items():
            print(f"{key}: {value}")
    else:
        print(f"测试图片不存在: {test_image}")
        print("用法: python video_ocr_service.py <图片路径>")
    # import time
    # time.sleep(100)
        # Step 3: 测试 GPU OCR（仅在 Step 2 正常时进行）
# if paddle.is_compiled_with_cuda():
#     ocr_gpu = PaddleOCR(lang='ch')
#     res_gpu = ocr_gpu.ocr('/data/chenjuntao/OtherProj/dataManage/ref_fengchen_251225/backend/data/video_frames/1/test_wrong/frame_521999.jpg')
#     print("GPU result:", res_gpu)  # 如果这里是 None，就是 GPU 初始化问题
