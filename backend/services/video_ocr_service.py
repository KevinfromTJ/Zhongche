"""
视频OCR服务
调用 PaddleOCR (PP-OCRv5_server) 识别图片中的文字
"""
import os
import sys
import re
from typing import Dict, List

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 全局变量
_ocr_model = None


def get_ocr():
    """获取OCR模型（单例模式）"""
    global _ocr_model
    
    if _ocr_model is None:
        print("正在加载OCR模型 (PP-OCRv5_server)...")
        # 指定 OCR 推理设备（可在 config.py / 环境变量 OCR_DEVICE 中配置）
        try:
            from config import OCR_DEVICE
        except Exception:
            OCR_DEVICE = "gpu:0"
        try:
            import paddle
            try:
                paddle.set_device(OCR_DEVICE)
                print(f"  OCR设备: {OCR_DEVICE}")
            except Exception as e:
                print(f"⚠️ OCR设备设置失败({OCR_DEVICE})，回退cpu: {e}")
                try:
                    paddle.set_device("cpu")
                except Exception:
                    pass
        except Exception as e:
            print(f"⚠️ Paddle导入失败，OCR将使用默认设备: {e}")
        from paddleocr import PaddleOCR
        
        _ocr_model = PaddleOCR(
            text_detection_model_name="PP-OCRv5_server_det",
            text_recognition_model_name="PP-OCRv5_server_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        
        print("OCR模型加载完成")
    
    return _ocr_model


def recognize_text(image_path):
    """
    识别图片中的文字
    
    Args:
        image_path: 图片路径
    
    Returns:
        results: 识别结果列表，每个元素包含：
            - box: 文本框坐标
            - text: 识别的文字
            - confidence: 置信度（如果有）
    """
    ocr = get_ocr()
    
    assert os.path.exists(image_path), f"图片不存在: {image_path}"
    # 使用 predict 方法
    # image_path="https://paddle-model-ecology.bj.bcebos.com/paddlex/imgs/demo_image/general_ocr_002.png"
    result = ocr.predict(image_path)
    # print(result)
    # result = result[0]
    # print(result)
    if not result:
        return []
    
    recognized_items = []

    for page in result:
        det_polys = page["rec_polys"]
        rec_texts = page["rec_texts"]
        rec_scores = page["rec_scores"]
        # print(det_polys, rec_texts, rec_scores)
        for i in range(len(det_polys)):
            bbox = det_polys[i]         # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            text = rec_texts[i]         # 识别出的文本
            score = rec_scores[i]       # 置信度得分

            recognized_items.append({
                'box': bbox,
                'text': text,
                'confidence': float(score) if score else 1.0
            })
    
    # for res in result:
    #     if isinstance(res, dict):
    #         text = res.get('text', '')
    #         box = res.get('box', [])
    #         confidence = res.get('confidence', res.get('score', 1.0))  # 尝试获取置信度
            
    #         recognized_items.append({
    #             'box': box,
    #             'text': text,
    #             'confidence': float(confidence) if confidence else 1.0
    #         })
    # print("--------------------------------")
    return recognized_items


class VideoOCRService:
    """视频OCR识别服务"""
    
    def __init__(self):
        pass
    
    def extract_text(self, image_path: str, frame_idx: int = 0) -> Dict:
        """
        从图片中提取OCR文本并解析结构化信息
        
        Args:
            image_path: 图片路径
            frame_idx: 帧序号
        
        Returns:
            OCR结果字典
        """
        # 调用 PaddleOCR 识别
        ocr_items = recognize_text(image_path)
        
        # 拼接所有文本
        full_text = ' '.join([item['text'] for item in ocr_items])
        
        # 计算平均置信度
        avg_confidence = sum([item['confidence'] for item in ocr_items]) / len(ocr_items) if ocr_items else 0.0
        
        # 解析结构化信息（字段名与数据库一致）
        ocr_result = {
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
        
        return ocr_result
    
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


if __name__ == '__main__':
    # 测试
    import sys
    if len(sys.argv) > 1:
        test_image = sys.argv[1]
    else:
        test_image = "/data/chenjuntao/OtherProj/dataManage/ref_fengchen_251225/backend/data/video_frames/1/test_wrong/frame_540000.jpg"
    
    if os.path.exists(test_image):
        service = VideoOCRService()
        result = service.extract_text(test_image, 0)
        print("\n=== OCR 结果 ===")
        for key, value in result.items():
            print(f"{key}: {value}")
    else:
        print(f"测试图片不存在: {test_image}")
        print("用法: python video_ocr_service.py <图片路径>")

        # Step 3: 测试 GPU OCR（仅在 Step 2 正常时进行）
# if paddle.is_compiled_with_cuda():
#     ocr_gpu = PaddleOCR(lang='ch')
#     res_gpu = ocr_gpu.ocr('/data/chenjuntao/OtherProj/dataManage/ref_fengchen_251225/backend/data/video_frames/1/test_wrong/frame_521999.jpg')
#     print("GPU result:", res_gpu)  # 如果这里是 None，就是 GPU 初始化问题
