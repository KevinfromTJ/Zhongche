#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试OCR解析鲁棒性的脚本
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.video_ocr_service import VideoOCRService

def test_time_extraction():
    """测试时间提取的鲁棒性"""
    print("\n" + "="*60)
    print("测试1: 时间提取")
    print("="*60)
    
    service = VideoOCRService()
    
    test_cases = [
        ("标准格式", "时间：2025-02-14 04:42:12"),
        ("缺少空格", "时间：2025-02-1404:42:12"),
        ("多余空格", "时间：2025-02-14  04:42:12"),
        ("斜杠分隔", "时间：2025/02/14 04:42:12"),
    ]
    
    for desc, text in test_cases:
        result = service._extract_time(text)
        print(f"  {desc}: '{text}'")
        print(f"    → 提取结果: {result}")

def test_route_extraction():
    """测试区间提取的鲁棒性"""
    print("\n" + "="*60)
    print("测试2: 区间提取")
    print("="*60)
    
    service = VideoOCRService()
    
    test_cases = [
        ("标准格式", "区间：广州南-韶关"),
        ("缺'区'字", "间：广州南-韶关"),
        ("缺分隔符", "区间：广州南韶关"),
        ("错别字", "匹间：佛山西-宜宾"),
        ("无标签", "广州南-韶关 速度：200"),
    ]
    
    for desc, text in test_cases:
        result = service._extract_route_section(text)
        print(f"  {desc}: '{text}'")
        print(f"    → 提取结果: {result}")

def test_speed_extraction():
    """测试速度提取的鲁棒性"""
    print("\n" + "="*60)
    print("测试3: 速度提取")
    print("="*60)
    
    service = VideoOCRService()
    
    test_cases = [
        ("标准格式", "速度：211.5km/h"),
        ("错别字'魔'", "速魔：211km/h"),
        ("错别字'庭'", "速庭：211"),
        ("无单位", "速度：211.5"),
    ]
    
    for desc, text in test_cases:
        result = service._extract_float(text, r'速度[:：]?\s*(\d+\.?\d*)')
        print(f"  {desc}: '{text}'")
        print(f"    → 提取结果: {result}")

def test_mileage_extraction():
    """测试里程提取的鲁棒性"""
    print("\n" + "="*60)
    print("测试4: 里程提取")
    print("="*60)
    
    service = VideoOCRService()
    
    test_cases = [
        ("标准格式", "里程：Z123.5"),
        ("无Z前缀", "里程：123.5"),
        ("错别字'呈'", "呈程：Z123.5"),
        ("错别字'撇'", "里撇：123.5"),
    ]
    
    for desc, text in test_cases:
        result = service._extract_float(text, r'里程[:：]?\s*[Zz]?(\d+\.?\d*)')
        print(f"  {desc}: '{text}'")
        print(f"    → 提取结果: {result}")

def test_car_no_extraction():
    """测试车厢号提取的鲁棒性"""
    print("\n" + "="*60)
    print("测试5: 车厢号提取")
    print("="*60)
    
    service = VideoOCRService()
    
    test_cases = [
        ("标准格式", "车厢号：5"),
        ("错别字'相'", "车相号：5"),
        ("错别字'箱'", "车箱号：5"),
        ("缺'号'字", "车厢：5"),
    ]
    
    for desc, text in test_cases:
        result = service._extract_number(text, r'车厢号[:：]?\s*(\d+)')
        print(f"  {desc}: '{text}'")
        print(f"    → 提取结果: {result}")

def test_pos_no_extraction():
    """测试位置号提取的鲁棒性"""
    print("\n" + "="*60)
    print("测试6: 位置号提取")
    print("="*60)
    
    service = VideoOCRService()
    
    test_cases = [
        ("标准格式", "位置号：3"),
        ("错别字'立'", "立置号：3"),
        ("错别字'量'", "位量号：3"),
        ("缺'号'字", "位置：3"),
    ]
    
    for desc, text in test_cases:
        result = service._extract_number(text, r'位置号[:：]?\s*(\d+)')
        print(f"  {desc}: '{text}'")
        print(f"    → 提取结果: {result}")

def test_full_text():
    """测试完整OCR文本解析"""
    print("\n" + "="*60)
    print("测试7: 完整文本解析")
    print("="*60)
    
    service = VideoOCRService()
    
    # 模拟包含多种错误的OCR文本
    test_text = "2025-02-1404:42:12 G4926 间：广州南韶关 车相号：5 立置号：3 速魔：211km/h 呈程：Z123.5"
    
    print(f"  输入文本: {test_text}")
    print(f"\n  解析结果:")
    
    ocr_result = {
        '时间': service._extract_time(test_text),
        '车次': service._extract_train_no(test_text),
        '区间': service._extract_route_section(test_text),
        '车厢号': service._extract_number(test_text, r'车厢号[:：]?\s*(\d+)'),
        '位置号': service._extract_number(test_text, r'位置号[:：]?\s*(\d+)'),
        '速度': service._extract_float(test_text, r'速度[:：]?\s*(\d+\.?\d*)'),
        '里程': service._extract_float(test_text, r'里程[:：]?\s*[Zz]?(\d+\.?\d*)'),
    }
    
    for key, value in ocr_result.items():
        print(f"    {key}: {value}")

if __name__ == '__main__':
    print("\n" + "#"*60)
    print("#" + " "*58 + "#")
    print("#" + " "*15 + "OCR解析鲁棒性测试" + " "*15 + "#")
    print("#" + " "*58 + "#")
    print("#"*60)
    
    test_time_extraction()
    test_route_extraction()
    test_speed_extraction()
    test_mileage_extraction()
    test_car_no_extraction()
    test_pos_no_extraction()
    test_full_text()
    
    print("\n" + "="*60)
    print("测试完成！")
    print("="*60 + "\n")
