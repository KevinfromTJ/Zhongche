#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频管理API测试脚本

测试功能：
1. 视频上传与信息提取
2. 视频抽帧
3. AI处理（OCR + 分类）
4. 多条件查询
"""

import requests
import json
import time
import os
from pathlib import Path

# API基础URL
BASE_URL = "http://localhost:6008/api"

def print_separator(title=""):
    """打印分隔线"""
    print("\n" + "="*80)
    if title:
        print(f"  {title}")
        print("="*80)

def print_response(response):
    """美化打印响应"""
    try:
        data = response.json()
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(data, indent=2, ensure_ascii=False)}")
    except:
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")

# ============================================================================
# 测试1: 注册视频路径
# ============================================================================
def test_upload_video():
    """测试视频注册（使用已存在的视频路径）"""
    print_separator("测试1: 注册视频路径")
    
    # 使用已存在的视频路径
    # video_path = "/data1/sd_webui/anomaly_video/1塑料膜.mp4"
    video_path = "/data1/sd_webui/first_8class_video/video/晴天无太阳/20250205_03_08_1815_G895.MP4"
    
    data = {
        "path": video_path,
        "train_no": "G4926",
        "route_section": "佛山西-宜宾"
    }
    
    print(f"注册视频: {video_path}")
    print(f"车次: {data['train_no']}, 区间: {data['route_section']}")
    
    try:
        response = requests.post(f"{BASE_URL}/videos/register", json=data)
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                video_id = result['data']['id']
                print(f"\n✓ 视频注册成功，ID: {video_id}")
                return video_id
    except Exception as e:
        print(f"✗ 注册失败: {str(e)}")
    
    return None

# ============================================================================
# 测试2: 获取视频列表
# ============================================================================
def test_get_videos():
    """测试获取视频列表"""
    print_separator("测试2: 获取视频列表")
    
    try:
        response = requests.get(f"{BASE_URL}/videos")
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            videos = result.get('data', [])
            print(f"\n✓ 获取到 {len(videos)} 个视频")
            return videos
    except Exception as e:
        print(f"✗ 获取视频列表失败: {str(e)}")
    
    return []

# ============================================================================
# 测试3: 视频抽帧
# ============================================================================
def test_extract_frames(video_id):
    """测试视频抽帧"""
    print_separator(f"测试3: 抽帧视频 (ID={video_id})")
    
    data = {
        "max_frames": 100,  # 最多抽50帧
        "async": False  # 同步执行
    }
    
    print(f"开始抽帧，最大帧数: {data['max_frames']}")
    
    try:
        response = requests.post(f"{BASE_URL}/videos/{video_id}/extract", json=data)
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                frame_count = result.get('frame_count', 0)
                print(f"\n✓ 抽帧成功，共 {frame_count} 帧")
                return True
    except Exception as e:
        print(f"✗ 抽帧失败: {str(e)}")
    
    return False

# ============================================================================
# 测试4: AI处理帧
# ============================================================================
def test_process_frames(video_id):
    """测试AI处理"""
    print_separator(f"测试4: AI处理帧 (ID={video_id})")
    
    data = {
        "batch_size": 10,
        "async": False  # 同步执行
    }
    
    print(f"开始AI处理，批次大小: {data['batch_size']}")
    
    try:
        response = requests.post(f"{BASE_URL}/videos/{video_id}/process-ai", json=data)
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                processed = result.get('processed_count', 0)
                print(f"\n✓ AI处理成功，处理了 {processed} 帧")
                return True
    except Exception as e:
        print(f"✗ AI处理失败: {str(e)}")
    
    return False

# ============================================================================
# 测试5: 查询视频的所有帧
# ============================================================================
def test_get_frames_by_video(video_id):
    """测试查询视频的帧"""
    print_separator(f"测试5: 查询视频帧 (ID={video_id})")
    
    params = {
        "video_id": video_id,
        "limit": 10,
        "offset": 0
    }
    
    try:
        response = requests.get(f"{BASE_URL}/frames", params=params)
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            frames = result.get('data', [])
            count = result.get('count', 0)
            print(f"\n✓ 获取到 {count} 帧")
            return frames
    except Exception as e:
        print(f"✗ 查询失败: {str(e)}")
    
    return []

# ============================================================================
# 测试6: 按时间范围查询
# ============================================================================
def test_query_by_time_range():
    """测试按时间范围查询"""
    print_separator("测试6: 按时间范围查询")
    
    params = {
        "start_time": "2025-02-14T00:00:00",
        "end_time": "2025-02-14T23:59:59",
        "limit": 20,
        "offset": 0
    }
    
    print(f"查询时间范围: {params['start_time']} ~ {params['end_time']}")
    
    try:
        response = requests.get(f"{BASE_URL}/frames/query", params=params)
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            frames = result.get('data', [])
            count = result.get('count', 0)
            print(f"\n✓ 查询到 {count} 帧")
            return frames
    except Exception as e:
        print(f"✗ 查询失败: {str(e)}")
    
    return []

# ============================================================================
# 测试7: 按车次查询
# ============================================================================
def test_query_by_train():
    """测试按车次查询"""
    print_separator("测试7: 按车次查询")
    
    params = {
        "train_no": "G4926",
        "limit": 20,
        "offset": 0
    }
    
    print(f"查询车次: {params['train_no']}")
    
    try:
        response = requests.get(f"{BASE_URL}/frames/query", params=params)
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            frames = result.get('data', [])
            count = result.get('count', 0)
            print(f"\n✓ 查询到 {count} 帧")
            return frames
    except Exception as e:
        print(f"✗ 查询失败: {str(e)}")
    
    return []


# ============================================================================
# 测试8: 按区间查询
# ============================================================================
def test_query_by_route():
    """测试按区间查询"""
    print_separator("测试8: 按区间查询")
    
    params = {
        "route_section": "佛山西-宜宾",
        "limit": 20,
        "offset": 0
    }
    
    print(f"查询区间: {params['route_section']}")
    
    try:
        response = requests.get(f"{BASE_URL}/frames/query", params=params)
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            frames = result.get('data', [])
            count = result.get('count', 0)
            print(f"\n✓ 查询到 {count} 帧")
            return frames
    except Exception as e:
        print(f"✗ 查询失败: {str(e)}")
    
    return []


# ============================================================================
# 测试9: 按标签查询（多标签）
# ============================================================================
def test_query_by_labels():
    """测试按标签查询"""
    print_separator("测试9: 按标签查询")
    
    params = {
        "weather": "晴天",
        "location": "隧道内",
        "limit": 20,
        "offset": 0
    }
    
    print(f"查询条件: 天气={params['weather']}, 位置={params['location']}")
    
    try:
        response = requests.get(f"{BASE_URL}/frames/query", params=params)
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            frames = result.get('data', [])
            count = result.get('count', 0)
            print(f"\n✓ 查询到 {count} 帧")
            return frames
    except Exception as e:
        print(f"✗ 查询失败: {str(e)}")
    
    return []


# ============================================================================
# 测试10: OCR全文检索
# ============================================================================
def test_ocr_search():
    """测试OCR全文检索"""
    print_separator("测试10: OCR全文检索")
    
    params = {
        "keyword": "G4926",
        "limit": 20
    }
    
    print(f"搜索关键词: {params['keyword']}")
    
    try:
        response = requests.get(f"{BASE_URL}/frames/search", params=params)
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            frames = result.get('data', [])
            count = result.get('count', 0)
            print(f"\n✓ 搜索到 {count} 帧")
            return frames
    except Exception as e:
        print(f"✗ 搜索失败: {str(e)}")
    
    return []


# ============================================================================
# 测试11: 组合查询
# ============================================================================
def test_combined_query():
    """测试组合查询"""
    print_separator("测试11: 组合查询（时间+车次+标签）")
    
    params = {
        "start_time": "2025-02-14T00:00:00",
        "end_time": "2025-02-14T23:59:59",
        "train_no": "G4926",
        "weather": "晴天",
        "limit": 20,
        "offset": 0
    }
    
    print(f"查询条件:")
    print(f"  时间: {params['start_time']} ~ {params['end_time']}")
    print(f"  车次: {params['train_no']}")
    print(f"  天气: {params['weather']}")
    
    try:
        response = requests.get(f"{BASE_URL}/frames/query", params=params)
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            frames = result.get('data', [])
            count = result.get('count', 0)
            print(f"\n✓ 查询到 {count} 帧")
            return frames
    except Exception as e:
        print(f"✗ 查询失败: {str(e)}")
    
    return []


# ============================================================================
# 测试12: 获取统计信息
# ============================================================================
def test_get_stats():
    """测试获取统计信息"""
    print_separator("测试12: 获取统计信息")
    
    try:
        # 获取视频统计
        response = requests.get(f"{BASE_URL}/videos/statistics")
        print("视频统计:")
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            stats = result.get('data', {})
            print(f"\n✓ 视频统计:")
            print(f"  总视频数: {stats.get('total_videos', 0)}")
            print(f"  总帧数: {stats.get('total_frames', 0)}")
            print(f"  已处理帧数: {stats.get('processed_frames', 0)}")
            
        # 获取帧分布统计
        print("\n\n帧分布统计:")
        response2 = requests.get(f"{BASE_URL}/frames/statistics")
        print_response(response2)
        
        return stats
    except Exception as e:
        print(f"✗ 获取统计失败: {str(e)}")
    
    return {}

# ============================================================================
# 主测试流程
# ============================================================================
def run_all_tests():
    """运行所有测试"""
    print("\n" + "█"*80)
    print("█" + " "*78 + "█")
    print("█" + " "*25 + "视频管理系统 API 测试" + " "*25 + "█")
    print("█" + " "*78 + "█")
    print("█"*80)
    
    # 检查服务是否运行
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=2)
        print(f"\n✓ 服务运行正常 (Status: {response.status_code})")
    except:
        print("\n✗ 无法连接到服务，请确保后端服务已启动")
        print("  启动命令: python app.py")
        return
    
    # 执行测试
    video_id = None
    
    # 1. 上传视频
    video_id = test_upload_video()
    if not video_id:
        print("\n⚠ 视频上传失败，尝试获取现有视频...")
        videos = test_get_videos()
        if videos:
            video_id = videos[0]['id']
            print(f"使用现有视频 ID: {video_id}")
    
    time.sleep(1)
    
    # 2. 获取视频列表
    test_get_videos()
    time.sleep(1)
    
    if video_id:
        # 3. 视频抽帧
        if test_extract_frames(video_id):
            time.sleep(2)
            
            # 4. AI处理
            test_process_frames(video_id)
            time.sleep(2)
            
            # exit()
            # 5. 查询视频的帧
            test_get_frames_by_video(video_id)
            time.sleep(1)
    
    # 6-11. 各种查询测试
    test_query_by_time_range()
    time.sleep(1)
    
    test_query_by_train()
    time.sleep(1)
    
    test_query_by_route()
    time.sleep(1)
    
    test_query_by_labels()
    time.sleep(1)
    
    test_ocr_search()
    time.sleep(1)
    
    test_combined_query()
    time.sleep(1)
    
    # 12. 统计信息
    test_get_stats()
    
    # 测试完成
    print_separator("测试完成")
    print("\n所有测试已执行完毕！")
    print("\n提示:")
    print("  - 如果某些测试失败，请检查后端日志")
    print("  - 确保视频文件路径正确")
    print("  - 数据库文件位于: backend/data/easydata.db")
    print("\n" + "█"*80 + "\n")

# ============================================================================
# 快速测试（不需要真实视频文件）
# ============================================================================
def quick_test():
    """快速测试（仅测试查询功能）"""
    print_separator("快速测试模式")
    
    # 测试获取列表
    videos = test_get_videos()
    time.sleep(1)
    
    if videos:
        video_id = videos[0]['id']
        test_get_frames_by_video(video_id)
    
    # 测试各种查询
    test_query_by_time_range()
    test_query_by_train()
    test_query_by_labels()
    test_ocr_search()
    test_get_stats()
    
    print_separator("快速测试完成")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "quick":
        quick_test()
    else:
        run_all_tests()
