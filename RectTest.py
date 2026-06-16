#!/usr/bin/env python3
"""
从剪贴板读取图片，根据 JSON 中给定的相对坐标绘制矩形，并显示。
JSON 格式示例：
[
  {
    "text": "Hello",
    "box": {
      "leftTop": {"x": 0.1, "y": 0.2},
      "rightBottom": {"x": 0.3, "y": 0.4}
    }
  }
]
"""

import sys
import json
from PIL import Image, ImageDraw, ImageFont, ImageGrab

def get_clipboard_image():
    """尝试从剪贴板获取图像，失败则返回 None"""
    img = ImageGrab.grabclipboard()
    if isinstance(img, Image.Image):
        return img
    return None

def parse_json_input():
    """从命令行参数或标准输入读取 JSON 字符串"""
    if len(sys.argv) > 1:
        # 优先使用命令行参数
        raw = sys.argv[1]
    else:
        # 否则从标准输入读取
        print("请粘贴 JSON 字符串（输入完成后按 Ctrl+D 或 Ctrl+Z 结束）：")
        raw = sys.stdin.read().strip()
    try:
        data = json.loads(raw)
        return data
    except json.JSONDecodeError as e:
        print(f"JSON 解析错误: {e}")
        sys.exit(1)

def draw_boxes(image, annotations):
    """在图片上绘制矩形和文本"""
    draw = ImageDraw.Draw(image)
    width, height = image.size

    # 尝试加载一个默认字体，如果失败就用 PIL 默认字体
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except IOError:
        font = ImageFont.load_default()

    for item in annotations:
        text = item.get("text", "")
        box = item.get("box", {})
        left_top = box.get("leftTop", {})
        right_bottom = box.get("rightBottom", {})

        # 相对坐标转换为绝对像素坐标
        x1 = int(left_top.get("x", 0) * width)
        y1 = int(left_top.get("y", 0) * height)
        x2 = int(right_bottom.get("x", 0) * width)
        y2 = int(right_bottom.get("y", 0) * height)

        # 确保矩形合法（左上角在右上角之前）
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1

        # 绘制矩形边框（红色，宽度3）
        draw.rectangle([x1, y1, x2, y2], outline="red", width=3)

        # 在矩形上方绘制文字（白色背景，黑色文字）
        if text:
            # 简单处理：文字放在左上角外侧，如果空间不够就放在内侧
            text_x = x1
            text_y = y1 - 20 if y1 >= 20 else y1 + 2
            # 获取文字尺寸
            bbox = draw.textbbox((text_x, text_y), text, font=font)
            draw.rectangle(bbox, fill="white")
            draw.text((text_x, text_y), text, fill="black", font=font)

def main():
    # 1. 获取剪贴板图片
    img = get_clipboard_image()
    if img is None:
        print("错误：剪贴板中没有图片。请先使用截图工具复制图片到剪贴板。")
        sys.exit(1)

    # 2. 读取 JSON 描述
    annotations = parse_json_input()

    # 3. 在图片副本上绘制（保留原图）
    img_draw = img.copy()
    draw_boxes(img_draw, annotations)

    # 4. 显示结果
    img_draw.show()
    print("绘制完成，图片已打开。")

if __name__ == "__main__":
    main()